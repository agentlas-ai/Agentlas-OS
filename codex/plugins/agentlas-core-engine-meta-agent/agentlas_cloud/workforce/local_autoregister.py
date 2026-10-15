"""Register what the builder wrote, without asking the author to remember to.

A package built into the global agent folder only reached the roster when
someone ran ``cards migrate`` for it. Measured 2026-10-15 on this machine: 11 of
the 17 packages in the agent folder were absent from the local roster, so
``/hep-local`` could not staff them, and nothing said so.

The agent folder is the builder's own output folder, not a scan of the user's
disk, so registering from it keeps the rule the registry protects ("never widen
to whatever is on disk"). Limits that keep this safe to run on every search:

- only a package that passes the contract is registered; a failing one is named
  with its first blockers, never registered and never silently skipped;
- a folder that already has a definition record is left alone, whatever its
  status, so an agent the owner removed is not given back;
- a package is judged again only when its own files changed, so the search that
  triggers this pays for reading a few small files, not for re-verifying;
- one package failing never stops the others.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

_STATE_FILE = "builder-home-state.json"
_FINGERPRINT_FILES = (".agentlas/routing-card.json", "AGENTS.md", "agent.md", "agentlas.json")


def _fingerprint(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in _FINGERPRINT_FILES:
        path = root / relative
        digest.update(relative.encode())
        try:
            digest.update(path.read_bytes() if path.is_file() else b"-")
        except OSError:
            digest.update(b"?")
    return digest.hexdigest()


def _card_type(root: Path) -> str:
    from ..networking.bootstrap import read_json

    card = read_json(root / ".agentlas" / "routing-card.json", default={}) or {}
    return "team" if card.get("type") == "team" else "single"


def _has_global_card(root: Path, networking_root: Path) -> bool:
    from ..networking.card_store import load_global_cards

    cards, _ = load_global_cards(networking_root)
    target = str(root)
    return any(
        isinstance(card.get("source"), dict) and str(card["source"].get("ref") or "") == target
        for card in cards
    )


def serves_default_home(registry: Any) -> bool:
    """True when this registry is the machine's own roster, not an injected one."""

    from .local_registry import default_local_workforce_home

    try:
        return Path(registry.home).resolve() == default_local_workforce_home().expanduser().resolve()
    except (OSError, RuntimeError, AttributeError):
        return False


def autoregister_builder_home(
    registry: Any,
    *,
    home: str | Path | None = None,
    networking_root: str | Path | None = None,
) -> dict[str, Any]:
    from ..agent_package_sweep import local_agents_home
    from ..networking.bootstrap import atomic_write_json, networking_home, read_json
    from ..networking.card_migrate import migrate_package
    from ..package_contract import verify

    base = Path(home).expanduser() if home else local_agents_home()
    report: dict[str, Any] = {
        "status": "ok",
        "home": str(base),
        "registered": [],
        "alreadyRegistered": 0,
        "unchanged": 0,
        "contractFailing": [],
        "refused": [],
    }
    if not base.is_dir():
        report["status"] = "agent_home_not_found"
        return report

    net_root = (Path(networking_root) if networking_root else networking_home()).expanduser()
    state_path = registry.home / _STATE_FILE
    state = read_json(state_path, default={}) or {}
    if not isinstance(state, dict):
        state = {}
    changed = False

    for entry in sorted(base.iterdir()):
        # Hidden folders and fixtures (`_fixture-…`) are not the author's agents.
        if not entry.is_dir() or entry.name.startswith((".", "_")):
            continue
        if not ((entry / "AGENTS.md").is_file() or (entry / "agentlas.json").is_file()):
            continue
        try:
            root = entry.resolve()
        except (OSError, RuntimeError):
            continue
        key = str(root)
        known = registry._by_source(root)
        if known is not None:
            report["alreadyRegistered"] += 1
            continue
        fingerprint = _fingerprint(root)
        previous = state.get(key) if isinstance(state.get(key), dict) else {}
        if previous.get("fingerprint") == fingerprint:
            report["unchanged"] += 1
            # Say again what the last attempt found; silence is how 11 packages vanished.
            if previous.get("blockers"):
                report["contractFailing"].append({"slug": entry.name, "blockers": previous["blockers"]})
            elif previous.get("reasonCode"):
                report["refused"].append({"slug": entry.name, "reasonCode": previous["reasonCode"]})
            continue

        try:
            verdict = verify(str(root), mode=_card_type(root))
        except Exception as exc:  # noqa: BLE001 - one unreadable package must not stop the rest
            state[key] = {"fingerprint": fingerprint, "reasonCode": type(exc).__name__}
            report["refused"].append({"slug": entry.name, "reasonCode": type(exc).__name__})
            changed = True
            continue
        if not verdict.get("ok"):
            blockers = [str(item)[:240] for item in (verdict.get("blockers") or [])[:4]]
            state[key] = {"fingerprint": fingerprint, "blockers": blockers}
            report["contractFailing"].append({"slug": entry.name, "blockers": blockers})
            changed = True
            continue

        try:
            if not _has_global_card(root, net_root):
                migrate_package(root, tier="local", home=net_root, overwrite=False)
            outcome = registry.register(root, managed_by="networking")
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            state[key] = {"fingerprint": fingerprint, "reasonCode": type(exc).__name__}
            report["refused"].append({"slug": entry.name, "reasonCode": type(exc).__name__})
            changed = True
            continue
        if outcome.get("status") == "active":
            state[key] = {"fingerprint": fingerprint, "registered": True}
            report["registered"].append(entry.name)
        else:
            reason = str(outcome.get("reasonCode") or outcome.get("status"))
            state[key] = {"fingerprint": fingerprint, "reasonCode": reason}
            report["refused"].append({"slug": entry.name, "reasonCode": reason})
        changed = True

    if changed:
        atomic_write_json(state_path, state)
    return report
