"""hep-plugin evolution proposal bridge (Phase 2 / 2+).

hep sessions run in a folder host with no UI, so — exactly like the Desktop's
``electron/agents/evolution-hep.ts`` — this module writes a human-readable
``.agentlas/evolution-proposals.json`` (the ``agentlas.evolution-proposals.v1``
contract) into the project working folder and produces one session-start context
line ("N growth proposals pending — review with agentlas evolve"). Apply / revert
happens only through the ``agentlas evolve`` command; here we only produce the
file and the notice.

Parity is deliberate: the JSON shape, the ``contract`` string, the
``reviewCommand``, the per-entry fields and the low/high trust tier all mirror
the Desktop so a host reading either surface sees the same thing. Trigger
detection is deterministic (counters over the per-slug experience store) — no
embedding, no LLM — so it stays cheap and fail-open in the hook.
"""

from __future__ import annotations

import hashlib
import json
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

# Deterministic trigger thresholds (mirror of the Desktop evolution-triggers
# intent: repeated failure / accumulated experience). Kept conservative so a
# single noisy session never fabricates a proposal.
ACCUMULATED_EXPERIENCE_MIN = 5
REPEATED_FAILURE_MIN = 3
_FAILURE_TAG_RE = re.compile(
    r"(fail|error|gotcha|incident|regress|bug|attack|vuln|보안|취약|버그|사고|실패)",
    re.IGNORECASE,
)
_SECRET_HINT_RE = re.compile(
    r"(sk-[A-Za-z0-9]{16,}|gh[opsu]_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_-]{20,}"
    r"|AKIA[0-9A-Z]{16}|-----BEGIN|password|secret|token|api[_-]?key)",
    re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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
    """Deterministic, content-free-ish proposal derivation from a per-slug
    experience store. Reads only counts and safe tag keywords — never raw
    candidate text — then emits at most two low-risk growth proposals.

    Returns [] on any error (fail-open).
    """

    if not db_path.is_file() or db_path.is_symlink():
        return []
    try:
        with closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT tags_json, memory_kind FROM memory_candidates "
                "WHERE agent_id = ? AND status = 'active'",
                (agent_id,),
            ).fetchall()
    except sqlite3.Error:
        return []

    total = len(rows)
    failure_count = 0
    keywords: list[str] = []
    for row in rows:
        try:
            tags = json.loads(row["tags_json"] or "[]")
        except (json.JSONDecodeError, TypeError):
            tags = []
        joined = " ".join(str(t) for t in tags)
        if _FAILURE_TAG_RE.search(joined) or str(row["memory_kind"] or "") == "risk":
            failure_count += 1
        for tag in tags[:3]:
            safe = _safe_keyword(tag)
            if safe and safe not in keywords:
                keywords.append(safe)

    proposals: list[dict[str, Any]] = []
    topic = ", ".join(keywords[:4]) or "recent work"
    if total >= ACCUMULATED_EXPERIENCE_MIN:
        proposals.append(
            build_proposal_entry(
                agent_id=agent_id,
                trigger_kind="accumulated-experience",
                learned=f"Accumulated {total} experience notes on {topic}.",
                change="Reflect these accumulated learnings into future runs for this agent.",
                reversible=f"Yes — review or revert with `{EVOLUTION_REVIEW_COMMAND}`.",
                risk_tier="low",
            )
        )
    if failure_count >= REPEATED_FAILURE_MIN:
        proposals.append(
            build_proposal_entry(
                agent_id=agent_id,
                trigger_kind="repeated-failure",
                learned=f"Repeated failure/gotcha pattern observed {failure_count} times on {topic}.",
                change="Add a guardrail note so this agent avoids the repeated failure.",
                reversible=f"Yes — review or revert with `{EVOLUTION_REVIEW_COMMAND}`.",
                risk_tier="low",
            )
        )
    return [p for p in proposals if validate_proposal_entry(p)]


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

    auto_applied = auto_applied or []
    result = {"pending": len(pending), "autoApplied": len(auto_applied)}
    if project_dir is None:
        return result
    agentlas_dir = _ensure_agentlas_dir(Path(project_dir))
    if agentlas_dir is None:
        return result
    file_path = agentlas_dir / "evolution-proposals.json"
    try:
        if not pending and not auto_applied:
            if file_path.exists():
                file_path.unlink()
            return result
        payload = build_payload(pending, auto_applied)
        tmp = agentlas_dir / f".evolution-proposals.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, file_path)
    except OSError:
        pass
    return result


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
