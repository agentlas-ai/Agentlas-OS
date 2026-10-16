"""Plan operations: the only way a stored plan changes. Pure over a plan dict; the caller persists the result.

Operations never touch permissions, payments or any service outside the goal store (contracts/goal-rules.json writes).
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta
from typing import Any, Mapping

from .kpi import iso, parse_time
from .rules import load_rules
from .shape import ID_RE, ShapeError, _acyclic, _text

OPS = ("add_strategy", "retire_strategy", "add_tactic", "replace_tactic", "set_tactic_status")
TACTIC_STATUS = ("active", "done", "blocked", "retired")
OPEN_STATUS = ("active", "blocked")


class PlanError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def open_tactics(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [t for t in plan.get("tactics", []) if t.get("status", "active") in OPEN_STATUS]


def active_strategies(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [s for s in plan.get("strategies", []) if s.get("status", "active") == "active"]


def protected_until(strategy: Mapping[str, Any]) -> datetime | None:
    """A new strategy gets its observation window before anything may retire it."""
    activated = strategy.get("activated_at")
    if not activated:
        return None
    return parse_time(activated) + timedelta(hours=float(strategy.get("observation_window_hours") or 0))


def _find(items: list[dict[str, Any]], item_id: str, kind: str) -> dict[str, Any]:
    for item in items:
        if item.get("id") == item_id:
            return item
    raise PlanError(f"{kind}_unknown", item_id)


def _new_tactic(raw: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    lim = load_rules()["limits"]
    tid = raw.get("id")
    if not isinstance(tid, str) or not ID_RE.match(tid):
        raise PlanError("id_invalid", str(tid))
    if any(t["id"] == tid for t in plan.get("tactics", [])):
        raise PlanError("id_duplicate", tid)
    sid = raw.get("strategy_id")
    if plan["shape"] == "mission_tree" and sid is None:
        raise PlanError("tactic_needs_strategy", tid)
    if sid is not None:
        strat = _find(plan.get("strategies", []), sid, "strategy")
        if strat.get("status", "active") != "active":
            raise PlanError("strategy_retired", sid)
    return {"id": tid, "strategy_id": sid, "description": _text(raw.get("description"), "tactic.description", lim["text"]),
            "done_when": _text(raw.get("done_when"), "tactic.done_when", lim["text"]),
            "kind": raw.get("kind") if raw.get("kind") in ("one_off", "recurring") else "one_off",
            "depends_on": [str(x) for x in (raw.get("depends_on") or [])], "status": "active"}


def _check_cap(plan: Mapping[str, Any]) -> None:
    cap = load_rules()["limits"]["tactics"]
    if len(open_tactics(plan)) > cap:
        raise PlanError("tactic_cap", f"{len(open_tactics(plan))} open tactics, limit {cap}")


def _add_strategy(plan: dict[str, Any], raw: Mapping[str, Any], now: datetime, born_from: str | None) -> dict[str, Any]:
    rules = load_rules()
    lim = rules["limits"]
    sid = raw.get("id")
    if not isinstance(sid, str) or not ID_RE.match(sid):
        raise PlanError("id_invalid", str(sid))
    if any(s["id"] == sid for s in plan.get("strategies", [])):
        raise PlanError("id_duplicate", sid)
    if len(active_strategies(plan)) >= lim["strategies"]:
        raise PlanError("strategy_cap", str(lim["strategies"]))
    strategy = {"id": sid, "hypothesis": _text(raw.get("hypothesis"), "strategy.hypothesis", lim["text"]),
                "serves_krs": [str(x) for x in (raw.get("serves_krs") or [])], "kpi": _text(raw.get("kpi"), "strategy.kpi", lim["shortText"]),
                "budget": dict(raw.get("budget") or {}), "timebox_hours": float(raw.get("timebox_hours") or lim["defaultTimeboxHours"]),
                "observation_window_hours": float(raw.get("observation_window_hours") or rules["kpi"]["longWindowHoursDefault"]),
                "expected_delta": str(raw.get("expected_delta") or "")[: lim["shortText"]],
                "kill_if": str(raw.get("kill_if") or "")[: lim["shortText"]],
                "status": "active", "activated_at": iso(now), "born_from_trigger": born_from}
    plan.setdefault("strategies", []).append(strategy)
    return strategy


def _retire_strategy(plan: dict[str, Any], sid: str, evidence: str, now: datetime, force_window: bool) -> list[str]:
    strat = _find(plan.get("strategies", []), sid, "strategy")
    if strat.get("status", "active") != "active":
        raise PlanError("strategy_retired", sid)
    until = protected_until(strat)
    if not force_window and until and now < until:
        raise PlanError("strategy_protected", f"{sid} until {iso(until)}")
    if not str(evidence or "").strip():
        raise PlanError("evidence_required", sid)
    strat.update({"status": "retired", "retired_at": iso(now), "retire_evidence": str(evidence)[:300]})
    closed = []
    for t in plan.get("tactics", []):
        if t.get("strategy_id") == sid and t.get("status", "active") in OPEN_STATUS:
            t.update({"status": "retired", "retired_at": iso(now)})
            closed.append(t["id"])
    return closed


def apply_op(plan: Mapping[str, Any], op: Mapping[str, Any], now: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return (new_plan, receipt). The input plan is never mutated; a failing op raises PlanError."""
    kind = op.get("op")
    if kind not in OPS:
        raise PlanError("op_unknown", str(kind))
    if plan.get("shape") == "single_tactic" and kind in ("add_strategy", "retire_strategy"):
        raise PlanError("shape_has_no_strategies", plan.get("shape", ""))
    new = copy.deepcopy(dict(plan))
    receipt: dict[str, Any] = {"op": kind}
    try:
        if kind == "add_strategy":
            strat = _add_strategy(new, op, now, None)
            receipt["added"] = [strat["id"]]
        elif kind == "retire_strategy":
            receipt["retired_tactics"] = _retire_strategy(new, str(op.get("id")), str(op.get("evidence") or ""), now, False)
            receipt["retired"] = [str(op.get("id"))]
        elif kind == "add_tactic":
            new.setdefault("tactics", []).append(_new_tactic(op, new))
            receipt["added_tactic"] = op.get("id")
        elif kind == "replace_tactic":
            old = _find(new.get("tactics", []), str(op.get("replaces")), "tactic")
            if old.get("status", "active") not in OPEN_STATUS:
                raise PlanError("tactic_not_open", str(op.get("replaces")))
            old.update({"status": "retired", "retired_at": iso(now), "replaced_by": op.get("id")})
            new["tactics"].append(_new_tactic(op, new))
            receipt.update({"replaced": op.get("replaces"), "added_tactic": op.get("id")})
        else:
            tactic = _find(new.get("tactics", []), str(op.get("id")), "tactic")
            status = op.get("status")
            if status not in TACTIC_STATUS:
                raise PlanError("status_invalid", str(status))
            tactic.update({"status": status, "status_at": iso(now)})
            receipt.update({"tactic": tactic["id"], "status": status})
        _acyclic(new.get("tactics", []))
    except ShapeError as exc:
        raise PlanError(exc.code, exc.detail) from exc
    _check_cap(new)
    return new, receipt


SHIFT_DECISIONS = ("hold", "pivot", "double_down", "escalate_owner")


def apply_shift(plan: Mapping[str, Any], shift: Mapping[str, Any], trigger: Mapping[str, Any], sample_ids: set[str],
                now: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
    """A re-plan in one step: retire the named strategies with their open tactics, then add the new ones.

    Doing both together is what keeps the tactic cap from blocking a change of direction, which is exactly how 13
    operations were refused on the Desktop.
    """
    decision = shift.get("decision")
    if decision not in SHIFT_DECISIONS:
        raise PlanError("decision_invalid", str(decision))
    if shift.get("trigger_id") != trigger.get("id"):
        raise PlanError("trigger_mismatch", str(shift.get("trigger_id")))
    diagnosis = str(shift.get("diagnosis") or "").strip()
    if not diagnosis:
        raise PlanError("diagnosis_required")
    refs = [str(r) for r in (shift.get("evidence_refs") or [])]
    if decision != "hold" and not refs:
        raise PlanError("evidence_refs_required")
    unknown = [r for r in refs if r not in sample_ids]
    if unknown:
        raise PlanError("evidence_unknown_sample", ",".join(unknown))
    new = copy.deepcopy(dict(plan))
    receipt: dict[str, Any] = {"op": "strategy_shift", "decision": decision, "retired": [], "added": [], "retired_tactics": []}
    if decision in ("hold", "escalate_owner"):
        return new, receipt
    for item in shift.get("retire") or []:
        receipt["retired_tactics"] += _retire_strategy(new, str(item.get("id")), str(item.get("evidence") or ""), now, False)
        receipt["retired"].append(str(item.get("id")))
    for raw in shift.get("add") or []:
        strat = _add_strategy(new, raw, now, str(trigger.get("id")))
        receipt["added"].append(strat["id"])
        for t in raw.get("tactics") or []:
            new.setdefault("tactics", []).append(_new_tactic({**t, "strategy_id": strat["id"]}, new))
    try:
        _acyclic(new.get("tactics", []))
    except ShapeError as exc:
        raise PlanError(exc.code, exc.detail) from exc
    if not open_tactics(new):
        # A re-plan that retires the current approach must leave work to do. Retiring without adding is a stop, not a pivot.
        raise PlanError("shift_leaves_no_open_tactic", "add a strategy with at least one tactic, or use decision=hold or escalate_owner")
    _check_cap(new)
    return new, receipt
