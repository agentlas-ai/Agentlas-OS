"""Content-only workforce retrieval after deterministic hard eligibility."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from .contracts import (
    assertion_concepts,
    canonical_digest,
    content_tokens,
    load_ontology,
    normalized_strings,
    stable_id,
    tool_concepts,
    verify_profile_integrity,
)


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


def _hard_eligibility(profile: Mapping[str, Any], slot: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Return exact pass/fail only; no threshold-overage ranking."""

    reasons: list[str] = []
    if profile.get("status") != "active":
        reasons.append("release_not_active")
    qualification = profile.get("qualification") if isinstance(profile.get("qualification"), Mapping) else {}
    if qualification.get("structuralStatus") == "invalid":
        reasons.append("structural_contract_invalid")
    operational = profile.get("operational") if isinstance(profile.get("operational"), Mapping) else {}
    if operational.get("routingEligible") is not True:
        reasons.append("release_not_routing_eligible")

    req = _slot_requirements(slot)
    have = _profile_sets(profile)
    entity_kind = str(profile.get("entityKind") or "")
    if req["entity_kinds"] and entity_kind not in req["entity_kinds"]:
        reasons.append("entity_kind_mismatch")
    if req["excluded_communities"] & have["communities"]:
        reasons.append("excluded_community")
    if req["roles"] - have["roles"]:
        reasons.append("missing_required_role")
    if req["skills"] - have["skills"]:
        reasons.append("missing_required_skill")
    if req["knowledge"] - have["knowledge"]:
        reasons.append("missing_required_knowledge")
    if req["tools"] - have["tools"]:
        reasons.append("missing_required_tool")
    minimum_level = {"declared": 0, "checked": 1, "demonstrated": 2, "attested": 3}.get(
        str(slot.get("minimumEvidenceLevel") or "declared"), 0
    )
    if any(have["skill_levels"].get(item, -1) < minimum_level for item in req["skills"]):
        reasons.append("required_skill_evidence_below_minimum")
    if any(have["tool_levels"].get(item, -1) < minimum_level for item in req["tools"]):
        reasons.append("required_tool_evidence_below_minimum")
    if req["consumes"] - have["consumes"]:
        reasons.append("missing_consumed_artifact_contract")
    if req["produces"] - have["produces"]:
        reasons.append("missing_produced_artifact_contract")
    if req["authorities"] - have["authorities"]:
        reasons.append("missing_required_authority")
    if req["forbidden_authorities"] & have["authorities"]:
        reasons.append("forbidden_authority_conflict")
    if have["forbidden_authorities"] & req["authorities"]:
        reasons.append("candidate_prohibits_required_authority")
    if req["runtimes"] and not req["runtimes"] & have["runtimes"]:
        reasons.append("runtime_mismatch")
    if req["languages"] and not req["languages"] & have["languages"]:
        reasons.append("language_mismatch")
    if req["modalities"] and not req["modalities"] & have["modalities"]:
        reasons.append("modality_mismatch")

    # A required occupational community is a semantic recall constraint, not an
    # exclusion shortcut.  Direct role/skill/tool evidence may satisfy an
    # open-world candidate whose community edge has not been curated yet.
    missing_communities = req["communities"] - have["communities"]
    has_direct_evidence = bool(req["roles"] or req["skills"] or req["tools"])
    if missing_communities and not has_direct_evidence:
        reasons.append("missing_required_community")
    return not reasons, reasons


def _fit_evidence(profile: Mapping[str, Any], slot: Mapping[str, Any]) -> tuple[list[str], list[str], int]:
    req = _slot_requirements(slot)
    have = _profile_sets(profile)
    evidence: list[str] = []
    optional_gaps: list[str] = []
    for axis in ("communities", "roles", "skills", "knowledge", "tools", "consumes", "produces", "authorities", "runtimes", "languages", "modalities"):
        for item in sorted(req[axis] & have[axis]):
            evidence.append(f"fit:{axis}:{item}")

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
        semantic.get("communities"), [item.get("concept") for item in semantic.get("skills") or [] if isinstance(item, Mapping)],
    )
    overlap = sorted(query_tokens & candidate_tokens)
    for token in overlap[:12]:
        evidence.append(f"fit:text:{stable_id('term', token)}")
    # Internal recall score is content-only and used solely to bound the set.
    # It is intentionally absent from the candidate card.
    recall_score = len(evidence) * 10 + len(overlap)
    return sorted(set(evidence)), sorted(set(optional_gaps)), recall_score


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


def _candidate_card(profile: Mapping[str, Any], evidence: list[str], optional_gaps: list[str]) -> dict[str, Any]:
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
            "toolCapabilities": concepts(semantic.get("toolCapabilities"), "capability"),
            "consumes": sorted(_strings(semantic.get("consumes"))),
            "produces": sorted(_strings(semantic.get("produces"))),
            "authorities": sorted(_strings(semantic.get("authorities"))),
            "runtimes": sorted(_strings(semantic.get("runtimes"))),
            "languages": sorted(_strings(semantic.get("languages"))),
        },
        "fitEvidence": evidence,
        "qualificationEvidence": _qualification_evidence(profile),
        "optionalGaps": optional_gaps,
        "operational": {
            "callable": bool(operational.get("callable")),
            "installable": bool(operational.get("installable")),
            "unavailableReasons": [stable_id("unavailable", item) for item in normalized_strings(operational.get("unavailableReasons"))],
        },
    }


def _diverse_window(rows: list[tuple[dict[str, Any], int]], limit: int) -> list[dict[str, Any]]:
    groups: dict[str, deque[tuple[dict[str, Any], int]]] = defaultdict(deque)
    for card, score in sorted(rows, key=lambda item: (-item[1], item[0]["agentReleaseId"])):
        primary = card.get("communities", ["community:unclassified"])
        group = str(primary[0]) if primary else "community:unclassified"
        groups[group].append((card, score))
    ordered_groups = sorted(groups)
    result: list[dict[str, Any]] = []
    while len(result) < limit and ordered_groups:
        remaining: list[str] = []
        for group in ordered_groups:
            if groups[group]:
                result.append(groups[group].popleft()[0])
                if len(result) >= limit:
                    break
            if groups[group]:
                remaining.append(group)
        ordered_groups = remaining
    return result


class WorkforceIndex:
    """In-memory reference index used by local Core and contract tests."""

    def __init__(self, profiles: Iterable[Mapping[str, Any]] | None = None, *, ontology: Mapping[str, Any] | None = None):
        self.ontology = dict(ontology or load_ontology())
        self.profiles: dict[str, dict[str, Any]] = {}
        for profile in profiles or []:
            self.upsert(profile)

    def upsert(self, profile: Mapping[str, Any]) -> None:
        release_id = str(profile.get("agentReleaseId") or "")
        if not release_id:
            raise ValueError("agentReleaseId is required")
        verify_profile_integrity(profile)
        self.profiles[release_id] = dict(profile)

    def remove(self, release_id: str) -> None:
        self.profiles.pop(release_id, None)

    def search_candidates(
        self,
        work_order: Mapping[str, Any],
        *,
        now: datetime | None = None,
        expand_slot_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        if work_order.get("schemaVersion") != "agentlas.workforce-work-order.v1":
            raise ValueError("unsupported work order")
        if work_order.get("redacted") is not True:
            raise ValueError("Hub workforce search requires a redacted work order")
        requested_ontology = work_order.get("ontologyVersion")
        active_ontology = self.ontology.get("ontologyVersion")
        if requested_ontology is not None and str(requested_ontology) != str(active_ontology):
            raise ValueError(
                f"work order ontology version mismatch: requested {requested_ontology}, active {active_ontology}"
            )
        slots = work_order.get("roleSlots")
        if not isinstance(slots, list) or not slots:
            raise ValueError("work order requires roleSlots")
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
        slot_results: list[dict[str, Any]] = []
        for slot in slots:
            if not isinstance(slot, Mapping) or not slot.get("slotId"):
                raise ValueError("invalid role slot")
            rows: list[tuple[dict[str, Any], int]] = []
            for profile in self.profiles.values():
                forbidden = _strings(work_order.get("forbiddenCommunities"))
                if forbidden & _profile_sets(profile)["communities"]:
                    continue
                eligible, _reasons = _hard_eligibility(profile, slot)
                if not eligible:
                    continue
                evidence, optional_gaps, score = _fit_evidence(profile, slot)
                rows.append((_candidate_card(profile, evidence, optional_gaps), score))
            slot_limit = min(100, maximum * 2) if str(slot["slotId"]) in expanded else maximum
            cards = _diverse_window(rows, slot_limit)
            gaps: list[str] = []
            if len(cards) < minimum:
                gaps.append("gap:minimum-candidate-count")
            if not cards:
                gaps.append("gap:no-hard-eligible-candidate")
            slot_results.append({"slotId": str(slot["slotId"]), "candidates": cards, "coverageGaps": gaps})

        digest_payload = {
            "workOrderId": work_order.get("workOrderId"),
            "ontologyVersion": self.ontology.get("ontologyVersion"),
            "slots": slot_results,
            "historyInfluence": "none",
        }
        candidate_digest = canonical_digest(digest_payload)
        clock = now or _now()
        return {
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


__all__ = ["WorkforceIndex"]
