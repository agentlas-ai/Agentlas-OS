"""Content-free context-source markers (Phase 4+).

When the hep memory hook injects a recall source into an agent's prompt, we
record ONLY which source it was and an approximate token size — never any
value/content. This makes recall usage measurable after the fact (the Desktop
does the same via run_events ``context_source`` markers; here we persist a
sibling ``context_source_markers`` table inside the per-project
``ontology-runtime.sqlite``).

The marker names are the shared canonical set (memory_contract.CONTEXT_SOURCE_NAMES):
pm_soul, code_map, sitemap, experience, memory.
"""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .memory_contract import CONTEXT_SOURCE_NAMES

_MARKER_TABLE = "context_source_markers"


def classify_source(label: str) -> str:
    """Map a hep project/source label to a canonical context-source name.

    hep labels project chunks by file basename, so classify by well-known names
    and fall back to the generic ``memory`` bucket. Anything already canonical
    passes through unchanged.
    """
    name = str(label or "").strip().lower()
    if name in CONTEXT_SOURCE_NAMES:
        return name
    if "soul" in name:
        return "pm_soul"
    if "code" in name and "map" in name or name.startswith("code-map") or name == "codemap":
        return "code_map"
    if "sitemap" in name or "site-map" in name:
        return "sitemap"
    if "experience" in name:
        return "experience"
    return "memory"


def _ensure_table(conn: sqlite3.Connection) -> None:
    # Additive sibling table — created with IF NOT EXISTS so it never disturbs
    # the OntologyRuntime schema/version or triggers a reindex.
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_MARKER_TABLE} (
          marker_id TEXT PRIMARY KEY,
          source TEXT NOT NULL,
          approx_tokens INTEGER NOT NULL,
          host TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL
        )
        """
    )


def record_markers(
    db_path: str | Path,
    markers: list[tuple[str, int]],
    *,
    host: str = "",
) -> int:
    """Persist content-free (source, approx_tokens) markers. Only canonical
    source names are stored; unknown names are dropped. Returns the count
    written. Fail-open: any error returns 0 without raising.
    """
    if not markers:
        return 0
    path = Path(db_path)
    if not path.is_file() or path.is_symlink():
        return 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    safe_host = "".join(ch for ch in str(host)[:32] if ch.isalnum() or ch in "-_")
    rows = [
        (uuid.uuid4().hex, source, max(0, int(tokens)), safe_host, now)
        for source, tokens in markers
        if source in CONTEXT_SOURCE_NAMES
    ]
    if not rows:
        return 0
    try:
        with closing(sqlite3.connect(path)) as conn, conn:
            _ensure_table(conn)
            conn.executemany(
                f"INSERT INTO {_MARKER_TABLE}(marker_id, source, approx_tokens, host, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                rows,
            )
        return len(rows)
    except sqlite3.Error:
        return 0


def read_markers(db_path: str | Path, *, limit: int = 256) -> list[dict[str, Any]]:
    """Read recorded markers (newest first). Returns [] if the table is absent."""
    path = Path(db_path)
    if not path.is_file():
        return []
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT source, approx_tokens, host, created_at FROM {_MARKER_TABLE}"
                " ORDER BY created_at DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
    except sqlite3.Error:
        return []
    return [
        {
            "source": row["source"],
            "approx_tokens": row["approx_tokens"],
            "host": row["host"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def distinct_sources(db_path: str | Path) -> set[str]:
    """The set of canonical sources ever recorded for this project."""
    return {marker["source"] for marker in read_markers(db_path)}
