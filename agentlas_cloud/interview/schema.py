"""Work Brief — the frozen output of a briefing interview.

A Work Brief pins a request down to: one-line goal, constraints, verifiable
acceptance criteria, an assumption ledger with source tags, anti-scope (what
NOT to do — the direct source of routing-card anti_triggers), weighted
evaluation principles and exit conditions. The interview's final ambiguity
score is stamped into metadata so any downstream consumer (builder, pipeline
planner, stormbreaker runner, router) can audit how settled the spec was.

The engine only validates/loads/derives — it never calls a model (BYOC).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NamedTuple

WORK_BRIEF_SCHEMA_VERSION = "work-brief/1.0"
WORK_BRIEF_RELPATH = ".agentlas/work-brief.json"

_VALID_ASSUMPTION_STATUS = {"verified", "assumed"}
_VALID_ASSUMPTION_SOURCE = {"user", "code", "memory", "research", "default"}
_VALID_SURFACES = {"hep-build", "stormbreaker", "chat", "hub-draft"}


def work_brief_problem(record: dict[str, Any]) -> str | None:
    """Validate a Work Brief dict. Returns a human-readable problem or None."""
    if not isinstance(record, dict):
        return "work brief must be an object"
    if str(record.get("schemaVersion") or "") != WORK_BRIEF_SCHEMA_VERSION:
        return f"schemaVersion must be {WORK_BRIEF_SCHEMA_VERSION}"
    goal = record.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        return "goal must be a non-empty one-line string"
    if "\n" in goal.strip():
        return "goal must be a single line (the restated, confirmed sentence)"
    for field in ("constraints", "acceptance_criteria", "anti_scope"):
        value = record.get(field)
        if value is None:
            continue
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            return f"{field} must be a list of strings"
    for entry in record.get("assumptions") or []:
        if not isinstance(entry, dict) or not str(entry.get("text") or "").strip():
            return "assumptions entries must be objects with text"
        if str(entry.get("status") or "") not in _VALID_ASSUMPTION_STATUS:
            return "assumption status must be verified|assumed"
        if str(entry.get("source") or "") not in _VALID_ASSUMPTION_SOURCE:
            return "assumption source must be user|code|memory|research|default"
    principles = record.get("evaluation_principles") or []
    if principles:
        total = 0.0
        for entry in principles:
            if not isinstance(entry, dict) or not str(entry.get("name") or "").strip():
                return "evaluation_principles entries must be objects with name"
            try:
                total += float(entry.get("weight") or 0)
            except (TypeError, ValueError):
                return "evaluation_principles weight must be numeric"
        if abs(total - 1.0) > 0.01:
            return f"evaluation_principles weights must sum to 1.0 (got {round(total, 3)})"
    meta = record.get("metadata") or {}
    if not isinstance(meta, dict):
        return "metadata must be an object"
    surface = str(meta.get("surface") or "")
    if surface and surface not in _VALID_SURFACES:
        return f"metadata.surface must be one of {sorted(_VALID_SURFACES)}"
    score = meta.get("ambiguity_score")
    if score is not None:
        try:
            value = float(score)
        except (TypeError, ValueError):
            return "metadata.ambiguity_score must be numeric"
        if not 0.0 <= value <= 1.0:
            return "metadata.ambiguity_score must be within [0, 1]"
    return None


class WorkBriefResolution(NamedTuple):
    """Outcome of resolving a Work Brief source, with the reason kept.

    `problem` is set only when a Work Brief file exists but cannot be used;
    `exists` False with `problem` None is simply "no brief here".
    """

    path: Path
    brief: dict[str, Any] | None
    problem: str | None
    exists: bool


def resolve_work_brief(source: str | Path) -> WorkBriefResolution:
    """Resolve a Work Brief from a file path or a project dir, keeping the reason.

    `work_brief_problem` already computes a precise human-readable diagnosis, and
    `load_work_brief` used to throw it away. That is fine for discovery (no brief
    in a project dir is the normal case) but wrong for an explicit `--brief`: the
    caller could not tell "no brief was asked for" from "the brief you named is
    unreadable", so routing continued brief-less and returned a normal-looking
    plan the user's frozen goal/acceptance_criteria/anti_scope never shaped.
    Callers now decide: explicit request -> refuse with `problem`; discovery ->
    surface `problem` without blocking the run.
    """
    path = Path(source)
    if path.is_dir():
        path = path / WORK_BRIEF_RELPATH
    if not path.is_file():
        return WorkBriefResolution(path=path, brief=None, problem=None, exists=False)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return WorkBriefResolution(path, None, f"cannot read Work Brief file ({exc})", True)
    except ValueError as exc:
        return WorkBriefResolution(path, None, f"Work Brief is not valid JSON ({exc})", True)
    problem = work_brief_problem(record)
    if problem:
        return WorkBriefResolution(path, None, problem, True)
    return WorkBriefResolution(path, record, None, True)


def load_work_brief(source: str | Path) -> dict[str, Any] | None:
    """Load a Work Brief from a file path or a project dir (.agentlas/work-brief.json).

    Returns None when the file is missing or invalid. Use `resolve_work_brief`
    when the source came from an explicit user request — this wrapper cannot
    tell "absent" from "broken" and must not be used to decide either.
    """
    return resolve_work_brief(source).brief


def brief_scope_text(brief: dict[str, Any]) -> str:
    """Flatten the brief's scoping fields into one text blob.

    Used by the pipeline planner for stage-intent detection: the confirmed
    goal + acceptance criteria carry the user's real intent far better than
    the raw first message did.
    """
    parts: list[str] = [str(brief.get("goal") or "")]
    parts.extend(str(item) for item in brief.get("acceptance_criteria") or [])
    parts.extend(str(item) for item in brief.get("constraints") or [])
    return "\n".join(part for part in parts if part.strip())


def brief_packet_context(brief: dict[str, Any], max_items: int = 6) -> dict[str, Any]:
    """Compact brief view for embedding into execution packets/prompts."""
    return {
        "goal": str(brief.get("goal") or ""),
        "constraints": [str(c) for c in (brief.get("constraints") or [])[:max_items]],
        "acceptance_criteria": [str(c) for c in (brief.get("acceptance_criteria") or [])[:max_items]],
        "anti_scope": [str(c) for c in (brief.get("anti_scope") or [])[:max_items]],
        "exit_conditions": [
            {"name": str(e.get("name") or ""), "criteria": str(e.get("criteria") or "")}
            for e in (brief.get("exit_conditions") or [])[:max_items]
            if isinstance(e, dict)
        ],
        "ambiguity_score": (brief.get("metadata") or {}).get("ambiguity_score"),
    }
