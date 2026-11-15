"""The engine's smallest registration step: pick a character, register on this computer, get a folder.

For the person who uses the engine without the desktop app (a terminal plugin only). `hephaestus register-agent <ref>`:

  * ``hub:<slug>`` / ``cloud:<slug>`` / ``<slug>``: a call-only agent becomes a *pointer folder* ``<agents root>/<slug>/`` holding the card copy (``card.json``), a one-line
    ``agent.md`` and ``.agentlas-local/`` (``origin.json`` with the slug and the Hub definition id, ``character.json``). The run still goes to the Hub; the Hub agent keeps no
    memory, so no memory file is made. Nothing is copied that the Hub owns (no prompt, no bundle).
  * an existing folder path: the existing local registration (``LocalWorkforceRegistry.register``, in place) plus a state-only companion folder with the character.

Only the owner registers: a model that is refused with ``needs_registration`` tells the owner this command; there is no MCP tool for it. Idempotent; a name already taken by a
folder that is not this agent's is never overwritten. Writes one folder (built beside it, then renamed), so a crash leaves nothing half-registered.
Retention: a registration is kept until the owner removes the folder (``hephaestus register-agent --remove <slug>`` removes only a pointer folder this command made).
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import agent_home
from .agent_usability import CHARACTER_FILE, DEFAULT_CHARACTERS, ORIGIN_FILE, RegisteredHere, default_character, norm_slug


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state_dir(folder: Path) -> Path:
    return folder / agent_home.AGENT_LOCAL_STATE_FOLDER


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _split_ref(ref: str) -> tuple[str, str]:
    value = (ref or "").strip().lstrip("@")
    source = "hub"
    if ":" in value:
        prefix, rest = value.split(":", 1)
        if prefix.lower() in {"hub", "cloud"}:
            source, value = prefix.lower(), rest
    return source, norm_slug(value.rsplit("/", 1)[-1])


def _root_for_write() -> tuple[Path | None, dict[str, Any] | None]:
    status = agent_home.agents_root_status()
    if not status.get("available"):
        # The configured root is not there right now (an unplugged drive): never fall back to the default (the memory would end up in two places).
        return None, {"status": "error", "error": "agent_root_unavailable", "reason": status.get("reason"), "path": status.get("path"), "external": True}
    return Path(str(status["path"])), None


def _pick_character(character: str | None, slug: str) -> tuple[str, str]:
    if character:
        if character not in DEFAULT_CHARACTERS:
            raise ValueError("character_invalid")
        return character, "owner"
    return default_character(slug), "default"


def _claim_folder(root: Path, slug: str) -> tuple[Path | None, dict[str, Any] | None]:
    """The folder for ``slug``: free, or already this agent's pointer (idempotent). A folder that is someone else's is never touched."""
    folder = root / slug
    if not folder.exists():
        return folder, None
    origin = None
    try:
        origin = json.loads((_state_dir(folder) / ORIGIN_FILE).read_text(encoding="utf-8").lstrip("﻿"))
    except (OSError, ValueError):
        pass
    if isinstance(origin, dict) and origin.get("kind") == "hub-pointer" and norm_slug(origin.get("slug")) == slug:
        return None, {"status": "already_registered", "slug": slug, "folder": str(folder), "usable": True}
    if (_state_dir(folder) / "owner.json").is_file():
        return None, {"status": "already_registered", "slug": slug, "folder": str(folder), "usable": True, "managedBy": "desktop"}
    return None, {"status": "error", "error": "agent_folder_name_taken", "folder": str(folder), "message": "A folder with this name already exists and is not this agent's."}


def register_pointer(ref: str, *, character: str | None = None, fetch: Any = None, home: Path | str | None = None) -> dict[str, Any]:
    """Register a call-only Hub/Cloud agent as a pointer folder. ``fetch(tool, arguments)`` is the Hub call (tests pass a fake)."""
    source, slug = _split_ref(ref)
    if not slug:
        return {"status": "error", "error": "agent_ref_invalid"}
    root, failure = _root_for_write()
    if failure:
        return failure
    assert root is not None
    folder, existing = _claim_folder(root, slug)
    if existing:
        return existing
    try:
        chosen, chosen_by = _pick_character(character, slug)
    except ValueError:
        return {"status": "error", "error": "character_invalid", "characters": list(DEFAULT_CHARACTERS)}
    if fetch is None:
        from .networking.bootstrap import networking_home
        from .networking.hub_client import call_hub_tool

        base = Path(home) if home else networking_home()
        fetch = lambda tool, arguments: call_hub_tool(tool, arguments, home=base)  # noqa: E731
    from .networking.hub_client import HubToolError
    from .networking.hub_invocation import _server_refusal

    try:
        response = fetch("agentlas.get_runtime_bundle", {"slug": slug, "version": "latest"})
    except HubToolError as exc:
        return {"status": "error", "error": "hub_tool_error", "detail": str(exc), "external": True}
    refusal = _server_refusal(response)
    if refusal is not None:
        return {"status": "error", "error": refusal["status"], "slug": slug, **refusal["fields"], "external": True}
    bundle = response.get("bundle") if isinstance(response, dict) else None
    if not isinstance(bundle, dict):
        return {"status": "error", "error": "bundle_unavailable", "slug": slug, "external": True}
    localized = bundle.get("localized") if isinstance(bundle.get("localized"), dict) else {}
    name = str(localized.get("titleEn") or localized.get("titleKo") or slug)
    definition = str(bundle.get("agentDefinitionId") or bundle.get("agent_definition_id") or "")
    card = {
        "v": 1, "slug": slug, "name": name, "source": source, "entityKind": str(bundle.get("entityKind") or "agent"),
        "agentDefinitionId": definition, "agentReleaseId": str(bundle.get("agentReleaseId") or bundle.get("agent_release_id") or ""),
        "packageHash": str(bundle.get("packageHash") or ""), "descriptionEn": str(localized.get("descriptionEn") or ""),
        "descriptionKo": str(localized.get("descriptionKo") or ""),
    }
    root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".register-{slug[:24]}-", dir=str(root)))
    try:
        (staging / "agent.md").write_text(
            f"# {name}\n\nA {source} agent registered on this computer. It runs on the Agentlas Hub: call it with "
            f"`hephaestus call {source}:{slug} \"<task>\"`. It keeps no memory of its own.\n", encoding="utf-8")
        _write_json(staging / "card.json", card)
        _write_json(_state_dir(staging) / ORIGIN_FILE, {"v": 1, "kind": "hub-pointer", "source": source, "slug": slug, "agentDefinitionId": definition, "registeredAt": _now()})
        _write_json(_state_dir(staging) / CHARACTER_FILE, {"v": 1, "character": chosen, "chosenBy": chosen_by})
        assert folder is not None
        os.rename(staging, folder)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        return {"status": "error", "error": "register_write_failed", "detail": type(exc).__name__}
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return {"status": "registered", "slug": slug, "source": source, "folder": str(folder), "character": chosen, "usable": True,
            "memory": "none: a Hub agent keeps no memory of its own"}


def register_folder(path: str, *, character: str | None = None, registry: Any = None) -> dict[str, Any]:
    """Register an agent folder in place (the existing local registration) and give it a character in a state-only companion folder."""
    from .workforce.local_registry import LocalWorkforceRegistry

    source = Path(path).expanduser()
    if not source.is_dir():
        return {"status": "error", "error": "agent_folder_missing", "path": str(source)}
    resolved = source.resolve()
    outcome = (registry or LocalWorkforceRegistry()).register(resolved)
    if outcome.get("status") != "active":
        return outcome
    slug = norm_slug(resolved.name)
    root, failure = _root_for_write()
    if failure:
        return {**outcome, "character": None, "characterNote": failure["error"]}
    assert root is not None
    try:
        inside = resolved.is_relative_to(root.resolve())
    except OSError:
        inside = False
    folder = resolved if inside else root / slug
    if not inside and folder.exists() and not (_state_dir(folder) / ORIGIN_FILE).is_file():
        folder = root / f"{slug}-{__import__('hashlib').sha256(str(resolved).encode()).hexdigest()[:6]}"
    try:
        chosen, chosen_by = _pick_character(character, slug)
        if not (_state_dir(folder) / CHARACTER_FILE).is_file() or character:
            _write_json(_state_dir(folder) / CHARACTER_FILE, {"v": 1, "character": chosen, "chosenBy": chosen_by})
        if not inside and not (_state_dir(folder) / ORIGIN_FILE).is_file():
            _write_json(_state_dir(folder) / ORIGIN_FILE, {"v": 1, "kind": "in-place", "slug": slug, "from": str(resolved), "registeredAt": _now()})
    except (OSError, ValueError) as exc:
        return {**outcome, "character": None, "characterNote": type(exc).__name__}
    return {**outcome, "slug": slug, "character": chosen, "folder": str(folder), "usable": True}


def register(ref: str, *, character: str | None = None, fetch: Any = None) -> dict[str, Any]:
    """An existing folder path registers in place; anything else is a Hub/Cloud slug."""
    candidate = Path(ref).expanduser() if ref and (os.sep in ref or ref.startswith(("~", "."))) else None
    if candidate is not None and candidate.is_dir():
        return register_folder(str(candidate), character=character)
    return register_pointer(ref, character=character, fetch=fetch)


def remove_pointer(slug: str) -> dict[str, Any]:
    """Remove a pointer folder THIS command made (its origin says ``hub-pointer``). Any other folder is left alone."""
    key = norm_slug(slug)
    folder = RegisteredHere().folders.get(key)
    if folder is None:
        return {"status": "not_registered", "slug": key}
    try:
        origin = json.loads((_state_dir(folder) / ORIGIN_FILE).read_text(encoding="utf-8").lstrip("﻿"))
    except (OSError, ValueError):
        origin = None
    if not isinstance(origin, dict) or origin.get("kind") != "hub-pointer":
        return {"status": "refused", "error": "not_a_pointer_folder", "folder": str(folder)}
    shutil.rmtree(folder, ignore_errors=True)
    return {"status": "removed", "slug": key, "folder": str(folder), "stillThere": folder.exists()}
