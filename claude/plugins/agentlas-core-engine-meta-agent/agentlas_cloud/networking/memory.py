"""Routing memory: structured preferences and corrections only.

Hard rules:
- never store raw prompts, secrets, file contents, or transcripts;
- feedback adjusts a user-local boost/suppression profile only — it can never
  promote a card's routing_status (that requires lint + benchmarks), so bad
  routes cannot be reinforced into the shared card inventory.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .bootstrap import append_jsonl, atomic_write_json, memory_enabled, networking_home, read_json, utc_now

from ..text_safety import PRIVATE_PATH_PATTERNS, SECRET_PATTERNS, contains_secret, route_input_issues  # noqa: F401  (the one definition; the names stay importable from here)

BOOST_LIMIT = 3.0
CORRECTIONS_LIMIT = 200


def redact_tokens(tokens: list[str]) -> list[str]:
    safe: list[str] = []
    for token in tokens:
        if any(pattern.search(token) for pattern in SECRET_PATTERNS):
            safe.append("[redacted]")
        else:
            safe.append(token)
    return safe


def unsafe_route_refusal(text: str) -> dict[str, Any] | None:
    """Return a bounded local-only refusal before tokenization, cache, or I/O."""
    issues = route_input_issues(text)
    if not issues:
        return None
    ko = bool(re.search(r"[가-힣]", text or ""))
    return {
        "action": "refuse",
        "status": "rejected",
        "error": "unsafe_route_input",
        "reasons": issues,
        "boundary": {
            "issues": [{"path": "request", "code": code} for code in issues],
            "remoteCalls": 0,
            "projectWrites": 0,
        },
        "executionAllowed": False,
        "detail": (
            "credential·비밀값·로컬 경로를 빼고, 필요한 에이전트의 역할만 설명해 주세요."
            if ko
            else (
                "Remove credentials, secret-like values, and private local paths, "
                "then describe only the capability you want the agent to have."
            )
        ),
    }


def load_profile(home: Path | str | None = None) -> dict[str, Any]:
    empty = {"boosts": {}, "suppressions": {}, "corrections": []}
    if not memory_enabled():
        return empty
    base = Path(home) if home else networking_home()
    profile = read_json(base / "memory" / "routing-profile.json", default=empty)
    return profile if memory_enabled() else empty


def profile_adjustment(profile: dict[str, Any], card_id: str) -> float:
    if not memory_enabled():
        return 0.0
    boost = float((profile.get("boosts") or {}).get(card_id, 0.0))
    suppression = float((profile.get("suppressions") or {}).get(card_id, 0.0))
    return max(-BOOST_LIMIT, min(BOOST_LIMIT, boost - suppression))


def record_feedback(
    query_tokens: list[str],
    chosen_card: str | None,
    correct_card: str | None,
    home: Path | str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    if not memory_enabled():
        return {"status": "disabled", "error": "feature_disabled", "feature": "memory-hooks", "writeAttempted": False}
    base = Path(home) if home else networking_home()
    tokens = redact_tokens(query_tokens)
    append_jsonl(
        base / "memory" / "feedback.jsonl",
        {"ts": utc_now(), "tokens": tokens, "chosen": chosen_card, "correct": correct_card, "note": note},
    )
    if not memory_enabled():
        return {"status": "partial", "error": "feature_disabled", "feature": "memory-hooks", "feedbackRecorded": True}
    profile = load_profile(base)
    if not memory_enabled():
        return {"status": "partial", "error": "feature_disabled", "feature": "memory-hooks", "feedbackRecorded": True}
    boosts = profile.setdefault("boosts", {})
    suppressions = profile.setdefault("suppressions", {})
    if correct_card:
        boosts[correct_card] = min(BOOST_LIMIT, float(boosts.get(correct_card, 0.0)) + 0.5)
    if chosen_card and chosen_card != correct_card:
        suppressions[chosen_card] = min(BOOST_LIMIT, float(suppressions.get(chosen_card, 0.0)) + 0.5)
    corrections = profile.setdefault("corrections", [])
    corrections.append({"ts": utc_now(), "tokens": tokens[:12], "correct": correct_card, "chosen": chosen_card})
    profile["corrections"] = corrections[-CORRECTIONS_LIMIT:]
    if not memory_enabled():
        return {"status": "partial", "error": "feature_disabled", "feature": "memory-hooks", "feedbackRecorded": True}
    atomic_write_json(Path(base) / "memory" / "routing-profile.json", profile)
    return {"status": "recorded", "boosts": boosts.get(correct_card) if correct_card else None}
