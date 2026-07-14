"""Lens library — questions are picked from a table, never free-styled.

A lens is a (what-it-detects, question-template) pair. Four groups:
scope / system / intent / challenge. The challenge group's anti-scope lens is
the direct source of routing-card anti_triggers: the user's own words about
what the agent must NOT do always beat a model's guess.

Surface profiles carry the question budget — the UX contract that keeps
interviews from harming simple tasks: trivial/simple asks get ZERO questions.
"""

from __future__ import annotations

from typing import Any

LENS_GROUPS: dict[str, list[dict[str, str]]] = {
    "scope": [
        {"id": "negative_space", "find": "언급되지 않은 인접 영역", "ko": "X는 언급 안 하셨는데, 의도적으로 뺀 건가요?", "en": "You didn't mention X — deliberately out of scope?"},
        {"id": "minimum_version", "find": "과설계", "ko": "80%를 해결하는 가장 작은 버전은 뭔가요?", "en": "What is the smallest version that solves 80%?"},
        {"id": "anti_scope", "find": "하면 안 되는 인접 작업 (anti_triggers 원천)", "ko": "비슷해 보여도 '이건 하면 안 된다'가 있다면요?", "en": "Anything that looks similar but must NOT be done?"},
        {"id": "done_signal", "find": "끝의 정의", "ko": "뭘 보면 '됐다'고 판단하실 건가요?", "en": "What will you look at to call this done?"},
    ],
    "system": [
        {"id": "dependency_chain", "find": "숨은 결합", "ko": "X가 실패하면 같이 부서지는 게 뭔가요?", "en": "If X fails, what breaks with it?"},
        {"id": "existing_assets", "find": "중복 구축", "ko": "이미 있는 Y를 확장할까요, 새로 만들까요?", "en": "Extend the existing Y, or build new?"},
        {"id": "time_horizon", "find": "단기 해법의 부채", "ko": "3개월 뒤에도 이 결정이 유효한가요?", "en": "Will this decision still hold in 3 months?"},
        {"id": "failure_mode", "find": "예외 경로", "ko": "가장 흔하게 잘못될 상황은 뭔가요?", "en": "What is the most common way this goes wrong?"},
    ],
    "intent": [
        {"id": "goal_of_goal", "find": "표층 요청 뒤 진짜 목표", "ko": "이게 되면 그다음에 뭘 하실 건가요?", "en": "Once this works, what happens next?"},
        {"id": "audience", "find": "산출물의 소비자", "ko": "결과물을 누가 보나요/쓰나요?", "en": "Who consumes the output?"},
        {"id": "rejected_alternatives", "find": "이미 시도한 것", "ko": "이미 해봤는데 안 됐던 방법이 있나요?", "en": "What have you already tried that didn't work?"},
        {"id": "confidence_level", "find": "사실 vs 추정", "ko": "그건 확인된 사실인가요, 느낌인가요?", "en": "Is that a verified fact or a hunch?"},
    ],
    "challenge": [
        {"id": "premortem", "find": "실패 시나리오", "ko": "6개월 뒤 실패했다고 치죠. 왜였을까요?", "en": "It failed six months from now — why?"},
        {"id": "inversion", "find": "필수 회피 조건", "ko": "확실히 망치려면 뭘 하면 되나요?", "en": "What would guarantee failure?"},
        {"id": "stop_criterion", "find": "손절 조건", "ko": "어떤 결과가 나오면 '그만두자'인가요?", "en": "What result would make you stop?"},
        {"id": "forced_tradeoff", "find": "우선순위", "ko": "속도와 품질이 부딪히면 어느 쪽인가요?", "en": "When speed and quality collide, which wins?"},
    ],
}

# Question budgets per surface. `soft_threshold` is the chat-mode escape hatch:
# after one batch, if ambiguity re-scores at or below it, state the remaining
# assumptions explicitly and proceed instead of asking again.
SURFACE_PROFILES: dict[str, dict[str, Any]] = {
    "chat": {
        "groups": ["scope", "intent"],
        "batch_max": 5,
        "batches_max": 1,
        "total_max": 5,
        "min_rounds": 1,
        "streak_required": 1,
        "soft_threshold": 0.35,
    },
    "stormbreaker": {
        "groups": ["scope", "system"],
        "batch_max": 5,
        "batches_max": 2,
        "total_max": 8,
        "min_rounds": 1,
        "streak_required": 2,
        "soft_threshold": 0.3,
    },
    "hep-build": {
        "groups": ["scope", "system", "intent", "challenge"],
        "batch_max": 12,
        "batches_max": 3,
        "total_max": 20,
        "min_rounds": 2,
        "streak_required": 2,
        "soft_threshold": None,
        "required_lenses": ["anti_scope", "done_signal", "stop_criterion"],
    },
    "hub-draft": {
        "groups": ["scope", "system", "intent", "challenge"],
        "batch_max": 12,
        "batches_max": 2,
        "total_max": 12,
        "min_rounds": 1,
        "streak_required": 1,
        "soft_threshold": 0.3,
    },
}


def surface_profile(surface: str) -> dict[str, Any]:
    return SURFACE_PROFILES.get(surface) or SURFACE_PROFILES["chat"]


def question_budget(surface: str) -> dict[str, int]:
    profile = surface_profile(surface)
    return {
        "batch_max": int(profile["batch_max"]),
        "batches_max": int(profile["batches_max"]),
        "total_max": int(profile["total_max"]),
    }


def render_lens_table(surface: str, locale: str = "en") -> str:
    """Render the surface's lens groups as a prompt-ready table."""
    profile = surface_profile(surface)
    key = "ko" if locale == "ko" else "en"
    lines: list[str] = []
    required = set(profile.get("required_lenses") or [])
    for group in profile["groups"]:
        lines.append(f"[{group}]")
        for lens in LENS_GROUPS[group]:
            marker = " (필수)" if lens["id"] in required else ""
            lines.append(f"- {lens['id']}{marker}: {lens['find']} → \"{lens[key]}\"")
    return "\n".join(lines)
