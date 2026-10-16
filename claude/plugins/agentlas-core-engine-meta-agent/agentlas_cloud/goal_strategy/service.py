"""Service layer: what the CLI, the `goal.*` MCP tools and `/hep-goal` call. Every function takes the clock as `now`.

Mode is `AGENTLAS_GOAL_STRATEGY=on|shadow|off` (default `shadow`): in shadow, samples are stored and states evaluated,
but no context is injected and no strategy shift changes the plan.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from . import kpi as K
from .plan import PlanError, active_strategies, apply_op, apply_shift, open_tactics, protected_until
from .rules import load_rules
from .shape import ShapeError, validate_draft
from .store import GoalStore, GoalStoreError

_SECRET = re.compile(r"(?<![A-Za-z0-9_-])(?:sk-[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[bp]-[A-Za-z0-9-]{10,})"
                     r"|(?:api[_-]?key|token|secret|password|authorization)\s*[:=]\s*\S+", re.I)
_URL = re.compile(r"https?://([^\s/?#]+)[^\s]*", re.I)
_DURATION = re.compile(r"^P(?:(\d+)W)?(?:(\d+)D)?$")


class GoalError(ValueError):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


def mode() -> str:
    value = os.environ.get("AGENTLAS_GOAL_STRATEGY", "shadow").strip().lower()
    return value if value in ("on", "shadow", "off") else "shadow"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def goal_id_for(goal_text: str) -> str:
    return "goal-" + hashlib.sha256(goal_text.strip().encode("utf-8")).hexdigest()[:12]


def scrub(text: str, limit: int | None = None) -> str:
    cap = limit or load_rules()["samples"]["maxEvidenceChars"]
    return _URL.sub(lambda m: f"<url:{m.group(1)}>", _SECRET.sub("[redacted]", " ".join(str(text).split())))[:cap]


def _deadline(raw: Any, created: datetime) -> str | None:
    if not raw:
        return None
    match = _DURATION.match(str(raw))
    if match:
        days = int(match.group(1) or 0) * 7 + int(match.group(2) or 0)
        return K.iso(created + timedelta(days=days)) if days else None
    try:
        return K.iso(K.parse_time(str(raw)))
    except ValueError:
        raise GoalError("deadline_invalid", f"{raw!r}: use an ISO date such as 2026-12-31, an ISO time, or a duration such as P30D or P3W")


def _store(project: str, goal_id: str) -> GoalStore:
    store = GoalStore(project, goal_id)
    if not store.exists():
        raise GoalError("goal_unknown", goal_id)
    return store


def _record(store: GoalStore, kind: str, now: datetime, receipt: dict[str, Any], key: str | None, extra: Mapping[str, Any] | None = None) -> None:
    store.append("decisions.jsonl", {"ts": K.iso(now), "kind": kind, "idempotency_key": key or None, "receipt": receipt, **(extra or {})})


def _kpis_from_plan(plan: Mapping[str, Any], created: datetime) -> list[dict[str, Any]]:
    out = []
    for kr in (plan.get("mission") or {}).get("key_results", []):
        integral = all(v is None or float(v).is_integer() for v in (kr.get("target"), kr.get("baseline")))
        out.append({"id": kr["id"], "name": kr["metric"], "unit": kr.get("unit", ""), "direction": kr.get("direction", "up"),
                    "kr_id": kr["id"], "target": kr.get("target"), "deadline_at": _deadline(kr.get("deadline"), created),
                    "baseline": kr.get("baseline"), "cadence_hours": 24, "integer": integral})
    return out


def start(project: str, goal_text: str, draft: Mapping[str, Any], key: str | None = None, now: datetime | None = None,
          goal_id: str | None = None) -> dict[str, Any]:
    now = now or utcnow()
    if not goal_text.strip():
        raise GoalError("goal_text_required")
    gid = goal_id or goal_id_for(goal_text)
    store = GoalStore(project, gid)
    try:
        body = validate_draft(draft, goal_text)
    except ShapeError as exc:
        raise GoalError(exc.code, exc.detail) from exc
    with store.locked():
        replay = store.receipt_for(key or "")
        if replay:
            return {**replay, "replayed": True}
        if store.exists():
            raise GoalError("goal_exists", gid)
        plan = {"schema": "agentlas.goal-plan.v1", "goal_id": gid, "goal_text": goal_text.strip(), "status": "active",
                "created_at": K.iso(now), **body}
        for s in plan.get("strategies", []):
            s.update({"status": "active", "activated_at": K.iso(now)})
        for t in plan["tactics"]:
            t["status"] = "active"
        plan["kpis"] = _kpis_from_plan(plan, now)
        stored = store.write_plan(plan, None)
        receipt = {"goal_id": gid, "shape": stored["shape"], "revision": stored["revision"], "kpis": [k["id"] for k in stored["kpis"]],
                   "shape_matches_nature": stored["shape_matches_nature"], "mode": mode()}
        _record(store, "goal_started", now, receipt, key)
    return receipt


def plan_op(project: str, goal_id: str, op: Mapping[str, Any], key: str | None = None, now: datetime | None = None,
            expect_revision: int | None = None) -> dict[str, Any]:
    now = now or utcnow()
    store = _store(project, goal_id)
    with store.locked():
        replay = store.receipt_for(key or "")
        if replay:
            return {**replay, "replayed": True}
        plan = store.read_plan()
        if plan.get("status") != "active":
            raise GoalError("goal_not_active", plan.get("status", ""))
        try:
            new, receipt = apply_op(plan, op, now)
        except PlanError as exc:
            _record(store, "plan_op_rejected", now, {"op": op.get("op"), "reason": exc.code, "detail": exc.detail}, None)
            raise GoalError(exc.code, exc.detail) from exc
        stored = store.write_plan(new, expect_revision if expect_revision is not None else plan["revision"])
        receipt.update({"goal_id": goal_id, "revision": stored["revision"]})
        _record(store, "plan_op", now, receipt, key)
    return receipt


def kpi_define(project: str, goal_id: str, definition: Mapping[str, Any], key: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Add a tracking KPI (no owner target needed). Without a target only stalled, declining and breakout can fire."""
    now = now or utcnow()
    store = _store(project, goal_id)
    with store.locked():
        replay = store.receipt_for(key or "")
        if replay:
            return {**replay, "replayed": True}
        plan = store.read_plan()
        kid = str(definition.get("id") or "")
        if not re.match(r"^[A-Za-z][A-Za-z0-9_.-]{0,39}$", kid):
            raise GoalError("kpi_id_invalid", kid)
        if any(k["id"] == kid for k in plan.get("kpis", [])):
            raise GoalError("kpi_exists", kid)
        if definition.get("target") is not None:
            raise GoalError("target_only_from_goal", "a target must come from a key result stated by the owner")
        plan.setdefault("kpis", []).append({"id": kid, "name": scrub(definition.get("name") or kid, 200), "unit": str(definition.get("unit") or "")[:40],
                                            "direction": "down" if definition.get("direction") == "down" else "up", "kr_id": None, "target": None,
                                            "deadline_at": None, "baseline": None, "cadence_hours": int(definition.get("cadence_hours") or 24),
                                            "integer": bool(definition.get("integer"))})
        stored = store.write_plan(plan, plan["revision"])
        receipt = {"goal_id": goal_id, "kpi": kid, "revision": stored["revision"]}
        _record(store, "kpi_defined", now, receipt, key)
    return receipt


def _window_hours(plan: Mapping[str, Any]) -> float:
    windows = [s["observation_window_hours"] for s in active_strategies(plan)]
    return float(min(windows)) if windows else float(load_rules()["kpi"]["longWindowHoursDefault"])


def kpi_sample(project: str, goal_id: str, sample: Mapping[str, Any], key: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    rules = load_rules()
    store = _store(project, goal_id)
    with store.locked():
        replay = store.receipt_for(key or "")
        if replay:
            return {**replay, "replayed": True}
        plan = store.read_plan()
        kpi = next((k for k in plan.get("kpis", []) if k["id"] == sample.get("kpi_id")), None)
        if kpi is None:
            raise GoalError("kpi_unknown", str(sample.get("kpi_id")))
        try:
            value = float(sample.get("value"))
            observed = K.parse_time(str(sample.get("observed_at")))
        except (TypeError, ValueError):
            raise GoalError("sample_invalid", "value and observed_at must be a number and an ISO time")
        if not math.isfinite(value):
            raise GoalError("sample_invalid", "value is not finite")
        if observed > now + timedelta(seconds=rules["samples"]["futureSkewSeconds"]):
            raise GoalError("sample_in_future")
        source = scrub(sample.get("source") or "", 120)
        evidence = scrub(sample.get("evidence") or "")
        if not source or not evidence:
            raise GoalError("source_and_evidence_required")
        rows = [r for r in store.rows("kpi.jsonl") if r["kpi_id"] == kpi["id"]]
        if any(r["observed_at"] == K.iso(observed) for r in rows):
            raise GoalError("sample_duplicate", K.iso(observed))
        if sum(1 for r in rows if now - K.parse_time(r["recorded_at"]) < timedelta(days=1)) >= rules["samples"]["maxPerKpiPerDay"]:
            raise GoalError("sample_rate_cap")
        recent = [r["value"] for r in rows[-5:]]
        ceiling = rules["samples"]["valueCeilingFactor"] * max([abs(x) for x in [kpi.get("target"), kpi.get("baseline"), *recent] if x is not None] or [abs(value)])
        if value < 0 or abs(value) > max(ceiling, 1.0):
            raise GoalError("sample_out_of_range", f"{value} against ceiling {ceiling}")
        verified = False
        second = sample.get("reobserved")
        if isinstance(second, Mapping) and second.get("source") and scrub(second["source"], 120) != source:
            try:
                verified = abs(float(second["value"]) - value) <= max(abs(value) * 0.01, K.noise_floor(value, bool(kpi.get("integer")), rules))
            except (KeyError, TypeError, ValueError):
                verified = False
        record = {"id": "s" + hashlib.sha256(f"{goal_id}{kpi['id']}{K.iso(observed)}".encode()).hexdigest()[:10], "kpi_id": kpi["id"], "value": value,
                  "observed_at": K.iso(observed), "recorded_at": K.iso(now), "source": source, "evidence": evidence, "verified": verified,
                  "run_id": str(sample.get("run_id") or "")[:60]}
        store.append("kpi.jsonl", record)
        rows.append(record)
        state = store.read_state()
        evaluation = K.evaluate(kpi, rows, state["kpis"].get(kpi["id"]), now, _window_hours(plan), bool(kpi.get("integer")), rules)
        state["kpis"][kpi["id"]] = evaluation["row"]
        receipt = {"goal_id": goal_id, "sample": record["id"], "verified": verified, "state": evaluation["row"]["state"],
                   "changed": evaluation["changed"], "trigger": None, "owner_hold": bool(state.get("owner_hold"))}
        if evaluation["changed"]:
            _record(store, "kpi_state", now, {"kpi": kpi["id"], "from": evaluation["from"], "to": evaluation["to"],
                                              "measure": {k: evaluation["measure"].get(k) for k in ("latest", "vLong", "vShort", "required", "rho")}}, None)
        # Tried on every sample, not only on a change: a state that began inside a strategy's protection window must still
        # fire once the window is over. Cooldown, daily budget and the shift budget keep this from nagging.
        _maybe_fire(store, plan, kpi, evaluation, rows, state, now, receipt)
        _maybe_report_infeasible(store, plan, kpi, evaluation, rows, state, now, receipt)
        store.write_state(state)
    return receipt


def _maybe_fire(store: GoalStore, plan: Mapping[str, Any], kpi: Mapping[str, Any], evaluation: Mapping[str, Any], rows: list[dict[str, Any]],
                state: dict[str, Any], now: datetime, receipt: dict[str, Any]) -> None:
    rules = load_rules()
    row = state["kpis"][kpi["id"]]
    new_state = row["state"]
    open_trigger = state.get("trigger")
    if open_trigger and open_trigger.get("kpi") == kpi["id"] and new_state not in rules["trigger"]["fireStates"]:
        # The episode ended on its own (for example the new strategy worked): nothing is left to decide.
        state["trigger"] = None
        _record(store, "trigger_closed", now, {"trigger_id": open_trigger["id"], "kpi": kpi["id"], "state": new_state, "reason": "recovered"}, None)
        receipt["trigger_closed"] = open_trigger["id"]
    if state.get("owner_hold") or state.get("trigger"):
        return
    protected = [protected_until(s) for s in active_strategies(plan)]
    protected = [p for p in protected if p]
    until = max(protected) if protected else None
    fired_at = K.parse_time(row["last_fired_at"]) if row.get("last_fired_at") else None
    ok, reason = K.may_fire(new_state, fired_at, row.get("last_fired_state"), now, _window_hours(plan), until, rules)
    if ok and not K.trusted_enough(rows, now, rules):
        ok, reason = False, "samples_not_trusted"
    if ok:
        shifts = [K.parse_time(r["ts"]) for r in store.rows("decisions.jsonl") if r.get("kind") == "strategy_shift" and r["receipt"].get("applied")]
        if not K.shift_budget_left(shifts, now, rules):
            ok, reason = False, "shift_budget"
    if not ok:
        if reason != "state_not_fireable":
            receipt["trigger"] = {"fired": False, "reason": reason}
        return
    trigger = {"id": "t" + hashlib.sha256(f"{store.goal_id}{kpi['id']}{K.iso(now)}".encode()).hexdigest()[:10], "kpi": kpi["id"],
               "from": evaluation["from"] if evaluation["changed"] else row.get("last_fired_state") or new_state, "to": new_state, "created_at": K.iso(now), "sample_ids": evaluation["measure"].get("sampleIds", [])}
    state["trigger"] = trigger
    row.update({"last_fired_at": K.iso(now), "last_fired_state": new_state})
    receipt["trigger"] = {"fired": True, "id": trigger["id"]}


def _maybe_report_infeasible(store: GoalStore, plan: Mapping[str, Any], kpi: Mapping[str, Any], evaluation: Mapping[str, Any], rows: list[dict[str, Any]],
                             state: dict[str, Any], now: datetime, receipt: dict[str, Any]) -> None:
    rules = load_rules()
    row = state["kpis"][kpi["id"]]
    if state.get("owner_hold") or row.get("infeasible_ack"):
        return
    m = evaluation["measure"]
    if m.get("status") != "ok" or not K.infeasible(m, row["state"], rules) or not K.trusted_enough(rows, now, rules):
        row["infeasible_count"] = 0
        return
    newest = (m.get("sampleIds") or [None])[-1]
    if not newest or newest == row.get("infeasible_last"):
        return
    row["infeasible_last"] = newest
    row["infeasible_count"] = int(row.get("infeasible_count") or 0) + 1
    if row["infeasible_count"] >= rules["kpi"]["confirmEvaluations"]:
        report = {"kpi": kpi["id"], "latest": m.get("latest"), "required_per_day": m.get("required"), "observed_per_day": m.get("vLong"), "since": K.iso(now)}
        state["owner_hold"] = {"reason": "target_infeasible", **report}
        state["trigger"] = None
        _record(store, "owner_report", now, report, None)
        receipt["owner_hold"] = True
        receipt["owner_report"] = report


def owner_answer(project: str, goal_id: str, answer: str, note: str = "", key: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    if answer not in ("continue", "adjust", "stop"):
        raise GoalError("answer_invalid", answer)
    store = _store(project, goal_id)
    with store.locked():
        replay = store.receipt_for(key or "")
        if replay:
            return {**replay, "replayed": True}
        state = store.read_state()
        if not state.get("owner_hold"):
            raise GoalError("no_owner_hold")
        held_kpi = state["owner_hold"].get("kpi")
        state["owner_hold"] = None
        for kid, row in state["kpis"].items():
            row["infeasible_count"] = 0
            if kid == held_kpi and answer in ("continue", "adjust"):
                # The owner has seen the numbers and chose to go on: do not report the same gap again and again.
                row["infeasible_ack"] = True
        plan = store.read_plan()
        if answer == "stop":
            plan["status"] = "stopped"
            store.write_plan(plan, plan["revision"])
        store.write_state(state)
        receipt = {"goal_id": goal_id, "answer": answer, "note": scrub(note, 200)}
        _record(store, "owner_answer", now, receipt, key)
    return receipt


def _oscillating(store: GoalStore, retire_ids: list[str], plan: Mapping[str, Any], now: datetime) -> bool:
    cfg = load_rules()["trigger"]["oscillation"]
    window = timedelta(hours=cfg["windowHours"])
    texts = {s["id"]: s["hypothesis"] for s in plan.get("strategies", [])}
    count = 0
    for row in store.rows("decisions.jsonl"):
        if row.get("kind") != "strategy_shift" or now - K.parse_time(row["ts"]) > window:
            continue
        for added in row["receipt"].get("added_hypotheses", []):
            if any(texts.get(r) == added for r in retire_ids):
                count += 1
    return count >= cfg["maxAddRetireRepeats"]


def review(project: str, goal_id: str, shift: Mapping[str, Any] | None = None, key: str | None = None,
           now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    store = _store(project, goal_id)
    with store.locked():
        replay = store.receipt_for(key or "")
        if replay:
            return {**replay, "replayed": True}
        plan, state = store.read_plan(), store.read_state()
        rows = store.rows("kpi.jsonl")
        if shift is None:
            return {"goal_id": goal_id, "revision": plan["revision"], "trigger": state.get("trigger"), "owner_hold": state.get("owner_hold"),
                    "kpis": _kpi_table(plan, state, rows, now), "strategies": [
                        {"id": s["id"], "hypothesis": s["hypothesis"], "expected_delta": s.get("expected_delta"), "kill_if": s.get("kill_if"),
                         "activated_at": s["activated_at"], "protected_until": (K.iso(protected_until(s)) if protected_until(s) else None)}
                        for s in active_strategies(plan)], "recent_samples": [
                        {k: r[k] for k in ("id", "kpi_id", "value", "observed_at", "source", "verified")} for r in rows[-8:]]}
        if state.get("owner_hold"):
            raise GoalError("owner_hold", "waiting for the owner's answer to the infeasible report")
        trigger = state.get("trigger")
        if not trigger:
            raise GoalError("no_open_trigger")
        sample_ids = {r["id"] for r in rows}
        receipt: dict[str, Any] = {"goal_id": goal_id, "trigger_id": trigger["id"], "mode": mode()}
        try:
            new, applied = apply_shift(plan, shift, trigger, sample_ids, now)
        except PlanError as exc:
            _record(store, "strategy_shift", now, {**receipt, "applied": False, "rejected": exc.code, "detail": exc.detail}, None)
            raise GoalError(exc.code, exc.detail) from exc
        if shift.get("decision") in ("pivot", "double_down") and _oscillating(store, applied["retired"], plan, now):
            state["owner_hold"] = {"reason": "oscillation", "kpi": trigger["kpi"], "since": K.iso(now)}
            state["trigger"] = None
            store.write_state(state)
            receipt.update({"applied": False, "rejected": "oscillation", "owner_hold": True})
            _record(store, "strategy_shift", now, receipt, key)
            return receipt
        receipt.update(applied)
        receipt["added_hypotheses"] = [s["hypothesis"] for s in new["strategies"] if s["id"] in applied["added"]]
        if mode() == "on" and shift["decision"] in ("pivot", "double_down"):
            stored = store.write_plan(new, plan["revision"])
            receipt.update({"applied": True, "revision": stored["revision"]})
        else:
            receipt["applied"] = False
            if shift["decision"] in ("pivot", "double_down"):
                receipt["not_applied_reason"] = "mode_" + mode()
        if shift["decision"] == "escalate_owner":
            state["owner_hold"] = {"reason": "escalated_by_model", "kpi": trigger["kpi"], "since": K.iso(now)}
        state["trigger"] = None
        store.write_state(state)
        _record(store, "strategy_shift", now, receipt, key)
    return receipt


def _kpi_table(plan: Mapping[str, Any], state: Mapping[str, Any], rows: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    table = []
    for kpi in plan.get("kpis", []):
        mine = [r for r in rows if r["kpi_id"] == kpi["id"]]
        m = K.measure(kpi, mine, now, _window_hours(plan), bool(kpi.get("integer")))
        table.append({"id": kpi["id"], "name": kpi["name"], "target": kpi.get("target"), "latest": mine[-1]["value"] if mine else None,
                      "state": state.get("kpis", {}).get(kpi["id"], {}).get("state", "no_data"), "vLong": m.get("vLong"), "required": m.get("required"),
                      "samples": len(mine)})
    return table


def refresh(project: str, goal_id: str, now: datetime | None = None) -> dict[str, Any]:
    """Re-evaluate every KPI with the clock alone, so a trigger held back by a protection window or cooldown can fire.

    Nothing new is observed here: no sample is written. Hosts call it from `goal.status` and `goal.review`.
    """
    now = now or utcnow()
    store = _store(project, goal_id)
    fired: list[str] = []
    with store.locked():
        plan, state, rows = store.read_plan(), store.read_state(), store.rows("kpi.jsonl")
        for kpi in plan.get("kpis", []):
            mine = [r for r in rows if r["kpi_id"] == kpi["id"]]
            if not mine:
                continue
            evaluation = K.evaluate(kpi, mine, state["kpis"].get(kpi["id"]), now, _window_hours(plan), bool(kpi.get("integer")))
            state["kpis"][kpi["id"]] = evaluation["row"]
            receipt: dict[str, Any] = {}
            _maybe_fire(store, plan, kpi, evaluation, mine, state, now, receipt)
            _maybe_report_infeasible(store, plan, kpi, evaluation, mine, state, now, receipt)
            if (receipt.get("trigger") or {}).get("fired"):
                fired.append(kpi["id"])
        store.write_state(state)
    return {"goal_id": goal_id, "fired": fired}


def status(project: str, goal_id: str, now: datetime | None = None) -> dict[str, Any]:
    now = now or utcnow()
    _store(project, goal_id)
    refresh(project, goal_id, now)
    store = _store(project, goal_id)
    plan, state, rows = store.read_plan(), store.read_state(), store.rows("kpi.jsonl")
    return {"goal_id": goal_id, "status": plan["status"], "shape": plan["shape"], "revision": plan["revision"], "mode": mode(),
            "open_tactics": [{"id": t["id"], "description": t["description"], "done_when": t["done_when"]} for t in open_tactics(plan)],
            "kpis": _kpi_table(plan, state, rows, now), "trigger": state.get("trigger"), "owner_hold": state.get("owner_hold")}


def context(project: str, goal_id: str, now: datetime | None = None) -> str:
    """The block a host adds to the next turn: at most N active tactics and one KPI line. Empty when it should stay silent."""
    now = now or utcnow()
    if mode() != "on":
        return ""
    store = GoalStore(project, goal_id)
    if not store.exists():
        return ""
    plan, state, rows = store.read_plan(), store.read_state(), store.rows("kpi.jsonl")
    if plan.get("status") != "active" or plan["shape"] == "single_tactic":
        return ""  # a single tactic is just the host's own goal; adding text would only cost tokens
    cfg = load_rules()["context"]
    done = {t["id"] for t in plan["tactics"] if t.get("status") == "done"}
    ready = [t for t in open_tactics(plan) if all(d in done for d in t.get("depends_on", []))] or open_tactics(plan)
    lines = [f"goal-plan {goal_id} r{plan['revision']} shape={plan['shape']} (the host goal decides when it is done; this only reports state)"]
    for t in ready[: cfg["maxActiveTactics"]]:
        lines.append(f"- tactic {t['id']}: {t['description']} | done when: {t['done_when']}")
    if state.get("owner_hold"):
        lines.append(f"owner hold: {state['owner_hold']['reason']}; ask the owner, do not re-plan until they answer")
    elif state.get("trigger"):
        t = state["trigger"]
        lines.append(f"review due: {t['kpi']} {t['from']}->{t['to']}; call goal.review then goal.review with a shift (trigger {t['id']})")
    table = _kpi_table(plan, state, rows, now)[: cfg["maxKpiLines"]]
    for k in table:
        if k["state"] == "no_data":
            lines.append(f"kpi {k['id']}: no data yet; measure it now and call goal.kpi_sample with source and evidence")
        else:
            lines.append(f"kpi {k['id']}: {k['latest']} / {k['target']} {k['state']}")
    text = "\n".join(lines)[: cfg["maxChars"]]
    return text + f"\nctx:{hashlib.sha256(text.encode()).hexdigest()[:8]}"


def contracts() -> dict[str, Any]:
    """Field lists a model needs to call the goal tools correctly, so no command text has to restate them."""
    lim = load_rules()["limits"]
    return {
        "schema": "agentlas.goal-contracts.v1", "mode": mode(),
        "start": {"shape": "single_tactic|tactic_list|mission_tree", "problem_nature": "clear|complicated|complex|chaotic",
                  "rationale": "text", "tactics": f"1..{lim['tactics']} of {{id, strategy_id|null, description, done_when, kind: one_off|recurring, depends_on[]}}",
                  "strategies": f"0..{lim['strategies']} of {{id, hypothesis, serves_krs[], kpi, timebox_hours, observation_window_hours, expected_delta, kill_if}}",
                  "mission": "mission_tree only: {objective, diagnosis, key_results[{id, metric, target, unit, deadline, baseline}], boundaries[{text, source: owner+quote|platform_rule+rule_ref}]}",
                  "rules": ["a target must be a number the owner wrote in the goal text", "an owner boundary needs a quote that appears in the goal text",
                            "single_tactic means one tactic with strategy_id null, strategies [] and no mission: use it for short, clearly checkable work",
                            "tactic_list means tactics only (strategy_id null), no strategies and no mission",
                            "mission_tree needs a mission, at least one strategy, and EVERY tactic must name a strategy_id",
                            "key result deadline: an ISO date (2026-12-31), an ISO time, or a duration like P30D / P3W; null when the owner gave none",
                            "ids start with a letter and use letters, digits, _ . - only"]},
        "plan_op": {"op": "add_strategy|retire_strategy|add_tactic|replace_tactic|set_tactic_status",
                    "fields": "retire_strategy {id, evidence}; add_tactic {id, strategy_id, description, done_when}; replace_tactic {replaces, ...add_tactic}; set_tactic_status {id, status: active|done|blocked|retired}"},
        "kpi_sample": {"kpi_id": "id", "value": "number", "observed_at": "ISO time", "source": "tool or screen the value came from (required)",
                       "evidence": "short quote of what was read (required, secrets and URL queries are removed)",
                       "reobserved": "optional {source, value}: a second reading from a different source makes the sample verified"},
        "shift": {"trigger_id": "the open trigger", "decision": "exactly one of: hold | pivot | double_down | escalate_owner",
                  "diagnosis": "why, citing samples", "evidence_refs": "sample ids from the review table",
                  "retire": "[{id, evidence}]", "add": "[{id, hypothesis, kpi, serves_krs, tactics[{id, description, done_when}]}]",
                  "rules": ["pivot retires the current strategy AND adds a new one with at least one tactic; retiring without adding is refused",
                            "hold needs only a diagnosis; escalate_owner stops re-planning until the owner answers"]},
        "writes": load_rules()["writes"],
    }
