"""Broad-recall workforce retrieval after deterministic governance eligibility."""

from __future__ import annotations

import re

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from ontology.embeddings import (
    LocalHashingVectorAdapter,
    cosine_similarity,
    select_vector_adapter,
)

from .contracts import (
    WORKFORCE_COVERAGE_GAP_CODES,
    assertion_concepts,
    canonical_digest,
    content_tokens,
    load_ontology,
    normalized_strings,
    stable_id,
    tool_concepts,
    validate_candidate_set_coverage_gaps,
    verify_profile_integrity,
)
from .privacy import assert_hub_work_order_boundary


_COVERAGE_GAP_CODES = frozenset(WORKFORCE_COVERAGE_GAP_CODES)
_RRF_K = 60


def _excluded_gap(reason: str) -> str:
    code = f"gap:excluded:{reason}"
    if code not in _COVERAGE_GAP_CODES:
        raise ValueError("candidate_set_coverage_gaps_invalid")
    return code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _strings(value: Any) -> set[str]:
    return {str(item) for item in (value or []) if item is not None and str(item)}


def _slot_requirements(slot: Mapping[str, Any]) -> dict[str, set[str]]:
    return {
        "communities": _strings(slot.get("requiredCommunities")),
        "roles": _strings(slot.get("requiredRoles")),
        "skills": _strings(slot.get("requiredSkills")),
        "knowledge": _strings(slot.get("requiredKnowledge")),
        "tools": _strings(slot.get("requiredToolCapabilities")),
        "consumes": _strings(slot.get("consumes")),
        "produces": _strings(slot.get("produces")),
        "authorities": _strings(slot.get("requiredAuthorities")),
        "forbidden_authorities": _strings(slot.get("forbiddenAuthorities")),
        "runtimes": _strings(slot.get("runtimes")),
        "languages": _strings(slot.get("languages")),
        "modalities": _strings(slot.get("modalities")),
        "excluded_communities": _strings(slot.get("excludedCommunities")),
        "entity_kinds": _strings(slot.get("allowedEntityKinds")),
    }


_CONCEPT_INFLECTION_RE = re.compile(r"(ations?|ments?|ings?|ers?|eds?|es|s)$")


def _concept_tokens(value: str) -> list[str]:
    """Tokens of a concept id with the endings publishers vary on folded off."""

    body = re.sub(r"^[a-z]+:", "", str(value).strip().lower())
    tokens = [token for token in re.split(r"[^a-z0-9]+", body) if token]
    folded = [_CONCEPT_INFLECTION_RE.sub("", token) for token in tokens]
    return [token for token in folded if len(token) >= 3]


def _covers(subset: list[str], superset: list[str]) -> bool:
    return all(
        any(
            other.startswith(token) if len(token) <= len(other) else token.startswith(other)
            for other in superset
        )
        for token in subset
    )


def concept_family_matches(left: str, right: str) -> bool:
    """Does one concept id name the same thing as another, as actually spelled?

    Measured across 188 live listings: the authority vocabulary contains
    ``authority:shell-execution`` (13 listings) and ``authority:shell-exec`` (8)
    while the public catalogue advertises ``authority:shell``; the runtime list
    has 186 listings declaring ``claude-code`` and none declaring the advertised
    ``claude``. Compared as opaque strings, a slot forbidding
    ``authority:shell`` excludes none of them — the host LLM asks for no shell
    access and is handed an agent that declares it.

    This is morphology, not a synonym list: tokens compare by prefix so ``exec``
    covers ``execution``, and one id matches when its token set is contained in
    the other's. Containment keeps the pairs that must stay apart apart —
    ``file-read`` and ``file-write`` share only ``file``. Where the rule is
    asymmetric it errs wide, the safe direction for a prohibition.

    Kept in step with `conceptFamilyMatches` in the Cloud workforce ontology;
    the two judge the same candidate for the same caller.
    """

    a = _concept_tokens(left)
    b = _concept_tokens(right)
    if not a or not b:
        return str(left).strip().lower() == str(right).strip().lower()
    return _covers(a, b) or _covers(b, a)


def _family_any(available: Iterable[str], required: str) -> bool:
    return any(concept_family_matches(term, required) for term in available)


def _profile_sets(profile: Mapping[str, Any]) -> dict[str, Any]:
    semantic = profile.get("semantic") if isinstance(profile.get("semantic"), Mapping) else {}
    levels = {"declared": 0, "checked": 1, "demonstrated": 2, "attested": 3}
    skill_levels = {
        str(item.get("concept")): levels.get(str(item.get("level")), 0)
        for item in semantic.get("skills") or []
        if isinstance(item, Mapping) and item.get("concept")
    }
    tool_levels = {
        str(item.get("capability")): levels.get(str(item.get("level")), 0)
        for item in semantic.get("toolCapabilities") or []
        if isinstance(item, Mapping) and item.get("capability")
    }
    return {
        "communities": _strings(semantic.get("communities")),
        "roles": _strings(semantic.get("roles")),
        "capabilities": assertion_concepts(semantic.get("capabilities")),
        "skills": assertion_concepts(semantic.get("skills")),
        "knowledge": assertion_concepts(semantic.get("knowledge")),
        "tools": tool_concepts(semantic.get("toolCapabilities")),
        "consumes": _strings(semantic.get("consumes")),
        "produces": _strings(semantic.get("produces")),
        "authorities": _strings(semantic.get("authorities")),
        "forbidden_authorities": _strings(semantic.get("forbiddenAuthorities")),
        "runtimes": _strings(semantic.get("runtimes")),
        "languages": _strings(semantic.get("languages")),
        "modalities": _strings(semantic.get("modalities")),
        "skill_levels": skill_levels,
        "tool_levels": tool_levels,
    }


# Every dimension a slot may require and the inventory may leave empty. The
# demotion below applies to all of them: a work order that names the language it
# needs must not empty every slot merely because no profile declares a language.
# `authorities` is deliberately absent — it is a security contract, not an
# inventory-coverage question, and must keep full hard-filter force even when no
# profile declares one.
_REQUIREMENT_VOCABULARY_KINDS = (
    "roles",
    "skills",
    "knowledge",
    "tools",
    "consumes",
    "produces",
    "runtimes",
    "languages",
    "modalities",
)
# Dimensions that can never hard-filter, however full they look. Publishers
# describe what they emit in their own words, so the compiler mints one
# identifier per asset: 660 distinct `produces` values across 188 live listings,
# 2.3% of them shared by more than one asset; `consumes` is 1291 values at 4.2%.
# A vocabulary that is 97% singletons cannot separate candidates, it can only
# empty the slot — and the published catalogue advertises seven artifact ids no
# live asset produces, so a caller who follows the documentation exactly gets
# zero results from every source. Measured: a work order asking for
# `artifact:worker-result` matched nothing anywhere.
#
# They stay in the slot search text, so they still rank, and the demotion is
# reported. Skills are deliberately not here: their terms come from a published
# closed vocabulary, and quietly dropping `skill:security-review` would hand
# back agents that never claimed to do security review.
_RANKING_ONLY_KINDS = frozenset({"consumes", "produces"})

_REQUIREMENT_GAP_KIND = {
    "roles": "role",
    "skills": "skill",
    "knowledge": "knowledge",
    "tools": "tool",
    "consumes": "consumed-artifact",
    "produces": "produced-artifact",
    "runtimes": "runtime",
    "languages": "language",
    "modalities": "modality",
}


def _inventory_vocabulary(profiles: Iterable[Mapping[str, Any]]) -> dict[str, bool]:
    """Which requirement dimensions the live inventory populates at all.

    A dimension no profile declares anything in (the Hub inventory publishes
    zero `role:*` terms) is a data gap, not a discriminator: requiring a role
    empties every slot no matter which role is asked for. Such a dimension is
    demoted to a ranking signal and reported.

    Coverage is measured per dimension, never per term: demoting an individual
    unmatched term would let a poisoned candidate through whenever no profile
    happens to declare the exact required term, which is precisely what a hard
    contract exists to prevent.
    """

    populated: dict[str, bool] = {kind: False for kind in _REQUIREMENT_VOCABULARY_KINDS}
    for profile in profiles:
        have = _profile_sets(profile)
        for kind in _REQUIREMENT_VOCABULARY_KINDS:
            if have[kind]:
                populated[kind] = True
        if all(populated.values()):
            break
    return populated


def _unsupported_requirements(
    req: Mapping[str, Any],
    populated: Mapping[str, bool] | None,
) -> dict[str, set[str]]:
    """Required terms that cannot act as a hard filter.

    Either the inventory never populates the dimension, or the dimension is
    ranking-only by measurement (see `_RANKING_ONLY_KINDS`). Both are reported
    the same way, because to a caller they mean the same thing: the constraint
    you wrote was not enforced as written.
    """

    if populated is None:
        return {
            kind: (set(req[kind]) if kind in _RANKING_ONLY_KINDS else set())
            for kind in _REQUIREMENT_VOCABULARY_KINDS
        }
    return {
        kind: (
            set(req[kind])
            if kind in _RANKING_ONLY_KINDS or not populated.get(kind)
            else set()
        )
        for kind in _REQUIREMENT_VOCABULARY_KINDS
    }


def _hard_eligibility(
    profile: Mapping[str, Any],
    slot: Mapping[str, Any],
    populated: Mapping[str, bool] | None = None,
) -> tuple[bool, list[str]]:
    """Apply lifecycle, integrity, and every explicit required contract.

    Requirements in a dimension the inventory never populates are excluded from
    the hard filter (they stay in the slot search text, so they still rank) and
    the caller reports them as an explicit vocabulary gap. Every dimension the
    inventory does populate keeps full hard-filter force.
    """

    reasons: list[str] = []
    if profile.get("status") != "active":
        reasons.append("release-not-active")
    qualification = profile.get("qualification") if isinstance(profile.get("qualification"), Mapping) else {}
    if qualification.get("structuralStatus") == "invalid":
        reasons.append("structural-or-security-invalid")
    operational = profile.get("operational") if isinstance(profile.get("operational"), Mapping) else {}
    if operational.get("routingEligible") is not True:
        reasons.append("release-not-routing-eligible")

    req = _slot_requirements(slot)
    have = _profile_sets(profile)
    unsupported = _unsupported_requirements(req, populated)
    enforced = {kind: set(req[kind]) - unsupported[kind] for kind in _REQUIREMENT_VOCABULARY_KINDS}
    entity_kind = str(profile.get("entityKind") or "")
    if req["entity_kinds"] and entity_kind not in req["entity_kinds"]:
        reasons.append("entity-kind-mismatch")
    if req["excluded_communities"] & have["communities"]:
        reasons.append("excluded-community")
    if enforced["roles"] - have["roles"]:
        reasons.append("missing-required-role")
    if enforced["skills"] - have["skills"]:
        reasons.append("missing-required-skill")
    if enforced["knowledge"] - have["knowledge"]:
        reasons.append("missing-required-knowledge")
    if enforced["tools"] - have["tools"]:
        reasons.append("missing-required-tool")
    minimum_level = {"declared": 0, "checked": 1, "demonstrated": 2, "attested": 3}.get(
        str(slot.get("minimumEvidenceLevel") or "declared"), 0
    )
    if any(have["skill_levels"].get(item, -1) < minimum_level for item in enforced["skills"]):
        reasons.append("required-skill-evidence-below-minimum")
    if any(have["tool_levels"].get(item, -1) < minimum_level for item in enforced["tools"]):
        reasons.append("required-tool-evidence-below-minimum")
    if enforced["consumes"] - have["consumes"]:
        reasons.append("missing-consumed-artifact")
    if enforced["produces"] - have["produces"]:
        reasons.append("missing-produced-artifact")
    # Authorities are never demoted, but they are matched by concept family:
    # the advertised spelling and the declared one differ for every authority
    # that matters, and set difference let a prohibition pass straight through.
    if any(not _family_any(have["authorities"], item) for item in req["authorities"]):
        reasons.append("missing-required-authority")
    if any(_family_any(have["authorities"], item) for item in req["forbidden_authorities"]):
        reasons.append("forbidden-authority-conflict")
    if any(_family_any(req["authorities"], item) for item in have["forbidden_authorities"]):
        reasons.append("candidate-prohibits-required-authority")
    if enforced["runtimes"] and not any(
        _family_any(have["runtimes"], item) for item in enforced["runtimes"]
    ):
        reasons.append("runtime-mismatch")
    if enforced["languages"] and not enforced["languages"] & have["languages"]:
        reasons.append("language-mismatch")
    if enforced["modalities"] and not enforced["modalities"] & have["modalities"]:
        reasons.append("modality-mismatch")

    # Community edges are a broad-recall hint when a slot already names direct
    # role/skill/tool requirements. Without any direct requirement, the
    # community itself remains the explicit hard contract.
    missing_communities = req["communities"] - have["communities"]
    has_direct_evidence = bool(req["roles"] or req["skills"] or req["tools"])
    if missing_communities and not has_direct_evidence:
        reasons.append("missing-required-community")
    return not reasons, reasons


def _profile_search_text(profile: Mapping[str, Any]) -> str:
    """Project only immutable semantic content into the retrieval corpus."""

    semantic = profile.get("semantic") if isinstance(profile.get("semantic"), Mapping) else {}
    values: list[Any] = [
        semantic.get("names"), semantic.get("summaries"), semantic.get("communities"),
        semantic.get("roles"), semantic.get("consumes"), semantic.get("produces"),
        semantic.get("runtimes"), semantic.get("languages"), semantic.get("modalities"),
    ]
    values.extend(
        item.get("concept")
        for key in ("capabilities", "skills", "knowledge")
        for item in (semantic.get(key) or [])
        if isinstance(item, Mapping) and item.get("concept")
    )
    values.extend(
        item.get("capability")
        for item in (semantic.get("toolCapabilities") or [])
        if isinstance(item, Mapping) and item.get("capability")
    )
    parts: list[str] = []
    for value in values:
        if isinstance(value, (list, tuple, set, frozenset)):
            parts.extend(normalized_strings(value, limit=2048))
        else:
            parts.extend(normalized_strings([value]))
    return " ".join(normalized_strings(parts, limit=2048))


def _slot_search_text(slot: Mapping[str, Any]) -> str:
    req = _slot_requirements(slot)
    return " ".join(
        normalized_strings(
            [
                slot.get("title"), slot.get("task"),
                *sorted(req["communities"]), *sorted(req["roles"]),
                *sorted(req["skills"]), *sorted(req["knowledge"]),
                *sorted(req["tools"]), *sorted(req["consumes"]),
                *sorted(req["produces"]), *sorted(req["runtimes"]),
                *sorted(req["languages"]), *sorted(req["modalities"]),
            ],
            limit=2048,
        )
    )


def _missing_id(axis: str, value: str) -> str:
    return stable_id(f"missing-{axis}", value)


def _fit_evidence(
    profile: Mapping[str, Any], slot: Mapping[str, Any]
) -> tuple[list[str], list[str], list[str], float, float]:
    req = _slot_requirements(slot)
    have = _profile_sets(profile)
    evidence: list[str] = []
    mandatory_gaps: list[str] = []
    optional_gaps: list[str] = []
    fit_axes = (
        "communities", "roles", "skills", "knowledge", "tools", "consumes",
        "produces", "authorities", "runtimes", "languages", "modalities",
    )
    for axis in fit_axes:
        for item in sorted(req[axis] & have[axis]):
            evidence.append(f"fit:{axis}:{item}")

    required_all = {
        "community": (req["communities"], have["communities"]),
        "role": (req["roles"], have["roles"]),
        "skill": (req["skills"], have["skills"]),
        "knowledge": (req["knowledge"], have["knowledge"]),
        "tool": (req["tools"], have["tools"]),
        "consumes": (req["consumes"], have["consumes"]),
        "produces": (req["produces"], have["produces"]),
    }
    for axis, (required, available) in required_all.items():
        mandatory_gaps.extend(_missing_id(axis, item) for item in sorted(required - available))
    singular_axes = {
        "runtimes": "runtime",
        "languages": "language",
        "modalities": "modality",
    }
    for axis, singular_axis in singular_axes.items():
        if req[axis] and not req[axis] & have[axis]:
            mandatory_gaps.extend(
                _missing_id(singular_axis, item) for item in sorted(req[axis])
            )

    levels = {"declared": 0, "checked": 1, "demonstrated": 2, "attested": 3}
    minimum_name = str(slot.get("minimumEvidenceLevel") or "declared")
    minimum_level = levels.get(minimum_name, 0)
    for item in sorted(req["skills"] & have["skills"]):
        if have["skill_levels"].get(item, -1) < minimum_level:
            mandatory_gaps.append(_missing_id("skill-evidence", f"{item}-{minimum_name}"))
    for item in sorted(req["tools"] & have["tools"]):
        if have["tool_levels"].get(item, -1) < minimum_level:
            mandatory_gaps.append(_missing_id("tool-evidence", f"{item}-{minimum_name}"))

    optional_communities = _strings(slot.get("optionalCommunities"))
    optional_skills = _strings(slot.get("optionalSkills"))
    for item in sorted(optional_communities & have["communities"]):
        evidence.append(f"fit:optional-community:{item}")
    for item in sorted(optional_skills & have["skills"]):
        evidence.append(f"fit:optional-skill:{item}")
    for item in sorted(optional_communities - have["communities"]):
        optional_gaps.append(f"gap:community:{item}")
    for item in sorted(optional_skills - have["skills"]):
        optional_gaps.append(f"gap:skill:{item}")

    semantic = profile.get("semantic") if isinstance(profile.get("semantic"), Mapping) else {}
    query_tokens = content_tokens(slot.get("title"), slot.get("task"))
    candidate_tokens = content_tokens(
        semantic.get("names"), semantic.get("summaries"), semantic.get("roles"),
        semantic.get("communities"),
        [
            item.get("concept")
            for item in semantic.get("skills") or []
            if isinstance(item, Mapping)
        ],
    )
    overlap = sorted(query_tokens & candidate_tokens)
    for token in overlap[:12]:
        evidence.append(f"fit:text:{stable_id('term', token)}")
    lexical_score = float(len(overlap))
    structured_score = float(len(evidence) * 2 - len(mandatory_gaps) * 3)
    return (
        sorted(set(evidence)),
        sorted(set(mandatory_gaps)),
        sorted(set(optional_gaps)),
        lexical_score,
        structured_score,
    )


def _qualification_evidence(profile: Mapping[str, Any]) -> list[str]:
    qualification = profile.get("qualification") if isinstance(profile.get("qualification"), Mapping) else {}
    result: list[str] = []
    for assertion in qualification.get("assertions") or []:
        if not isinstance(assertion, Mapping):
            continue
        value = assertion.get("assertionId") or assertion.get("subject")
        if value:
            result.append(str(value))
    return sorted(set(result))


def _candidate_card(
    profile: Mapping[str, Any],
    evidence: list[str],
    mandatory_gaps: list[str],
    optional_gaps: list[str],
) -> dict[str, Any]:
    semantic = profile.get("semantic") if isinstance(profile.get("semantic"), Mapping) else {}
    operational = profile.get("operational") if isinstance(profile.get("operational"), Mapping) else {}
    names = normalized_strings(semantic.get("names"))
    provenance = profile.get("provenance") if isinstance(profile.get("provenance"), Mapping) else {}

    def concepts(rows: Any, key: str) -> list[dict[str, Any]]:
        return [
            {"concept": str(item.get(key)), "level": str(item.get("level") or "declared")}
            for item in rows or []
            if isinstance(item, Mapping) and item.get(key)
        ]

    return {
        "agentDefinitionId": str(profile.get("agentDefinitionId")),
        "agentReleaseId": str(profile.get("agentReleaseId")),
        "releaseVersion": str(profile.get("releaseVersion")),
        "packageHash": str(profile.get("packageHash")),
        "contentDigest": str(provenance.get("contentDigest")),
        "entityKind": str(profile.get("entityKind")),
        "name": names[0] if names else str(profile.get("agentReleaseId")),
        "communities": sorted(_strings(semantic.get("communities"))),
        "semanticSnapshot": {
            "summaries": normalized_strings(semantic.get("summaries")),
            "roles": sorted(_strings(semantic.get("roles"))),
            "skills": concepts(semantic.get("skills"), "concept"),
            "knowledge": concepts(semantic.get("knowledge"), "concept"),
            "toolCapabilities": concepts(semantic.get("toolCapabilities"), "capability"),
            "consumes": sorted(_strings(semantic.get("consumes"))),
            "produces": sorted(_strings(semantic.get("produces"))),
            "authorities": sorted(_strings(semantic.get("authorities"))),
            "runtimes": sorted(_strings(semantic.get("runtimes"))),
            "languages": sorted(_strings(semantic.get("languages"))),
            "modalities": sorted(_strings(semantic.get("modalities"))),
        },
        "fitEvidence": evidence,
        "qualificationEvidence": _qualification_evidence(profile),
        "missingMandatory": mandatory_gaps,
        "optionalGaps": optional_gaps,
        "operational": {
            "callable": bool(operational.get("callable")),
            "installable": bool(operational.get("installable")),
            "unavailableReasons": [
                stable_id("unavailable", item)
                for item in normalized_strings(operational.get("unavailableReasons"))
            ],
        },
    }


def _diverse_window(rows: list[tuple[dict[str, Any], float]], limit: int) -> list[dict[str, Any]]:
    groups: dict[str, deque[tuple[dict[str, Any], float]]] = defaultdict(deque)
    for card, score in sorted(rows, key=lambda item: (-item[1], item[0]["agentReleaseId"])):
        primary = card.get("communities", ["community:unclassified"])
        group = str(primary[0]) if primary else "community:unclassified"
        groups[group].append((card, score))
    result: list[dict[str, Any]] = []
    while len(result) < limit:
        ordered_groups = sorted(
            (group for group, queue in groups.items() if queue),
            key=lambda group: (-groups[group][0][1], group),
        )
        if not ordered_groups:
            break
        for group in ordered_groups:
            if groups[group]:
                result.append(groups[group].popleft()[0])
                if len(result) >= limit:
                    break
    return result


def _descending_ranks(
    rows: list[dict[str, Any]],
    score_key: str,
) -> dict[str, int]:
    """Assign equal content scores equal rank; release IDs are not evidence."""

    ranked = sorted(
        rows,
        key=lambda row: (-float(row[score_key]), row["card"]["agentReleaseId"]),
    )
    result: dict[str, int] = {}
    previous_score: float | None = None
    current_rank = 0
    for position, row in enumerate(ranked, 1):
        score = round(float(row[score_key]), 12)
        if previous_score is None or score != previous_score:
            current_rank = position
            previous_score = score
        result[row["card"]["agentReleaseId"]] = current_rank
    return result


class WorkforceIndex:
    """In-memory reference index used by local Core and contract tests."""

    def __init__(
        self,
        profiles: Iterable[Mapping[str, Any]] | None = None,
        *,
        ontology: Mapping[str, Any] | None = None,
        vector_adapter: Any | None = None,
    ):
        self.ontology = dict(ontology or load_ontology())
        if vector_adapter is None:
            try:
                vector_adapter = select_vector_adapter("auto")
            except (OSError, ValueError):
                vector_adapter = LocalHashingVectorAdapter(
                    status="degraded_fallback",
                    fallback_reason="verified_local_model2vec_asset_unavailable",
                )
        self.vector_adapter = vector_adapter
        self.profiles: dict[str, dict[str, Any]] = {}
        self._profile_vectors: dict[str, list[float] | None] = {}
        for profile in profiles or []:
            self.upsert(profile)

    def upsert(self, profile: Mapping[str, Any]) -> None:
        release_id = str(profile.get("agentReleaseId") or "")
        if not release_id:
            raise ValueError("agentReleaseId is required")
        verify_profile_integrity(profile)
        self.profiles[release_id] = dict(profile)
        try:
            self._profile_vectors[release_id] = self.vector_adapter.embed(_profile_search_text(profile))
        except Exception:
            self._profile_vectors[release_id] = None

    def remove(self, release_id: str) -> None:
        self.profiles.pop(release_id, None)
        self._profile_vectors.pop(release_id, None)

    def search_candidates(
        self,
        work_order: Mapping[str, Any],
        *,
        now: datetime | None = None,
        expand_slot_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        if work_order.get("schemaVersion") != "agentlas.workforce-work-order.v1":
            raise ValueError("unsupported work order")
        # This is the first operation at the public search boundary.  It reads
        # the exact WorkOrder and raises before profile lookup/session creation;
        # the caller must perform the same helper before remote transport.
        assert_hub_work_order_boundary(work_order)
        requested_ontology = work_order.get("ontologyVersion")
        active_ontology = self.ontology.get("ontologyVersion")
        if requested_ontology is not None and str(requested_ontology) != str(active_ontology):
            raise ValueError(
                f"work order ontology version mismatch: requested {requested_ontology}, active {active_ontology}"
            )
        slots = work_order.get("roleSlots")
        if not isinstance(slots, list) or not slots:
            raise ValueError("work order requires roleSlots")
        if any(
            isinstance(slot, Mapping) and "group" in (slot.get("allowedEntityKinds") or [])
            for slot in slots
        ):
            raise ValueError("group entity kind is discovery-only and not executable")
        policy = work_order.get("selectionPolicy") if isinstance(work_order.get("selectionPolicy"), Mapping) else {}
        minimum = max(2, min(30, int(policy.get("minimumCandidatesPerSlot") or 5)))
        maximum = max(minimum, min(100, int(policy.get("maximumCandidatesPerSlot") or 20)))
        expanded = {str(item) for item in (expand_slot_ids or [])}
        active_digest = canonical_digest(
            sorted(
                (release_id, profile.get("provenance", {}).get("contentDigest"), profile.get("status"))
                for release_id, profile in self.profiles.items()
            )
        )
        base = {
            "workOrderId": work_order.get("workOrderId"),
            "ontologyVersion": self.ontology.get("ontologyVersion"),
            "activeDigest": active_digest,
            "slots": slots,
        }
        session_id = "selection:" + canonical_digest(base).split(":", 1)[1][:24]
        vocabulary = _inventory_vocabulary(self.profiles.values())
        slot_results: list[dict[str, Any]] = []
        for slot in slots:
            if not isinstance(slot, Mapping) or not slot.get("slotId"):
                raise ValueError("invalid role slot")
            ranked_inputs: list[dict[str, Any]] = []
            exclusion_reasons: set[str] = set()
            unsupported = _unsupported_requirements(_slot_requirements(slot), vocabulary)
            slot_text = _slot_search_text(slot)
            try:
                slot_vector = self.vector_adapter.embed(slot_text)
            except Exception:
                slot_vector = None
            for profile in self.profiles.values():
                forbidden = _strings(work_order.get("forbiddenCommunities"))
                if forbidden & _profile_sets(profile)["communities"]:
                    exclusion_reasons.add("forbidden-community")
                    continue
                eligible, reasons = _hard_eligibility(profile, slot, vocabulary)
                if not eligible:
                    exclusion_reasons.update(reasons)
                    continue
                (
                    evidence,
                    mandatory_gaps,
                    optional_gaps,
                    lexical_score,
                    structured_score,
                ) = _fit_evidence(profile, slot)
                release_id = str(profile.get("agentReleaseId"))
                profile_vector = self._profile_vectors.get(release_id)
                vector_available = slot_vector is not None and profile_vector is not None
                vector_score = cosine_similarity(slot_vector, profile_vector) if vector_available else 0.0
                if lexical_score > 0:
                    evidence.append("fit:retrieval:lexical")
                if vector_available and vector_score > 0.15:
                    evidence.append(stable_id("fit-retrieval", str(getattr(self.vector_adapter, "name", "local"))))
                ranked_inputs.append(
                    {
                        "card": _candidate_card(
                            profile,
                            sorted(set(evidence)),
                            mandatory_gaps,
                            optional_gaps,
                        ),
                        "lexical": lexical_score,
                        "structured": structured_score,
                        "vector": vector_score,
                        "vectorAvailable": vector_available,
                    }
                )
            lexical_rank = _descending_ranks(ranked_inputs, "lexical")
            structured_rank = _descending_ranks(ranked_inputs, "structured")
            vector_rank = _descending_ranks(
                [row for row in ranked_inputs if row["vectorAvailable"]],
                "vector",
            )
            rows: list[tuple[dict[str, Any], float]] = []
            for row in ranked_inputs:
                release_id = row["card"]["agentReleaseId"]
                rrf_score = (
                    1.0 / (_RRF_K + lexical_rank[release_id])
                    + 1.0 / (_RRF_K + structured_rank[release_id])
                )
                if release_id in vector_rank:
                    rrf_score += 1.0 / (_RRF_K + vector_rank[release_id])
                rows.append((row["card"], rrf_score))
            slot_limit = min(100, maximum * 2) if str(slot["slotId"]) in expanded else maximum
            cards = _diverse_window(rows, slot_limit)
            gaps: list[str] = []
            if len(cards) < minimum:
                gaps.append("gap:minimum-candidate-count")
            # Report a demoted requirement term even when the slot filled: the
            # host LLM must know its stated contract was not enforced as written.
            gaps.extend(
                f"gap:requirement-vocabulary-unsupported:{_REQUIREMENT_GAP_KIND[kind]}"
                for kind in _REQUIREMENT_VOCABULARY_KINDS
                if unsupported[kind]
            )
            if not cards:
                gaps.append("gap:no-hard-eligible-candidate")
                gaps.extend(_excluded_gap(reason) for reason in sorted(exclusion_reasons)[:12])
            slot_results.append({"slotId": str(slot["slotId"]), "candidates": cards, "coverageGaps": gaps})

        digest_payload = {
            "workOrderId": work_order.get("workOrderId"),
            "ontologyVersion": self.ontology.get("ontologyVersion"),
            "slots": slot_results,
            "historyInfluence": "none",
        }
        candidate_digest = canonical_digest(digest_payload)
        clock = now or _now()
        candidate_set = {
            "schemaVersion": "agentlas.workforce-candidate-set.v1",
            "selectionSessionId": session_id,
            "workOrderId": str(work_order.get("workOrderId")),
            "ontologyVersion": str(self.ontology.get("ontologyVersion")),
            "candidateSetDigest": candidate_digest,
            "decisionOwner": "host_llm",
            "historyInfluence": "none",
            "slots": slot_results,
            "issuedAt": clock.isoformat().replace("+00:00", "Z"),
            "expiresAt": (clock + timedelta(minutes=10)).isoformat().replace("+00:00", "Z"),
        }
        validate_candidate_set_coverage_gaps(candidate_set)
        return candidate_set


__all__ = ["WorkforceIndex"]
