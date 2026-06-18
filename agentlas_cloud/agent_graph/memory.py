"""Phase 3: bi-temporal agent memory (frontier memory bar).

Two invariants the redesign requires:

- **Supersede-not-delete**: a fact is never overwritten. A new version
  supersedes the old; the old is retained (status='superseded') for audit and
  provenance. This lifts the Memory Curator's "deprecate, never silent
  overwrite" rule from prose into the storage model.
- **Bi-temporal**: *valid-time* (when a fact holds in the world:
  valid_from/valid_to) is tracked separately from *ingestion-time* (when we
  recorded it: ingested_at), so we can ask "what did we believe was true at T".

Pure stdlib and deterministic: timestamps are ISO-8601 strings passed in by the
caller (never read from the clock), so it is reproducible and test-friendly.
ISO-8601 strings sort lexicographically, so plain ``<=`` comparison is correct.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

ACTIVE = "active"
SUPERSEDED = "superseded"
DEPRECATED = "deprecated"


def _to_utc(ts: str) -> datetime:
    """Parse an ISO-8601 timestamp to a comparable UTC-naive datetime.

    Comparing raw ISO strings is wrong across timezone offsets (the same instant
    written ``...+09:00`` vs ``...Z`` does not string-compare equal). Parse first
    so valid-time queries are instant-correct; naive timestamps are treated as
    UTC.
    """
    dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


@dataclass
class MemoryEntry:
    id: str
    scope: str
    text: str
    valid_from: str
    ingested_at: str
    valid_to: str | None = None
    confidence: float = 1.0
    evidence_refs: list[str] = field(default_factory=list)
    status: str = ACTIVE
    supersedes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class BiTemporalStore:
    """In-memory bi-temporal store. Supersede-not-delete; valid-time queries."""

    def __init__(self) -> None:
        self._entries: dict[str, MemoryEntry] = {}

    def add(self, entry: MemoryEntry) -> MemoryEntry:
        self._entries[entry.id] = entry
        return entry

    def get(self, entry_id: str) -> MemoryEntry | None:
        return self._entries.get(entry_id)

    def all(self) -> list[MemoryEntry]:
        return list(self._entries.values())

    def by_scope(self, scope: str) -> list[MemoryEntry]:
        return [e for e in self._entries.values() if e.scope == scope]

    def supersede(self, old_id: str, new_entry: MemoryEntry) -> MemoryEntry:
        """Replace ``old_id`` with ``new_entry`` without deleting the old one."""
        old = self._entries.get(old_id)
        if old is None:
            raise KeyError(old_id)
        old.status = SUPERSEDED
        new_entry.supersedes = old_id
        self._entries[new_entry.id] = new_entry
        return new_entry

    def deprecate(self, entry_id: str, at: str | None = None) -> MemoryEntry:
        entry = self._entries.get(entry_id)
        if entry is None:
            raise KeyError(entry_id)
        entry.status = DEPRECATED
        if at is not None:
            entry.valid_to = at
        return entry

    def active_at(self, ts: str) -> list[MemoryEntry]:
        """Entries that are active and valid at instant ``ts`` (valid-time query)."""
        at = _to_utc(ts)
        out: list[MemoryEntry] = []
        for entry in self._entries.values():
            if entry.status != ACTIVE:
                continue
            if _to_utc(entry.valid_from) <= at and (
                entry.valid_to is None or at < _to_utc(entry.valid_to)
            ):
                out.append(entry)
        return out

    def history(self, entry_id: str) -> list[MemoryEntry]:
        """The supersession chain for ``entry_id`` (newest first, following ``supersedes``)."""
        chain: list[MemoryEntry] = []
        seen: set[str] = set()
        current = self._entries.get(entry_id)
        while current is not None and current.id not in seen:
            seen.add(current.id)
            chain.append(current)
            current = self._entries.get(current.supersedes) if current.supersedes else None
        return chain
