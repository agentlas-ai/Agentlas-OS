"""Goal shape: which plan form fits this goal, and the host-side check of a model's draft.

The model proposes; this module decides what may be stored. Owner numbers and quotes are matched against the goal text
itself, so the model cannot invent a target or a boundary.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

from .rules import load_rules

SHAPES = ("single_tactic", "tactic_list", "mission_tree")
NATURES = ("clear", "complicated", "complex", "chaotic")
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,39}$")
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")


class ShapeError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def owner_numbers(text: str) -> set[float]:
    found = set()
    for token in NUMBER_RE.findall(text or ""):
        try:
            found.add(float(token.replace(",", "")))
        except ValueError:
            continue
    return found


def _text(value: Any, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ShapeError("text_required", field)
    if len(value) > limit:
        raise ShapeError("text_too_long", field)
    return value.strip()


def _id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not ID_RE.match(value):
        raise ShapeError("id_invalid", f"{field}={value!r}")
    return value


def _acyclic(tactics: list[dict[str, Any]]) -> None:
    deps = {t["id"]: list(t.get("depends_on") or []) for t in tactics}
    state: dict[str, int] = {}

    def visit(node: str) -> None:
        if state.get(node) == 1:
            raise ShapeError("dependency_cycle", node)
        if state.get(node) == 2:
            return
        state[node] = 1
        for nxt in deps.get(node, []):
            if nxt not in deps:
                raise ShapeError("dependency_unknown", f"{node}->{nxt}")
            visit(nxt)
        state[node] = 2

    for node in deps:
        visit(node)


def validate_draft(draft: Mapping[str, Any], goal_text: str) -> dict[str, Any]:
    """Return a normalized plan body or raise ShapeError. Nothing is stored here."""
    rules = load_rules()
    lim = rules["limits"]
    shape, nature = draft.get("shape"), draft.get("problem_nature")
    if shape not in SHAPES:
        raise ShapeError("shape_invalid", str(shape))
    if nature not in NATURES:
        raise ShapeError("nature_invalid", str(nature))
    out: dict[str, Any] = {
        "shape": shape,
        "problem_nature": nature,
        "rationale": _text(draft.get("rationale"), "rationale", lim["text"]),
        "shape_matches_nature": rules["natureShape"][nature] == shape,
    }
    tactics_in = draft.get("tactics") or []
    strategies_in = draft.get("strategies") or []
    if not 1 <= len(tactics_in) <= lim["tactics"]:
        raise ShapeError("tactic_count", f"{len(tactics_in)} (1..{lim['tactics']})")
    if len(strategies_in) > lim["strategies"]:
        raise ShapeError("strategy_count", str(len(strategies_in)))
    if shape == "single_tactic" and (len(tactics_in) != 1 or strategies_in or draft.get("mission")):
        raise ShapeError("single_tactic_has_extras")
    if shape == "tactic_list" and (strategies_in or draft.get("mission")):
        raise ShapeError("tactic_list_has_tree")
    strategies, strategy_ids = [], set()
    for s in strategies_in:
        sid = _id(s.get("id"), "strategy.id")
        if sid in strategy_ids:
            raise ShapeError("id_duplicate", sid)
        strategy_ids.add(sid)
        strategies.append({
            "id": sid,
            "hypothesis": _text(s.get("hypothesis"), "strategy.hypothesis", lim["text"]),
            "serves_krs": [str(x) for x in (s.get("serves_krs") or [])],
            "kpi": _text(s.get("kpi"), "strategy.kpi", lim["shortText"]),
            "budget": dict(s.get("budget") or {}),
            "timebox_hours": float(s.get("timebox_hours") or lim["defaultTimeboxHours"]),
            "observation_window_hours": float(s.get("observation_window_hours") or rules["kpi"]["longWindowHoursDefault"]),
            "expected_delta": str(s.get("expected_delta") or "")[: lim["shortText"]],
            "kill_if": str(s.get("kill_if") or "")[: lim["shortText"]],
        })
    tactics, tactic_ids = [], set()
    for t in tactics_in:
        tid = _id(t.get("id"), "tactic.id")
        if tid in tactic_ids:
            raise ShapeError("id_duplicate", tid)
        tactic_ids.add(tid)
        sid = t.get("strategy_id")
        if sid is not None and sid not in strategy_ids:
            raise ShapeError("strategy_unknown", f"{tid}->{sid}")
        if shape == "mission_tree" and sid is None:
            raise ShapeError("tactic_needs_strategy", tid)
        tactics.append({
            "id": tid,
            "strategy_id": sid,
            "description": _text(t.get("description"), "tactic.description", lim["text"]),
            "done_when": _text(t.get("done_when"), "tactic.done_when", lim["text"]),
            "kind": t.get("kind") if t.get("kind") in ("one_off", "recurring") else "one_off",
            "depends_on": [str(x) for x in (t.get("depends_on") or [])],
        })
    _acyclic(tactics)
    out["strategies"], out["tactics"] = strategies, tactics
    if shape == "mission_tree":
        mission = draft.get("mission")
        if not isinstance(mission, Mapping):
            raise ShapeError("mission_required")
        if not strategies:
            raise ShapeError("strategy_required")
        numbers = owner_numbers(goal_text)
        key_results = []
        for index, kr in enumerate(mission.get("key_results") or []):
            if index >= lim["keyResults"]:
                raise ShapeError("kr_count")
            target = kr.get("target")
            if target is not None and float(target) not in numbers:
                # R3: a target is the owner's number or it is not a target.
                raise ShapeError("target_not_owner_number", f"{kr.get('metric')}={target}")
            key_results.append({
                "id": _id(kr.get("id") or re.sub(r"[^A-Za-z0-9_]+", "_", str(kr.get("metric", "kr")))[:30] or "kr", "kr.id"),
                "metric": _text(kr.get("metric"), "kr.metric", lim["shortText"]),
                "target": None if target is None else float(target),
                "unit": str(kr.get("unit") or "")[:40],
                "deadline": kr.get("deadline"),
                "baseline": kr.get("baseline"),
                "direction": "down" if kr.get("direction") == "down" else "up",
            })
        boundaries = []
        for b in (mission.get("boundaries") or [])[: lim["boundaries"]]:
            if b.get("source") == "owner":
                quote = str(b.get("quote") or "")
                if not quote or quote not in goal_text:
                    raise ShapeError("boundary_quote_not_in_goal", str(b.get("text")))
                boundaries.append({"text": _text(b.get("text"), "boundary.text", lim["text"]), "source": "owner", "quote": quote})
            elif b.get("source") == "platform_rule" and b.get("rule_ref"):
                boundaries.append({"text": _text(b.get("text"), "boundary.text", lim["text"]), "source": "platform_rule", "rule_ref": str(b["rule_ref"])})
            else:
                raise ShapeError("boundary_source_invalid", str(b.get("text")))
        out["mission"] = {
            "objective": _text(mission.get("objective"), "mission.objective", lim["text"]),
            "diagnosis": _text(mission.get("diagnosis"), "mission.diagnosis", lim["text"]),
            "key_results": key_results,
            "boundaries": boundaries,
        }
    review = draft.get("review_every_hours")
    out["review_every_hours"] = min(max(float(review), lim["minReviewHours"]), lim["maxReviewHours"]) if review else lim["defaultReviewHours"]
    out["deadline"] = draft.get("deadline")
    return out
