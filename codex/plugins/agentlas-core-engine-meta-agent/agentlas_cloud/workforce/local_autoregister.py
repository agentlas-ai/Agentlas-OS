"""Register hand-placed packages from the builder's agent folder when the owner asks for it.

`autoregister_builder_home` runs only when the owner asks (`hephaestus workforce
local-autoregister`); a search does not scan folders. `register_package` is the
single registration step, shared with `session compile --global-agent` for the
one package a build just wrote. (A search still lists agents the
owner's card store already holds that the roster has not seen; that is
`adopt_new_networking_cards`, not this module. A package the builder registers
itself goes through `cards migrate --tier local`.)

The agent folder is the builder's own output folder, not a scan of the user's
disk, so registering from it keeps the rule the registry protects ("never widen
to whatever is on disk"). Limits that keep a repeated run cheap:

- a package with an instruction file is registered; what the contract still
  wants is returned as `advisories`, never as a reason to skip it;
- a folder with no instruction file is listed in `skipped` with the reason
  `no_instruction_file`, so the owner can see why it is not on the roster;
- a folder that already has a definition record is left alone, whatever its
  status, so an agent the owner removed is not given back;
- a package is judged again only when its own files changed, so repeating the
  command pays for reading a few small files, not for re-verifying;
- one package failing never stops the others.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from .local_registry import LOCAL_RULES_VERSION

_STATE_FILE = "builder-home-state.json"
# Same instruction files the registry accepts without a card (package_adapter.inspect_package):
# a root agent or team file, or a SKILL.md anywhere in the package.
_ROOT_INSTRUCTION_FILES = ("agent.md", "AGENT.md", "AGENTS.md", "CLAUDE.md", "TEAM.md", "team.md")
_SKILL_FILE = "SKILL.md"
_SKILL_SEARCH_LIMIT = 4096  # entries looked at before giving up; the registry's own file ceiling
# Folders the registry's snapshot never reads (package_adapter._IGNORED_DIRS); links are not followed.
_SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".pytest_cache"})
_FINGERPRINT_FILES = (".agentlas/routing-card.json", "AGENTS.md", "agent.md", "AGENT.md", "CLAUDE.md", "TEAM.md", "team.md", "agentlas.json")


def _has_instruction_file(root: Path) -> bool:
    if any((root / name).is_file() for name in _ROOT_INSTRUCTION_FILES):
        return True
    seen = 0
    for _current, dirs, files in os.walk(root):
        if _SKILL_FILE in files:
            return True
        dirs[:] = [name for name in dirs if name not in _SKIP_DIRS]
        seen += len(files) + len(dirs)
        if seen > _SKILL_SEARCH_LIMIT:
            return False
    return False


def _fingerprint(root: Path) -> str:
    # The rules version is part of every fingerprint: raising it makes a package an earlier rule refused get judged again.
    digest = hashlib.sha256(LOCAL_RULES_VERSION.encode())
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


def register_package(registry: Any, root: Path, *, networking_root: str | Path | None = None) -> dict[str, Any]:
    """The one way a local package becomes a roster entry: make its card if the store has none, then register it.

    Used for every package autoregister finds and for the package a build just wrote, so the two cannot
    disagree about the same folder.
    """

    from ..networking.bootstrap import networking_home
    from ..networking.card_migrate import migrate_package

    net_root = (Path(networking_root) if networking_root else networking_home()).expanduser()
    root = Path(root).resolve()
    if not _has_global_card(root, net_root):
        migrate_package(root, tier="local", home=net_root, overwrite=False)
    return registry.register(root, managed_by="networking")


def _is_hub_pointer(folder: Path) -> bool:
    from ..agent_usability import ORIGIN_FILE, _read_small_json
    from ..agent_home import AGENT_LOCAL_STATE_FOLDER

    origin = _read_small_json(folder / AGENT_LOCAL_STATE_FOLDER / ORIGIN_FILE)
    return bool(origin) and origin.get("kind") == "hub-pointer"


def autoregister_builder_home(
    registry: Any,
    *,
    home: str | Path | None = None,
    networking_root: str | Path | None = None,
) -> dict[str, Any]:
    from ..agent_home import agent_homes_to_read, has_owner_marker
    from ..agent_package_sweep import local_agents_home
    from ..networking.bootstrap import atomic_write_json, networking_home, read_json
    from ..package_contract import verify

    # The agents root and the pre-2.0 `agentlas-agent` home are both read; an explicit `home` is the only one.
    bases = [Path(home).expanduser()] if home else (agent_homes_to_read() or [local_agents_home()])
    base = bases[0]
    report: dict[str, Any] = {
        "status": "ok",
        "home": str(base),
        "registered": [],
        "alreadyRegistered": 0,
        "unchanged": 0,
        "advisories": [],
        "refused": [],
        "skipped": [],
    }
    if not home:
        from ..agent_home import agents_root_status

        report["rootStatus"] = agents_root_status()
    bases = [item for item in bases if item.is_dir()]
    if not bases:
        status = report.get("rootStatus") or {}
        # A configured root that is not there (unplugged drive) is not "no agent home": name it.
        report["status"] = "agent_root_unavailable" if status.get("configured") and not status.get("available") else "agent_home_not_found"
        return report

    net_root = (Path(networking_root) if networking_root else networking_home()).expanduser()
    state_path = registry.home / _STATE_FILE
    state = read_json(state_path, default={}) or {}
    if not isinstance(state, dict):
        state = {}
    changed = False

    seen_names: set[str] = set()
    for entry in [item for each in bases for item in sorted(each.iterdir())]:
        # Hidden folders and fixtures (`_fixture-…`) are not the author's agents.
        if not entry.is_dir() or entry.name.startswith((".", "_")):
            continue
        if entry.name in seen_names:
            # Same name in an older home: the first (newest) home wins, so one agent is registered once.
            report["skipped"].append({"slug": entry.name, "reason": "legacy_duplicate"})
            continue
        seen_names.add(entry.name)
        if has_owner_marker(entry):
            # The desktop manages this folder (`.agentlas-local/owner.json`) and registers it itself; registering it
            # here as well would give one identity two roots.
            report["skipped"].append({"slug": entry.name, "reason": "desktop_managed"})
            continue
        if _is_hub_pointer(entry):
            # A call-only Hub agent registered by `hephaestus register-agent` runs on the Hub; its folder is the registration, not a package to import.
            report["skipped"].append({"slug": entry.name, "reason": "hub_pointer"})
            continue
        if not _has_instruction_file(entry):
            # Say why it is not on the roster; silence left owners asking "why didn't it show up?".
            report["skipped"].append({"slug": entry.name, "reason": "no_instruction_file"})
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
            if previous.get("reasonCode"):
                report["refused"].append({"slug": entry.name, "reasonCode": previous["reasonCode"]})
            continue

        # What the contract still wants is a to-do list for the owner, not a gate: it is reported as
        # advisories and never keeps a package with an agent file out of the roster.
        advisories: list[str] = []
        try:
            verdict = verify(str(root), mode=_card_type(root))
            if not verdict.get("ok"):
                advisories = [str(item)[:240] for item in (verdict.get("blockers") or [])[:4]]
        except Exception:  # noqa: BLE001 - an unreadable verdict never decides registration
            advisories = []

        try:
            outcome = register_package(registry, root, networking_root=net_root)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            if advisories:
                report["advisories"].append({"slug": entry.name, "advisories": advisories})
            state[key] = {"fingerprint": fingerprint, "reasonCode": type(exc).__name__}
            report["refused"].append({"slug": entry.name, "reasonCode": type(exc).__name__})
            changed = True
            continue
        # Files the registry left out of the snapshot (credentials, secrets, links) are named here too.
        advisories = [*advisories, *[str(item)[:240] for item in outcome.get("advisories") or []]]
        if advisories:
            report["advisories"].append({"slug": entry.name, "advisories": advisories})
        if outcome.get("status") == "active":
            state[key] = {"fingerprint": fingerprint, "registered": True, **({"advisories": advisories} if advisories else {})}
            report["registered"].append(entry.name)
        else:
            reason = str(outcome.get("reasonCode") or outcome.get("status"))
            state[key] = {"fingerprint": fingerprint, "reasonCode": reason}
            report["refused"].append({"slug": entry.name, "reasonCode": reason})
        changed = True

    if changed:
        atomic_write_json(state_path, state)
    return report
