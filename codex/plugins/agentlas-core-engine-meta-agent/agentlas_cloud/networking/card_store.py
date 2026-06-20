"""Routing card storage.

cards/<type>/<id>.json files are the source of truth; registry.sqlite is a
rebuildable cache (WAL + busy_timeout, FTS5 when available). A malformed card
is quarantined individually — indexing never aborts because of one bad card.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from .bootstrap import atomic_write_json, networking_home, read_json, utc_now
from .tokenize import tokenize

CARD_FILENAME = "routing-card.json"
TYPE_DIRS = {"agent": "agents", "team": "teams", "plugin": "plugins"}
_SCAN_MAX_DEPTH = 6


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", (value or "card").lower()).strip("-") or "card"


def card_path(home: Path, card: dict[str, Any]) -> Path:
    type_dir = TYPE_DIRS.get(str(card.get("type")), "agents")
    return home / "cards" / type_dir / f"{_slug(str(card.get('id')))}.json"


def content_hash(card: dict[str, Any]) -> str:
    clone = {key: value for key, value in card.items() if key != "integrity"}
    canonical = json.dumps(clone, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def save_card(home: Path, card: dict[str, Any]) -> Path:
    card.setdefault("integrity", {})
    card["integrity"]["content_hash"] = content_hash(card)
    card["updated_at"] = card.get("updated_at") or utc_now()
    target = card_path(home, card)
    atomic_write_json(target, card)
    return target


def load_global_cards(home: Path | str | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    base = Path(home) if home else networking_home()
    cards: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    cards_root = base / "cards"
    if not cards_root.is_dir():
        return cards, quarantined
    for path in sorted(cards_root.rglob("*.json")):
        payload = read_json(path)
        if not isinstance(payload, dict) or not payload.get("id") or not payload.get("type"):
            quarantined.append({"path": str(path), "reason": "malformed JSON or missing id/type"})
            continue
        payload["_card_path"] = str(path)
        cards.append(payload)
    return cards, quarantined


def iter_source_cards(source_path: Path) -> list[tuple[Path, dict[str, Any] | None]]:
    found: list[tuple[Path, dict[str, Any] | None]] = []
    if not source_path.is_dir():
        return found
    for card_file in source_path.rglob(f".agentlas/{CARD_FILENAME}"):
        try:
            depth = len(card_file.relative_to(source_path).parts)
        except ValueError:
            continue
        if depth > _SCAN_MAX_DEPTH + 2:
            continue
        found.append((card_file, read_json(card_file)))
    return found


def reindex(home: Path | str | None = None) -> dict[str, Any]:
    base = Path(home) if home else networking_home()
    sources = (read_json(base / "sources.json", default={}) or {}).get("sources", [])
    imported = 0
    quarantined: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for source in sources:
        source_path = Path(str(source.get("path", "")))
        for card_file, payload in iter_source_cards(source_path):
            if not isinstance(payload, dict) or not payload.get("id") or not payload.get("type"):
                quarantined.append({"path": str(card_file), "reason": "malformed source card"})
                continue
            payload.setdefault("source", {})
            payload["source"].setdefault("kind", "local_path")
            payload["source"]["ref"] = str(card_file.parent.parent)
            seen_ids.add(str(payload.get("canonical_id") or payload.get("id")))
            save_card(base, dict(payload))
            imported += 1

    # Stale pass: a global card whose local source folder no longer exists is
    # excluded from auto routing but kept for inspection.
    cards, bad_global = load_global_cards(base)
    quarantined.extend(bad_global)
    stale = 0
    for card in cards:
        source = card.get("source") or {}
        if source.get("kind") == "local_path" and source.get("ref"):
            is_stale = not Path(str(source["ref"])).is_dir()
            if bool(card.get("stale")) != is_stale:
                card_clean = {key: value for key, value in card.items() if not key.startswith("_")}
                card_clean["stale"] = is_stale
                if is_stale:
                    card_clean["routing_status_reason"] = "source folder no longer exists"
                save_card(base, card_clean)
            if is_stale:
                stale += 1

    cards, _ = load_global_cards(base)
    _rebuild_registry(base, cards)
    # Materialize the card-derived Agent Ontology graph so global cards are
    # actually mapped (ExternalAgent nodes + in_domain/has_capability edges).
    # Best-effort: never let AO materialization break a reindex.
    ao_summary: dict[str, Any] = {}
    try:
        from ..agent_graph import ingest_routing_cards

        ao_summary = ingest_routing_cards(base, cards)
    except Exception:  # pragma: no cover
        ao_summary = {"status": "skipped"}
    return {
        "home": str(base),
        "sources": len(sources),
        "imported": imported,
        "total_cards": len(cards),
        "stale": stale,
        "quarantined": quarantined,
        "agent_ontology": ao_summary,
    }


def _rebuild_registry(base: Path, cards: list[dict[str, Any]]) -> None:
    db_path = base / "registry.sqlite"
    connection = sqlite3.connect(str(db_path), timeout=10)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        with connection:
            connection.execute("DROP TABLE IF EXISTS cards")
            connection.execute(
                "CREATE TABLE cards (id TEXT PRIMARY KEY, type TEXT, status TEXT, stale INTEGER, name TEXT, payload TEXT, tokens TEXT)"
            )
            try:
                connection.execute("DROP TABLE IF EXISTS cards_fts")
                connection.execute("CREATE VIRTUAL TABLE cards_fts USING fts5(id, tokens)")
                has_fts = True
            except sqlite3.OperationalError:
                has_fts = False
            for card in cards:
                tokens = " ".join(sorted(set(_index_tokens(card))))
                payload = json.dumps(
                    {key: value for key, value in card.items() if not key.startswith("_")},
                    ensure_ascii=False,
                    sort_keys=True,
                )
                connection.execute(
                    "INSERT OR REPLACE INTO cards (id, type, status, stale, name, payload, tokens) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(card.get("id")),
                        str(card.get("type")),
                        str(card.get("routing_status") or "draft"),
                        1 if card.get("stale") else 0,
                        str(card.get("name") or ""),
                        payload,
                        tokens,
                    ),
                )
                if has_fts:
                    connection.execute("INSERT INTO cards_fts (id, tokens) VALUES (?, ?)", (str(card.get("id")), tokens))
    finally:
        connection.close()


def _index_tokens(card: dict[str, Any]) -> list[str]:
    chunks: list[str] = [
        str(card.get("name") or ""),
        str(card.get("name_ko") or ""),
        str(card.get("summary") or ""),
        str(card.get("summary_ko") or ""),
        " ".join(card.get("aliases") or []),
        " ".join(str(cap) for cap in card.get("capabilities") or []),
    ]
    for trigger in card.get("trigger_examples") or []:
        if isinstance(trigger, dict):
            chunks.append(str(trigger.get("text") or ""))
    return tokenize(" ".join(chunks))
