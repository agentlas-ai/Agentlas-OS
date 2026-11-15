"""Write-time classification of one curated memory proposal (section 12; always-part).

Pure rules over the canonical ruleset's ``stores`` block (``system-agents/curator-ruleset.json``) and the memory contract's
``personalSet`` (``schemas/memory-scopes.json``). Nothing here touches a database, a model or the disk, so the same
answers can be pinned by the shared vectors (``contracts/test-vectors/memory-classification-vectors.json``) and ported to
the desktop executor.

The rules run in two stages. ``stage1`` decides the scope and kind a proposal ends up with (the model's answer is
corrected by code, never asked again, except a too-long Personal line); ``stage2`` is what the writer decides at write
time (a forgotten text, a replacement, a full store). A ruleset without a usable ``stores`` block, or a contract without
``personalSet``, switches the corresponding rule off: the behaviour is then the one before.
"""
from __future__ import annotations

import os
import re
import sqlite3
import unicodedata
from typing import Any, Callable

STORE_SCOPES = ("user_identity", "agent_repo", "project")
# The reason code of a refused write. It lives in the ruleset (stores.ceiling.reason); this is only the file-missing value.
_FULL = "store_" + "full"
DEFAULT_HOME_STATE_KEY = "one_home_state"
HOME_STATES = ("home", "away", "sealed")
_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}


def active(ruleset: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The whole ruleset when its ``stores`` block is usable, else None (the rules are then off)."""
    try:
        if ruleset is None:
            from .one_workspace import load_ruleset
            ruleset = load_ruleset()[0]
        stores = ruleset.get("stores") if isinstance(ruleset, dict) else None
        if not isinstance(stores, dict):
            return None
        for scope in STORE_SCOPES:
            block = stores.get(scope)
            if not isinstance(block, dict) or not isinstance(block.get("acceptedKinds"), list):
                return None
        if not isinstance(stores["user_identity"].get("admission"), dict):
            return None
        return ruleset
    except Exception:  # noqa: BLE001 - a damaged ruleset switches the rules off, it never stops a curation
        return None


def _stores(rs: dict[str, Any]) -> dict[str, Any]:
    return rs["stores"]


def remap_table(rs: dict[str, Any], scope: str) -> dict[str, str]:
    """The plain kind-to-kind corrections of one store (an entry that is not a string is a conditional rule)."""
    table = _stores(rs).get(scope, {}).get("kindRemap")
    return {k: v for k, v in table.items() if isinstance(k, str) and isinstance(v, str)} if isinstance(table, dict) else {}


def accepted_kinds(rs: dict[str, Any], scope: str) -> list[str]:
    return [k for k in _stores(rs)[scope]["acceptedKinds"] if isinstance(k, str)]


def read_kind(rs: dict[str, Any], scope: str, kind: str) -> str:
    """How a STORED line reads (stored lines are never rewritten): a Personal line that is not a fact reads as a
    preference; elsewhere the store's own correction applies."""
    if scope == "user_identity":
        return "fact" if kind == "fact" else "preference"
    return remap_table(rs, scope).get(kind, kind) if scope in STORE_SCOPES else kind


def equivalent_kinds(rs: dict[str, Any] | None, scope: str, kind: str) -> list[str]:
    """Every stored kind that the corrected ``kind`` stands for in ``scope``: the duplicate check and the forget stamp
    follow the corrected kind, so a text forgotten as a decision does not come back as a preference."""
    if rs is None or scope not in STORE_SCOPES:
        return [kind]
    table = remap_table(rs, scope)
    return sorted({kind} | {k for k, v in table.items() if v == kind})


def _count(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def ceiling_of(rs: dict[str, Any] | None, scope: str, actor_kind: str | None = None) -> int | None:
    """The line ceiling of a store. An agent's own store of a resident actor (the One family, host:*) has its own, higher number
    (``residentActorCeilingRows``); without it, or for any other actor, ``ceilingRows``."""
    if rs is None or scope not in STORE_SCOPES:
        return None
    block = _stores(rs)[scope]
    if scope == "agent_repo" and actor_kind == "resident":
        resident = _count(block.get("residentActorCeilingRows"))
        if resident is not None:
            return resident
    return _count(block.get("ceilingRows"))


def ceiling_counts_from(rs: dict[str, Any] | None) -> str | None:
    """Only lines written on or after this timestamp count towards a ceiling (a store that was already large when the
    rules began is never blocked by lines it already held). None = every live line counts (the file says nothing)."""
    value = ((_stores(rs).get("ceiling") or {}).get("countsFrom")) if rs is not None else None
    return value if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", value) else None


def named_containment_min(rs: dict[str, Any] | None) -> float | None:
    """The token containment (shared / shorter side) at which a text replaces the ONE line the model named; None = off."""
    value = (((_stores(rs).get("replacement") or {}).get("namedContainmentMin")) if rs is not None else None)
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value <= 1 else None


_FORGET_TRAILING = ".!?。！？…"


def forget_trailing(rs: dict[str, Any] | None) -> str:
    value = (((_stores(rs).get("forget") or {}).get("trailingChars")) if rs is not None else None)
    return value if isinstance(value, str) and 0 < len(value) <= 16 else _FORGET_TRAILING


def _norm(text: str) -> str:
    """The memory contract's normal form of a text (memory_runtime.content_hash): NFKC, runs of space as one, lower case."""
    return " ".join(unicodedata.normalize("NFKC", str(text)).split()).lower()


def forget_key(text: str, rs: dict[str, Any] | None = None) -> str:
    """The text a forget stamp compares: the normal form (NFKC, runs of space as one, lower case) and ONE trailing character of the ruleset's
    ``stores.forget.trailingChars`` taken off. Kind never takes part."""
    return _norm(text)[:-1] if _norm(text) and _norm(text)[-1] in forget_trailing(rs) else _norm(text)


def forget_forms(text: str, rs: dict[str, Any] | None = None) -> list[str]:
    """Every normalised form of ``text`` that a stored stamp may have been made from: as offered, and the key with no or
    with one trailing character. A stamp compares equal to the offered text exactly when ``forget_key`` is equal."""
    trailing = forget_trailing(rs)
    norm = _norm(text)
    key = forget_key(text, rs)
    forms = [norm] + [key + c for c in trailing]
    if not key or key[-1] not in trailing:
        forms.append(key)
    return sorted(set(forms))


def full_reason(rs: dict[str, Any] | None) -> str:
    value = ((_stores(rs).get("ceiling") or {}).get("reason")) if rs is not None else None
    return value if isinstance(value, str) and re.fullmatch(r"[a-z0-9_]{1,40}", value) else _FULL


def merge_overlap_min(rs: dict[str, Any] | None) -> float:
    value = ((rs or {}).get("limits") or {}).get("mergeTokenOverlapMin")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.6


def _regex(rs: dict[str, Any], name: str) -> "re.Pattern[str] | None":
    spec = (rs.get("patterns") or {}).get(name)
    if not isinstance(spec, dict) or not isinstance(spec.get("regex"), str):
        return None
    flags = 0
    for letter, flag in (("i", re.IGNORECASE), ("m", re.MULTILINE), ("s", re.DOTALL)):
        if letter in str(spec.get("flags") or ""):
            flags |= flag
    try:
        # ASCII: the desktop executor's RegExp reads \b and \w as ASCII, Python reads them as Unicode by default, so a key
        # glued to a Hangul letter was a secret there and not here. No pattern read here uses \s.
        return re.compile(spec["regex"], flags | re.ASCII)
    except re.error:
        return None


def home_state_key(rs: dict[str, Any] | None) -> str:
    value = ((_stores(rs)["user_identity"].get("admission") or {}).get("homeStateMetaKey")) if rs is not None else None
    return value if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{2,63}", value) else DEFAULT_HOME_STATE_KEY


def home_state(db: Any, rs: dict[str, Any] | None = None) -> str:
    """Whether this computer is the personal agent's home: the root store's ``memory_store_meta`` key (written by the
    desktop's home record). A missing key, a missing table or an unreadable file is ``home``: an engine that cannot
    tell never blocks a write. A key that IS there with a value this engine does not know (``HOME``, an empty text,
    a number) is ``sealed``: a mirror that cannot be read is not a home, which is how ``one_pack`` reads it for an
    import (F-16; before this the normal write opened on such a value while the import closed)."""
    try:
        row = db.execute("SELECT value FROM memory_store_meta WHERE key=?", (home_state_key(rs),)).fetchone()
    except Exception:  # noqa: BLE001
        return "home"
    if not row:
        return "home"
    value = row[0]
    return value if isinstance(value, str) and value in HOME_STATES else "sealed"


# --- the workspace-rules switch (Agentlas 2.0 memory algorithm P1) --------------------------------------------------------------
#
# ONE root ``memory_store_meta`` row switches the new reading and writing scopes on (the first-run step ``workspace-rules`` writes it; nothing in
# the engine does). Off (no row, no table, any other value) every function below answers what it answered before ruleset 1.7.0.

DEFAULT_RULES_STATE_KEY = "workspace_rules_state"
DEFAULT_PERSONAL_READ_ENV = "AGENTLAS_MEMORY_PERSONAL_READ"
RULES_ON_VALUE = "on"


def _workspace_block(rs: dict[str, Any] | None) -> dict[str, Any]:
    block = (rs or {}).get("workspaceRules") if isinstance(rs, dict) else None
    return block if isinstance(block, dict) else {}


def workspace_rules_state_key(rs: dict[str, Any] | None = None) -> str:
    value = _workspace_block(rs).get("stateMetaKey")
    return value if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{2,63}", value) else DEFAULT_RULES_STATE_KEY


def personal_read_env_name(rs: dict[str, Any] | None = None) -> str:
    value = _workspace_block(rs).get("personalReadEnv")
    return value if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", value) else DEFAULT_PERSONAL_READ_ENV


OUTSIDE_MARKER_NAME = "workspace-rules-outside.json"
OUTSIDE_MARKER_SCHEMA = "agentlas.workspace-rules-outside.v1"
_OUTSIDE_MARKER_MAX_BYTES = 4096


def outside_marker_on() -> bool:
    """The machine-level word that the workspace-rules switch is on for at least one account of this computer, for the callers that have no host binding
    (a Claude Code or Codex window opened outside the app; X1): the file ``workspace-rules-outside.json`` in the memory root. The desktop's first-run
    step ``workspace-rules`` writes it (before the switch row, and again when it finds the row already on); this reads it and nothing removes it (turning a
    switch back off leaves it: the narrower side). A caller that carries a host binding (the app's own turns) never asks it. A missing file is off; a file that is there but broken or unreadable (not a plain small file, not JSON, not an object, no schema, or looked at and failed) is ON, the narrower side; a file that names another schema is off. It opens no memory store, so it can never read or write another account's file."""
    from .memory_owner_binding import FILE_ENV, REV_ENV
    if os.environ.get(FILE_ENV) or os.environ.get(REV_ENV):
        return False
    try:
        import json
        import stat
        from .memory_runtime import memory_io_root
        path = memory_io_root() / OUTSIDE_MARKER_NAME
    except Exception:  # noqa: BLE001 - the root itself cannot be named: nothing says it is there
        return False
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False   # no file: no account has turned the switch on from this computer
    except Exception:  # noqa: BLE001 - it is there and cannot even be looked at
        return True
    try:
        if not stat.S_ISREG(info.st_mode) or info.st_size > _OUTSIDE_MARKER_MAX_BYTES:
            return True   # a marker that is there but is not a plain small file is damaged; the narrower side
        with open(path, "rb") as handle:
            value = json.loads(handle.read(_OUTSIDE_MARKER_MAX_BYTES + 1).decode("utf-8"))
        if not isinstance(value, dict):
            return True   # parsed, but not an object: damaged
        return value.get("schema") == OUTSIDE_MARKER_SCHEMA or "schema" not in value   # a file that names another schema is another program's; one that names none is damaged
    except Exception:  # noqa: BLE001 - there but unreadable or broken: the narrower side
        return True


def workspace_rules_on(db: Any, rs: dict[str, Any] | None = None, *, locked: bool | None = None) -> bool:
    """Whether the workspace-rules switch is on for the store ``db`` (a root store connection): its ``memory_store_meta`` row says ``on``.
    A missing row or table, an unreadable file or any other value is off (the same ``cannot tell`` rule as ``home_state``). One case is
    different: a store that is busy or locked right now. ``locked=None`` (the default) lets that error out, so a caller that has to read the
    same file next (the hook, the curator) takes its own lock handling and never reads in the old scope for one call; a caller that must
    answer anyway passes the value to use (a search tool passes True: it hides what the switch hides).

    A caller with no host binding (a window opened outside the app) also gets ``on`` when the machine-level marker says so (``outside_marker_on``):
    that window always opens the first account's store, so the row of the store it happens to open is not the word of the account that turned the
    switch on."""
    try:
        row = db.execute("SELECT value FROM memory_store_meta WHERE key=?", (workspace_rules_state_key(rs),)).fetchone()
        if bool(row) and row[0] == RULES_ON_VALUE:
            return True
    except sqlite3.OperationalError as error:
        text = str(error).lower()
        if "locked" in text or "busy" in text:
            if locked is None:
                raise
            return locked
    except Exception:  # noqa: BLE001
        pass
    return outside_marker_on()


def personal_flag(rs: dict[str, Any] | None = None) -> bool:
    """The host's word that this executor serves the personal agent's own conversation: the environment variable is exactly ``1``. Read from
    the process environment only, never from model output or a hook payload (the host that starts the executor sets it)."""
    return os.environ.get(personal_read_env_name(rs)) == "1"


def personal_conversation_here(surface: str, personal_conversation: bool | None) -> bool:
    """The engine hook is never the personal agent's own conversation (it serves a Claude Code or Codex window); the desktop says so per turn."""
    return surface == "desktop" and personal_conversation is True


def _flag_or(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _needs_personal_conversation(side: dict[str, Any], surface: str, kind: str) -> bool:
    """With the switch on, does a Personal line of this ``kind`` need the personal agent's own conversation? Desktop: the side's
    ``requiresPersonalConversationAfterWorkspaceRules`` (default true when the file has no such key). Engine hook: the kind is not among
    ``kindsAfterWorkspaceRules`` (default none)."""
    if surface == "desktop":
        return _flag_or(side.get("requiresPersonalConversationAfterWorkspaceRules"), True)
    allowed = side.get("kindsAfterWorkspaceRules")
    return kind not in (allowed if isinstance(allowed, list) else [])


def stage1(rs: dict[str, Any], *, scope: str, kind: str, confidence: str | None, text: str, surface: str, project: bool,
           in_project: bool | None, actor_kind: str, owner_spoke: bool | None,
           home_state: "str | Callable[[], str]" = "home", personal: dict[str, Any] | None = None,
           rules_on: "bool | Callable[[], bool]" = False, personal_conversation: bool | None = None) -> dict[str, Any]:
    """The scope and kind a proposal ends up with, in the vector ``expect`` forms:
    ``{scope, kind}`` | ``{scope: 'session'}`` (not stored) | ``{discard}`` | ``{askAgain}`` | ``{write: False, modelCall: False}``.

    ``in_project``: the project binding came from an enclosing project root (engine: the hook's ``in_project``; desktop: the
    same as ``project``); None = unknown = False. ``personal``: the contract's ``personalSet`` or None (rule off).

    ``rules_on`` (the workspace-rules switch, a bool or a callable that is asked only when it matters) and ``personal_conversation`` (this turn
    is the personal agent's own conversation; None = not known = no; the engine hook is never one): with the switch off nothing below
    changes and the answer carries no new key. With it on, a Personal line is only written from the personal agent's own conversation:
    an instruction (user_identity/preference, or a resident actor's agent_repo/preference) from any other conversation becomes the folder
    agent's or a special agent's agent_repo/procedure, a resident actor's project decision when the turn is inside a project, and otherwise
    is not stored; a Personal fact from any other conversation is not stored. An instruction from a turn the owner did not type (``owner_spoke`` not true, on a side that
    requires it: a group member, an @ chain, a peer message, an automation) is not stored either, exactly as with the switch off. The answer then also says ``instruction`` (the original
    proposal's scope was user_identity or its kind was preference): the desktop marks those lines so they never count towards a skill."""
    stores = _stores(rs)
    if actor_kind == "hub":
        return {"write": False, "modelCall": False}
    instruction = scope == "user_identity" or kind == "preference"
    switch: list[bool] = []

    def on() -> bool:   # asked at most once per call, and only when the answer can differ
        if not switch:
            switch.append(bool(rules_on() if callable(rules_on) else rules_on))
        return switch[0]
    secret = _regex(rs, "secretValueShapes")
    if secret is not None and secret.search(text):
        return {"discard": True}
    resident_kinds = (personal or {}).get("residentActorKinds") or []
    if scope == "agent_repo":
        rule = stores["agent_repo"].get("kindRemap", {}).get(kind) if isinstance(stores["agent_repo"].get("kindRemap"), dict) else None
        if isinstance(rule, dict):  # the conditional correction: a preference from an agent_repo proposal
            if personal is not None and kind in resident_kinds:
                if actor_kind == "resident":
                    scope = "user_identity"
                elif isinstance(rule.get("folderAgent"), str):
                    kind = rule["folderAgent"]
        elif isinstance(rule, str):
            kind = rule
    elif scope in ("user_identity", "project"):
        kind = remap_table(rs, scope).get(kind, kind)
    if scope in STORE_SCOPES and kind not in accepted_kinds(rs, scope):
        return {"scope": "session"}
    if scope == "user_identity":
        side_rules = (stores["user_identity"].get("admission") or {}).get("desktop" if surface == "desktop" else "engineHook")
        if isinstance(side_rules, dict) and not personal_conversation_here(surface, personal_conversation):
            if _needs_personal_conversation(side_rules, surface, kind) and on():
                if kind != "preference":
                    return {"scope": "session"}
                if side_rules.get("requiresOwnerSpoke") and owner_spoke is not True:
                    return {"scope": "session"}   # a turn the owner did not type (a group member, an @ chain, a peer, an automation): what it calls an instruction is not stored, as with the switch off
                if actor_kind in ("folderAgent", "special"):
                    scope, kind = "agent_repo", "procedure"
                elif actor_kind == "resident" and in_project:
                    scope, kind = "project", "decision"
                else:
                    return {"scope": "session"}
    if scope == "user_identity":
        admission = stores["user_identity"]["admission"]
        side = admission.get("desktop" if surface == "desktop" else "engineHook")
        if not isinstance(side, dict):
            return {"scope": "session"}
        if confidence != admission.get("minConfidence") or kind not in (side.get("kinds") or []):
            return {"scope": "session"}
        if side.get("requiresOwnerSpoke") and owner_spoke is not True:
            return {"scope": "session"}
        state = home_state() if callable(home_state) else home_state
        path = _regex(rs, "hostAbsolutePath")
        if state in (admission.get("deniedHomeStates") or []) or (path is not None and path.search(text)):
            return {"scope": "session"}
        limit = stores["user_identity"].get("maxChars")
        if isinstance(limit, int) and len(text) > limit:
            return {"askAgain": True}
    if scope == "project" and not project:
        return {"scope": "session"}
    if scope == "agent_repo" and personal is not None and actor_kind == "resident" and in_project:
        scope = "project"
    if scope in STORE_SCOPES and on():
        return {"scope": scope, "kind": kind, "instruction": instruction}
    return {"scope": scope, "kind": kind}


def stage2(rs: dict[str, Any], *, scope: str, kind: str, forgotten: dict[str, str] | None = None, store_rows: int = 0,
           similarity: float | None = None, target: dict[str, str] | None = None, containment: float | None = None,
           named: bool = False, actor_kind: str | None = None, text: str | None = None) -> dict[str, Any]:
    """What the writer decides after ``stage1``: a forgotten text is not written; a line that replaces an older one (similar
    enough, same scope, same corrected kind) is written even in a full store; any other new line in a full store is refused
    (``store_full``, not tried again). Code never retires a line to make room.

    A forget stamp of the same scope stops the text whatever kind it was stamped with and, when ``forgotten`` carries its
    ``text``, whatever trailing character differs (``forget_key``). ``named``: the model named exactly one line; then a
    ``containment`` (shared tokens / the shorter text's tokens) of ``namedContainmentMin`` is enough to replace it."""
    if forgotten and forgotten.get("scope") == scope:
        if forgotten.get("text") is None or text is None or forget_key(forgotten["text"], rs) == forget_key(text, rs):
            return {"write": False, "reason": "forgotten"}
    out: dict[str, Any] = {"scope": scope, "kind": kind}
    replace = None
    if similarity is not None or target is not None or containment is not None:
        floor = named_containment_min(rs)
        close = ((similarity is not None and similarity >= merge_overlap_min(rs))
                 or (named and floor is not None and containment is not None and containment >= floor))
        replace = (close and (target is None or (target.get("scope") == scope and read_kind(rs, scope, target.get("kind") or "") == kind)))
        out["replace"] = replace
    ceiling = ceiling_of(rs, scope, actor_kind)
    if ceiling is not None and store_rows >= ceiling and not replace:
        return {"write": False, "reason": full_reason(rs)}
    return out


def classify(rs: dict[str, Any], case: dict[str, Any], personal: dict[str, Any] | None) -> dict[str, Any]:
    """The reference answer for one code-judged vector case (both stages). The desktop executor ports this."""
    host, model = case["host"], case["model"]
    surface = host["surface"]
    project = bool(host["project"])
    in_project = host.get("inProject", project if surface == "desktop" else False)
    first = stage1(rs, scope=model["scope"], kind=model["kind"], confidence=model.get("confidence"), text=case["text"], surface=surface,
                   project=project, in_project=in_project, actor_kind=host["actorKind"], owner_spoke=host.get("ownerSpoke"),
                   home_state=host.get("homeState", "home"), personal=personal,
                   rules_on=bool(host.get("rulesOn")), personal_conversation=host.get("personalConversation"))
    if "scope" not in first or first["scope"] == "session":
        return first
    second = stage2(rs, scope=first["scope"], kind=first["kind"], forgotten=host.get("forgotten"), store_rows=host.get("storeRows", 0),
                    similarity=host.get("similarity"), target=host.get("target"), containment=host.get("containment"),
                    named=bool(host.get("named")), actor_kind=host["actorKind"], text=case["text"])
    if "instruction" in first and "scope" in second:
        second["instruction"] = first["instruction"]
    return second


def personal_min_confidence(rs: dict[str, Any] | None) -> str | None:
    """The confidence word the Personal admission of ``stage1`` compares against (``stores.user_identity.admission.minConfidence``), or None.

    Agentlas 2.0: a model's own confidence no longer decides whether a Personal line is kept (where a line came from is two host-decided
    columns, not a gate). ``stage1`` stays as the shared vectors pin it (the desktop's port is the same function); a caller that does not want the model's confidence
    to decide passes this value as the confidence, exactly as the desktop's writer does."""
    try:
        value = _stores(rs)["user_identity"]["admission"].get("minConfidence") if rs is not None else None
    except (KeyError, TypeError, AttributeError):
        return None
    return value if isinstance(value, str) else None


def observed_confidence(observations: Any, text: str) -> str | None:
    """The host's own confidence for a proposal: that of the observation with the same text; with none matching, the best
    confidence among the turn's observations; None when the turn carried no observation (a model's reading of the summary
    alone is not "high")."""
    if not isinstance(observations, list):
        return None
    wanted = " ".join(text.split()).casefold()
    best: str | None = None
    for item in observations:
        if not isinstance(item, dict):
            continue
        level = item.get("suggested_confidence")
        if level not in _CONFIDENCE_RANK:
            continue
        if " ".join(str(item.get("content") or "").split()).casefold() == wanted:
            return level
        if best is None or _CONFIDENCE_RANK[level] > _CONFIDENCE_RANK[best]:
            best = level
    return best


# --- the reading scope of Personal facts (section 12-6) -------------------------------------------------------

ONE_FAMILY_ONLY = "one-family-only"


def reads_personal_fact(actor_id: str | None, rs: dict[str, Any] | None = None) -> bool:
    """Whether this subject may read the owner's Personal ``fact`` lines (``user_identity`` scope, kind ``fact``): only the personal agent (the One
    family). The ruleset's ``stores.user_identity.readers.fact`` says so (``one-family-only``); without a usable ``stores`` block (an older ruleset)
    nobody is held back, as before. A Personal line that is not a fact (a preference, or an old line of another kind that reads as one) is read by every subject.
    Since 1.7.0 a thin alias of ``reads_personal`` with the workspace-rules switch off (kept one release for older callers); the callers that can
    see the store ask ``reads_personal`` with the switch."""
    return reads_personal(actor_id, rs, False, False)


def reads_personal(actor_id: str | None, rs: dict[str, Any] | None = None, rules_on: bool = False, personal_flag: bool = False) -> bool:
    """Whether this subject may read the owner's Personal lines (``user_identity`` scope): the ONE definition of the condition. The hook's recall
    SQL, ``merge_rows``, the curator's view of existing lines, the search tools and the file views all ask it (the desktop's ``listMemoryForContext``
    asks the same of the same shared vectors).

    Switch OFF: what ``reads_personal_fact`` always answered, the answer for a Personal FACT: the personal agent (the One family) only; a Personal
    preference (or any line that reads as one) is read by every subject, whatever this returns. Switch ON
    (``stores.user_identity.readers.preferenceAfterWorkspaceRules`` is ``one-family-only``, also when the file has no such key): the answer is for
    EVERY Personal line, a preference included: only the One family AND the host's flag (``personal_flag``: the desktop started this executor for the
    personal agent's own conversation) may read it. Without a usable ``stores`` block nobody is held back (``active()``).
    The preference reader of ``readers.preference`` stays ``all-subjects``: only the switch narrows it."""
    from .memory_actor_family import is_one_memory_actor
    rs = active(rs)   # the given ruleset when its ``stores`` block is usable, else None (``active()`` with no argument loads the installed one)
    if rs is None:
        return True
    readers = _stores(rs)["user_identity"].get("readers") or {}
    if rules_on and readers.get("preferenceAfterWorkspaceRules", ONE_FAMILY_ONLY) == ONE_FAMILY_ONLY:
        return is_one_memory_actor(actor_id) and bool(personal_flag)
    return True if readers.get("fact", ONE_FAMILY_ONLY) != ONE_FAMILY_ONLY else is_one_memory_actor(actor_id)


def personal_hidden_scope(rs: dict[str, Any] | None, rules_on: bool) -> str:
    """What a subject that may not read Personal lines is held back from: ``"all"`` (every ``user_identity`` line; the switch is on and the file
    narrows preferences too) or ``"fact"`` (the facts only; the switch is off, as before 1.7.0)."""
    rs = active(rs)
    readers = (_stores(rs)["user_identity"].get("readers") or {}) if rs is not None else {}
    return "all" if rules_on and readers.get("preferenceAfterWorkspaceRules", ONE_FAMILY_ONLY) == ONE_FAMILY_ONLY else "fact"


def hidden_personal_sql(actor_id: str | None, alias: str = "m", rs: dict[str, Any] | None = None, rules_on: bool = False,
                        personal_flag: bool = False) -> str:
    """The ``AND NOT (...)`` piece for a subject that may not read Personal lines, else ``""``: with the switch off the facts
    (``" AND NOT (<alias>.scope='user_identity' AND <alias>.kind='fact')"``, byte for byte what 1.6.1 built), with it on every ``user_identity`` line."""
    if reads_personal(actor_id, rs, rules_on, personal_flag):
        return ""
    if personal_hidden_scope(rs, rules_on) == "all":
        return f" AND NOT ({alias}.scope='user_identity')"
    return f" AND NOT ({alias}.scope='user_identity' AND {alias}.kind='fact')"


def personal_visible(scope: Any, kind: Any, actor_id: str | None, rs: dict[str, Any] | None = None, rules_on: bool = False,
                     personal_flag: bool = False) -> bool:
    """The same condition for one line already read (a ``scope`` and ``kind``)."""
    if scope != "user_identity":
        return True
    if personal_hidden_scope(rs, rules_on) == "fact" and kind != "fact":
        return True
    return reads_personal(actor_id, rs, rules_on, personal_flag)


def hidden_personal_fact_sql(actor_id: str | None, alias: str = "m", rs: dict[str, Any] | None = None) -> str:
    """Alias of ``hidden_personal_sql`` with the switch off (kept one release)."""
    return hidden_personal_sql(actor_id, alias, rs, False, False)


def personal_fact_visible(scope: Any, kind: Any, actor_id: str | None, rs: dict[str, Any] | None = None) -> bool:
    """Alias of ``personal_visible`` with the switch off (kept one release)."""
    return personal_visible(scope, kind, actor_id, rs, False, False)


def personal_always(rows: list[tuple[Any, ...]], rs: dict[str, Any] | None) -> list[tuple[Any, ...]]:
    """The owner's Personal preference lines a turn always carries: newest first up to ``alwaysLoad.hookPersonalFirstChars``
    characters and ``hookPersonalFirstMaxLines`` lines, then written in id order (the same text every turn while the lines are unchanged).
    A row is ``(id, kind, content, created_at, scope)``; a row without a scope is never Personal. Empty without a usable ruleset."""
    if rs is None:
        return []
    block = _stores(rs)["user_identity"]
    always = block.get("alwaysLoad") if isinstance(block.get("alwaysLoad"), dict) else {}
    budget = always.get("hookPersonalFirstChars")
    max_lines = _count(always.get("hookPersonalFirstMaxLines"))
    line_max = always.get("maxLineChars")
    kinds = always.get("kinds") if isinstance(always.get("kinds"), list) else ["preference"]
    if not isinstance(budget, int) or isinstance(budget, bool) or budget <= 0 or not isinstance(line_max, int):
        return []
    picked: list[tuple[Any, ...]] = []
    used = 0
    for row in sorted(rows, key=lambda r: (str(r[3]), str(r[0])), reverse=True):
        if max_lines is not None and len(picked) >= max_lines:
            break
        if (len(row) > 4 and row[4] == "user_identity" and read_kind(rs, "user_identity", str(row[1])) in kinds
                and isinstance(row[2], str) and 0 < len(row[2]) <= line_max and used + len(row[2]) <= budget):
            picked.append(row)
            used += len(row[2])
    return sorted(picked, key=lambda r: str(r[0]))


def personal_first(rows: list[tuple[Any, ...]], rs: dict[str, Any] | None, *, limit: int) -> list[tuple[Any, ...]]:
    """The hook's order (section 12-6): the owner's Personal preference lines first (``personal_always``), then the
    other lines newest first; at most ``limit`` lines. A row is ``(id, kind, content, created_at[, scope])``; a row without a scope
    column is never Personal. Without a usable ruleset the rows come back as they were (newest first)."""
    newest = sorted(rows, key=lambda r: (str(r[3]), str(r[0])), reverse=True)
    picked = personal_always(rows, rs)
    if not picked:
        return newest[:limit]
    picked_ids = {row[0] for row in picked}
    rest = [row for row in newest if row[0] not in picked_ids]
    always = _stores(rs)["user_identity"].get("alwaysLoad") or {}
    if _count(always.get("hookPersonalFirstMaxLines")) is None:
        return (picked + rest)[:limit]
    # flaw 8: the Personal preferences that did not make the first group (too many lines or characters) must not take
    # every other slot just because they are the newest: project and agent lines come first, the rest of the slots go to them.
    kinds = always.get("kinds") if isinstance(always.get("kinds"), list) else ["preference"]
    line_max = always.get("maxLineChars")

    def personal(row: tuple[Any, ...]) -> bool:
        return (len(row) > 4 and row[4] == "user_identity" and read_kind(rs, "user_identity", str(row[1])) in kinds
                and isinstance(row[2], str) and 0 < len(row[2]) <= line_max)

    others = [row for row in rest if not personal(row)]
    left = [row for row in rest if personal(row)]
    return (picked + others + left)[:limit]
