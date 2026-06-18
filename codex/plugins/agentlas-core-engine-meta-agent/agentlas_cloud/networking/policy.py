"""Local Operator Mode policy labels for Hephaestus Network decisions.

This module is intentionally not a heavy approval engine. The desktop/local
runtime owns execution permissions; the router adds a small, machine-readable
policy label so receipts explain whether memory/context should be used as-is,
redacted, candidate-only, or handled by the host runtime.
"""

from __future__ import annotations

from typing import Any


_PRIVATE_MEMORY_TERMS = {
    "private",
    "secret",
    "secrets",
    "credential",
    "credentials",
    "token",
    "apikey",
    "api_key",
    "raw",
    "memory",
    "prompt",
    "비밀",
    "시크릿",
    "토큰",
    "자격증명",
    "인증키",
    "메모리",
    "기억",
    "원문",
    "프롬프트",
}

_EXTERNAL_TERMS = {
    "hub",
    "cloud",
    "external",
    "upload",
    "export",
    "share",
    "send",
    "agentlas",
    "허브",
    "클라우드",
    "외부",
    "업로드",
    "내보내",
    "전송",
    "공유",
}

_IRREVERSIBLE_TERMS = {
    "delete",
    "payment",
    "charge",
    "refund",
    "publish",
    "deploy",
    "submit",
    "release",
    "삭제",
    "결제",
    "환불",
    "게시",
    "배포",
    "제출",
    "릴리즈",
}

_GLOBAL_PROMOTION_TERMS = {
    "global",
    "durable",
    "promote",
    "playbook",
    "registry",
    "전역",
    "영구",
    "승격",
    "플레이북",
    "레지스트리",
}

_SEVERITY = {
    "allow": 0,
    "allow_with_label": 1,
    "candidate_only": 2,
    "auto_redact": 3,
    "ask_once": 4,
    "deny": 5,
}


def evaluate_local_operator_policy(
    query_tokens: list[str],
    *,
    action: str,
    hub_used: bool = False,
    hub_only: bool = False,
    scope: str = "network",
    pipeline: bool = False,
) -> dict[str, Any]:
    """Return a minimal Local Operator Mode policy decision.

    The default is allow. Most super-ontology signals become labels, candidate
    promotion, or automatic redaction guidance. Human approval is deliberately
    rare in local mode.
    """

    terms = {str(token).lower() for token in query_tokens}
    external = hub_used or hub_only or action == "hub_candidates"
    has_private = bool(terms & _PRIVATE_MEMORY_TERMS)
    has_external_term = bool(terms & _EXTERNAL_TERMS)
    has_irreversible = bool(terms & _IRREVERSIBLE_TERMS)
    has_global_promotion = bool(terms & _GLOBAL_PROMOTION_TERMS)

    decision = "allow"
    labels: list[str] = ["local_operator_mode"]
    controls: list[str] = ["host_runtime_executes_with_its_own_permissions"]
    approval_reasons: list[str] = []

    def lift(target: str) -> None:
        nonlocal decision
        if _SEVERITY[target] > _SEVERITY[decision]:
            decision = target

    if pipeline:
        lift("allow_with_label")
        labels.append("temporary_task_force")
        controls.append("stormbreaker_final_gate_required")

    if external:
        lift("allow_with_label")
        labels.append("external_or_hub_context")
        controls.append("hub_receives_redacted_keywords_only")

    if has_private and (external or has_external_term):
        lift("auto_redact")
        labels.append("privacy_confidentiality_boundary")
        controls.append("share_public_playbooks_or_redacted_summaries_only")

    if has_global_promotion:
        lift("candidate_only")
        labels.append("memory_playbook_promotion")
        controls.append("global_memory_or_playbook_write_stays_candidate_until_curator")

    if has_irreversible:
        lift("allow_with_label")
        labels.append("irreversible_action_boundary")
        controls.append("host_runtime_must_gate_real_publish_delete_payment_submit_actions")

    if {"raw", "secret"} <= terms and (external or has_external_term):
        lift("deny")
        labels.append("raw_secret_external_transfer")
        approval_reasons.append("raw secret export is never a routing-time action")

    return {
        "mode": "local_operator",
        "decision": decision,
        "labels": list(dict.fromkeys(labels)),
        "controls": list(dict.fromkeys(controls)),
        "approval": "none" if decision not in {"ask_once", "deny"} else decision,
        "approval_reasons": approval_reasons,
    }
