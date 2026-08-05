"""Desktop handoff for completed local registrations.

A trusted ``local/*`` card whose ``source.ref`` points at a real package
folder is the engine's "registration finished" signal. Every runtime copy
(Claude plugin, Codex plugin, terminal runtime, desktop-vendored engine)
funnels card writes through ``card_store.save_card``, so enqueueing here is
what makes a local registration reach the Agentlas Desktop library no matter
where the build ran: the desktop drains ``<home>/desktop-sync/pending/`` and
imports each referenced folder through its own local importer.

Contract (paired with the desktop's ``electron/agents/hephaestus-sync.ts``):
- only ``trusted`` + ``local/*`` + non-stale cards with a valid absolute
  ``source.ref`` qualify — ``routing_ready`` forge experiments never do;
- pending entries are idempotent (same filename, atomic overwrite);
- the desktop moves a drained entry to ``done/`` carrying the card's
  ``content_hash`` so an unchanged card is not re-enqueued forever;
- everything is best-effort: a machine without the desktop app just keeps a
  few harmless pending files, and registration NEVER fails because this did.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .bootstrap import atomic_write_json, read_json, utc_now

PENDING_DIR = "desktop-sync/pending"
DONE_DIR = "desktop-sync/done"

# Markers that confirm a real package — a folder must have at least one of
# these to be treated as importable.
_PACKAGE_MARKERS = ("agentlas.json", "AGENT.md", "AGENTS.md", "TEAM.md", "CLAUDE.md")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", (value or "card").lower()).strip("-") or "card"


def _package_ref(card: dict[str, Any]) -> Path | None:
    source = card.get("source") or {}
    if not isinstance(source, dict) or source.get("kind") != "local_path":
        return None
    raw = str(source.get("ref") or "")
    if not raw:
        return None
    ref = Path(raw)
    # reindex has a history of leaving a relative path ('.') behind — require
    # an absolute path, that it actually exists, and a package marker too.
    if not ref.is_absolute() or not ref.is_dir():
        return None
    if not any((ref / marker).is_file() for marker in _PACKAGE_MARKERS):
        return None
    return ref


def qualifies_for_desktop(card: dict[str, Any]) -> bool:
    if str(card.get("type")) not in ("agent", "team"):
        return False
    if not str(card.get("id") or "").startswith("local/"):
        return False
    if card.get("stale"):
        return False
    if str(card.get("routing_status")) != "trusted":
        return False
    return _package_ref(card) is not None


def enqueue_desktop_sync(home: Path, card: dict[str, Any]) -> Path | None:
    """Enqueue a qualifying card for desktop import. Never raises."""
    try:
        if not qualifies_for_desktop(card):
            return None
        ref = _package_ref(card)
        if ref is None:
            return None
        entry_name = _slug(str(card.get("id")))
        content_hash = str((card.get("integrity") or {}).get("content_hash") or "")
        done = read_json(home / DONE_DIR / f"{entry_name}.json")
        if isinstance(done, dict) and content_hash and done.get("content_hash") == content_hash:
            return None
        target = home / PENDING_DIR / f"{entry_name}.json"
        atomic_write_json(
            target,
            {
                "id": card.get("id"),
                "type": card.get("type"),
                "ref": str(ref),
                "content_hash": content_hash,
                "enqueued_at": utc_now(),
                "origin": "hephaestus/card-store",
            },
        )
        return target
    except Exception:  # pragma: no cover — handoff must never break registration
        return None
