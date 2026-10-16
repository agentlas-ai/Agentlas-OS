"""KPI pace, state machine and trigger rules. Pure functions: no files, no clock, no randomness.

Every threshold is read from contracts/goal-rules.json. Hysteresis keeps a state until its exit condition holds, and a
state only changes after the same candidate is seen on `confirmEvaluations` evaluations that saw more samples each time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping, Sequence

from .rules import load_rules

STATES = ("no_data", "ahead", "on_pace", "behind", "stalled", "breakout", "declining")
DAY = 86400.0


def parse_time(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    moment = datetime.fromisoformat(text)
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slope_per_day(points: Sequence[tuple[datetime, float]]) -> float | None:
    """Least-squares slope in units per day, or None with fewer than two distinct times."""
    if len(points) < 2:
        return None
    t0 = points[0][0]
    xs = [(t - t0).total_seconds() / DAY for t, _ in points]
    ys = [v for _, v in points]
    mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
    denom = sum((x - mean_x) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom


def required_per_day(kpi: Mapping[str, Any], latest: float, now: datetime) -> float | None:
    """Pace the owner's number needs from here, or None when there is no target or deadline."""
    target, deadline = kpi.get("target"), kpi.get("deadline_at")
    if target is None or not deadline:
        return None
    days_left = (parse_time(deadline) - now).total_seconds() / DAY
    if days_left <= 0:
        return None
    direction = -1.0 if kpi.get("direction") == "down" else 1.0
    return direction * (float(target) - latest) / days_left


def noise_floor(latest: float, integer_unit: bool, rules: Mapping[str, Any] | None = None) -> float:
    cfg = (rules or load_rules())["kpi"]
    floor = cfg["relativeNoisePerDay"] * abs(latest)
    if integer_unit:
        floor = max(floor, cfg["integerNoiseFloorPerDay"])
    return max(floor, 1e-9)


def usable_samples(samples: Iterable[Mapping[str, Any]], now: datetime, rules: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    """Samples inside the expiry age, oldest first. Expired samples never feed a state."""
    cfg = rules or load_rules()
    limit = timedelta(hours=cfg["samples"]["maxAgeHours"])
    kept = [dict(s) for s in samples if now - parse_time(s["observed_at"]) <= limit]
    return sorted(kept, key=lambda s: s["observed_at"])


def _window(points: Sequence[tuple[datetime, float]], now: datetime, hours: float) -> list[tuple[datetime, float]]:
    start = now - timedelta(hours=hours)
    return [(t, v) for t, v in points if t >= start]


def _enter_candidate(rho: float | None, v_long: float, v_short: float, v_prev: float, eps: float,
                     required: float | None, cfg: Mapping[str, Any]) -> str:
    if v_long < 0 and v_short < 0:
        return "declining"
    b = cfg["breakout"]
    # A breakout is a change against an earlier slope; with no earlier window to compare there is nothing to break out of.
    if v_prev is not None and v_short >= b["enterMultiple"] * max(v_prev, eps) and (required is None or v_short >= b["minPaceFraction"] * required):
        return "breakout"
    if rho is None:
        return "stalled" if abs(v_long) < eps else "on_pace"
    if rho < cfg["stalled"]["enterRho"]:
        return "stalled"
    if rho < cfg["onPace"]["enterRho"]:
        return "behind"
    if rho < cfg["ahead"]["enterRho"]:
        return "on_pace"
    return "ahead"


def _still_holds(state: str, rho: float | None, v_long: float, v_short: float, v_prev: float, eps: float,
                 cfg: Mapping[str, Any]) -> bool:
    """Hysteresis: a state is kept until its exit condition is met."""
    if state == "declining":
        return v_short < 0
    if state == "breakout":
        return v_short >= cfg["breakout"]["keepMultiple"] * max(v_prev or 0.0, eps)
    if rho is None:
        return state == "stalled" and abs(v_long) < eps
    if state == "ahead":
        return rho >= cfg["ahead"]["keepRho"]
    if state == "on_pace":
        return cfg["onPace"]["keepMinRho"] <= rho < cfg["onPace"]["keepMaxRho"]
    if state == "behind":
        return cfg["behind"]["keepMinRho"] <= rho < cfg["behind"]["keepMaxRho"]
    if state == "stalled":
        return rho < cfg["stalled"]["keepBelowRho"]
    return False


def measure(kpi: Mapping[str, Any], samples: Sequence[Mapping[str, Any]], now: datetime, window_hours: float,
            integer_unit: bool = False, rules: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The numbers one evaluation looks at. `status` is `no_data` when the window cannot support a state."""
    cfg = rules or load_rules()
    k = cfg["kpi"]
    usable = usable_samples(samples, now, cfg)
    points = [(parse_time(s["observed_at"]), float(s["value"])) for s in usable]
    long_pts = _window(points, now, window_hours)
    short_hours = max(k["shortWindowMinHours"], window_hours / k["shortWindowDivisor"])
    short_pts = _window(points, now, short_hours)
    span_hours = (long_pts[-1][0] - long_pts[0][0]).total_seconds() / 3600 if len(long_pts) >= 2 else 0.0
    result: dict[str, Any] = {"samples": len(usable), "windowSamples": len(long_pts), "status": "ok",
                              "sampleIds": [s.get("id") for s in usable if parse_time(s["observed_at"]) >= now - timedelta(hours=window_hours)]}
    if len(long_pts) < k["minSamples"] or span_hours < k["minWindowFraction"] * window_hours:
        result["status"] = "no_data"
        return result
    v_long = slope_per_day(long_pts) or 0.0
    v_short = slope_per_day(short_pts) if len(short_pts) >= 2 else v_long
    prev_pts = [(t, v) for t, v in points if now - timedelta(hours=2 * window_hours) <= t < now - timedelta(hours=window_hours)]
    v_prev = slope_per_day(prev_pts) if len(prev_pts) >= 2 else None
    latest = long_pts[-1][1]
    direction = -1.0 if kpi.get("direction") == "down" else 1.0
    v_long, v_short = direction * v_long, direction * v_short
    v_prev = None if v_prev is None else direction * v_prev
    required = required_per_day(kpi, latest, now)
    rho = (v_long / required) if required not in (None, 0) else None
    result.update({"latest": latest, "vLong": v_long, "vShort": v_short, "vPrev": v_prev, "required": required, "rho": rho,
                   "eps": noise_floor(latest, integer_unit, cfg)})
    return result


def evaluate(kpi: Mapping[str, Any], samples: Sequence[Mapping[str, Any]], row: Mapping[str, Any] | None, now: datetime,
             window_hours: float, integer_unit: bool = False, rules: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """One evaluation: the next state row plus whether the state changed this time."""
    cfg = rules or load_rules()
    k = cfg["kpi"]
    row = dict(row or {"state": "no_data", "since": iso(now), "pending_state": None, "pending_count": 0, "pending_last": None})
    m = measure(kpi, samples, now, window_hours, integer_unit, cfg)
    out = {"row": row, "measure": m, "changed": False, "from": row["state"], "to": row["state"]}
    if m["status"] == "no_data":
        # Missing or sparse data is an infrastructure state, never a strategy failure.
        if row["state"] != "no_data" and not samples:
            row.update({"state": "no_data", "since": iso(now), "pending_state": None, "pending_count": 0})
            out.update({"changed": True, "to": "no_data"})
        return out
    held = row["state"] != "no_data" and _still_holds(row["state"], m["rho"], m["vLong"], m["vShort"], m["vPrev"], m["eps"], k)
    candidate = row["state"] if held else _enter_candidate(m["rho"], m["vLong"], m["vShort"], m["vPrev"], m["eps"], m["required"], k)
    if candidate == row["state"]:
        row.update({"pending_state": None, "pending_count": 0})
        return out
    if row["state"] == "no_data":
        # The first state is taken on sight: there is no earlier state to be stable against.
        row.update({"state": candidate, "since": iso(now), "pending_state": None, "pending_count": 0, "pending_last": (m.get("sampleIds") or [None])[-1]})
        out.update({"changed": True, "to": candidate})
        return out
    # A confirmation needs a newer reading than the last one that counted. Comparing the newest sample (not how many fit
    # in the window) is what keeps a sliding window from freezing a pending change forever.
    newest = (m.get("sampleIds") or [None])[-1]
    if candidate == row.get("pending_state") and newest and newest != row.get("pending_last"):
        row["pending_count"] = int(row.get("pending_count") or 0) + 1
    elif candidate != row.get("pending_state"):
        row.update({"pending_state": candidate, "pending_count": 1})
    row["pending_last"] = newest
    if row["pending_count"] >= k["confirmEvaluations"]:
        row.update({"state": candidate, "since": iso(now), "pending_state": None, "pending_count": 0})
        out.update({"changed": True, "to": candidate})
    return out


def trusted_enough(samples: Sequence[Mapping[str, Any]], now: datetime, rules: Mapping[str, Any] | None = None) -> bool:
    """Whether the window may fire a shift or an infeasible report.

    One verified sample is enough. Otherwise unverified samples need `unverifiedNeedsDistinctSources` different sources,
    so one tool's repeated reading cannot decide a strategy alone.
    """
    cfg = rules or load_rules()
    t = cfg["trust"]
    usable = usable_samples(samples, now, cfg)
    if any(s.get("verified") for s in usable) and t["verifiedCountsAlone"]:
        return True
    sources = {s.get("source") for s in usable if s.get("source")}
    return len(sources) >= t["unverifiedNeedsDistinctSources"]


def shift_budget_left(shift_times: Iterable[datetime], now: datetime, rules: Mapping[str, Any] | None = None) -> bool:
    cfg = (rules or load_rules())["trigger"]
    times = list(shift_times)
    day = sum(1 for t in times if now - t < timedelta(days=1))
    week = sum(1 for t in times if now - t < timedelta(days=7))
    return day < cfg["shiftsPerDay"] and week < cfg["shiftsPerRolling7Days"]


def may_fire(new_state: str, last_fired_at: datetime | None, last_fired_state: str | None, now: datetime,
             window_hours: float, protected_until: datetime | None, rules: Mapping[str, Any] | None = None) -> tuple[bool, str]:
    """Whether a state change may raise a trigger, with the reason when it may not."""
    cfg = (rules or load_rules())["trigger"]
    if new_state not in cfg["fireStates"]:
        return False, "state_not_fireable"
    if protected_until and now < protected_until:
        return False, "strategy_protected"
    if last_fired_at:
        base = max(cfg["cooldownMinHours"], window_hours)
        hours = base * (cfg["repeatCooldownFactor"] if last_fired_state == new_state else 1)
        if now - last_fired_at < timedelta(hours=hours):
            return False, "cooldown"
        if now - last_fired_at < timedelta(days=1) / max(cfg["firesPerDay"], 1):
            return False, "daily_fire_budget"
    return True, "ok"


def infeasible(measurement: Mapping[str, Any], state: str, rules: Mapping[str, Any] | None = None) -> bool:
    cfg = (rules or load_rules())["trigger"]
    required, v_long = measurement.get("required"), measurement.get("vLong")
    if required is None or v_long is None or state not in ("stalled", "behind"):
        return False
    return required > 0 and (v_long <= 0 or required / v_long >= cfg["infeasibleRatio"])
