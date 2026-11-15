"""\"Can this agent be used right now?\" in the engine.

 whatever the source (built here, the Hub, Agent Cloud, a local folder) an agent is used only after it was registered on this computer
and has its folder. The desktop answers this in ``electron/agents/usability.ts`` (``shared/agent-usability.ts``); this is the engine's one answer so the
windows that run outside the app (Claude Code, Codex and the other hosts) say the same words:

  ``not_registered`` | ``no_folder`` | ``archived`` | ``removed``   (the closed ``why``; the refusal's code is ``needs_registration`` | ``agent_no_folder`` | ...)

The engine has no archive of its own, so it never answers ``archived`` (the word stays in the list so both sides read the same table).
A folder that VANISHED keeps the registration's stored copy working (the same rule as the desktop's ``reconnectable``): it answers usable.

THE SWITCH: the rule is on only when the 2.0 workspace-rules switch is on for this caller (``memory_classify.outside_marker_on`` for a window outside the app,
the bound account's ``workspace_rules_state`` row for an app turn). Off, every answer is ``usable: True, enforced: False`` and nothing changes.

What is registered: a folder under the agents root (or the legacy home) that carries the agent's name or its recorded origin, or a local workforce registration.
A call-only Hub agent is registered as a *pointer folder* (``agent_registration``): the folder holds the card copy, the character and the place for its state; the run
still goes to the Hub. This module only READS: it never creates a folder and never raises.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

from . import agent_home

USABILITY_WHY = ("not_registered", "no_folder", "archived", "removed")
NEEDS_REGISTRATION_CODE = "needs_registration"
REGISTER_COMMAND = "hephaestus register-agent"
HOST_GATES_ENV = "AGENTLAS_AGENT_REGISTRATION_GATE"
ORIGIN_FILE = "origin.json"
CHARACTER_FILE = "character.json"
# The preset ids the desktop's registration step picks from (electron/agents/registration-character.ts DEFAULT_CHARACTERS) and the same pick rule: sha256(slug)[0] % 6.
DEFAULT_CHARACTERS = ("orange-dino", "blue-wave", "green-cloud", "purple-beacon", "amber-pod", "orange-sprout")
_SCAN_LIMIT = 4000  # folders looked at under one agents root before giving up (a registered agent is found by name first)
_ORIGIN_MAX_BYTES = 16 * 1024


def norm_slug(value: Any) -> str:
    """The one slug form (the same rule as ``hub_invocation._norm_slug``)."""
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def default_character(slug: str) -> str:
    import hashlib

    return DEFAULT_CHARACTERS[hashlib.sha256(slug.encode("utf-8")).digest()[0] % len(DEFAULT_CHARACTERS)]


# --- the switch ---------------------------------------------------------------------------------------------------------------

def registration_rule_on() -> bool:
    """The 2.0 switch for the "register to use" rule. Never raises; a caller that cannot be told is OFF (the old behaviour, nothing refused)."""
    if os.environ.get(HOST_GATES_ENV) == "host":
        return False  # the host that started this process asked the same question itself before calling (the desktop's `agentUsability`); asking twice would refuse what it allowed
    try:
        from . import memory_classify, memory_owner_binding

        if os.environ.get(memory_owner_binding.FILE_ENV) or os.environ.get(memory_owner_binding.REV_ENV):
            # An app turn: the word of the account the host bound this process to (the marker is for windows with no binding).
            binding = memory_owner_binding.host_binding()
            owner = (binding or {}).get("owner_namespace")
            if not isinstance(owner, str) or not owner:
                return False
            from .memory_runtime import memory_path

            path = memory_path(owner)
            if not path.is_file():
                return False
            connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=0.3)
            try:
                row = connection.execute(
                    "SELECT value FROM memory_store_meta WHERE key=?", (memory_classify.workspace_rules_state_key(None),)
                ).fetchone()
            finally:
                connection.close()
            return bool(row) and row[0] == memory_classify.RULES_ON_VALUE
        return memory_classify.outside_marker_on()
    except Exception:  # noqa: BLE001 - cannot tell: off
        return False


# --- what is registered here ----------------------------------------------------------------------------------------------------

def _read_small_json(path: Path) -> dict[str, Any] | None:
    try:
        if path.stat().st_size > _ORIGIN_MAX_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8").lstrip("﻿"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


class RegisteredHere:
    """What this computer has registered, read once: folder names, recorded slugs / definition ids, and the local workforce definitions."""

    def __init__(self) -> None:
        self.folders: dict[str, Path] = {}          # normalized slug -> folder
        self.definition_ids: set[str] = set()       # Hub/Cloud definition ids recorded in pointer folders + active local definitions
        self.removed: set[str] = set()              # slugs of local definitions that were removed
        self.registry_slugs: dict[str, Path] = {}   # slug of an active local definition -> its source root
        self._scan()

    def _scan(self) -> None:
        try:
            roots = agent_home.agent_homes_to_read()
        except Exception:  # noqa: BLE001
            roots = []
        for root in roots:
            seen = 0
            try:
                entries = sorted(root.iterdir(), key=lambda item: item.name)
            except OSError:
                continue
            for entry in entries:
                seen += 1
                if seen > _SCAN_LIMIT:
                    break
                try:
                    if not entry.is_dir() or entry.name.startswith("."):
                        continue
                except OSError:
                    continue
                key = norm_slug(entry.name)
                if key:
                    self.folders.setdefault(key, entry)
                origin = _read_small_json(entry / agent_home.AGENT_LOCAL_STATE_FOLDER / ORIGIN_FILE)
                if origin:
                    recorded = norm_slug(origin.get("slug"))
                    if recorded:
                        self.folders.setdefault(recorded, entry)
                    definition = origin.get("agentDefinitionId")
                    if isinstance(definition, str) and definition:
                        self.definition_ids.add(definition)
        self._scan_local_definitions()

    def _scan_local_definitions(self) -> None:
        try:
            from .workforce.local_registry import default_local_workforce_home

            definitions = default_local_workforce_home().expanduser() / "definitions"
            files = sorted(definitions.glob("*.json"))[:_SCAN_LIMIT]
        except Exception:  # noqa: BLE001
            return
        for path in files:
            record = _read_small_json(path)
            if not record:
                continue
            source = str(record.get("sourceRoot") or "")
            keys = {norm_slug(Path(source).name)} if source else set()
            card = _read_small_json(Path(source) / ".agentlas" / "routing-card.json") if source else None
            ref = card.get("agent_card_ref") if isinstance(card, dict) else None
            if isinstance(ref, dict) and ref.get("slug"):
                keys.add(norm_slug(ref.get("slug")))
            keys.discard("")
            if record.get("status") == "active":
                definition = record.get("agentDefinitionId")
                if isinstance(definition, str) and definition:
                    self.definition_ids.add(definition)
                for key in keys:
                    self.registry_slugs.setdefault(key, Path(source))
            elif record.get("status") == "removed":
                self.removed.update(keys)


def register_sentence(slug: str | None, source: str, locale: str = "en") -> str:
    """How to register it, in one sentence (the desktop's ``usabilitySentence`` for ``not_registered``, plus the engine's own command)."""
    ref = f"{source}:{slug}" if slug and source in {"hub", "cloud"} else (slug or "<agent>")
    if locale == "ko":
        return (f"이 에이전트는 아직 이 컴퓨터에 등록되지 않았습니다. 오너가 `{REGISTER_COMMAND} {ref}` 로 등록하거나 "
                "Agentlas 앱에서 캐릭터를 고르고 등록하면 쓸 수 있습니다.")
    return (f"This agent is not registered on this computer yet. The owner registers it with `{REGISTER_COMMAND} {ref}` "
            "or in the Agentlas app (pick a character, then register); after that it can be used.")


def agent_usability(
    slug: str | None = None,
    *,
    source: str = "hub",
    agent_definition_id: str | None = None,
    enforce: bool | None = None,
    here: RegisteredHere | None = None,
) -> dict[str, Any]:
    """The engine's one answer. ``{"usable": True, "enforced": bool, ...}`` or ``{"usable": False, "why": ..., "code": ..., "slug": ..., "source": ...}``.

    ``source`` is where the caller found the agent (``hub`` | ``cloud`` | ``local``). The ask is by slug, or by the Hub definition id when the caller has no slug (a workforce pin).
    """
    on = registration_rule_on() if enforce is None else enforce
    if not on:
        return {"usable": True, "enforced": False, "slug": norm_slug(slug) or None, "source": source}
    key = norm_slug(slug)
    try:
        here = here or RegisteredHere()
    except Exception:  # noqa: BLE001 - cannot read what is registered: the narrow side is "usable" (a read failure must not stop a turn)
        return {"usable": True, "enforced": True, "slug": key or None, "source": source, "unreadable": True}
    if (agent_definition_id and agent_definition_id in here.definition_ids) or (key and (key in here.folders or key in here.registry_slugs)):
        folder = here.folders.get(key) or here.registry_slugs.get(key)
        result: dict[str, Any] = {"usable": True, "enforced": True, "slug": key or None, "source": source}
        if folder is not None and not Path(folder).is_dir():
            # a folder that vanished keeps the stored copy working; the owner is offered to reconnect it.
            result.update(folder="folder-missing", reconnectable=True)
        return result
    if key and key in here.removed:
        return _refusal("removed", key, source)
    return _refusal("not_registered", key or None, source)


def _refusal(why: str, slug: str | None, source: str) -> dict[str, Any]:
    code = {"not_registered": NEEDS_REGISTRATION_CODE, "no_folder": "agent_no_folder", "archived": "agent_archived", "removed": "no-agent"}[why]
    return {"usable": False, "enforced": True, "why": why, "code": code, "slug": slug, "source": source}


def refusal_fields(result: dict[str, Any], *, name: str | None = None) -> dict[str, Any]:
    """What a refused call carries on the wire: the closed word, one sentence, the way out. Nothing here is read back by code."""
    slug = result.get("slug")
    source = str(result.get("source") or "hub")
    why = result.get("why")
    fields: dict[str, Any] = {
        "error": result.get("code") or NEEDS_REGISTRATION_CODE,
        "why": why,
        "usable": False,
        "slug": slug,
        "source": source,
        "register": {"command": f"{REGISTER_COMMAND} {source}:{slug}" if slug else REGISTER_COMMAND + " <hub:slug>", "owner_action": True},
    }
    if name:
        fields["name"] = name
    if why == "removed":
        fields["message"] = "This agent was removed on this computer. Register it again to use it."
    else:
        fields["message"] = register_sentence(slug, source)
    return fields


def legacy_drawers() -> dict[str, Any]:
    """COUNT the old per-agent drawers (``networking/hub-agents/<slug>``, kept by engines before 2.0) and mark which slugs are not registered. Reads only, deletes
    nothing: removing them is the migration's cleanup ('), never this function."""
    try:
        from .networking.bootstrap import hub_agents_dir

        base = hub_agents_dir()
        names = sorted(item.name for item in base.iterdir() if item.is_dir())
    except OSError:
        return {"drawers": 0, "withMemory": 0, "needRegistration": []}
    here = RegisteredHere()
    with_memory = sum(1 for name in names if (base / name / "memory").is_dir())
    need = [name for name in names if norm_slug(name) not in here.folders and norm_slug(name) not in here.registry_slugs]
    return {"drawers": len(names), "withMemory": with_memory, "needRegistration": need[:200], "needRegistrationCount": len(need)}
