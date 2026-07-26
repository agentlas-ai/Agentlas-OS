"""Host-neutral model allocation contract and policy safety resolver.

Agentlas Core does not call an LLM.  A parent/leader model authors the workload
decision, while this module validates that decision against the host's actual
model inventory and operator policy.  User task text is deliberately not an
input to the resolver, so prompt keywords can never directly buy a larger
model.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Mapping


SCHEMA_VERSION = "agentlas.model-allocation-decision.v1"
TIERS = ("economy", "balanced", "frontier")
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
PHASES = ("plan", "execute", "verify", "synthesize", "route", "clarify")
TIER_RANK = {tier: index for index, tier in enumerate(TIERS)}
EFFORT_RANK = {effort: index for index, effort in enumerate(EFFORTS)}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{2,255}$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
DECISION_FIELDS = {
    "schemaVersion",
    "decisionId",
    "packetId",
    "agentId",
    "phase",
    "authoredBy",
    "selectorVersion",
    "inputFeatureHash",
    "features",
    "selection",
    "reasonCodes",
}
REQUIRED_DECISION_FIELDS = {
    "schemaVersion",
    "decisionId",
    "phase",
    "authoredBy",
    "selectorVersion",
    "features",
    "selection",
    "reasonCodes",
}
FEATURE_FIELDS = {
    "complexity",
    "risk",
    "inputTokens",
    "expectedOutputTokens",
    "toolRequired",
    "multimodalRequired",
    "parallelFanout",
}
SELECTION_FIELDS = {
    "tier",
    "modelClass",
    "effort",
    "exactModelId",
    "provider",
    "fallbackTiers",
    "maxEscalations",
}
REQUIRED_SELECTION_FIELDS = {"tier", "effort", "fallbackTiers", "maxEscalations"}

def _text(value: Any) -> str:
    return str(value or "").strip()


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    parsed = max(minimum, parsed)
    return min(maximum, parsed) if maximum is not None else parsed


def _is_integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _valid_nullable_id(value: Any) -> bool:
    return value is None or isinstance(value, str) and ID_RE.fullmatch(value) is not None


def _valid_nullable_text(value: Any, maximum: int) -> bool:
    return value is None or isinstance(value, str) and len(value) <= maximum


def normalize_tier(value: Any) -> str | None:
    normalized = _text(value).lower()
    return normalized if normalized in TIERS else None


def normalize_effort(value: Any) -> str | None:
    normalized = _text(value).lower()
    return normalized if normalized in EFFORTS else None


def validate_allocation_decision(raw: Mapping[str, Any] | None) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate the parent AI's control-plane output.

    The decision contains derived workload features and reason codes, not raw
    task/prompt content.  Unknown fields are ignored in the normalized view but
    reported so hosts can reject strict-contract violations.
    """

    if not isinstance(raw, Mapping):
        return None, ["decision_not_object"]

    issues: list[str] = []
    if missing := sorted(REQUIRED_DECISION_FIELDS - set(raw)):
        issues.append("missing_required_fields:" + ",".join(missing))
    if unknown := sorted(set(raw) - DECISION_FIELDS):
        issues.append("unknown_fields:" + ",".join(unknown))

    if raw.get("schemaVersion") != SCHEMA_VERSION:
        issues.append("unsupported_schema_version")
    decision_id = _text(raw.get("decisionId"))
    if not ID_RE.fullmatch(decision_id):
        issues.append("missing_decision_id")
    authored_by = _text(raw.get("authoredBy")).lower()
    if authored_by not in {"parent-ai", "leader-ai", "user-pin"}:
        issues.append("untrusted_decision_author")
    phase = _text(raw.get("phase")).lower()
    if phase not in PHASES:
        issues.append("invalid_phase")
    selector_version = _text(raw.get("selectorVersion"))
    if not ID_RE.fullmatch(selector_version):
        issues.append("invalid_selector_version")
    raw_feature_hash_value = raw.get("inputFeatureHash")
    raw_feature_hash = _text(raw_feature_hash_value)
    if "inputFeatureHash" in raw and raw_feature_hash_value is not None and not (
        isinstance(raw_feature_hash_value, str) and HASH_RE.fullmatch(raw_feature_hash_value)
    ):
        issues.append("invalid_input_feature_hash")
    for field in ("packetId", "agentId"):
        if field in raw and not _valid_nullable_id(raw.get(field)):
            issues.append(f"invalid_{field}")

    features_raw = raw.get("features")
    if not isinstance(features_raw, Mapping):
        features_raw = {}
        issues.append("features_not_object")
    else:
        if missing := sorted(FEATURE_FIELDS - set(features_raw)):
            issues.append("missing_feature_fields:" + ",".join(missing))
        if unknown := sorted(set(features_raw) - FEATURE_FIELDS):
            issues.append("unknown_feature_fields:" + ",".join(unknown))
    complexity = _text(features_raw.get("complexity")).lower()
    risk = _text(features_raw.get("risk")).lower()
    if complexity not in {"simple", "moderate", "complex"}:
        issues.append("invalid_complexity")
    if risk not in {"low", "moderate", "high", "critical"}:
        issues.append("invalid_risk")
    for field in ("inputTokens", "expectedOutputTokens"):
        if not _is_integer(features_raw.get(field)) or features_raw.get(field) < 0:
            issues.append(f"invalid_{field}")
    for field in ("toolRequired", "multimodalRequired"):
        if not isinstance(features_raw.get(field), bool):
            issues.append(f"invalid_{field}")
    parallel_fanout = features_raw.get("parallelFanout")
    if not _is_integer(parallel_fanout) or not 1 <= parallel_fanout <= 128:
        issues.append("invalid_parallelFanout")

    selection_raw = raw.get("selection")
    if not isinstance(selection_raw, Mapping):
        selection_raw = {}
        issues.append("selection_not_object")
    else:
        if missing := sorted(REQUIRED_SELECTION_FIELDS - set(selection_raw)):
            issues.append("missing_selection_fields:" + ",".join(missing))
        if unknown := sorted(set(selection_raw) - SELECTION_FIELDS):
            issues.append("unknown_selection_fields:" + ",".join(unknown))
    tier = normalize_tier(selection_raw.get("tier"))
    effort = normalize_effort(selection_raw.get("effort"))
    if tier is None:
        issues.append("invalid_tier")
    if effort is None:
        issues.append("invalid_effort")
    if not _valid_nullable_text(selection_raw.get("modelClass"), 32):
        issues.append("invalid_model_class")
    if not _valid_nullable_text(selection_raw.get("exactModelId"), 255):
        issues.append("invalid_exact_model_id")
    if not _valid_nullable_text(selection_raw.get("provider"), 80):
        issues.append("invalid_provider")
    raw_fallbacks = selection_raw.get("fallbackTiers")
    if not isinstance(raw_fallbacks, list):
        raw_fallbacks = []
        issues.append("fallback_tiers_not_array")
    elif len(raw_fallbacks) > 3:
        issues.append("too_many_fallback_tiers")
    fallback_tiers: list[str] = []
    for item in raw_fallbacks:
        candidate = normalize_tier(item)
        if candidate is None:
            issues.append("invalid_fallback_tier")
        elif candidate in fallback_tiers:
            issues.append("duplicate_fallback_tier")
        else:
            fallback_tiers.append(candidate)
    max_escalations = selection_raw.get("maxEscalations")
    if not _is_integer(max_escalations) or not 0 <= max_escalations <= 2:
        issues.append("invalid_max_escalations")

    raw_reason_codes = raw.get("reasonCodes")
    if not isinstance(raw_reason_codes, list):
        raw_reason_codes = []
        issues.append("reason_codes_not_array")
    elif not 1 <= len(raw_reason_codes) <= 12:
        issues.append("invalid_reason_code_count")
    reason_codes = [
        _text(item)
        for item in raw_reason_codes
        if isinstance(item, str) and ID_RE.fullmatch(item)
    ][:12]
    if len(reason_codes) != len(raw_reason_codes):
        issues.append("invalid_reason_code")
    if len(reason_codes) != len(set(reason_codes)):
        issues.append("duplicate_reason_code")
    if not reason_codes:
        issues.append("missing_reason_codes")

    normalized = {
        "schemaVersion": SCHEMA_VERSION,
        "decisionId": decision_id,
        "packetId": _text(raw.get("packetId")) or None,
        "agentId": _text(raw.get("agentId")) or None,
        "phase": phase,
        "authoredBy": authored_by,
        "selectorVersion": selector_version,
        "inputFeatureHash": raw_feature_hash if HASH_RE.fullmatch(raw_feature_hash) else None,
        "features": {
            "complexity": complexity,
            "risk": risk,
            "inputTokens": _bounded_int(features_raw.get("inputTokens"), default=0, minimum=0),
            "expectedOutputTokens": _bounded_int(features_raw.get("expectedOutputTokens"), default=0, minimum=0),
            "toolRequired": bool(features_raw.get("toolRequired")),
            "multimodalRequired": bool(features_raw.get("multimodalRequired")),
            "parallelFanout": _bounded_int(features_raw.get("parallelFanout"), default=1, minimum=1, maximum=128),
        },
        "selection": {
            "tier": tier,
            "modelClass": _text(selection_raw.get("modelClass")).lower() or None,
            "effort": effort,
            "exactModelId": _text(selection_raw.get("exactModelId")) or None,
            "provider": _text(selection_raw.get("provider")) or None,
            "fallbackTiers": fallback_tiers,
            "maxEscalations": _bounded_int(max_escalations, default=0, minimum=0, maximum=2),
        },
        "reasonCodes": reason_codes,
    }
    return normalized, issues


def _normalize_inventory(raw_inventory: list[Any] | None) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_inventory or []):
        if isinstance(raw, str):
            raw = {"model": raw, "session_id": raw}
        if not isinstance(raw, Mapping):
            continue
        model_id = _text(raw.get("model") or raw.get("model_id") or raw.get("id"))
        if not model_id:
            continue
        tier = normalize_tier(raw.get("tier") or raw.get("cost_tier") or raw.get("costTier"))
        raw_efforts = raw.get("supported_efforts")
        efforts_known = isinstance(raw_efforts, list)
        if not efforts_known:
            raw_efforts = []
        efforts = [
            effort
            for item in raw_efforts
            if (effort := normalize_effort(item))
        ]
        raw_context_window = raw.get("context_window")
        context_window = (
            raw_context_window
            if _is_integer(raw_context_window) and raw_context_window >= 0
            else None
        )
        supports_tools = raw.get("supports_tools")
        supports_multimodal = raw.get("supports_multimodal")
        inventory.append(
            {
                "index": index,
                "session_id": _text(raw.get("session_id") or raw.get("id") or model_id),
                "provider": _text(raw.get("provider") or raw.get("family") or "host").lower(),
                "model_id": model_id,
                "tier": tier,
                "supported_efforts": efforts or ["none"],
                "supported_efforts_known": efforts_known,
                "context_window": context_window,
                "supports_tools": supports_tools if isinstance(supports_tools, bool) else None,
                "supports_multimodal": supports_multimodal if isinstance(supports_multimodal, bool) else None,
                "capabilities": [str(item).lower() for item in (raw.get("capabilities") or [])],
            }
        )
    return inventory


def _bounded_effort(requested: str, supported: list[str], max_effort: str) -> tuple[str, bool]:
    ceiling = EFFORT_RANK[max_effort]
    requested_rank = min(EFFORT_RANK[requested], ceiling)
    eligible = [item for item in supported if EFFORT_RANK[item] <= requested_rank]
    if eligible:
        resolved = max(eligible, key=lambda item: EFFORT_RANK[item])
    else:
        resolved = min(supported, key=lambda item: EFFORT_RANK[item])
    return resolved, resolved != requested


def _feature_hash(decision: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {"features": decision.get("features"), "phase": decision.get("phase")},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def resolve_model_allocation(
    raw_decision: Mapping[str, Any] | None,
    raw_inventory: list[Any] | None,
    *,
    policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a parent AI decision inside deterministic host guardrails."""

    decision, issues = validate_allocation_decision(raw_decision)
    inventory = _normalize_inventory(raw_inventory)
    policy = dict(policy or {})
    current_model_id = _text(policy.get("currentModelId"))
    pinned_model_id = _text(policy.get("pinnedModelId"))
    configured_max_tier = normalize_tier(policy.get("maxTier"))
    max_tier = configured_max_tier or "frontier"
    max_effort = normalize_effort(policy.get("maxEffort")) or "max"
    required_capabilities = {str(item).lower() for item in (policy.get("requiredCapabilities") or [])}

    def compatible(item: Mapping[str, Any]) -> bool:
        if decision is None:
            return True
        features = decision["features"]
        total_tokens = features["inputTokens"] + features["expectedOutputTokens"]
        if item["tier"] is None:
            return False
        if total_tokens and (
            item["context_window"] is None or item["context_window"] < total_tokens
        ):
            return False
        if features["toolRequired"] and item["supports_tools"] is not True:
            return False
        if features["multimodalRequired"] and item["supports_multimodal"] is not True:
            return False
        if required_capabilities and not required_capabilities.issubset(set(item["capabilities"])):
            return False
        if decision["selection"]["effort"] != "none" and not item["supported_efforts_known"]:
            return False
        return True

    compatible_inventory = [item for item in inventory if compatible(item)]
    selected: dict[str, Any] | None = None
    status = "resolved"
    reasons: list[str] = []

    if pinned_model_id:
        pinned_candidates = [
            item for item in compatible_inventory if item["model_id"] == pinned_model_id
        ]
        if len(pinned_candidates) == 1:
            selected = pinned_candidates[0]
            status = "user-pin"
            reasons.append("explicit_user_or_scope_pin")
        elif len(pinned_candidates) > 1:
            reasons.append("pinned_model_ambiguous_across_sessions")
        else:
            reasons.append("pinned_model_unavailable_or_incompatible")

    if selected is None and decision is not None and not issues:
        requested_tier = decision["selection"]["tier"]
        if TIER_RANK[requested_tier] > TIER_RANK[max_tier]:
            requested_tier = max_tier
            reasons.append("tier_clamped_by_cost_policy")
        tiers = [requested_tier]
        tiers.extend(
            tier
            for tier in decision["selection"]["fallbackTiers"]
            if tier not in tiers and TIER_RANK[tier] <= TIER_RANK[max_tier]
        )
        exact = decision["selection"]["exactModelId"]
        if exact:
            exact_candidates = [
                item for item in compatible_inventory if item["model_id"] == exact
            ]
            requested_provider = _text(decision["selection"]["provider"]).lower()
            if requested_provider:
                exact_candidates = [
                    item for item in exact_candidates if item["provider"] == requested_provider
                ]
            exact_candidate = exact_candidates[0] if len(exact_candidates) == 1 else None
            if len(exact_candidates) > 1:
                reasons.append("requested_exact_model_ambiguous_across_sessions")
            elif exact_candidate is None:
                reasons.append("requested_exact_model_unavailable")
            elif exact_candidate["tier"] is None and configured_max_tier is not None:
                reasons.append("requested_exact_model_cost_tier_unknown")
            elif exact_candidate["tier"] is not None and TIER_RANK[exact_candidate["tier"]] > TIER_RANK[max_tier]:
                reasons.append("requested_exact_model_exceeds_cost_policy")
            elif exact_candidate["tier"] is not None and exact_candidate["tier"] not in tiers:
                reasons.append("requested_exact_model_tier_mismatch")
            else:
                selected = exact_candidate
        else:
            tier_candidates = [item for item in compatible_inventory if item["tier"] in tiers]
            current_candidate = next(
                (item for item in tier_candidates if item["model_id"] == current_model_id),
                None,
            )
            if current_candidate is not None:
                selected = current_candidate
                if current_candidate["tier"] != requested_tier:
                    reasons.append("same_policy_fallback_tier_used")
            elif len(tier_candidates) == 1:
                selected = tier_candidates[0]
                reasons.append("unique_live_candidate_used")
            elif len(tier_candidates) > 1:
                reasons.append("parent_exact_model_required_for_ambiguous_inventory")

    if selected is None:
        if decision is None or issues:
            selected = next((item for item in compatible_inventory if item["model_id"] == current_model_id), None)
        status = "fallback-current" if selected else "unresolved"
        reasons.append("parent_decision_missing_or_invalid" if decision is None or issues else "no_compatible_requested_model")

    requested_effort = decision["selection"]["effort"] if decision and not issues else "none"
    resolved_effort = "none"
    if selected:
        resolved_effort, effort_changed = _bounded_effort(requested_effort, selected["supported_efforts"], max_effort)
        if effort_changed:
            reasons.append("effort_clamped_to_host_support")

    risk = decision["features"]["risk"] if decision else "unknown"
    receipt = {
        "schemaVersion": "agentlas.model-allocation-receipt.v1",
        "decisionId": decision["decisionId"] if decision else None,
        "packetId": decision["packetId"] if decision else None,
        "status": status,
        "requested": {
            "tier": decision["selection"]["tier"] if decision else None,
            "modelClass": decision["selection"]["modelClass"] if decision else None,
            "modelId": decision["selection"]["exactModelId"] if decision else None,
            "effort": requested_effort,
        },
        "resolved": {
            "tier": selected["tier"] if selected else None,
            "provider": selected["provider"] if selected else None,
            "modelId": selected["model_id"] if selected else None,
            "sessionId": selected["session_id"] if selected else None,
            "effort": resolved_effort,
        },
        "reasonCodes": list(dict.fromkeys((decision["reasonCodes"] if decision else []) + reasons)),
        "inputFeatureHash": decision.get("inputFeatureHash") or _feature_hash(decision) if decision else None,
        "selectorVersion": decision["selectorVersion"] if decision else "deterministic-host-fallback",
        "independentVerificationRequired": risk in {"high", "critical"},
        "validationIssues": issues,
        "privacy": {"rawPromptIncluded": False, "rawTranscriptIncluded": False},
    }
    return receipt
