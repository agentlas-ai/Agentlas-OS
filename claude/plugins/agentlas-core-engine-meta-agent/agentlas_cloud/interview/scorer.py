"""Ambiguity scoring for the briefing interview — deterministic composition.

The HOST runtime's model judges per-dimension clarity (low temperature, JSON,
justification required); this module owns everything that must be reproducible:
weights, floors, the composed ambiguity value, milestones and the completion
gate. The engine never calls a model (BYOC) — `build_scoring_prompt` hands the
judging instructions to the host.

Stop gates (all must hold to finish an interview):
  1. overall ambiguity <= AMBIGUITY_THRESHOLD
  2. every dimension clears its floor (no passing on averages)
  3. the two conditions held for `streak_required` consecutive rounds
     (a fresh answer can reshuffle the picture — never end on the first pass)
Deliberate deferrals are never penalised: an explicitly deferred topic is
recorded, not scored as unclear.
"""

from __future__ import annotations

from typing import Any

AMBIGUITY_THRESHOLD = 0.2

# Per-surface dimension weights. Build interviews also judge how the new agent
# fits existing assets (context); chat/stormbreaker keep three dimensions.
_DIMENSIONS: dict[str, list[tuple[str, float, float]]] = {
    # (dimension, weight, floor)
    "chat": [("goal", 0.40, 0.75), ("constraints", 0.30, 0.65), ("success", 0.30, 0.70)],
    "stormbreaker": [("goal", 0.40, 0.75), ("constraints", 0.30, 0.65), ("success", 0.30, 0.70)],
    "hep-build": [
        ("goal", 0.35, 0.75),
        ("constraints", 0.25, 0.65),
        ("success", 0.25, 0.70),
        ("context", 0.15, 0.60),
    ],
    "hub-draft": [
        ("goal", 0.35, 0.75),
        ("constraints", 0.25, 0.65),
        ("success", 0.25, 0.70),
        ("context", 0.15, 0.60),
    ],
}

_MILESTONES: list[tuple[float, str]] = [
    (0.2, "READY"),
    (0.3, "REFINED"),
    (0.4, "PROGRESS"),
]


def dimensions_for(surface: str) -> list[tuple[str, float, float]]:
    return _DIMENSIONS.get(surface) or _DIMENSIONS["chat"]


def milestone_of(ambiguity: float) -> str:
    for ceiling, name in _MILESTONES:
        if ambiguity <= ceiling:
            return name
    return "INITIAL"


def compose_ambiguity(clarity: dict[str, Any], surface: str) -> dict[str, Any]:
    """Compose per-dimension clarity scores into one auditable ambiguity value."""
    dims = dimensions_for(surface)
    breakdown: list[dict[str, Any]] = []
    weighted = 0.0
    floor_failures: list[str] = []
    for name, weight, floor in dims:
        try:
            score = float(clarity.get(name, 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(1.0, score))
        weighted += score * weight
        if score < floor:
            floor_failures.append(name)
        breakdown.append({"dimension": name, "clarity": round(score, 4), "weight": weight, "floor": floor})
    ambiguity = round(1.0 - weighted, 4)
    return {
        "ambiguity": ambiguity,
        "weighted_clarity": round(weighted, 4),
        "breakdown": breakdown,
        "floor_failures": floor_failures,
        "milestone": milestone_of(ambiguity),
        "weakest": sorted(breakdown, key=lambda item: item["clarity"])[:2],
    }


def completion_check(
    rounds: list[dict[str, Any]],
    surface: str,
    *,
    streak_required: int = 2,
    min_rounds: int = 1,
) -> dict[str, Any]:
    """Decide whether the interview may end, from the per-round score history.

    `rounds` is chronological; each entry needs `ambiguity` and `floor_failures`
    (the output of `compose_ambiguity`). Ending requires the gate conditions to
    hold on a trailing streak — a low score is permission to AUDIT the close,
    not permission to close.
    """
    if not rounds:
        return {"ready": False, "streak": 0, "reason": "no_rounds"}
    streak = 0
    for entry in reversed(rounds):
        ambiguity = float(entry.get("ambiguity", 1.0))
        failures = entry.get("floor_failures") or []
        if ambiguity <= AMBIGUITY_THRESHOLD and not failures:
            streak += 1
        else:
            break
    latest = rounds[-1]
    if len(rounds) < min_rounds:
        return {"ready": False, "streak": streak, "reason": "below_min_rounds"}
    if float(latest.get("ambiguity", 1.0)) > AMBIGUITY_THRESHOLD:
        return {"ready": False, "streak": streak, "reason": "ambiguity_above_threshold"}
    if latest.get("floor_failures"):
        return {
            "ready": False,
            "streak": streak,
            "reason": "dimension_floor_failed",
            "floor_failures": latest.get("floor_failures"),
        }
    if streak < streak_required:
        return {"ready": False, "streak": streak, "reason": "stability_streak_not_met"}
    return {"ready": True, "streak": streak, "reason": "gates_met"}


def build_scoring_prompt(surface: str, locale: str = "en") -> str:
    """Judging instructions the host model runs after each interview round."""
    dims = dimensions_for(surface)
    dim_lines = "\n".join(
        f'- "{name}" (weight {weight}, floor {floor}): '
        + {
            "goal": "what outcome the user actually wants — one specific deliverable",
            "constraints": "boundaries, scope limits, tech/format/budget constraints",
            "success": "how completion will be judged — verifiable acceptance criteria",
            "context": "how this relates to existing assets/code/agents (extend vs new)",
        }[name]
        for name, weight, floor in dims
    )
    return (
        "You are scoring how settled a work request is after the interview so far.\n"
        f"Score each dimension from 0.0 (unclear) to 1.0 (perfectly clear):\n{dim_lines}\n"
        "Rules:\n"
        "- Scores above 0.8 require very specific, concrete answers in the transcript.\n"
        "- Topics the user explicitly deferred ('나중에 정할게') are deliberate decisions —\n"
        "  do NOT penalise them; list them under deferred_topics instead.\n"
        "- Judge only what is in the transcript. Do not give credit for plausible guesses.\n"
        'Respond ONLY with JSON: {"clarity": {"<dimension>": <0..1>, ...}, '
        '"justification": {"<dimension>": "<one sentence>", ...}, '
        '"deferred_topics": ["..."]}'
    )
