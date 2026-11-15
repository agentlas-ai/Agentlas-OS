"""Agentlas 2.0: the ticket receiver (memory write v2). Pure functions: no model, store, clock or file IO.

A ticket is one memory write that the model doing the work makes itself: add a line, rewrite one shown line, condense several shown
lines into one, or remove a shown line. This module is the engine's reference for contracts/test-vectors/memory-ticket-v2-vectors.json:
``receive_tickets(raw, host)`` takes the tool call (1-5 tickets) and the host's FACTS (which conversation, who wrote the turn, whether
a project is bound, what the owner wrote, whether tools or attachments put text in the turn, a verification receipt, the lines the
model could see) and answers, per ticket, whether it is saved and what exactly would be written. Nothing calls it yet: the desktop
('), the engine writer (') and the server (TA1') will, and the desktop and web ports must give the SAME answers on the shared
vectors. The tables below equal ``ticket.*`` in system-agents/curator-ruleset.json (a test pins that).

Rules that never change:
- No word list decides whether something is "a request to remember". The host's facts decide where a line may go and how it is
  labelled; the model decides what is worth writing.
- Four refusals only: a secret (``secret_like``), something about the person that they did not say (``not_said``: an instruction, or an inferred Personal fact), a memory this conversation
  may not write (``not_here``), a permission (``needs_approval``). Everything else is accepted with the source written down lower.
- Each ticket is received alone. A wrong ticket is corrected when the correction cannot change its meaning (the five kind lines, an
  alias, a default) and otherwise dropped alone with a code that is counted. Nothing asks the model again and nothing stops the turn.
- The model's ``source`` is only ever lowered by the host (said -> observed or inferred), never raised.
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any

TICKET_SCHEMA = "agentlas.memory-ticket.v2"
RECEIPT_SCHEMA = "agentlas.memory-ticket-receipt.v2"
INPUT_SCHEMA = "agentlas.memory-curation-input.v2"

MAX_TICKETS = 5
ACTIONS = ("add", "rewrite", "condense", "remove")
TARGET_COUNTS = {"add": (0, 0), "rewrite": (1, 1), "condense": (2, 8), "remove": (1, 8)}
SCOPES = ("user_identity", "project", "agent_repo")
KINDS = {"user_identity": ("identity", "preference", "fact", "boundary"),
         "agent_repo": ("procedure", "risk", "fact"),
         "project": ("fact", "decision", "procedure", "risk")}
LINE_MAX = {"user_identity": 200, "agent_repo": 600, "project": 600}
KIND_FIX = (("user_identity", "procedure", "preference"), ("user_identity", "decision", "preference"),
            ("user_identity", "risk", "boundary"), ("project", "preference", "decision"), ("agent_repo", "decision", "procedure"))
COMPUTER_FOLD = {"identity": "fact", "boundary": "preference"}
INSTRUCTION_KINDS = ("preference", "boundary")
PERSONAL_FACT_KINDS = ("identity", "fact")
TEXT_MIN = 4
NATIVE_MAX = 1200
NON_ENGLISH_MAX_RATIO = 0.3
WHYS = ("changed", "corrected")

CONVERSATIONS = ("personal_agent", "server_home", "work_session", "outside_window", "folder_agent", "guest")
TURN_SOURCES = ("owner", "chain", "session_message", "automation")
_WORK = {"user_identity": "not_here", "project": "project_if_bound", "agent_repo": "project_if_bound_else_worker"}
ROUTES = {
    "personal_agent": {"user_identity": "personal", "project": "project_if_bound", "agent_repo": "project_if_bound_else_worker"},
    "server_home": {"user_identity": "card", "project": "not_here", "agent_repo": "not_here"},
    "work_session": dict(_WORK),
    "outside_window": dict(_WORK),
    "folder_agent": {"user_identity": "not_here", "project": "project_if_bound", "agent_repo": "agent"},
    "guest": {"user_identity": "not_here", "project": "not_here", "agent_repo": "not_here"},
}
SOURCES = ("said", "seen", "did", "inferred")
ORIGIN_OF_SOURCE = {"said": "user", "seen": "observed", "did": "result", "inferred": "inferred"}
REFUSED = ("secret_like", "not_said", "not_here", "needs_approval")
INVALID = ("not_an_object", "text_missing", "action_unknown", "scope_unknown", "kind_unknown", "kind_not_in_store", "text_too_short",
           "text_too_long", "host_path", "targets_count", "target_unknown", "target_scope", "targets_mixed_kind", "over_limit")
RESULTS = ("saved", "merged", "rewritten", "condensed", "removed")
CARD_REGEX = r"(?<![0-9])[0-9](?:[ -]?[0-9]){14,15}(?![0-9])"

_ACTION_ALIASES = {
    "add": "add", "new": "add", "create": "add", "save": "add", "write": "add", "store": "add", "insert": "add",
    "rewrite": "rewrite", "update": "rewrite", "replace": "rewrite", "edit": "rewrite", "change": "rewrite", "supersede": "rewrite",
    "condense": "condense", "merge": "condense", "consolidate": "condense", "combine": "condense", "summarize": "condense",
    "remove": "remove", "delete": "remove", "forget": "remove", "drop": "remove",
}
_SCOPE_ALIASES = {"person": "user_identity", "personal": "user_identity", "user": "user_identity", "owner": "user_identity",
                  "agentrepo": "agent_repo", "agent": "agent_repo", "agents": "agent_repo", "agent_repository": "agent_repo",
                  "craft": "agent_repo", "worker": "agent_repo", "projects": "project", "sessions": "session"}
_KIND_ALIASES = {"identities": "identity", "preferences": "preference", "facts": "fact", "boundaries": "boundary",
                 "decisions": "decision", "procedures": "procedure", "risks": "risk"}
_SOURCE_ALIASES = {"said": "said", "user": "said", "owner": "said", "owner_said": "said", "told": "said",
                   "seen": "seen", "observed": "seen", "saw": "seen", "tool": "seen", "file": "seen", "image": "seen", "picture": "seen",
                   "did": "did", "done": "did", "result": "did", "action": "did",
                   "inferred": "inferred", "guess": "inferred", "derived": "inferred", "assumed": "inferred"}
_WHY_ALIASES = {"changed": "changed", "change": "changed", "update": "changed", "updated": "changed", "new": "changed",
                "corrected": "corrected", "correction": "corrected", "fix": "corrected", "wrong": "corrected",
                "mistake": "corrected", "error": "corrected"}
_WRAPPERS = ("result", "output", "ticket", "response", "answer", "data", "arguments", "args", "input", "params")
_TICKETS_KEYS = ("tickets", "items", "memories", "entries", "lines", "results")
_TICKET_KEYS = {
    "action": ("op", "operation"),
    "targets": ("target", "target_ids", "ids", "replaces"),
    "why": ("reason",),
    "scope": ("about", "store", "memory"),
    "kind": ("category",),
    "text": ("memory", "content", "note", "summary", "statement", "line"),
    "en": ("english", "text_en", "content_en"),
    "source": ("origin", "from"),
    "quote": ("evidence", "owner_quote"),
    "permission": ("approval", "without_asking"),
}
_TRUE_TEXT = frozenset({"true", "yes", "y", "1"})

_EDGE = " \t\r\n.,;:!?\"'`()[]{}*"
_SEPARATORS = re.compile(r"[ \t\r\n\f\v\-]+")
_SPACES = re.compile(r"[ \t\r\n\f\v 　]+")
_FENCE = re.compile(r"```[A-Za-z0-9_-]*[ \t]*\r?\n?(.*?)```", re.S)
_ID_HEAD = re.compile(r"^\s*\[?\s*([^\s\]\[·|,;]+)")

_NON_LATIN_RANGES = ((0x0370, 0x03FF), (0x0400, 0x04FF), (0x0590, 0x05FF), (0x0600, 0x06FF), (0x0900, 0x097F),
                     (0x0E00, 0x0E7F), (0x1100, 0x11FF), (0x3040, 0x30FF), (0x3130, 0x318F), (0x3400, 0x4DBF),
                     (0x4E00, 0x9FFF), (0xAC00, 0xD7A3))

DEFAULT_HOST: dict[str, Any] = {"conversation": "guest", "turn_source": "unknown", "project_bound": False, "owner_text": None,
                                "outside_text": True, "tools_ran": False, "receipt": False, "visible": []}


# ---------------------------------------------------------------- small helpers

def _token(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return _SEPARATORS.sub("_", value.strip(_EDGE).lower()) or None


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _chars(text: str) -> int:
    return len(text)


def non_english(text: str) -> bool:
    latin = other = 0
    for char in text:
        code = ord(char)
        if (0x41 <= code <= 0x5A) or (0x61 <= code <= 0x7A) or (0xC0 <= code <= 0x24F and code not in (0xD7, 0xF7)):
            latin += 1
        elif any(low <= code <= high for low, high in _NON_LATIN_RANGES):
            other += 1
    return other + latin > 0 and other / (other + latin) > NON_ENGLISH_MAX_RATIO


def normalize(text: str) -> str:
    """Whitespace collapsed to one space, trimmed, lower-cased: how two lines (or a quote and the owner's text) are compared."""
    return _SPACES.sub(" ", text).strip(" ").lower()


def _rule_hit(text: str, names: tuple[str, ...]) -> bool:
    from .one_workspace import _rule_re
    return any(_rule_re(name).search(text) for name in names)


def luhn_ok(digits: str) -> bool:
    total, flip = 0, False
    for char in reversed(digits):
        number = ord(char) - 48
        if flip:
            number *= 2
            if number > 9:
                number -= 9
        total += number
        flip = not flip
    return total % 10 == 0


def _card_hit(text: str) -> bool:
    for match in re.finditer(CARD_REGEX, text):
        digits = re.sub(r"[ -]", "", match.group(0))
        if 15 <= len(digits) <= 16 and luhn_ok(digits):
            return True
    return False


def secret_like(*texts: str | None) -> bool:
    """A key=value secret, a credential shape (the shared patterns) or a card number (15-16 digits that pass the Luhn check)."""
    for text in texts:
        if text and (_rule_hit(text, ("secretKeyValue", "secretValueShapes")) or _card_hit(text)):
            return True
    return False


# ---------------------------------------------------------------- reading the tool call

def _extract(raw: Any) -> Any:
    """The first JSON object or array in a reply: the value itself, the whole text, a code fence, or text around it."""
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str):
        return None
    text = raw.lstrip("﻿").strip()
    try:
        value = json.loads(text)
        if isinstance(value, (dict, list)):
            return value
    except ValueError:
        pass
    for match in _FENCE.finditer(text):
        try:
            value = json.loads(match.group(1).strip())
        except ValueError:
            continue
        if isinstance(value, (dict, list)):
            return value
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value = decoder.raw_decode(text[start:])[0]
            if isinstance(value, dict):
                return value
        except ValueError:
            pass
        start = text.find("{", start + 1)
    start = text.find("[")
    while start != -1:
        try:
            value = decoder.raw_decode(text[start:])[0]
            if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
                return value
        except ValueError:
            pass
        start = text.find("[", start + 1)
    return None


def _keys(obj: dict[Any, Any]) -> dict[str, Any]:
    named: dict[str, Any] = {}
    for key, value in obj.items():
        name = _token(key)
        if name is not None and name not in named:
            named[name] = value
    return named


def _tickets_of(raw: Any) -> tuple[list[Any], str | None]:
    """(raw tickets, an unreadable code or None). A list, {tickets: [...]}, a wrapped call, or one bare ticket."""
    value = _extract(raw)
    if value is None:
        return [], "not_json"
    for _ in range(2):
        if isinstance(value, dict) and len(value) == 1:
            only = next(iter(value))
            if _token(only) in _WRAPPERS and isinstance(value[only], (dict, list)):
                value = value[only]
    if isinstance(value, list):
        return value, None
    named = _keys(value)
    for name in _TICKETS_KEYS:
        if name in named:
            found = named[name]
            if found is None:
                return [], None
            if isinstance(found, list):
                return found, None
            if isinstance(found, dict):
                return [found], None
            return [], "tickets_not_list"
    if any(name in named for name in ("scope", "text", "en", "action", "kind")) or any(
            alias in named for alias in _TICKET_KEYS["text"] + _TICKET_KEYS["scope"]):
        return [value], None
    return [], None if not value else "unrecognized_shape"


def _field(named: dict[str, Any], name: str) -> Any:
    if name in named:
        return named[name]
    for alias in _TICKET_KEYS[name]:
        if alias in named:
            return named[alias]
    return None


def _enum(value: Any, aliases: dict[str, str], allowed: tuple[str, ...]) -> str | None:
    token = _token(value)
    token = aliases.get(token, token) if token is not None else None
    return token if token in allowed else None


def _text_of(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _ids(value: Any) -> tuple[list[str], bool]:
    """(ids in order without repeats, whether anything was dropped or repeated)."""
    if value is None:
        return [], False
    items = value if isinstance(value, list) else [value]
    found: list[str] = []
    changed = False
    for item in items:
        ident = None
        if isinstance(item, bool):
            ident = None
        elif isinstance(item, int):
            ident = str(item)
        elif isinstance(item, str):
            match = _ID_HEAD.match(item)
            ident = match.group(1) if match else None
        if ident is None:
            changed = True
        elif ident in found:
            changed = True
        else:
            found.append(ident)
    return found, changed


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_TEXT
    return False


# ---------------------------------------------------------------- the host facts

def _host(raw: Any) -> dict[str, Any]:
    source = raw if isinstance(raw, dict) else {}
    conversation = source.get("conversation")
    turn = source.get("turn_source")
    owner_text = source.get("owner_text")
    visible: dict[str, dict[str, Any]] = {}
    for line in source.get("visible") or []:
        if not isinstance(line, dict) or not isinstance(line.get("id"), str) or line.get("forgotten") or line.get("superseded"):
            continue
        visible[line["id"]] = line
    return {"conversation": conversation if conversation in CONVERSATIONS else "guest",
            "turn_source": turn if turn in TURN_SOURCES else "unknown",
            "project_bound": source.get("project_bound") is True,
            "owner_text": owner_text if isinstance(owner_text, str) else None,
            "outside_text": source.get("outside_text") is not False,
            "tools_ran": source.get("tools_ran") is True,
            "receipt": source.get("receipt") is True,
            "visible": visible}


def _route(host: dict[str, Any], scope: str) -> tuple[str, str] | None:
    """(final scope, store) or None when this conversation may not write that memory."""
    rule = ROUTES[host["conversation"]][scope]
    owner = host["turn_source"] == "owner"
    if rule in ("personal", "card"):
        return ("user_identity", rule) if owner else None
    if rule == "project_if_bound":
        return ("project", "project") if host["project_bound"] else None
    if rule == "project_if_bound_else_worker":
        return ("project", "project") if host["project_bound"] else ("agent_repo", "worker")
    if rule == "agent":
        return ("agent_repo", "agent")
    return None


def _origin(source: str | None, host: dict[str, Any], quote: str | None) -> str:
    """origin_class. The model's claim is only ever lowered."""
    if source == "said":
        if host["turn_source"] != "owner":
            return "inferred"
        if not host["outside_text"]:
            return "user"
        found = bool(quote) and host["owner_text"] is not None and normalize(quote) != "" and normalize(quote) in normalize(host["owner_text"])
        return "user" if found else "observed"
    if source == "seen":
        return "observed"
    if source == "did":
        return "result" if host["tools_ran"] else "inferred"
    return "inferred"


def _certainty(origin: str, host: dict[str, Any]) -> str:
    if origin == "user":
        return "self_reported"
    if origin == "result" and host["receipt"]:
        return "run_verified"
    return "unverified"


# ---------------------------------------------------------------- one ticket

class _Stop(Exception):
    def __init__(self, status: str, why: str, limit: dict[str, int] | None = None) -> None:
        super().__init__(why)
        self.status, self.why, self.limit = status, why, limit  # limit: the numbers the model needs to write the ticket again once


def _effective_kind(line: dict[str, Any]) -> str:
    return line.get("ticket_kind") or line.get("kind")


def _receive_one(raw: Any, host: dict[str, Any], batch: dict[tuple, int]) -> dict[str, Any]:
    fixes: list[str] = []
    if not isinstance(raw, dict):
        raise _Stop("invalid", "not_an_object")
    named = _keys(raw)
    text = _text_of(_field(named, "text"))
    en = _text_of(_field(named, "en"))
    quote = _text_of(_field(named, "quote"))
    action_raw = _field(named, "action")
    ids, ids_changed = _ids(_field(named, "targets"))
    if ids_changed:
        fixes.append("targets_cleaned")
    action = _enum(action_raw, _ACTION_ALIASES, ACTIONS)
    if action is None:
        if action_raw is not None and not (isinstance(action_raw, str) and not action_raw.strip()):
            raise _Stop("invalid", "action_unknown")
        action = "add" if not ids else ("rewrite" if len(ids) == 1 else "condense")
        fixes.append("action_defaulted")
    elif action != action_raw:
        fixes.append("action_normalized")
    if text is None and en is None and action != "remove":
        raise _Stop("invalid", "text_missing")
    # the first refusal: a secret is refused wherever it is
    if secret_like(text, en, quote):
        raise _Stop("refused", "secret_like")
    # scope
    scope_raw = _field(named, "scope")
    scope_token = _token(scope_raw)
    scope_token = _SCOPE_ALIASES.get(scope_token, scope_token) if scope_token is not None else None
    if scope_token == "session":
        raise _Stop("refused", "not_here")
    visible = host["visible"]
    if action == "remove":
        known = [visible[i] for i in ids if i in visible]
        if scope_token not in SCOPES and known and len({line.get("scope") for line in known}) == 1 and known[0].get("scope") in SCOPES:
            scope_token = known[0]["scope"]
            fixes.append("scope_from_target")
    if scope_token not in SCOPES:
        raise _Stop("invalid", "scope_unknown")
    if scope_raw is not None and scope_token != scope_raw:
        fixes.append("scope_normalized")
    scope = scope_token
    if _truthy(_field(named, "permission")):
        raise _Stop("refused", "needs_approval")
    # the owner table: where this conversation may write
    if action == "remove":
        if host["conversation"] == "guest":
            raise _Stop("refused", "not_here")
        final, store = scope, None
    else:
        routed = _route(host, scope)
        if routed is None:
            raise _Stop("refused", "not_here")
        final, store = routed
        if final != scope:
            fixes.append("moved")
    # the two columns
    source = _enum(_field(named, "source"), _SOURCE_ALIASES, SOURCES)
    if source is None:
        fixes.append("source_defaulted")
    origin = _origin(source, host, quote)
    if source is not None and origin != ORIGIN_OF_SOURCE[source]:
        fixes.append("source_lowered")
    certainty = _certainty(origin, host)
    # the kind
    kind_raw = _field(named, "kind")
    kind = None
    kind_given = _token(kind_raw)
    if kind_given is not None:
        kind_given = _KIND_ALIASES.get(kind_given, kind_given)
    marks: list[str] = []
    if action == "remove":
        kind = None
    else:
        every = {k for kinds in KINDS.values() for k in kinds}
        if kind_given is None:
            kind = "fact"
            fixes.append("kind_defaulted")
        elif kind_given not in every:
            raise _Stop("invalid", "kind_unknown")
        elif kind_given in KINDS[final]:
            kind = kind_given
        else:
            kind = next((to for sc, frm, to in KIND_FIX if sc == final and frm == kind_given), None)
            if kind is None and final == "agent_repo" and host["conversation"] == "folder_agent" and origin == "user" and kind_given in INSTRUCTION_KINDS:
                kind = "procedure"
            if kind is None:
                raise _Stop("invalid", "kind_not_in_store")
            fixes.append("kind_remapped")
        if final == "agent_repo" and host["conversation"] == "folder_agent" and origin == "user" and kind == "procedure":
            marks.append("owner_instruction")
    # an instruction that the owner did not say
    if action == "remove" and origin != "user":
        raise _Stop("refused", "not_said")
    if action != "remove":
        wrote_instruction = (kind_given in INSTRUCTION_KINDS) or (kind in INSTRUCTION_KINDS)
        if wrote_instruction and origin != "user":
            raise _Stop("refused", "not_said")
        if origin != "user" and _rule_hit(en or text or "", ("imperative",)):
            raise _Stop("refused", "not_said")
        # a guess about the person is not a fact about the person (owner reference case 3,' ruling): a Personal identity or fact line
        # whose origin is inferred is refused; "what the person did not say" is the same closed word as an instruction they did not say
        if final == "user_identity" and kind in PERSONAL_FACT_KINDS and origin == "inferred":
            raise _Stop("refused", "not_said")
    # the words of the line
    line_text: str | None = None
    native: str | None = None
    if action != "remove":
        if en is not None and non_english(en):
            fixes.append("en_not_english")
            if text is None:
                text = en
            en = None
        if en is not None and text is not None and normalize(en) == normalize(text):
            text = None
            fixes.append("text_same_as_en")
        if en is None:
            line_text, native = text, None
        else:
            line_text, native = en, text
        if native is not None and _chars(native) > NATIVE_MAX:
            native = None
            fixes.append("text_dropped_too_long")
        assert line_text is not None
        if _chars(line_text) < TEXT_MIN:
            raise _Stop("invalid", "text_too_short", {"min": TEXT_MIN, "chars": _chars(line_text)})
        if _chars(line_text) > LINE_MAX[final] and en is not None and text is not None and _chars(text) <= LINE_MAX[final]:
            # The English wording is an optional field (the model's or the host's); it is longer than the line limit but the person's own words are not. The
            # person's line is kept as it was said and the English is dropped (a Korean line of 150 characters is 230 in English and was refused).
            line_text, native = text, None
            fixes.append("en_dropped_too_long")
        if _chars(line_text) > LINE_MAX[final]:
            raise _Stop("invalid", "text_too_long", {"max": LINE_MAX[final], "chars": _chars(line_text)})
        if _rule_hit(line_text, ("hostAbsolutePath",)) or (native is not None and _rule_hit(native, ("hostAbsolutePath",))):
            raise _Stop("invalid", "host_path")
    # the targets
    why = None
    if action == "rewrite":
        why_raw = _field(named, "why")
        why = _enum(why_raw, _WHY_ALIASES, WHYS)
        if why is None:
            why = "changed"
            if why_raw is not None:
                fixes.append("why_defaulted")
        elif why != why_raw:
            fixes.append("why_normalized")
    elif _field(named, "why") is not None:
        fixes.append("why_ignored")
    if action == "add" and ids:
        ids = []
        fixes.append("targets_ignored")
    if action == "condense" and len(ids) == 1:
        action = "rewrite"
        why = "changed"
        fixes.append("condense_one_to_rewrite")
    low, high = TARGET_COUNTS[action]
    if not low <= len(ids) <= high:
        raise _Stop("invalid", "targets_count", {"min": low, "max": high, "got": len(ids)})
    lines = []
    for ident in ids:
        line = visible.get(ident)
        if line is None:
            raise _Stop("invalid", "target_unknown")
        if line.get("scope") != final:
            raise _Stop("invalid", "target_scope")
        lines.append(line)
    if action == "condense" and final == "user_identity" and len({_effective_kind(line) for line in lines}) != 1:
        raise _Stop("invalid", "targets_mixed_kind")
    if action == "condense" and final == "user_identity" and kind != _effective_kind(lines[0]):
        kind = _effective_kind(lines[0])
        fixes.append("kind_from_targets")
    # what the store keeps
    store_kind = kind
    context: dict[str, Any] | None = None
    if kind is not None and store == "personal" and kind in COMPUTER_FOLD:
        store_kind = COMPUTER_FOLD[kind]
        context = {"ticket_kind": kind}
        fixes.append("folded")
    result: dict[str, Any] = {"status": "ok", "result": None, "why": None, "ask_owner": None, "scope": final, "kind": kind,
                              "store": store, "line": None, "targets": ids, "merge_into": None, "same_as_ticket": None, "fixes": fixes}
    if action == "remove":
        result.update(result="removed", kind=None, targets=ids, scope=final)
        return result
    line_out: dict[str, Any] = {"scope": final, "kind": kind, "store_kind": store_kind, "text": line_text, "native": native,
                                "origin_class": origin, "certainty": certainty, "replaces": [], "contradicts": [], "why": None,
                                "marks": marks, "context": context, "carry_evidence_from": []}
    if final != scope:
        line_out["moved_from"] = scope
    key = (final, store_kind, normalize(line_text))
    user_targets = [line["id"] for line in lines if line.get("origin_class") == "user"]
    if action in ("rewrite", "condense") and origin != "user" and user_targets:
        # an owner's line is never replaced by something the owner did not say: both stay and the owner is asked once
        line_out["contradicts"] = user_targets
        result.update(result="saved", ask_owner="conflict", targets=[], line=line_out)
        fixes.append("replace_refused_owner_line")
        return result
    if action == "add":
        for line in visible.values():
            if line.get("scope") == final and (line.get("kind") == store_kind) and normalize(str(line.get("text") or "")) == key[2]:
                result.update(result="merged", merge_into=line["id"], line=None, targets=[], kind=kind)
                return result
        if key in batch:
            result.update(result="merged", same_as_ticket=batch[key], line=None, targets=[])
            return result
        result.update(result="saved", line=line_out)
        return result
    if action == "rewrite":
        target = lines[0]
        if (target.get("kind") == store_kind and normalize(str(target.get("text") or "")) == key[2]
                and _effective_kind(target) == kind):
            result.update(result="merged", merge_into=target["id"], line=None, targets=[])
            return result
        line_out.update(replaces=ids, why=why)
        result.update(result="rewritten", line=line_out)
        return result
    line_out.update(replaces=ids)
    if final == "user_identity":
        line_out["carry_evidence_from"] = ids
    result.update(result="condensed", line=line_out)
    return result


def _answer(item: dict[str, Any]) -> dict[str, Any]:
    """What the tool answers the model for one ticket: ok + result + scope + kind (+ ask_owner), or refused/invalid + why."""
    if item["status"] != "ok":
        return {"status": item["status"], "why": item["why"], **(item.get("limit") or {})}
    answer: dict[str, Any] = {"status": "ok", "result": item["result"], "scope": item["scope"], "kind": item["kind"]}
    if item["merge_into"] is not None:
        answer["id"] = item["merge_into"]
    elif item["result"] == "removed" and item["targets"]:
        answer["id"] = item["targets"][0]
    if item["ask_owner"]:
        answer["ask_owner"] = item["ask_owner"]
    return answer


def receive_tickets(raw: Any, host: dict[str, Any] | None = None) -> dict[str, Any]:
    """Receive one memory_ticket call. Never raises.

    raw: the tool input ({"tickets": [...]}, a bare list or one ticket, or a text that holds one of them).
    host: {conversation, turn_source, project_bound, owner_text, outside_text, tools_ran, receipt, visible}; see ROUTES and.
    Returns {schema, items, answers, counts, unreadable}; items[i] is {status: ok | refused | invalid, result, why, ask_owner, scope, kind,
    store, line, targets, merge_into, same_as_ticket, fixes}. Each ticket is received alone: a wrong one is dropped alone and counted."""
    facts = _host(host)
    tickets, unreadable = _tickets_of(raw)
    items: list[dict[str, Any]] = []
    batch: dict[tuple, int] = {}
    for index, ticket in enumerate(tickets):
        base = {"status": "invalid", "result": None, "why": None, "ask_owner": None, "scope": None, "kind": None, "store": None,
                "line": None, "targets": [], "merge_into": None, "same_as_ticket": None, "fixes": []}
        try:
            if index >= MAX_TICKETS:
                raise _Stop("invalid", "over_limit", {"max": MAX_TICKETS})
            item = _receive_one(ticket, facts, batch)
            if item["line"] is not None:
                batch[(item["line"]["scope"], item["line"]["store_kind"], normalize(item["line"]["text"]))] = index
        except _Stop as stop:
            item = dict(base, status=stop.status, why=stop.why)
            if stop.limit:
                item["limit"] = dict(stop.limit)
        except Exception:  # noqa: BLE001 - receiving never raises: an unreadable ticket is dropped alone
            item = dict(base, status="invalid", why="not_an_object")
        item["index"] = index
        items.append(item)
    by_code: dict[str, int] = {}
    for item in items:
        if item["status"] != "ok":
            by_code[item["why"]] = by_code.get(item["why"], 0) + 1
    counts = {"received": len(items), "ok": sum(1 for i in items if i["status"] == "ok"),
              "refused": sum(1 for i in items if i["status"] == "refused"),
              "invalid": sum(1 for i in items if i["status"] == "invalid"),
              "fixed": sum(1 for i in items if i["status"] == "ok" and i["fixes"]), "by_code": by_code}
    return {"schema": RECEIPT_SCHEMA, "items": items, "answers": [_answer(i) for i in items], "counts": counts, "unreadable": unreadable}


# ---------------------------------------------------------------- the input of a gathering call (kept from nothing reads it yet)

_INPUT_CAPS = {"request": 600, "summary": 360, "extract": 400}
RELATED_MAX = 8
RELATED_CONTENT_MAX = 300
INPUT_MAX_BYTES = 8000
_FIT_STEPS = (
    ("extract", "clear", None, False, False),
    ("related", "cut", 150, False, False),
    ("request", "cut", 200, False, False),
    ("summary", "cut", 160, False, False),
    ("turn", "drop", None, True, True),
    ("turn", "drop", None, False, True),
)


def _cut(text: str, limit: int) -> str:
    return text[:limit]


def _size(packet: dict[str, Any]) -> int:
    return len(canonical_json(packet).encode("utf-8"))


def fit_input(packet: dict[str, Any], max_bytes: int = INPUT_MAX_BYTES) -> dict[str, Any]:
    """Make an input v2 packet fit max_bytes, cutting the least useful text first (curator.input.fitSteps).

    Field maxima are applied first (not counted as a cut). Returns {packet, bytes, omitted}."""
    work = copy.deepcopy(packet)
    for turn in work.get("turns", []):
        for name, limit in _INPUT_CAPS.items():
            if isinstance(turn.get(name), str):
                turn[name] = _cut(turn[name], limit)
    related = work.get("related") or []
    work["related"] = related[:RELATED_MAX]
    for line in work["related"]:
        if isinstance(line.get("content"), str):
            line["content"] = _cut(line["content"], RELATED_CONTENT_MAX)
    work.setdefault("omitted", 0)
    for step, action, chars, keep_owner, keep_newest in _FIT_STEPS:
        if _size(work) <= max_bytes:
            break
        if step == "related":
            for line in reversed(work["related"]):
                if _chars(line.get("content", "")) > chars:
                    line["content"] = _cut(line["content"], chars)
                    if _size(work) <= max_bytes:
                        break
        elif step == "turn":
            owner = set((work.get("boundary") or {}).get("owner_spoke_turns") or [])
            for turn in list(work["turns"]):
                if _size(work) <= max_bytes:
                    break
                if keep_newest and turn is work["turns"][-1]:
                    continue
                if keep_owner and turn.get("i") in owner:
                    continue
                work["turns"].remove(turn)
                work["omitted"] += 1
        else:
            for turn in work["turns"]:
                if action == "clear" and turn.get(step):
                    turn[step] = ""
                elif action == "cut" and _chars(turn.get(step) or "") > chars:
                    turn[step] = _cut(turn[step], chars)
                else:
                    continue
                if _size(work) <= max_bytes:
                    break
    return {"packet": work, "bytes": _size(work), "omitted": work["omitted"]}


def curator_input_prompt(packet: dict[str, Any]) -> str:
    """memory.curator.input (turn-context): the fitted packet as compact JSON."""
    from .prompt_order import compose_prompt
    return compose_prompt([{"id": "memory.curator.input", "revision": 1, "stability": "turn-context",
                            "changeTriggers": ["memory-ticket", "retrieval", "owner-input"],
                            "text": canonical_json(packet)}])
