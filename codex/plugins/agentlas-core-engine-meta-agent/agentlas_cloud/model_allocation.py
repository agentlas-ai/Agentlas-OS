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
# 알려진 값은 정책 상한과 비교할 "랭크 폴백"으로만 쓴다 — "유효한가" 게이트로 쓰지 않는다.
# 2026-07-28 라이브 실측: codex debug models가 gpt-5.6-sol에서 "ultra"(자동 위임) 리즌
# 레벨을 실제로 광고했다. 이 튜플로 게이트를 걸면 provider가 이미 출시한 값을 우리가
# 스키마 검증 단계에서 조용히 거절한다(전체 decision이 invalid_effort로 폐기됨). 새 값이
# 나올 때마다 이 튜플을 고치는 대신, 세션 인벤토리가 보고하는 모델 자체 순서(=능력 랭크,
# provider 계약)를 신뢰하는 쪽으로 옮겼다 — 아래 normalize_effort/_bounded_effort 참고.
EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
EFFORT_TOKEN_RE = re.compile(r"^[a-z][a-z0-9-]{0,23}$")
PHASES = ("plan", "execute", "verify", "synthesize", "route", "clarify")
MODEL_ROLES = ("orchestrator", "worker")
ORCHESTRATOR_PHASES = frozenset({"plan", "verify", "synthesize", "route", "clarify"})
INVOCATION_STAGE_PHASES = {
    "plan": "plan",
    "planner": "plan",
    "leader": "plan",
    "manager-plan": "plan",
    "nested-manager": "plan",
    "build": "execute",
    "execute": "execute",
    "worker": "execute",
    "delegate": "execute",
    "task": "execute",
    "verify": "verify",
    "verifier": "verify",
    "synthesize": "synthesize",
    "synthesis": "synthesize",
    "manager-synthesis": "synthesize",
    "route": "route",
    "clarify": "clarify",
}
TIER_RANK = {tier: index for index, tier in enumerate(TIERS)}
# 알려진 값의 폴백 랭크만 — 미지의 값을 이 표로 거절하지 않는다(_bounded_effort 참고).
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
    # 신택스만 검증한다 — 화이트리스트 존재는 게이트로 쓰지 않는다(위 EFFORTS 주석).
    # 이 함수는 parent-AI가 요청한 값과, 세션 인벤토리가 보고한 모델 자체 지원 목록
    # 양쪽에 다 쓰인다 — 열어두면 두 경로 모두에서 새 값이 조용히 안 드롭된다.
    normalized = _text(value).lower()
    return normalized if EFFORT_TOKEN_RE.fullmatch(normalized) else None


def normalize_model_role(value: Any) -> str | None:
    normalized = _text(value).lower()
    return normalized if normalized in MODEL_ROLES else None


def normalize_phase(value: Any) -> str | None:
    normalized = _text(value).lower()
    return normalized if normalized in PHASES else None


def model_role_for_phase(value: Any) -> str | None:
    phase = normalize_phase(value)
    if phase == "execute":
        return "worker"
    if phase in ORCHESTRATOR_PHASES:
        return "orchestrator"
    return None


def canonical_phase_for_stage(value: Any) -> str | None:
    """Map a host-owned invocation stage to the shared allocation phase."""

    return INVOCATION_STAGE_PHASES.get(_text(value).lower())


def model_role_for_stage(value: Any) -> str:
    """Unknown host stages stay on the quality-first orchestrator path."""

    return model_role_for_phase(canonical_phase_for_stage(value)) or "orchestrator"


def _policy_for_role(
    raw_policy: Mapping[str, Any],
    role: str,
) -> tuple[dict[str, Any], bool]:
    """Resolve one role without letting orchestrator fall through to worker."""

    flat_fields = {
        "currentModelId",
        "pinnedModelId",
        "pinnedProvider",
        "maxTier",
        "maxEffort",
        "requiredCapabilities",
    }
    resolved = {key: raw_policy[key] for key in flat_fields if key in raw_policy}
    orchestrator = raw_policy.get("orchestrator")
    worker = raw_policy.get("worker")
    orchestrator_policy = dict(orchestrator) if isinstance(orchestrator, Mapping) else {}
    worker_policy = dict(worker) if isinstance(worker, Mapping) else {}

    if role == "orchestrator":
        resolved.update({key: value for key, value in orchestrator_policy.items() if key != "inherit"})
        return resolved, False

    if not worker_policy or worker_policy.get("inherit") is True:
        resolved.update({key: value for key, value in orchestrator_policy.items() if key != "inherit"})
        return resolved, True

    resolved.update({key: value for key, value in worker_policy.items() if key != "inherit"})
    return resolved, False


def validate_allocation_decision(raw: Mapping[str, Any] | None) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate the parent AI's control-plane output.

    The decision contains derived workload features and reason codes, not raw
    task/prompt content.  Unknown fields are ignored in the normalized view but
    reported so hosts can reject strict-contract violations.
    """

    if raw is None:
        return None, []
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


def _effort_rank(value: str, supported: list[str]) -> float:
    """Capability rank for one effort value against one model's own live list.

    The model's own advertised order is the authoritative rank (provider
    contract: position 0..n-1 is ascending capability — verified live against
    Codex's `supported_reasoning_levels`, which listed low/medium/high/xhigh/
    max/ultra in that exact order).

    A value the model didn't advertise but that we still recognize by name
    (e.g. "medium" requested against a model that only lists low/xhigh/max)
    is inserted at its correct relative position among supported's own
    known-rankable entries — a half-step after the last one whose known
    rank is <= its own. Always ranking it "after everything" (the earlier,
    buggy scheme) silently escalated a mid-range request past every
    higher tier the model actually offers, since none of them scored above
    a threshold that was itself always the highest.

    A value neither advertised nor recognized has no provable rank, so it
    ranks last of all — it can never look "low enough" to pass a ceiling
    it wasn't proven to satisfy.
    """
    if value in supported:
        return float(supported.index(value))
    known = EFFORT_RANK.get(value)
    if known is None:
        return float("inf")
    insert_after = -1
    for index, item in enumerate(supported):
        item_known = EFFORT_RANK.get(item)
        if item_known is not None and item_known <= known:
            insert_after = index
    return insert_after + 0.5


def _known_effort_rank(value: str) -> int:
    """Pure global rank, independent of any one model's advertised subset.

    max_effort is an operator-configured policy ceiling in Agentlas's own
    vocabulary, not a specific model's supported list. Ranking it via
    _effort_rank(value, supported) breaks when supported is a narrow subset:
    e.g. supported=["max"], max_effort="high" would rank "high" *after*
    "max" (len(supported) + known-index offset), inverting the ceiling so it
    never clamps. Compare both sides against the known table only instead.
    """
    return EFFORT_RANK.get(value, len(EFFORT_RANK))


def _bounded_effort(requested: str, supported: list[str], max_effort: str) -> tuple[str, bool]:
    if not supported:
        return requested, False
    ceiling_rank = _known_effort_rank(max_effort)
    requested_rank = _effort_rank(requested, supported)
    eligible = [
        item
        for item in supported
        if _effort_rank(item, supported) <= requested_rank and _known_effort_rank(item) <= ceiling_rank
    ]
    if eligible:
        resolved = max(eligible, key=lambda item: _effort_rank(item, supported))
    else:
        # 요청/상한 어느 쪽과도 동시에 맞는 값이 없다 — 모델이 제공하는 가장 낮은
        # 값으로 최대한 보수적으로 내려간다(원래 폴백과 동일, 상한을 우선시해
        # 요청보다 위로 에스컬레이션하지 않는다).
        resolved = min(supported, key=lambda item: _effort_rank(item, supported))
    return resolved, resolved != requested


def _feature_hash(decision: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {"features": decision.get("features"), "phase": decision.get("phase")},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _validate_escalation(raw: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate a host-owned worker-to-orchestrator escalation request.

    The only accepted shape is the bounded tiering contract: the worker role
    failed the same task exactly twice and this call is the single allowed
    orchestrator retry.  Any other shape is recorded as an issue and the call
    resolves un-escalated — partial escalation metadata must never reach a
    receipt.
    """

    if raw is None:
        return None, []
    if (
        not isinstance(raw, Mapping)
        or set(raw) != {"fromRole", "failureCount", "attempt"}
        or raw.get("fromRole") != "worker"
        or isinstance(raw.get("failureCount"), bool)
        or raw.get("failureCount") != 2
        or isinstance(raw.get("attempt"), bool)
        or raw.get("attempt") != 1
    ):
        return None, ["escalation_metadata_invalid"]
    return {"fromRole": "worker", "failureCount": 2, "attempt": 1}, []


def resolve_model_allocation(
    raw_decision: Mapping[str, Any] | None,
    raw_inventory: list[Any] | None,
    *,
    policy: Mapping[str, Any] | None = None,
    role: str | None = None,
    expected_phase: str | None = None,
    escalation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve a parent AI decision inside deterministic host guardrails.

    ``escalation`` is the host-owned bounded retry contract: after exactly two
    worker-role failures on the same task, the single allowed retry resolves
    against the orchestrator role policy and the receipt carries all-or-nothing
    escalation metadata.  An invalid escalation request never degrades a valid
    parent decision — it is recorded in ``validationIssues`` and ignored.
    """

    decision, issues = validate_allocation_decision(raw_decision)
    inventory = _normalize_inventory(raw_inventory)
    policy = dict(policy or {})
    escalation_request, escalation_issues = _validate_escalation(escalation)
    # maxEscalations는 부모가 선언한 비용 상한이다. 상한은 "권한을 주는 값"이 아니라
    # "권한을 제한하는 값"이므로, 관계없는 검증 이슈(unknown_fields 등)가 하나만 섞여도
    # 상한 검사를 통째로 건너뛰면 안 된다. 예전에는 `and not issues` 때문에 무관한
    # 필드 하나가 상한을 무력화해 maxEscalations=0인 결정도 frontier/xhigh로 승격됐다.
    # decision이 존재하면 selection.maxEscalations는 항상 정규화되어 있고(불량/누락은
    # 기본값 0) 따라서 이슈가 있는 결정일수록 더 보수적으로 막힌다 — fail-closed.
    if (
        escalation_request is not None
        and decision is not None
        and decision["selection"]["maxEscalations"] < escalation_request["attempt"]
    ):
        escalation_issues.append("escalation_exceeds_max_escalations")
        escalation_request = None
    normalized_role = normalize_model_role(role)
    if role is not None and normalized_role is None:
        issues.append("invalid_model_role")
    normalized_expected_phase = normalize_phase(expected_phase)
    if expected_phase is not None and normalized_expected_phase is None:
        issues.append("invalid_expected_phase")
    expected_role = model_role_for_phase(normalized_expected_phase)
    if decision and normalized_expected_phase and decision["phase"] != normalized_expected_phase:
        issues.append("phase_stage_mismatch")
    if escalation_request is None and normalized_role and expected_role and normalized_role != expected_role:
        issues.append("role_phase_mismatch")
    resolved_role = (
        expected_role
        or normalized_role
        or model_role_for_phase(decision["phase"] if decision else None)
        or "orchestrator"
    )
    if escalation_request is not None:
        # 승격은 단계→역할 기본 매핑에 대한 유일한 허용 예외다. worker 단계의
        # 마지막 재시도 한 번만 orchestrator 역할 정책으로 해석한다.
        resolved_role = "orchestrator"
    role_policy, inherited_role_policy = _policy_for_role(policy, resolved_role)
    current_model_id = _text(role_policy.get("currentModelId"))
    pinned_model_id = _text(role_policy.get("pinnedModelId"))
    pinned_provider = _text(role_policy.get("pinnedProvider")).lower()
    configured_max_tier = normalize_tier(role_policy.get("maxTier"))
    max_tier = configured_max_tier or "frontier"
    max_effort = normalize_effort(role_policy.get("maxEffort")) or "max"
    required_capabilities = {
        str(item).lower() for item in (role_policy.get("requiredCapabilities") or [])
    }

    def compatible(item: Mapping[str, Any]) -> bool:
        if required_capabilities and not required_capabilities.issubset(set(item["capabilities"])):
            return False
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
        if decision["selection"]["effort"] != "none" and not item["supported_efforts_known"]:
            return False
        return True

    compatible_inventory = [item for item in inventory if compatible(item)]
    selected: dict[str, Any] | None = None
    status = "resolved"
    reasons: list[str] = []
    if inherited_role_policy:
        reasons.append("worker_inherits_orchestrator_policy")

    if pinned_model_id:
        pinned_candidates = [
            item for item in compatible_inventory if item["model_id"] == pinned_model_id
        ]
        if pinned_provider:
            pinned_candidates = [
                item for item in pinned_candidates if item["provider"] == pinned_provider
            ]
        if len(pinned_candidates) == 1:
            selected = pinned_candidates[0]
            status = "user-pin"
            reasons.append("explicit_user_or_scope_pin")
        elif len(pinned_candidates) > 1:
            reasons.append("pinned_model_ambiguous_across_sessions")
        else:
            reasons.append("pinned_model_unavailable_or_incompatible")

    # 승격된 재시도는 worker 단계용 parent decision이 아니라 orchestrator 역할
    # 정책이 지배한다 — decision은 맥락으로만 남고 모델 선택에는 쓰지 않는다.
    if selected is None and decision is not None and not issues and escalation_request is None:
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

    if selected is None and escalation_request is not None:
        # 승격 재시도는 위 블록에서 parent decision을 의도적으로 건너뛴다. 그래서
        # 운영자 핀(pinnedModelId)이 없으면 여기까지 어떤 분기도 selected를 채우지
        # 못했고, 유일하게 허용된 재시도가 항상 unresolved로 죽었다 — 핀은 선택
        # 사항이므로 핀을 두지 않은 모든 운영자에게 승격 계약 자체가 사문화된다.
        # 핀이 없을 때도 orchestrator 역할 정책만으로 결정적으로 고른다: maxTier
        # 이하 후보 중 최상위 tier를 쓰고("약모델 실패 → 강모델 승격"), 동률이면
        # 역할의 현재 모델로 가른다. 정책 상한을 넘기지 않으므로 승격이 비용
        # 가드레일을 뚫는 경로가 되지는 않는다.
        allowed = [
            item
            for item in compatible_inventory
            if item["tier"] is not None and TIER_RANK[item["tier"]] <= TIER_RANK[max_tier]
        ]
        if allowed:
            top_rank = max(TIER_RANK[item["tier"]] for item in allowed)
            top_candidates = [item for item in allowed if TIER_RANK[item["tier"]] == top_rank]
            current_candidate = next(
                (item for item in top_candidates if item["model_id"] == current_model_id),
                None,
            )
            if current_candidate is not None:
                selected = current_candidate
            elif len(top_candidates) == 1:
                selected = top_candidates[0]
            if selected is not None:
                reasons.append("escalated_to_highest_allowed_role_tier")
            else:
                reasons.append("escalation_target_ambiguous_across_sessions")

    if selected is None:
        if decision is None or issues:
            selected = next((item for item in compatible_inventory if item["model_id"] == current_model_id), None)
        status = "fallback-current" if selected else "unresolved"
        if decision is None or issues:
            reasons.append("parent_decision_missing_or_invalid")
        elif escalation_request is not None:
            # 승격 경로는 parent decision의 모델을 요청하지 않는다. 여기서
            # no_compatible_requested_model을 남기면 살아 있는 호환 모델을 두고도
            # "요청 모델이 비호환"이라는 거짓 사유를 보고하게 된다.
            reasons.append("escalation_target_unavailable")
        else:
            reasons.append("no_compatible_requested_model")

    requested_effort = decision["selection"]["effort"] if decision and not issues else "none"
    resolved_effort = "none"
    if selected:
        resolved_effort, effort_changed = _bounded_effort(requested_effort, selected["supported_efforts"], max_effort)
        if effort_changed:
            reasons.append("effort_clamped_to_host_support")

    risk = decision["features"]["risk"] if decision else "unknown"
    parent_reason_codes = list(decision["reasonCodes"]) if decision else []
    if escalation_request is None and "escalated-after-failure" in parent_reason_codes:
        # 승격 없이 승격 사유코드만 오는 것은 계약 위반이다 — 조용히 통과시키면
        # 소비자가 승격 필드 없는 승격을 믿게 된다. 사유코드를 떼고 이슈로 남긴다.
        escalation_issues.append("escalation_reason_code_without_escalation")
        parent_reason_codes = [code for code in parent_reason_codes if code != "escalated-after-failure"]
    if escalation_request is not None:
        reasons.append("escalated-after-failure")
    receipt = {
        "schemaVersion": "agentlas.model-allocation-receipt.v1",
        "decisionId": decision["decisionId"] if decision else None,
        "packetId": decision["packetId"] if decision else None,
        "role": resolved_role,
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
        "reasonCodes": list(dict.fromkeys(parent_reason_codes + reasons)),
        "inputFeatureHash": decision.get("inputFeatureHash") or _feature_hash(decision) if decision else None,
        "selectorVersion": decision["selectorVersion"] if decision else "deterministic-host-fallback",
        "independentVerificationRequired": risk in {"high", "critical"},
        "usage": None,
        "validationIssues": issues + escalation_issues,
        "privacy": {"rawPromptIncluded": False, "rawTranscriptIncluded": False},
    }
    if escalation_request is not None:
        receipt["escalatedFromRole"] = "worker"
        receipt["failureCount"] = 2
        receipt["escalationAttempt"] = 1
    return receipt
