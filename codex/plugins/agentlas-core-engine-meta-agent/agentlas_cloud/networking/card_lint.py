"""Routing card validation and quality gates.

routing_ready minimum requirements (docs/hephaestus-network-2.0.md):
>=5 trigger examples (>=2 ko and >=2 en), >=3 anti-triggers, verb-form
capabilities, declared required_inputs, declared risk profile, validated
entrypoints, >=10 benchmark cases, declared memory behavior, and no broad
"do anything" capability without penalty.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .domains import DOMAIN_IDS

VERB_CAPABILITY_RE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")
BROAD_CAPABILITIES = {
    "do_anything",
    "handle_everything",
    "general_assistant",
    "general_assistance",
    "anything_else",
    "all_tasks",
}
VALID_STATUSES = ["draft", "searchable", "candidate", "routing_ready", "trusted"]
REQUIRED_FIELDS = ["schemaVersion", "id", "type", "name", "summary", "capabilities", "routing_status"]
BREADTH_PENALTY_THRESHOLD = 12


def _triggers_by_locale(card: dict[str, Any], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in card.get(field) or []:
        if isinstance(entry, dict) and entry.get("text"):
            locale = str(entry.get("locale") or "en")
            counts[locale] = counts.get(locale, 0) + 1
    return counts


def _benchmark_case_count(card: dict[str, Any]) -> int:
    fixture = card.get("benchmark_fixtures")
    if not fixture:
        return 0
    fixture_path = Path(str(fixture))
    if not fixture_path.is_absolute():
        source_ref = ((card.get("source") or {}).get("ref")) or ""
        if source_ref:
            fixture_path = Path(str(source_ref)) / fixture_path
    if not fixture_path.is_file():
        return 0
    try:
        return sum(1 for line in fixture_path.read_text(encoding="utf-8").splitlines() if line.strip())
    except OSError:
        return 0


def lint_card(card: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    score = 0.0

    for field in REQUIRED_FIELDS:
        if not card.get(field):
            errors.append(f"missing required field: {field}")
    if card.get("type") not in ("agent", "team", "plugin", None):
        errors.append(f"invalid type: {card.get('type')}")
    if card.get("routing_status") not in VALID_STATUSES and card.get("routing_status") is not None:
        errors.append(f"invalid routing_status: {card.get('routing_status')}")

    capabilities = [str(cap) for cap in card.get("capabilities") or []]
    non_verb = [cap for cap in capabilities if not VERB_CAPABILITY_RE.match(cap)]
    broad = [cap for cap in capabilities if cap in BROAD_CAPABILITIES]
    trigger_counts = _triggers_by_locale(card, "trigger_examples")
    anti_counts = _triggers_by_locale(card, "anti_triggers")
    trigger_total = sum(trigger_counts.values())
    anti_total = sum(anti_counts.values())
    bench_cases = _benchmark_case_count(card)

    ready_blockers: list[str] = []
    if trigger_total < 5:
        ready_blockers.append(f"needs >=5 trigger_examples (has {trigger_total})")
    if trigger_counts.get("ko", 0) < 2 or trigger_counts.get("en", 0) < 2:
        ready_blockers.append(
            f"needs >=2 ko and >=2 en trigger_examples (ko={trigger_counts.get('ko', 0)}, en={trigger_counts.get('en', 0)})"
        )
    if anti_total < 3:
        ready_blockers.append(f"needs >=3 anti_triggers (has {anti_total})")
    if non_verb:
        ready_blockers.append(f"capabilities must be verb_object snake_case: {non_verb[:3]}")
    if broad:
        ready_blockers.append(f"broad 'do anything' capabilities are not allowed: {broad}")
    if "required_inputs" not in card:
        ready_blockers.append("required_inputs must be declared (empty list is allowed)")
    if not ((card.get("risk_profile") or {}).get("tier")):
        ready_blockers.append("risk_profile.tier must be declared")
    if not ((card.get("entrypoints") or {}).get("canonical_command")) and not (
        (card.get("entrypoints") or {}).get("agent")
    ):
        ready_blockers.append("entrypoints must declare canonical_command or agent path")
    if not card.get("memory_behavior"):
        ready_blockers.append("memory_behavior must be declared")
    if bench_cases < 10:
        ready_blockers.append(f"needs >=10 benchmark cases (has {bench_cases})")

    score += min(trigger_total, 8) * 0.06
    score += min(anti_total, 5) * 0.05
    score += 0.15 if capabilities and not non_verb else 0.0
    score += 0.10 if (card.get("risk_profile") or {}).get("tier") else 0.0
    score += 0.10 if card.get("memory_behavior") else 0.0
    score += min(bench_cases, 12) * 0.015
    if len(capabilities) > BREADTH_PENALTY_THRESHOLD:
        score -= 0.10
        warnings.append(f"breadth penalty: {len(capabilities)} capabilities declared")
    if broad:
        score -= 0.25
    score = max(0.0, min(1.0, round(score, 3)))

    # Domain tags (soft): validate the vocabulary but never block a route — the
    # router infers domains from text when the field is absent, so this is a
    # quality nudge, not a gate.
    declared_domains = card.get("domains")
    if declared_domains:
        if not isinstance(declared_domains, list):
            warnings.append("domains must be a list of domain ids")
        else:
            unknown = [str(d) for d in declared_domains if str(d) not in DOMAIN_IDS]
            if unknown:
                warnings.append(f"unknown domain tags (not in vocab): {unknown[:3]}")
    else:
        warnings.append("no domain tags declared (router will infer from text)")

    claimed = str(card.get("routing_status") or "draft")
    if errors:
        allowed = "quarantined"
    elif ready_blockers:
        allowed = "searchable" if trigger_total >= 1 else "draft"
    else:
        allowed = claimed if claimed in ("routing_ready", "trusted") else "routing_ready"

    return {
        "id": card.get("id"),
        "errors": errors,
        "warnings": warnings,
        "ready_blockers": ready_blockers,
        "quality_score": score,
        "claimed_status": claimed,
        "allowed_status": allowed,
        "benchmark_cases": bench_cases,
    }


def effective_status(card: dict[str, Any]) -> str:
    """The status the router actually honors: never above what lint allows."""
    if card.get("stale"):
        return "stale"
    report = lint_card(card)
    if report["errors"]:
        return "quarantined"
    claimed = report["claimed_status"]
    if claimed in ("routing_ready", "trusted") and report["ready_blockers"]:
        return "searchable"
    return claimed if claimed in VALID_STATUSES else "draft"
