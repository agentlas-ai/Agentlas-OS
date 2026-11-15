"""Computed memory ownership: personal | agent | project | session | legacy-shared (and, under the 2.0 ``split-2`` layout only, worker).

Reads only schemas/memory-scopes.json. Nothing is stored, no column or meta
value is added, so older engines and desktops that share the same
memory.sqlite never see a value they do not know. The function never raises
on an unfamiliar row shape; it answers with the safe default (legacy-shared).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any, NamedTuple

from .memory_actor_family import is_one_memory_actor

_PATH = Path(__file__).resolve().parent.parent / "schemas" / "memory-scopes.json"


class OwnerScope(NamedTuple):
    kind: str
    owner_id: str | None


@lru_cache(maxsize=1)
def contract() -> dict[str, Any]:
    return json.loads(_PATH.read_text(encoding="utf-8"))


# Used only when the contract file is missing, half written or shaped differently (an update replacing it
# mid-turn): every row is then legacy-shared, which stays in the root store and is never moved anywhere.
_FALLBACK: dict[str, Any] = {
    "hubAgentIdPrefix": "hub:",
    "systemActorPrefixes": [],
    "rows": {"rules": [], "fallback": "legacy-shared", "unmapped": []},
}

_RETRY_AFTER = 5.0
_bad_until = 0.0


def _usable(value: Any) -> bool:
    rows = value.get("rows") if isinstance(value, dict) else None
    return (isinstance(rows, dict) and isinstance(rows.get("rules"), list) and isinstance(rows.get("fallback"), str)
            and isinstance(rows.get("unmapped"), list) and isinstance(value.get("systemActorPrefixes"), list)
            and all(isinstance(r, dict) and isinstance(r.get("scope"), list) and isinstance(r.get("owner"), str) for r in rows["rules"]))


def _active() -> dict[str, Any]:
    """The file's contract, or the built-in copy; never raises. A failed read is retried after a few seconds."""
    global _bad_until
    if time.monotonic() < _bad_until:
        return _FALLBACK
    try:
        value = contract()
        if _usable(value):
            return value
    except Exception:
        pass
    contract.cache_clear()
    _bad_until = time.monotonic() + _RETRY_AFTER
    return _FALLBACK


def _get(row: Any, key: str) -> Any:
    """Works for dict, sqlite3.Row, and anything else; a missing column is None."""
    try:
        return row[key]
    except Exception:  # KeyError, IndexError, TypeError, odd mappings
        return None


def _text(row: Any, key: str) -> str | None:
    value = _get(row, key)
    return value if isinstance(value, str) and value.strip() else None


def _prefixed(actor: str | None, prefixes: Any) -> bool:
    wanted = tuple(p.casefold() for p in prefixes if isinstance(p, str) and p)
    return actor is not None and bool(wanted) and actor.strip().casefold().startswith(wanted)


def _project_key(row: Any) -> str | None:
    """The engine's revocation authority key for a project path; a bare project id is not a key (folder-name derived)."""
    path = _text(row, "project_path")
    return "project-path:" + hashlib.sha256(path.encode("utf-8")).hexdigest() if path else None


def _special_id(agent: str | None, active: dict[str, Any]) -> str | None:
    """The contract's own spelling of a special agent's id, so 'BUILTIN-AGENTLAS-FINANCE' and the lowercase id are one owner."""
    wanted = agent.strip().casefold() if agent is not None else None
    return next((i for i in active.get("specialAgentIds", []) if isinstance(i, str) and i.casefold() == wanted), None)


def _facts(row: Any, active: dict[str, Any]) -> dict[str, bool]:
    agent = _text(row, "agent_id")
    special = _special_id(agent, active) is not None
    return {
        "oneActor": agent is not None and is_one_memory_actor(agent.strip()),
        "specialAgent": special,
        "systemActor": not special and _prefixed(agent, active["systemActorPrefixes"]),
        "hubActor": _prefixed(agent, [active.get("hubAgentIdPrefix") or _FALLBACK["hubAgentIdPrefix"]]),
        "agentId": agent is not None,
        "projectLink": _project_key(row) is not None,
        "chatId": _text(row, "chat_id") is not None,
    }


def actor_kind(agent_id: str | None) -> str:
    """How the memory contract sees an actor: ``resident`` (the One family and the ``systemActorPrefixes`` actors such as
    ``host:claude``), ``special`` (a listed special agent), ``hub`` (a borrowed Hub agent, which keeps no memory) or
    ``folderAgent`` (any other agent id: an agent that has its own folder). Computed from the contract only; never raises."""
    active = _active()
    facts = _facts({"agent_id": agent_id}, active)
    if facts["hubActor"]:
        return "hub"
    if facts["specialAgent"]:
        return "special"
    if facts["oneActor"] or facts["systemActor"]:
        return "resident"
    return "folderAgent"


def personal_set() -> dict[str, Any] | None:
    """The contract's ``personalSet``: which scopes are the owner's Personal memory and which kinds a resident
    actor may put there (``residentActorKinds``). ``None`` when the contract has none (an older file, or the built-in
    fallback): the callers then behave as they did before the block existed."""
    value = _active().get("personalSet")
    if (isinstance(value, dict) and isinstance(value.get("scopes"), list) and isinstance(value.get("residentActorKinds"), list)
            and all(isinstance(v, str) for v in value["scopes"] + value["residentActorKinds"])):
        return {"scopes": list(value["scopes"]), "residentActorKinds": list(value["residentActorKinds"])}
    return None


def _split2_rules(active: dict[str, Any]) -> list[dict[str, Any]]:
    block = active.get("splitTwoRules")
    rules = block.get("rules") if isinstance(block, dict) else None
    return [r for r in rules if isinstance(r, dict) and isinstance(r.get("scope"), list) and isinstance(r.get("owner"), str)] if isinstance(rules, list) else []


def owner_scope_of(row: Any, *, split2: bool = False) -> OwnerScope | None:
    """Owner of one memory row, or None for a scope that is never stored.

    ``split2`` asks for the ownership under the ``split-2`` layout: the contract's ``splitTwoRules`` are tried first (the resident
    subjects' agent lines belong to ``worker``), then the ordinary rules. Without it the answer is exactly the 1.x one."""
    active = _active()
    rows = active["rows"]
    scope = _get(row, "scope")
    if not isinstance(scope, str):
        return OwnerScope(rows["fallback"], None)
    if scope in rows["unmapped"]:
        return None
    facts = _facts(row, active)
    for rule in ([*_split2_rules(active), *rows["rules"]] if split2 else rows["rules"]):
        if scope not in rule["scope"] or not all(facts.get(k) == want for k, want in (rule.get("when") or {}).items()):
            continue
        if rule.get("idFrom") == "projectKey":
            owner_id = _project_key(row)
        elif rule.get("idFrom") == "specialAgentId":
            owner_id = _special_id(_text(row, "agent_id"), active)
        else:
            owner_id = next((t.strip() for k in rule.get("id", ()) if (t := _text(row, k))), None)
        return OwnerScope(rule["owner"], owner_id)
    return OwnerScope(rows["fallback"], None)


_NOT_SAFE = re.compile(r"[^a-z0-9]")
_WINDOWS_RESERVED = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])$")


def _id_suffix(ident: str) -> str:
    # Node hashes a string as UTF-8 with a lone surrogate written as U+FFFD; Python would refuse it.
    clean = ident.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
    return hashlib.sha256(clean.encode("utf-8")).hexdigest()[:6]


def safe_store_key(owner: "OwnerScope | str | None", agent_id: str | None = None) -> str:
    """A folder / store name, identical to the desktop's safeHomeName(slug, id) (electron/agents/home.ts).

    NFKC, lowercase, EVERY character outside [a-z0-9] becomes '-' (one per UTF-16 unit, as in JavaScript: an
    emoji gives '--'), ends trimmed, cut at 36. An empty result or 'local' becomes 'agent-<sha256(id)[:6]>'
    ('agent' without an id); a Windows device name (con, nul, com1...) gets '-agent' appended. Lowercase ASCII
    only, so ':' ('host:claude'), dots, trailing spaces and case-only differences cannot occur or collide.
    An OwnerScope is both the name and the id; a bare string is only the slug. The desktop adds a '-<id6>' suffix when a folder
    is owned by another agent (decided from owner.json on disk); this function never looks at the disk and
    creates nothing. The shared test vectors live in contracts/test-vectors/safe-store-key-vectors.json.
    """
    slug = owner.owner_id if isinstance(owner, OwnerScope) else owner
    slug = slug if isinstance(slug, str) else ""
    ident = agent_id if isinstance(agent_id, str) else (slug if isinstance(owner, OwnerScope) else "")
    lowered = unicodedata.normalize("NFKC", slug).lower()
    spread = "".join(c if ord(c) < 0x10000 else "\ufffd\ufffd" for c in lowered)
    base = _NOT_SAFE.sub("-", spread).strip("-")[:36]
    if not base or base == "local":
        return "agent-" + _id_suffix(ident) if ident else "agent"
    return base + "-agent" if _WINDOWS_RESERVED.match(base) else base
