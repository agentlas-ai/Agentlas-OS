"""Semantic private-memory eligibility and read-only legacy proposal compatibility.

Only exact staged file proposals can enter the owner approval service. Historical
count-based summaries remain readable and cannot authorize executable changes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .memory_contract import (
    EVOLUTION_PROPOSALS_CONTRACT,
    EVOLUTION_PROPOSALS_RELATIVE,
    EVOLUTION_REVIEW_COMMAND,
    validate_proposal_entry,
)

_LOGGER = logging.getLogger(__name__)

# Deterministic trigger thresholds (mirror of the Desktop evolution-triggers
# intent: repeated failure / accumulated experience). Kept conservative so a
# single noisy session never fabricates a proposal.
ACCUMULATED_EXPERIENCE_MIN = 5
REPEATED_FAILURE_MIN = 3
# Reference vocabulary — passed to the judge as a HINT only, never a decider.
_FAILURE_HINT_WORDS = (
    "fail", "error", "gotcha", "incident", "regress", "bug", "attack",
    "vuln", "보안", "취약", "버그", "사고", "실패",
)
_SECRET_HINT_RE = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|gh[opsu]_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{20,}"
    r"|AKIA[0-9A-Z]{16}|-----BEGIN|password|secret|token|api[_-]?key)",
    re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_failure_signal(tag_text: str, memory_kind: str) -> bool:
    """Failure/gotcha classification for one experience row.

    ``memory_kind == "risk"`` is a closed-form stored id and always counts.
    For tag text, the connected model decides by meaning with the failure
    vocabulary as a hint. There is no keyword verdict: with no model connected
    (or on any runner error) the row is left UNDECIDED and NOT counted as a
    failure — never a keyword-derived True.
    """

    if memory_kind == "risk":
        return True
    if not tag_text.strip():
        return False
    try:
        from .judgment import has_judgment_runner, judge_bool
    except Exception:  # pragma: no cover - judgment module is optional at import time
        return False
    if not has_judgment_runner():
        return False
    decided, source = judge_bool(
        kind="evolution-failure-tag",
        question=(
            "Do these memory tags describe a failure, bug, incident, regression, or "
            "security problem the agent ran into?"
        ),
        text=tag_text,
        hints={"failure": list(_FAILURE_HINT_WORDS)},
        guidance=(
            "Judge meaning, not keyword presence — 'bugfix-released' is a success note, "
            "while a novel word for a production outage still counts as failure."
        ),
        fallback=False,
    )
    return decided if source == "model" else False


def _safe_keyword(value: str) -> str:
    """A single tag keyword, dropped entirely if it looks secret-ish."""
    text = " ".join(str(value or "").split())[:40]
    return "" if _SECRET_HINT_RE.search(text) else text


def build_proposal_entry(
    *,
    agent_id: str,
    trigger_kind: str,
    learned: str,
    change: str,
    reversible: str,
    risk_tier: str = "low",
    status: str = "pending",
) -> dict[str, Any]:
    """Build one contract-shaped entry with a stable, idempotent id.

    The id is keyed by (agent_id, trigger_kind) so re-running the hook as
    evidence grows updates the same entry instead of duplicating it.
    """

    stable = hashlib.sha256(f"{agent_id}:{trigger_kind}".encode("utf-8")).hexdigest()[:16]
    entry = {
        "id": f"hep-{trigger_kind}-{stable}",
        "agentId": agent_id,
        "riskTier": "high" if risk_tier == "high" else "low",
        "status": status,
        "learned": " ".join(str(learned).split())[:280],
        "change": " ".join(str(change).split())[:280],
        "reversible": " ".join(str(reversible).split())[:200],
    }
    return entry


def derive_proposals_from_experience(db_path: Path, agent_id: str) -> list[dict[str, Any]]:
    """Retired count-based summaries are not executable file proposals."""
    return []


def derive_memory_candidates(db_path: Path, agent_id: str) -> list[dict[str, Any]]:
    """Project existing private memories into semantic review states, never chips."""
    from .agent_revisions import eligible_memory
    if not db_path.is_file() or db_path.is_symlink():
        return []
    with closing(sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM memory_candidates WHERE agent_id = ? ORDER BY updated_at DESC LIMIT 200",
            (agent_id,),
        ).fetchall()
        # Retain the same structural supersession boundary as private recall.
        superseded = set()
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_links'").fetchone():
            superseded = {row[0] for row in conn.execute(
                """SELECT ml.to_ticket FROM memory_links ml
                   JOIN memory_candidates newer ON newer.ticket_id = ml.from_ticket
                   JOIN memory_candidates older ON older.ticket_id = ml.to_ticket
                   WHERE ml.link_type='supersedes' AND newer.agent_id=?
                     AND newer.agent_id=older.agent_id AND newer.privacy_scope=older.privacy_scope
                     AND newer.status IN ('active','accepted','approved','approved_pending_curator','promoted')
                     AND (newer.expiry IS NULL OR newer.expiry>?)""", (agent_id, _utc_now()),
            ).fetchall()}
    result = []
    for row in rows:
        candidate = dict(row)
        if candidate.get("ticket_id") in superseded:
            candidate["superseded_by"] = True
        try:
            candidate["source_refs"] = json.loads(candidate.get("source_refs_json") or "[]")
        except (TypeError, ValueError):
            candidate["source_refs"] = []
        result.append(eligible_memory(candidate, agent_id))
    return result


def refresh_memory_candidates(project_dir: Path, db_path: Path, agent_id: str) -> int:
    """Write a private derived index. Source memory and legacy evidence stay intact."""
    entries = derive_memory_candidates(db_path, agent_id)
    folder = _ensure_agentlas_dir(project_dir)
    if folder is None:
        return 0
    target = folder / "memory-evolution-candidates.json"
    if target.is_symlink():
        return 0
    payload = {"schemaVersion": "agentlas.memory-evolution-candidates.v1", "agentId": agent_id,
               "generatedAt": _utc_now(), "candidates": entries, "activationAuthorized": False}
    import tempfile
    fd, name = tempfile.mkstemp(prefix=".memory-evolution-", dir=folder)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return sum(item["state"] == "eligible" for item in entries)


def _ensure_agentlas_dir(project_dir: Path) -> Path | None:
    """Resolve `<project>/.agentlas`, creating it if absent. Symlinks rejected —
    parity with the Desktop ensureAgentlasDir."""
    try:
        resolved = project_dir.resolve()
        stat = resolved.lstat()
    except OSError:
        return None
    if stat.st_mode & 0o170000 == 0o120000 or not resolved.is_dir():
        return None
    agentlas_dir = resolved / ".agentlas"
    try:
        link_stat = agentlas_dir.lstat()
        if link_stat.st_mode & 0o170000 == 0o120000 or not agentlas_dir.is_dir():
            return None
        return agentlas_dir
    except OSError:
        try:
            agentlas_dir.mkdir(parents=False, exist_ok=False)
            return agentlas_dir
        except OSError:
            return None


def build_payload(
    pending: list[dict[str, Any]], auto_applied: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "contract": EVOLUTION_PROPOSALS_CONTRACT,
        "generatedAt": _utc_now(),
        "reviewCommand": EVOLUTION_REVIEW_COMMAND,
        "pending": [dict(p) for p in pending],
        "autoApplied": [dict(p) for p in auto_applied],
    }


def write_evolution_proposals(
    project_dir: str | os.PathLike[str] | None,
    pending: list[dict[str, Any]],
    auto_applied: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    """Write ``.agentlas/evolution-proposals.json`` (removes it when empty).

    Returns {"pending": N, "autoApplied": M}. Every failure is swallowed — file
    IO must never break a run (parity with the Desktop writer).
    """

    raise RuntimeError("legacy_evolution_writer_retired: use a staged evolution-proposal.v2")


def read_proposals(
    project_dir: str | os.PathLike[str] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (pending, autoApplied) entries from an existing proposals file, or
    ([], []) on absence / parse error. Only contract-valid entries survive."""
    if project_dir is None:
        return [], []
    file_path = Path(project_dir) / EVOLUTION_PROPOSALS_RELATIVE
    try:
        if not file_path.is_file() or file_path.is_symlink() or file_path.stat().st_size > 256_000:
            return [], []
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [], []
    if not isinstance(payload, dict):
        return [], []

    def _valid(bucket: str) -> list[dict[str, Any]]:
        items = payload.get(bucket)
        return [item for item in items if validate_proposal_entry(item)] if isinstance(items, list) else []

    return _valid("pending"), _valid("autoApplied")


def read_pending_count(project_dir: str | os.PathLike[str] | None) -> int:
    """Count of pending proposals in ``.agentlas/evolution-proposals.json`` (0 on
    absence or any parse error)."""
    return len(read_proposals(project_dir)[0])


# hep-authored entries carry this id prefix (build_proposal_entry). Used so a
# merge refreshes hep's own derived entries without clobbering entries another
# surface (Desktop) may have written into the same shared file.
HEP_ENTRY_PREFIX = "hep-"


def refresh_hep_proposals(
    project_dir: str | os.PathLike[str] | None,
    derived_pending: list[dict[str, Any]],
) -> int:
    """Merge freshly derived hep proposals into the project file: keep every
    non-hep entry as-is, replace all hep-authored entries with `derived_pending`.
    Returns the resulting pending count. Fail-open."""
    existing_pending, existing_auto = read_proposals(project_dir)
    kept = [p for p in existing_pending if not str(p.get("id", "")).startswith(HEP_ENTRY_PREFIX)]
    merged = kept + list(derived_pending)
    write_evolution_proposals(project_dir, merged, existing_auto)
    return len(merged)


def session_context_line(pending_count: int, locale: str = "en") -> str | None:
    """One content-free session-start line — parity with the Desktop
    evolutionSessionContextLine."""
    if pending_count <= 0:
        return None
    if locale == "ko":
        return (
            f"[Agentlas] 검토 대기 중인 에이전트 성장 제안 {pending_count}건 — "
            f"`{EVOLUTION_REVIEW_COMMAND}`로 확인하세요."
        )
    return (
        f"[Agentlas] {pending_count} agent growth proposal(s) pending — "
        f"review with `{EVOLUTION_REVIEW_COMMAND}`."
    )
