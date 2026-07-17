"""Source-neutral federation for Local, owner Cloud, and public Hub menus.

The federation layer never scores or selects workers.  Each source owns its
content retrieval and returns a normal CandidateSet v1.  This module validates
those immutable menus, resolves only cryptographically attested exact identity
shadowing, and emits a provenance-sealed union for the host LLM.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Callable, Iterable, Mapping

from .contracts import canonical_digest, canonical_json, validate_candidate_set_coverage_gaps


WORKFORCE_FEDERATION_RESULT_SCHEMA = "agentlas.workforce-federation-result.v1"
WORKFORCE_LINEAGE_ATTESTATION_SCHEMA = "agentlas.workforce-lineage-attestation.v1"
WORKFORCE_SOURCE_PRECEDENCE = ("local", "cloud", "hub")
WORKFORCE_SOURCE_SCOPES: dict[str, tuple[str, ...]] = {
    "network": WORKFORCE_SOURCE_PRECEDENCE,
    "local": ("local",),
    "cloud": ("cloud",),
    "hub": ("hub",),
}
WORKFORCE_SOURCE_FAILURE_CODES = (
    "source_not_configured",
    "source_not_supported",
    "source_unavailable",
    "source_timeout",
    "source_unauthorized",
    "source_forbidden",
    "source_rate_limited",
    "source_invalid_candidate_set",
    "source_candidate_set_expired",
    "source_work_order_mismatch",
    "source_ontology_mismatch",
    "source_slot_mismatch",
    "source_candidate_set_digest_mismatch",
    "source_history_influence_forbidden",
    "insufficient_credits",
    "owner_only",
    "no_cloud_package",
    "agent_not_found",
)

_FAILURES = frozenset(WORKFORCE_SOURCE_FAILURE_CODES)
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{1,255}$")
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MAX_TTL = timedelta(minutes=10)
_MAX_SOURCE_CANDIDATE_SET_BYTES = 16 * 1024 * 1024
_MAX_SOURCE_CANDIDATES = 500
_MAX_FEDERATION_RESULT_BYTES = 24 * 1024 * 1024
_VERIFICATIONS = frozenset(
    {"verified_transport", "verified_signature", "verified_local_registry"}
)
LineageVerifier = Callable[[str, str, Mapping[str, Any], Mapping[str, Any]], bool]
_CANDIDATE_FIELDS = frozenset(
    {
        "agentDefinitionId",
        "agentReleaseId",
        "releaseVersion",
        "packageHash",
        "contentDigest",
        "entityKind",
        "name",
        "communities",
        "fitEvidence",
        "qualificationEvidence",
        "missingMandatory",
        "optionalGaps",
        "semanticSnapshot",
        "operational",
    }
)
_REQUIRED_CANDIDATE_FIELDS = frozenset(
    {
        "agentDefinitionId",
        "agentReleaseId",
        "releaseVersion",
        "packageHash",
        "contentDigest",
        "entityKind",
        "name",
        "communities",
        "fitEvidence",
        "qualificationEvidence",
        "optionalGaps",
        "semanticSnapshot",
        "operational",
    }
)
_SEMANTIC_FIELDS = frozenset(
    {
        "summaries",
        "roles",
        "skills",
        "knowledge",
        "toolCapabilities",
        "consumes",
        "produces",
        "authorities",
        "runtimes",
        "languages",
        "modalities",
    }
)


def _bounded_json_size(value: Any, *, maximum: int) -> int:
    """Bound an already-decoded JSON tree without materializing another copy.

    Candidate menus are untrusted remote input.  Counting strings and
    container overhead incrementally lets us reject a very wide/deep menu
    before per-card normalization/deepcopy would amplify its memory use.
    """

    total = 0
    stack: list[tuple[Any, int]] = [(value, 0)]
    active: set[int] = set()
    while stack:
        item, state = stack.pop()
        if isinstance(item, Mapping):
            identity = id(item)
            if state:
                active.discard(identity)
                continue
            if identity in active:
                raise _SourceError("source_invalid_candidate_set")
            active.add(identity)
            total += 2 + max(0, len(item) - 1)
            stack.append((item, 1))
            for key, child in item.items():
                if not isinstance(key, str):
                    raise _SourceError("source_invalid_candidate_set")
                total += len(key.encode("utf-8")) + 3
                stack.append((child, 0))
        elif isinstance(item, list):
            identity = id(item)
            if state:
                active.discard(identity)
                continue
            if identity in active:
                raise _SourceError("source_invalid_candidate_set")
            active.add(identity)
            total += 2 + max(0, len(item) - 1)
            stack.append((item, 1))
            for child in item:
                stack.append((child, 0))
        elif isinstance(item, str):
            total += len(item.encode("utf-8")) + 2
        elif item is None or isinstance(item, (bool, int, float)):
            # A conservative constant is enough for the preflight cap.  The
            # strict validators below reject non-JSON numeric edge cases.
            total += 32
        else:
            raise _SourceError("source_invalid_candidate_set")
        if total > maximum:
            raise _SourceError("source_invalid_candidate_set")
    return total


def _preflight_candidate_set(value: Any) -> None:
    if not isinstance(value, Mapping):
        raise _SourceError("source_invalid_candidate_set")
    slots = value.get("slots")
    if not isinstance(slots, list) or len(slots) > 32:
        raise _SourceError("source_invalid_candidate_set")
    candidate_count = 0
    for slot in slots:
        if not isinstance(slot, Mapping) or not isinstance(slot.get("candidates"), list):
            raise _SourceError("source_invalid_candidate_set")
        candidate_count += len(slot["candidates"])
        if candidate_count > _MAX_SOURCE_CANDIDATES:
            raise _SourceError("source_invalid_candidate_set")
    _bounded_json_size(value, maximum=_MAX_SOURCE_CANDIDATE_SET_BYTES)


def _valid_string_list(value: Any, *, ids: bool, maximum: int = 256) -> bool:
    if not isinstance(value, list) or len(value) > maximum:
        return False
    observed: set[str] = set()
    for item in value:
        if not isinstance(item, str) or not item or len(item) > 500 or item in observed:
            return False
        if ids and not _valid_id(item):
            return False
        observed.add(item)
    return True


def _valid_leveled(value: Any) -> bool:
    if not isinstance(value, list) or len(value) > 256:
        return False
    observed: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, Mapping) or set(item) != {"concept", "level"}:
            return False
        pair = (str(item.get("concept") or ""), str(item.get("level") or ""))
        if not _valid_id(pair[0]) or pair[1] not in {"declared", "checked", "demonstrated", "attested"} or pair in observed:
            return False
        observed.add(pair)
    return True


class WorkforceFederationError(ValueError):
    """Finite fail-closed federation error safe to expose in a receipt."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class _SourceError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def sources_for_scope(scope: str) -> tuple[str, ...]:
    try:
        return WORKFORCE_SOURCE_SCOPES[str(scope)]
    except KeyError as exc:
        raise WorkforceFederationError("unsupported_source_scope") from exc


def _clock(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise WorkforceFederationError("federation_clock_must_be_timezone_aware")
    return result.astimezone(timezone.utc)


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise _SourceError("source_invalid_candidate_set")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _SourceError("source_invalid_candidate_set") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise _SourceError("source_invalid_candidate_set")
    return result.astimezone(timezone.utc)


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and _ID_RE.fullmatch(value) is not None


def _valid_hash(value: Any) -> bool:
    return isinstance(value, str) and _HASH_RE.fullmatch(value) is not None


def _result_timestamp(value: Any) -> datetime:
    try:
        return _parse_timestamp(value)
    except _SourceError as exc:
        raise WorkforceFederationError("invalid_federation_result") from exc


def _validate_candidate(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _SourceError("source_invalid_candidate_set")
    if not _REQUIRED_CANDIDATE_FIELDS <= set(value) or set(value) - _CANDIDATE_FIELDS:
        raise _SourceError("source_invalid_candidate_set")
    if not _valid_id(value.get("agentDefinitionId")) or not _valid_id(value.get("agentReleaseId")):
        raise _SourceError("source_invalid_candidate_set")
    if not _valid_hash(value.get("packageHash")) or not _valid_hash(value.get("contentDigest")):
        raise _SourceError("source_invalid_candidate_set")
    if value.get("entityKind") not in {"agent", "team", "group"}:
        raise _SourceError("source_invalid_candidate_set")
    if not isinstance(value.get("releaseVersion"), str) or not 1 <= len(value["releaseVersion"]) <= 100:
        raise _SourceError("source_invalid_candidate_set")
    if not isinstance(value.get("name"), str) or not 1 <= len(value["name"]) <= 200:
        raise _SourceError("source_invalid_candidate_set")
    # CandidateSet fields can evolve additively only through the pinned allow
    # list above.  Bound the full detached card before reflecting it.
    try:
        encoded = canonical_json(value).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise _SourceError("source_invalid_candidate_set") from exc
    if len(encoded) > 512_000:
        raise _SourceError("source_invalid_candidate_set")
    for key in ("communities", "fitEvidence", "qualificationEvidence", "optionalGaps"):
        if not _valid_string_list(value.get(key), ids=True):
            raise _SourceError("source_invalid_candidate_set")
    missing = value.get("missingMandatory", [])
    if not _valid_string_list(missing, ids=True):
        raise _SourceError("source_invalid_candidate_set")
    semantic = value.get("semanticSnapshot")
    if not isinstance(semantic, Mapping) or set(semantic) - _SEMANTIC_FIELDS:
        raise _SourceError("source_invalid_candidate_set")
    required_semantic = _SEMANTIC_FIELDS - {"knowledge", "modalities"}
    if not required_semantic <= set(semantic):
        raise _SourceError("source_invalid_candidate_set")
    for key in ("roles", "consumes", "produces", "authorities"):
        if not _valid_string_list(semantic.get(key), ids=True):
            raise _SourceError("source_invalid_candidate_set")
    for key in ("summaries", "runtimes", "languages", "modalities"):
        if not _valid_string_list(semantic.get(key, []), ids=False):
            raise _SourceError("source_invalid_candidate_set")
    for key in ("skills", "knowledge", "toolCapabilities"):
        if not _valid_leveled(semantic.get(key, [])):
            raise _SourceError("source_invalid_candidate_set")
    operational = value.get("operational")
    if (
        not isinstance(operational, Mapping)
        or not {"callable", "installable"} <= set(operational)
        or set(operational) - {"callable", "installable", "unavailableReasons"}
        or not isinstance(operational.get("callable"), bool)
        or not isinstance(operational.get("installable"), bool)
        or not _valid_string_list(operational.get("unavailableReasons", []), ids=True)
    ):
        raise _SourceError("source_invalid_candidate_set")
    return deepcopy(dict(value))


def _validate_candidate_set(
    value: Any,
    *,
    work_order_id: str,
    ontology_version: str,
    slot_ids: tuple[str, ...],
    now: datetime,
) -> tuple[dict[str, Any], datetime]:
    _preflight_candidate_set(value)
    if not isinstance(value, Mapping) or value.get("schemaVersion") != "agentlas.workforce-candidate-set.v1":
        raise _SourceError("source_invalid_candidate_set")
    if value.get("decisionOwner") != "host_llm":
        raise _SourceError("source_invalid_candidate_set")
    if value.get("historyInfluence") != "none":
        raise _SourceError("source_history_influence_forbidden")
    if value.get("workOrderId") != work_order_id:
        raise _SourceError("source_work_order_mismatch")
    if value.get("ontologyVersion") != ontology_version:
        raise _SourceError("source_ontology_mismatch")
    if not _valid_id(value.get("selectionSessionId")) or not _valid_hash(value.get("candidateSetDigest")):
        raise _SourceError("source_invalid_candidate_set")
    issued_at = _parse_timestamp(value.get("issuedAt"))
    expires_at = _parse_timestamp(value.get("expiresAt"))
    if expires_at <= issued_at:
        raise _SourceError("source_invalid_candidate_set")
    if expires_at <= now:
        raise _SourceError("source_candidate_set_expired")
    if issued_at > now + timedelta(seconds=5):
        raise _SourceError("source_invalid_candidate_set")

    slots = value.get("slots")
    if not isinstance(slots, list) or len(slots) != len(slot_ids):
        raise _SourceError("source_slot_mismatch")
    normalized_slots: list[dict[str, Any]] = []
    observed: list[str] = []
    release_definitions: dict[str, str] = {}
    for slot in slots:
        if not isinstance(slot, Mapping) or set(slot) != {"slotId", "candidates", "coverageGaps"}:
            raise _SourceError("source_invalid_candidate_set")
        slot_id = slot.get("slotId")
        if not _valid_id(slot_id):
            raise _SourceError("source_invalid_candidate_set")
        candidates = slot.get("candidates")
        if not isinstance(candidates, list) or len(candidates) > 100:
            raise _SourceError("source_invalid_candidate_set")
        normalized = [_validate_candidate(candidate) for candidate in candidates]
        definitions = [candidate["agentDefinitionId"] for candidate in normalized]
        if len(definitions) != len(set(definitions)):
            raise _SourceError("source_invalid_candidate_set")
        for candidate in normalized:
            release_id = candidate["agentReleaseId"]
            previous_definition = release_definitions.setdefault(release_id, candidate["agentDefinitionId"])
            if previous_definition != candidate["agentDefinitionId"]:
                raise _SourceError("source_invalid_candidate_set")
        normalized_slots.append(
            {
                "slotId": slot_id,
                "candidates": normalized,
                "coverageGaps": list(slot.get("coverageGaps") or []),
            }
        )
        observed.append(str(slot_id))
    if len(observed) != len(set(observed)) or set(observed) != set(slot_ids):
        raise _SourceError("source_slot_mismatch")
    normalized_set = {
        "schemaVersion": "agentlas.workforce-candidate-set.v1",
        "selectionSessionId": value["selectionSessionId"],
        "workOrderId": value["workOrderId"],
        "ontologyVersion": value["ontologyVersion"],
        "candidateSetDigest": value["candidateSetDigest"],
        "decisionOwner": "host_llm",
        "historyInfluence": "none",
        "slots": normalized_slots,
        "issuedAt": value["issuedAt"],
        "expiresAt": value["expiresAt"],
    }
    try:
        validate_candidate_set_coverage_gaps(normalized_set)
    except ValueError as exc:
        raise _SourceError("source_invalid_candidate_set") from exc
    expected_digest = canonical_digest(
        {
            "workOrderId": work_order_id,
            "ontologyVersion": ontology_version,
            "slots": normalized_slots,
            "historyInfluence": "none",
        }
    )
    if value.get("candidateSetDigest") != expected_digest:
        raise _SourceError("source_candidate_set_digest_mismatch")
    return normalized_set, expires_at


def validate_lineage_attestation(value: Any) -> dict[str, Any]:
    required = {
        "schemaVersion",
        "lineageDigest",
        "issuer",
        "verification",
    }
    if not isinstance(value, Mapping) or not required <= set(value) or set(value) - (required | {"claimDigest", "proof"}):
        raise WorkforceFederationError("lineage_attestation_invalid")
    if value.get("schemaVersion") != WORKFORCE_LINEAGE_ATTESTATION_SCHEMA:
        raise WorkforceFederationError("lineage_attestation_invalid")
    if not _valid_hash(value.get("lineageDigest")):
        raise WorkforceFederationError("lineage_attestation_invalid")
    issuer = value.get("issuer")
    if not isinstance(issuer, str) or not 1 <= len(issuer) <= 255:
        raise WorkforceFederationError("lineage_attestation_invalid")
    if value.get("verification") not in _VERIFICATIONS:
        raise WorkforceFederationError("lineage_attestation_unverified")
    if "claimDigest" in value and not _valid_hash(value.get("claimDigest")):
        raise WorkforceFederationError("lineage_attestation_invalid")
    if "proof" in value:
        if not isinstance(value.get("proof"), Mapping) or len(canonical_json(value["proof"]).encode("utf-8")) > 16_384:
            raise WorkforceFederationError("lineage_attestation_invalid")
    return deepcopy(dict(value))


def workforce_lineage_claim_digest(definition_id: str, appearance: Mapping[str, Any]) -> str:
    return canonical_digest(
        {
            "agentDefinitionId": definition_id,
            "agentReleaseId": appearance.get("agentReleaseId"),
            "releaseVersion": appearance.get("releaseVersion"),
            "packageHash": appearance.get("packageHash"),
            "contentDigest": appearance.get("contentDigest"),
            "entityKind": appearance.get("entityKind"),
            "lineageDigest": (appearance.get("lineageAttestation") or {}).get("lineageDigest"),
            "issuer": (appearance.get("lineageAttestation") or {}).get("issuer"),
        }
    )


def _source_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    detached = dict(payload)
    detached["receiptDigest"] = canonical_digest(detached)
    return detached


def _federation_preimage(result: Mapping[str, Any]) -> dict[str, Any]:
    candidate_set = result.get("candidateSet") if isinstance(result.get("candidateSet"), Mapping) else {}
    return {
        "scope": result.get("scope"),
        "sources": result.get("sources"),
        # selectionSessionId is derived from this digest and is the only
        # circular field.  Every other CandidateSet field, including the full
        # cards/slots, is sealed directly in addition to candidateSetDigest.
        "candidateSet": {
            key: deepcopy(value)
            for key, value in candidate_set.items()
            if key != "selectionSessionId"
        },
        "orderingPolicy": result.get("orderingPolicy"),
        "sourceReceipts": result.get("sourceReceipts"),
        "candidateProvenance": result.get("candidateProvenance"),
        "issuedAt": candidate_set.get("issuedAt"),
        "expiresAt": candidate_set.get("expiresAt"),
    }


def workforce_federation_digest(result: Mapping[str, Any]) -> str:
    return canonical_digest(_federation_preimage(result))


def federate_candidate_sets(
    source_candidate_sets: Mapping[str, Mapping[str, Any]] | None,
    *,
    scope: str,
    work_order_id: str,
    ontology_version: str,
    slot_ids: Iterable[str],
    source_failures: Mapping[str, str] | None = None,
    lineage_attestations: Mapping[str, Mapping[str, Mapping[str, Any]]] | None = None,
    lineage_verifier: LineageVerifier | None = None,
    minimum_candidates_per_slot: int | Mapping[str, int] = 2,
    maximum_candidates_per_slot: int | Mapping[str, int] = 100,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Union source menus without semantic ordering or implicit identity trust."""

    sources = sources_for_scope(scope)
    clock = _clock(now)
    candidate_sets = dict(source_candidate_sets or {})
    failures = dict(source_failures or {})
    attestations = dict(lineage_attestations or {})
    slots = tuple(str(item) for item in slot_ids)
    if not _valid_id(work_order_id) or not _valid_id(ontology_version):
        raise WorkforceFederationError("invalid_federation_identity")
    if not slots or len(slots) > 32 or len(slots) != len(set(slots)) or any(not _valid_id(item) for item in slots):
        raise WorkforceFederationError("invalid_federation_slots")
    supplied = set(candidate_sets) | set(failures) | set(attestations)
    if supplied - set(sources):
        raise WorkforceFederationError("source_outside_scope")
    if set(candidate_sets) & set(failures):
        raise WorkforceFederationError("source_has_conflicting_outcome")
    if any(value not in _FAILURES for value in failures.values()):
        raise WorkforceFederationError("invalid_source_failure_code")
    if isinstance(minimum_candidates_per_slot, Mapping):
        minimums = {str(key): value for key, value in minimum_candidates_per_slot.items()}
        if set(minimums) != set(slots):
            raise WorkforceFederationError("invalid_federation_candidate_minimum")
    else:
        minimums = {slot_id: minimum_candidates_per_slot for slot_id in slots}
    if any(isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 30 for value in minimums.values()):
        raise WorkforceFederationError("invalid_federation_candidate_minimum")
    if isinstance(maximum_candidates_per_slot, Mapping):
        maximums = {str(key): value for key, value in maximum_candidates_per_slot.items()}
        if set(maximums) != set(slots):
            raise WorkforceFederationError("invalid_federation_candidate_maximum")
    else:
        maximums = {slot_id: maximum_candidates_per_slot for slot_id in slots}
    if any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= 100
        or value < minimums[slot_id]
        for slot_id, value in maximums.items()
    ):
        raise WorkforceFederationError("invalid_federation_candidate_maximum")

    valid_sets: dict[str, dict[str, Any]] = {}
    expiries: list[datetime] = []
    receipts: list[dict[str, Any]] = []
    for source in sources:
        if source in failures:
            receipts.append(
                _source_receipt(
                    {
                        "source": source,
                        "status": "failed",
                        "failureCode": failures[source],
                        "observedAt": _timestamp(clock),
                    }
                )
            )
            continue
        if source not in candidate_sets:
            receipts.append(
                _source_receipt(
                    {
                        "source": source,
                        "status": "failed",
                        "failureCode": "source_not_configured",
                        "observedAt": _timestamp(clock),
                    }
                )
            )
            continue
        try:
            normalized, expiry = _validate_candidate_set(
                candidate_sets[source],
                work_order_id=work_order_id,
                ontology_version=ontology_version,
                slot_ids=slots,
                now=clock,
            )
        except _SourceError as exc:
            receipts.append(
                _source_receipt(
                    {
                        "source": source,
                        "status": "failed",
                        "failureCode": exc.code,
                        "observedAt": _timestamp(clock),
                    }
                )
            )
            continue
        valid_sets[source] = normalized
        expiries.append(expiry)
        receipts.append(
            _source_receipt(
                {
                    "source": source,
                    "status": "succeeded",
                    "selectionSessionId": normalized["selectionSessionId"],
                    "candidateSetDigest": normalized["candidateSetDigest"],
                    "issuedAt": normalized["issuedAt"],
                    "expiresAt": normalized["expiresAt"],
                    "slotCount": len(normalized["slots"]),
                    "candidateCount": sum(len(slot["candidates"]) for slot in normalized["slots"]),
                }
            )
        )

    precedence = {source: index for index, source in enumerate(WORKFORCE_SOURCE_PRECEDENCE)}
    # An immutable release id cannot belong to two definitions. Resolve a
    # cross-source collision by the fixed Local > Cloud > Hub source
    # precedence so a lower-trust appearance can never suppress the
    # higher-priority card. Same-source collisions were already rejected by
    # _validate_candidate_set and remain a source-level failure.
    release_winners: dict[str, tuple[int, str]] = {}
    for source in sources:
        source_set = valid_sets.get(source)
        if source_set is None:
            continue
        for source_slot in source_set["slots"]:
            for candidate in source_slot["candidates"]:
                release_id = candidate["agentReleaseId"]
                winner = release_winners.get(release_id)
                candidate_owner = (precedence[source], candidate["agentDefinitionId"])
                if winner is None or candidate_owner[0] < winner[0]:
                    release_winners[release_id] = candidate_owner
    merged_slots: list[dict[str, Any]] = []
    provenance_rows: list[dict[str, Any]] = []
    for slot_id in slots:
        appearances_by_definition: dict[str, list[dict[str, Any]]] = {}
        precedence_conflicted_definitions: set[str] = set()
        excluded_gaps: set[str] = set()
        slot_had_release_collision = False
        for source in sources:
            source_set = valid_sets.get(source)
            if source_set is None:
                continue
            source_slot = next(slot for slot in source_set["slots"] if slot["slotId"] == slot_id)
            excluded_gaps.update(
                gap for gap in source_slot["coverageGaps"] if gap.startswith("gap:excluded:")
            )
            for source_rank, candidate in enumerate(source_slot["candidates"]):
                release_winner = release_winners[candidate["agentReleaseId"]]
                if release_winner[1] != candidate["agentDefinitionId"]:
                    slot_had_release_collision = True
                    precedence_conflicted_definitions.add(release_winner[1])
                    continue
                definition_id = candidate["agentDefinitionId"]
                attestation = (attestations.get(source) or {}).get(definition_id)
                appearance = {
                    "source": source,
                    "sourceRank": source_rank,
                    "candidateSetDigest": source_set["candidateSetDigest"],
                    "agentReleaseId": candidate["agentReleaseId"],
                    "releaseVersion": candidate["releaseVersion"],
                    "packageHash": candidate["packageHash"],
                    "contentDigest": candidate["contentDigest"],
                    "entityKind": candidate["entityKind"],
                    "candidate": candidate,
                }
                if attestation is not None:
                    try:
                        appearance["lineageAttestation"] = validate_lineage_attestation(attestation)
                    except WorkforceFederationError:
                        # Lineage metadata is used only to prove an exact
                        # cross-source shadow.  A malformed proof must not take
                        # unrelated definitions or sources out of the menu.
                        appearance["lineageAttestationInvalid"] = True
                appearances_by_definition.setdefault(definition_id, []).append(appearance)

        selected_rows: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        quarantined_identity = slot_had_release_collision
        for definition_id, appearances in appearances_by_definition.items():
            merge_exact_shadow = False
            if len(appearances) > 1:
                immutable = {
                    (
                        row["agentReleaseId"],
                        row["releaseVersion"],
                        row["packageHash"],
                        row["contentDigest"],
                        row["entityKind"],
                    )
                    for row in appearances
                }
                lineage = [row.get("lineageAttestation") for row in appearances]
                claims = {
                    (item.get("lineageDigest"), item.get("issuer"))
                    for item in lineage
                    if isinstance(item, Mapping)
                }
                lineage_verified = (
                    len(immutable) == 1
                    and all(isinstance(item, Mapping) for item in lineage)
                    and len(claims) == 1
                    and lineage_verifier is not None
                )
                if lineage_verified:
                    for appearance in appearances:
                        attestation = appearance["lineageAttestation"]
                        expected_claim = workforce_lineage_claim_digest(definition_id, appearance)
                        if (
                            attestation.get("claimDigest") != expected_claim
                            or not isinstance(attestation.get("proof"), Mapping)
                            or lineage_verifier(
                                str(appearance["source"]),
                                definition_id,
                                attestation,
                                {key: value for key, value in appearance.items() if key != "candidate"},
                            )
                            is not True
                        ):
                            lineage_verified = False
                            break
                merge_exact_shadow = lineage_verified
                if not merge_exact_shadow:
                    # Retain only the higher-priority appearance. Publishing a
                    # lower conflicting/unattested claim in provenance would
                    # let it influence later source-pin validation.
                    quarantined_identity = True
                    precedence_conflicted_definitions.add(definition_id)
                    appearances = [
                        min(appearances, key=lambda row: precedence[row["source"]])
                    ]
            selected = min(appearances, key=lambda row: precedence[row["source"]])
            public_appearances = []
            for row in sorted(appearances, key=lambda item: precedence[item["source"]]):
                public_appearances.append(
                    {
                        key: deepcopy(value)
                        for key, value in row.items()
                        if key not in {"candidate", "lineageAttestationInvalid"}
                    }
                )
            provenance = {
                "slotId": slot_id,
                "agentDefinitionId": definition_id,
                "selectedAgentReleaseId": selected["agentReleaseId"],
                "selectedSource": selected["source"],
                "resolution": (
                    "exact_attested_shadow"
                    if merge_exact_shadow
                    else "precedence_conflict"
                    if definition_id in precedence_conflicted_definitions
                    else "unique_definition"
                ),
                "appearances": public_appearances,
            }
            selected_rows.append((definition_id, selected, provenance))

        # Bound the union without letting attacker-chosen canonical IDs from
        # one source crowd out the others. Membership is allocated in a fixed
        # Local/Cloud/Hub round-robin while preserving each source's own
        # content-retrieval rank. Core does no semantic reranking. The bounded
        # host-visible menu is then canonical-sorted for mapping-order-stable
        # bytes, digests, and model input.
        window_truncated = len(selected_rows) > maximums[slot_id]
        if window_truncated:
            by_source: dict[str, list[tuple[str, dict[str, Any], dict[str, Any]]]] = {
                source: [] for source in WORKFORCE_SOURCE_PRECEDENCE
            }
            for row in selected_rows:
                by_source[row[1]["source"]].append(row)
            for rows in by_source.values():
                rows.sort(
                    key=lambda row: (
                        row[1]["sourceRank"],
                        row[0],
                        row[1]["agentReleaseId"],
                    )
                )
            bounded_rows: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
            positions = {source: 0 for source in WORKFORCE_SOURCE_PRECEDENCE}
            while len(bounded_rows) < maximums[slot_id]:
                added = False
                for source in WORKFORCE_SOURCE_PRECEDENCE:
                    position = positions[source]
                    if position < len(by_source[source]):
                        bounded_rows.append(by_source[source][position])
                        positions[source] += 1
                        added = True
                        if len(bounded_rows) == maximums[slot_id]:
                            break
                if not added:
                    break
            selected_rows = bounded_rows
        selected_rows.sort(key=lambda row: (row[0], row[1]["agentReleaseId"]))
        cards = [deepcopy(row[1]["candidate"]) for row in selected_rows]
        coverage: set[str] = set()
        if quarantined_identity:
            # Public evidence remains aggregate and finite: never echo the
            # conflicted definition or an attacker-controlled reason.
            coverage.add("gap:excluded:structural-or-security-invalid")
        if len(cards) < minimums[slot_id]:
            coverage.add("gap:minimum-candidate-count")
        if not cards:
            coverage.add("gap:no-hard-eligible-candidate")
            coverage.update(excluded_gaps)
        merged_slots.append(
            {"slotId": slot_id, "candidates": cards, "coverageGaps": sorted(coverage)}
        )
        provenance_rows.extend(row[2] for row in selected_rows)

    candidate_digest = canonical_digest(
        {
            "workOrderId": work_order_id,
            "ontologyVersion": ontology_version,
            "slots": merged_slots,
            "historyInfluence": "none",
        }
    )
    expiry = min([clock + _MAX_TTL, *expiries]) if expiries else clock + _MAX_TTL
    candidate_set = {
        "schemaVersion": "agentlas.workforce-candidate-set.v1",
        "selectionSessionId": "selection:pending-federation-digest",
        "workOrderId": work_order_id,
        "ontologyVersion": ontology_version,
        "candidateSetDigest": candidate_digest,
        "decisionOwner": "host_llm",
        "historyInfluence": "none",
        "slots": merged_slots,
        "issuedAt": _timestamp(clock),
        "expiresAt": _timestamp(expiry),
    }
    succeeded = len(valid_sets)
    result = {
        "schemaVersion": WORKFORCE_FEDERATION_RESULT_SCHEMA,
        "scope": scope,
        "sources": list(sources),
        "status": "succeeded" if succeeded == len(sources) else "partial" if succeeded else "failed",
        "orderingPolicy": "canonical_identity_no_rerank",
        "candidateSet": candidate_set,
        "candidateProvenance": provenance_rows,
        "sourceReceipts": receipts,
    }
    try:
        _bounded_json_size(result, maximum=_MAX_FEDERATION_RESULT_BYTES)
    except _SourceError as exc:
        raise WorkforceFederationError("federated_result_overflow") from exc
    federation_digest = workforce_federation_digest(result)
    result["federationDigest"] = federation_digest
    candidate_set["selectionSessionId"] = "selection:" + federation_digest.split(":", 1)[1][:24]
    # The candidate-set digest intentionally excludes its transport/session id,
    # while the federation digest seals the source receipts and provenance.
    validate_candidate_set_coverage_gaps(candidate_set)
    return result


def validate_federation_result(
    result: Mapping[str, Any],
    *,
    lineage_verifier: LineageVerifier | None = None,
    now: datetime | None = None,
) -> None:
    """Validate digest continuity and the host-visible no-rerank contract."""

    try:
        _bounded_json_size(result, maximum=_MAX_FEDERATION_RESULT_BYTES)
    except _SourceError as exc:
        raise WorkforceFederationError("invalid_federation_result") from exc

    required_result_keys = {
        "schemaVersion",
        "scope",
        "sources",
        "status",
        "orderingPolicy",
        "candidateSet",
        "candidateProvenance",
        "sourceReceipts",
        "federationDigest",
    }
    if (
        not isinstance(result, Mapping)
        or set(result) != required_result_keys
        or result.get("schemaVersion") != WORKFORCE_FEDERATION_RESULT_SCHEMA
    ):
        raise WorkforceFederationError("invalid_federation_result")
    scope = result.get("scope")
    expected_sources = list(sources_for_scope(str(scope)))
    if result.get("sources") != expected_sources:
        raise WorkforceFederationError("invalid_federation_result")
    if result.get("orderingPolicy") != "canonical_identity_no_rerank":
        raise WorkforceFederationError("invalid_federation_result")
    candidate_set = result.get("candidateSet")
    candidate_set_keys = {
        "schemaVersion",
        "selectionSessionId",
        "workOrderId",
        "ontologyVersion",
        "candidateSetDigest",
        "decisionOwner",
        "historyInfluence",
        "slots",
        "issuedAt",
        "expiresAt",
    }
    if not isinstance(candidate_set, Mapping) or set(candidate_set) != candidate_set_keys:
        raise WorkforceFederationError("invalid_federation_result")
    if (
        candidate_set.get("schemaVersion") != "agentlas.workforce-candidate-set.v1"
        or candidate_set.get("decisionOwner") != "host_llm"
        or candidate_set.get("historyInfluence") != "none"
        or not _valid_id(candidate_set.get("selectionSessionId"))
        or not _valid_id(candidate_set.get("workOrderId"))
        or not _valid_id(candidate_set.get("ontologyVersion"))
        or not _valid_hash(candidate_set.get("candidateSetDigest"))
    ):
        raise WorkforceFederationError("invalid_federation_result")
    issued_at = _result_timestamp(candidate_set.get("issuedAt"))
    expires_at = _result_timestamp(candidate_set.get("expiresAt"))
    if expires_at <= issued_at or expires_at - issued_at > _MAX_TTL:
        raise WorkforceFederationError("invalid_federation_result")
    if now is not None:
        validation_clock = _clock(now)
        if issued_at > validation_clock + timedelta(seconds=5):
            raise WorkforceFederationError("federation_issued_in_future")
        if expires_at <= validation_clock:
            raise WorkforceFederationError("federation_session_expired")
    slots = candidate_set.get("slots")
    if not isinstance(slots, list) or not 1 <= len(slots) <= 32:
        raise WorkforceFederationError("invalid_federation_result")
    observed_slot_ids: set[str] = set()
    release_definitions: dict[str, str] = {}
    for slot in slots:
        if not isinstance(slot, Mapping) or set(slot) != {"slotId", "candidates", "coverageGaps"}:
            raise WorkforceFederationError("invalid_federation_result")
        slot_id = slot.get("slotId")
        candidates = slot.get("candidates")
        if not _valid_id(slot_id) or slot_id in observed_slot_ids or not isinstance(candidates, list):
            raise WorkforceFederationError("invalid_federation_result")
        observed_slot_ids.add(str(slot_id))
        if len(candidates) > 100:
            raise WorkforceFederationError("invalid_federation_result")
        definitions: list[str] = []
        for candidate in candidates:
            try:
                normalized = _validate_candidate(candidate)
            except _SourceError as exc:
                raise WorkforceFederationError("invalid_federation_result") from exc
            definitions.append(normalized["agentDefinitionId"])
            release_id = normalized["agentReleaseId"]
            previous_definition = release_definitions.setdefault(release_id, normalized["agentDefinitionId"])
            if previous_definition != normalized["agentDefinitionId"]:
                raise WorkforceFederationError("release_definition_conflict")
        if definitions != sorted(definitions) or len(definitions) != len(set(definitions)):
            raise WorkforceFederationError("invalid_federation_result")
    try:
        validate_candidate_set_coverage_gaps(candidate_set)
    except ValueError as exc:
        raise WorkforceFederationError("invalid_federation_result") from exc
    expected_candidate_digest = canonical_digest(
        {
            "workOrderId": candidate_set["workOrderId"],
            "ontologyVersion": candidate_set["ontologyVersion"],
            "slots": candidate_set["slots"],
            "historyInfluence": "none",
        }
    )
    if candidate_set.get("candidateSetDigest") != expected_candidate_digest:
        raise WorkforceFederationError("candidate_set_digest_mismatch")

    receipts = result.get("sourceReceipts")
    if not isinstance(receipts, list) or len(receipts) != len(expected_sources):
        raise WorkforceFederationError("invalid_federation_result")
    receipt_by_source: dict[str, Mapping[str, Any]] = {}
    failed_count = 0
    for receipt in receipts:
        if not isinstance(receipt, Mapping) or receipt.get("source") not in expected_sources:
            raise WorkforceFederationError("invalid_federation_result")
        source = str(receipt["source"])
        if source in receipt_by_source:
            raise WorkforceFederationError("invalid_federation_result")
        receipt_by_source[source] = receipt
        if receipt.get("receiptDigest") != canonical_digest(
            {key: value for key, value in receipt.items() if key != "receiptDigest"}
        ):
            raise WorkforceFederationError("source_receipt_digest_mismatch")
        if receipt.get("status") == "succeeded":
            expected_keys = {
                "source",
                "status",
                "selectionSessionId",
                "candidateSetDigest",
                "issuedAt",
                "expiresAt",
                "slotCount",
                "candidateCount",
                "receiptDigest",
            }
            if (
                set(receipt) != expected_keys
                or not _valid_id(receipt.get("selectionSessionId"))
                or not _valid_hash(receipt.get("candidateSetDigest"))
                or not isinstance(receipt.get("slotCount"), int)
                or not isinstance(receipt.get("candidateCount"), int)
            ):
                raise WorkforceFederationError("invalid_federation_result")
            _result_timestamp(receipt.get("issuedAt"))
            _result_timestamp(receipt.get("expiresAt"))
        elif receipt.get("status") == "failed":
            failed_count += 1
            if set(receipt) != {
                "source",
                "status",
                "failureCode",
                "observedAt",
                "receiptDigest",
            } or receipt.get("failureCode") not in _FAILURES:
                raise WorkforceFederationError("invalid_federation_result")
            _result_timestamp(receipt.get("observedAt"))
        else:
            raise WorkforceFederationError("invalid_federation_result")
    succeeded_count = len(receipts) - failed_count
    expected_status = "succeeded" if failed_count == 0 else "partial" if succeeded_count else "failed"
    if result.get("status") != expected_status:
        raise WorkforceFederationError("invalid_federation_result")

    digest = workforce_federation_digest(result)
    if result.get("federationDigest") != digest:
        raise WorkforceFederationError("federation_digest_mismatch")
    expected_session = "selection:" + digest.split(":", 1)[1][:24]
    if candidate_set.get("selectionSessionId") != expected_session:
        raise WorkforceFederationError("federation_digest_mismatch")
    cards = {
        (slot["slotId"], candidate["agentDefinitionId"], candidate["agentReleaseId"]): candidate
        for slot in candidate_set["slots"]
        for candidate in slot["candidates"]
    }
    card_keys = set(cards)
    provenance = result.get("candidateProvenance")
    if not isinstance(provenance, list) or len(provenance) != len(card_keys):
        raise WorkforceFederationError("invalid_federation_result")
    provenance_keys = {
        (row.get("slotId"), row.get("agentDefinitionId"), row.get("selectedAgentReleaseId"))
        for row in provenance
        if isinstance(row, Mapping)
    }
    if provenance_keys != card_keys:
        raise WorkforceFederationError("invalid_federation_result")
    seen_provenance: set[tuple[str, str, str]] = set()
    precedence = {source: index for index, source in enumerate(WORKFORCE_SOURCE_PRECEDENCE)}
    for row in provenance:
        if not isinstance(row, Mapping) or set(row) != {
            "slotId",
            "agentDefinitionId",
            "selectedAgentReleaseId",
            "selectedSource",
            "resolution",
            "appearances",
        }:
            raise WorkforceFederationError("invalid_federation_result")
        key = (row["slotId"], row["agentDefinitionId"], row["selectedAgentReleaseId"])
        card = cards.get(key)
        if card is None or key in seen_provenance:
            raise WorkforceFederationError("invalid_federation_result")
        seen_provenance.add(key)
        appearances = row.get("appearances")
        if not isinstance(appearances, list) or not appearances:
            raise WorkforceFederationError("invalid_federation_result")
        appearance_sources: set[str] = set()
        selected: Mapping[str, Any] | None = None
        immutable_claims: set[tuple[Any, ...]] = set()
        lineage_claims: set[tuple[Any, Any]] = set()
        for appearance in appearances:
            required_appearance = {
                "source",
                "sourceRank",
                "candidateSetDigest",
                "agentReleaseId",
                "releaseVersion",
                "packageHash",
                "contentDigest",
                "entityKind",
            }
            if (
                not isinstance(appearance, Mapping)
                or not required_appearance <= set(appearance)
                or set(appearance) - (required_appearance | {"lineageAttestation"})
            ):
                raise WorkforceFederationError("invalid_federation_result")
            source = appearance.get("source")
            receipt = receipt_by_source.get(str(source))
            if source in appearance_sources or not receipt or receipt.get("status") != "succeeded":
                raise WorkforceFederationError("invalid_federation_result")
            appearance_sources.add(str(source))
            if appearance.get("candidateSetDigest") != receipt.get("candidateSetDigest"):
                raise WorkforceFederationError("selected_release_source_pin_mismatch")
            if (
                not isinstance(appearance.get("sourceRank"), int)
                or not 0 <= appearance["sourceRank"] < 100
                or not _valid_id(appearance.get("agentReleaseId"))
                or not _valid_hash(appearance.get("packageHash"))
                or not _valid_hash(appearance.get("contentDigest"))
            ):
                raise WorkforceFederationError("invalid_federation_result")
            immutable_claims.add(
                (
                    appearance["agentReleaseId"],
                    appearance["releaseVersion"],
                    appearance["packageHash"],
                    appearance["contentDigest"],
                    appearance["entityKind"],
                )
            )
            if "lineageAttestation" in appearance:
                attestation = validate_lineage_attestation(appearance["lineageAttestation"])
                lineage_claims.add((attestation["lineageDigest"], attestation["issuer"]))
            if source == row.get("selectedSource"):
                selected = appearance
        expected_source = min(appearance_sources, key=lambda source: precedence[source])
        if row.get("selectedSource") != expected_source or selected is None:
            raise WorkforceFederationError("invalid_federation_result")
        if len(appearances) > 1:
            if row.get("resolution") != "exact_attested_shadow" or len(immutable_claims) != 1:
                raise WorkforceFederationError("invalid_federation_result")
            if len(lineage_claims) != 1 or any("lineageAttestation" not in item for item in appearances):
                raise WorkforceFederationError("invalid_federation_result")
            if lineage_verifier is None:
                raise WorkforceFederationError("definition_lineage_unproven")
            for appearance in appearances:
                attestation = appearance["lineageAttestation"]
                if (
                    attestation.get("claimDigest")
                    != workforce_lineage_claim_digest(str(row["agentDefinitionId"]), appearance)
                    or not isinstance(attestation.get("proof"), Mapping)
                    or lineage_verifier(
                        str(appearance["source"]),
                        str(row["agentDefinitionId"]),
                        attestation,
                        appearance,
                    )
                    is not True
                ):
                    raise WorkforceFederationError("definition_lineage_unproven")
        elif row.get("resolution") not in {"unique_definition", "precedence_conflict"}:
            raise WorkforceFederationError("invalid_federation_result")
        elif row.get("resolution") == "precedence_conflict":
            source_slot = next(
                slot for slot in candidate_set["slots"]
                if slot["slotId"] == row["slotId"]
            )
            if "gap:excluded:structural-or-security-invalid" not in source_slot["coverageGaps"]:
                raise WorkforceFederationError("invalid_federation_result")
        for field in ("agentReleaseId", "releaseVersion", "packageHash", "contentDigest", "entityKind"):
            if selected.get(field) != card.get(field):
                raise WorkforceFederationError("selected_release_claim_mismatch")


__all__ = [
    "WORKFORCE_FEDERATION_RESULT_SCHEMA",
    "WORKFORCE_LINEAGE_ATTESTATION_SCHEMA",
    "WORKFORCE_SOURCE_FAILURE_CODES",
    "WORKFORCE_SOURCE_PRECEDENCE",
    "WORKFORCE_SOURCE_SCOPES",
    "WorkforceFederationError",
    "LineageVerifier",
    "federate_candidate_sets",
    "sources_for_scope",
    "validate_lineage_attestation",
    "validate_federation_result",
    "workforce_federation_digest",
    "workforce_lineage_claim_digest",
]
