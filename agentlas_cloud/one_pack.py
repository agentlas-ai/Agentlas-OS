"""Packing the personal agent's memory, merging it into another computer's store, and deleting the old copy (Agentlas 2.0, O-M2).

Personal memory is the live ``user_identity`` rows (``memory_scopes.personal_set``). A move of the personal agent to another computer is four acts, and this
module is the only implementation of the memory part of them. Nothing here runs by itself: the desktop (``electron/one/bundle.ts``) calls the command line,
one act at a time, and every act answers with one JSON line (the last line of standard output; the ``state`` and ``reason`` decide, never the exit code).

``export``  reads the sender's root store (read-only: the file is byte-identical afterwards) and writes a small SQLite file: the live Personal rows, their
            native text, and the Personal forget stamps (hashes only). Superseded rows, forgotten rows, other agents' and projects' rows, tickets, episodes,
            checkpoints, project links and origin links are not in it. The embeddings are left out when ``--budget-bytes`` is exceeded or ``--no-embeddings``
            is given (the receiver builds them again); a bundle is never refused for its size: a store that does not fit ``--limit-bytes`` is packed newest first up to it and the rest stay on the sender (``partial``).
``check``   tells whether a bundle file is one this module can import (a code, nothing is read into the store). Given the engine copies the import will be given (``--engine``) it also says, before the commit, what the
            import would refuse before writing a line (``enginesConfirmed``, ``engines``, ``wouldRefuse``;), from the same functions the import uses.
``ready`` the same questions without a bundle, asked by the receiving computer before a move starts: engine copies (which host, which number), owner, store, original-wording table. Reads only.
``import``  merges a bundle into the receiving root. NOT ``memory_split.copy_rows`` (that one overwrites, keeps the sender's owner name and never looks at stamps).
            In order, each step safe to run again: 1. the bundle's stamps are merged into the receiver's ledger; 2. the receiver's live Personal rows that the
            stamps match (same words, one trailing mark more or less, the corrected kind) are blanked, with the older versions they replaced; 3. each incoming
            row is dropped when the receiver's ledger (the receiver's own stamps and the ones just merged) forgot its words; 4. dropped when a live Personal row
            of the receiver already says the same words; 5. ``INSERT OR IGNORE`` by id (a row of the receiver is never overwritten), with the receiver's
            owner name, and the project link, ``chat_id`` and path columns empty. Rows go in batches, one transaction each; a call that died is simply called again.
``purge``   deletes the old copies on the sender, by the list of ids it is given and nothing else (``memory_split.purge_entries``): it writes no stamp and
            touches no other row, however the words read. An id that is not a Personal row of this store is left alone and named in the answer.

An imported stamp is written with a fixed ``source_memory_id`` (``memory_stores.ONE_PACK_STAMP_SOURCE``), never with the bundle's value, and every reader of the ledger reads a stamp with that prefix as holding for
the Personal key only, whatever its number, the switch boundary or the clock. Entry checks: a bundle with more than ``STAMP_LIMIT`` stamps is invalid; an import that
would blank more than ``BLANK_LIMIT`` live Personal lines of the receiver is refused with ``blank_over_limit`` unless the caller gives that exact number (``--confirm-blank N``); an incoming line is checked like a
normal Personal write (length, accepted kind, secret shape, host path) and its evidence, context and audience columns are not taken from the bundle; a home mirror that is present but not a known value refuses the import.

The stamps' owner key is the Personal key, ``sha256("agentlas-memory-owner-v1\\0user_identity\\0shared")``: it does not depend on the device, the account or the
owner namespace, so a stamp made on one computer holds on another (pinned by a test). Stamps of agents and projects are never packed.

 (the sender of a bundle can be a compromised computer, so a bundle is hostile input): the file is opened by ``_open_bundle`` (read-only, ``trusted_schema`` off, ``cell_size_check`` on, ``DEFENSIVE`` and
views/triggers off where the Python has ``setconfig``; a bundle with a view or virtual table in place of a table this module reads, any virtual table or generated column anywhere, or more than ``BUNDLE_MAX_TABLES`` tables is
``invalid`` before any row is read or ``quick_check`` runs). Only ``id, kind, content, created_at`` (and the embedding columns, when they look like one) are taken from a line, read by name and with the text asked for by length
first; the id must fit ``memory_recall.ENTRY_ID_RE``, the date must be an ISO date not later than now, the original wording gets ``memory_runtime._safe_summary``, and a bundle with
more rows than the Personal ceiling is ``invalid`` (``too_many_rows``). Every other column of the line and the binding (confidence, sensitivity, agent, actor, curation, revision, policy) is made here, not read: a normal
write's values, the personal agent as the actor. ``import --no-stamps`` / ``export --no-stamps`` / ``check --no-stamps`` is the old-record road (a sender that is not the approved home): no stamp is carried or taken, so nothing of the receiver is blanked, and
confidence and sensitivity are not taken either (a move keeps them when they are in the closed sets of ``memory_runtime``). An import never pushes the receiver over its Personal ceiling: it takes the lines newest first and
refuses the rest as ``store_full`` (``check`` says how many in ``wouldStoreFull``); only the lines made on or after the ruleset's ``countsFrom`` count towards that ceiling on the move road (an owner's older lines all move,
the size of the file bounds the bundle), every line counts on the old-record road; a bundle file over ``BUNDLE_MAX_BYTES`` is ``invalid`` / ``too_large`` and is not opened. The
answer of the command line names what it knows in ``features`` (``no_stamps``, ``inserted_ids``) and an import lists ``insertedIds``.

Every answer that is not a success carries ``retryable`` and, when it is false, ``needs`` (``retry_hint``): whether the same call can end differently, and what must change if it cannot; the caller does not parse ``reason`` words
to decide whether to wait.

Resources: no new table or column. The bundle is a temporary file the caller owns and deletes; the engine keeps no state of its own (a lock file beside the root,
``.split.lock``, keeps two movers apart; the meta keys are untouched). No model call, no timer, no network.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import re
import shutil
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from . import long_path
from . import memory_classify
from . import memory_split as split
from . import memory_stores as ms
from .memory_actor_family import CORE_ONE_ACTOR_ID
from .memory_recall import ENTRY_ID_MAX_CHARS, ENTRY_ID_RE
from .memory_runtime import NATIVE_TABLE_DDL

SCHEMA = "agentlas.one-pack.v1"
PERSONAL_SCOPE = "user_identity"
BATCH_ROWS = 200
PURGE_BATCH = 400
PAUSE_SECONDS = split.PAUSE_SECONDS
SKIPPED_LIST_CAP = 200
BLANK_LIMIT = 20
"""An import that would blank more live Personal lines than this is refused until the caller gives the exact number (the owner has been shown it). A move of a real owner blanks the lines the owner forgot
on the old computer AND still holds here: a handful. Ceiling of a Personal store is 700 lines (``ceilingRows``), so 20 is under 3 % of a full store."""
STAMP_LIMIT = 5000
"""Most Personal stamps a bundle may carry. One stamp is one forget of a Personal line, the store holds at most 700 live lines (``ceilingRows``), so 5000 forgets is a store turned over seven times;
a normal sender is far under it (the bundle also has to fit the 8 MiB budget of the desktop). A larger ledger is a forged one: ``invalid`` (``too_many_stamps``)."""
REJECTED_IDS_CAP = 200
"""Most ids of refused lines an import answer lists (``rejectedIds``); more and ``rejectedIdsTruncated`` is true. The ids carry no text (they are hashes or the sender's own ids)."""
ENGINE_STAMP_CAPABILITY = 3
"""The ``memory_layout`` number (``agentlas_cloud/capabilities.json``) of an engine that reads a bundle stamp (``memory_stores.ONE_PACK_STAMP_SOURCE``) as Personal-only. The commit that adds the marker raises it from 2 to 3;
a copy that says less, says nothing or cannot be read reads the stamp as account-wide in a split store with no positive boundary, so an import is refused while any copy is below it (``engines_not_confirmed``).
``memory_split.MIN_ENGINE_LAYOUT_CAPABILITY`` (2, the number the layout move itself needs; every reader of the number compares with ``>=``) is not changed."""
PERSONAL_ROWS_FALLBACK = 700
"""The Personal ceiling when the ruleset cannot be read (``stores.user_identity.ceilingRows`` is 700)."""
INSERTED_IDS_CAP = 1000
"""Most ids of the lines an import added that its answer lists (``insertedIds``); more and ``insertedIdsTruncated`` is true. A bundle holds at most the Personal ceiling, so a normal import never reaches it."""
BUNDLE_MAX_BYTES = 8 * 1024 * 1024 + 64 * 1024
"""The largest bundle file ``check`` opens. The desktop's bundle is at most 8 MiB (``BUNDLE_MAX_BYTES`` of ``electron/one/bundle.ts``, the embeddings are dropped first) and it accepts 64 KiB more than that
(``too_large_unlisted``); a file over this is ``invalid`` / ``too_large`` and is never opened."""


LIMIT_100MIB = 100 * 1024 * 1024 + 64 * 1024
"""The largest size limit a caller may declare (``--limit-bytes``) for ``measure``, ``export``, ``check`` and ``import``: 100 MiB and the same 64 KiB of slack. A declared number above it is cut to it. Without a declaration the limit is still
``BUNDLE_MAX_BYTES`` (8 MiB + 64 KiB), so an older desktop, which never declares one and refuses a bundle over its own 8 MiB, is never handed a larger one; the current desktop declares ``LIMIT_100MIB`` to all four."""
KIND_TIERS = (("preference", ("preference",)), ("decision", ("decision", "procedure", "risk")), ("fact", ()))
"""What is packed first when a store does not fit: the tier of a line is its ``kind``, and a store packs tier by tier (newest ``created_at`` first, then id, inside a tier). The values are every kind a memory line is written with
(``memory_curation_decisions.KINDS``: fact, decision, preference, risk, procedure, hypothesis); the Personal store's own rules (``stores.user_identity``) accept ``preference`` and ``fact``, and correct ``decision``, ``procedure`` and ``risk`` to
``preference`` on a write, so a stored line of those three is an owner's rule or choice and goes in the second tier. ``fact``, ``hypothesis`` (which a Personal store does not take) and any value not listed go in the last tier.
There is no ``feedback`` kind in the engine. The last tier has an empty list: it is every other value."""


def kind_tier(kind: Any) -> int:
    for number, (_name, kinds) in enumerate(KIND_TIERS):
        if kind in kinds:
            return number
    return len(KIND_TIERS) - 1


def tier_order_sql() -> str:
    """The SQL expression of ``kind_tier`` for an ORDER BY: the order a bundle is packed in (``_walk_personal``) and, the same, the order a receiver places the lines of a bundle in (``import_rows``, ``check``'s ``wouldStoreFull``; E-2),
    so the lines that find no room under the receiver's ceiling are the last of the bundle's order and the same ones the sender would have left."""
    return "CASE kind " + " ".join(f"WHEN '{k}' THEN {n}" for n, (_name, kinds) in enumerate(KIND_TIERS) for k in kinds) + f" ELSE {len(KIND_TIERS) - 1} END"


def native_max_chars() -> int:
    """The longest original wording a line may carry: the longest ``content_native`` a normal write can store (the limit of ``memory_runtime._safe_summary``, which the decision validator puts on it)."""
    from .memory_runtime import SAFE_SUMMARY_MAX_CHARS
    return SAFE_SUMMARY_MAX_CHARS


CONTENT_FALLBACK_MAX_CHARS = 4000
"""The longest line text read from a bundle when the ruleset names no Personal ``maxChars`` (the limit of ``memory_runtime._safe_summary``)."""
FUTURE_SKEW = timedelta(minutes=10)
"""A line made on another computer may be a few minutes ahead of this clock; anything later is a forged date."""
BUNDLE_MAX_TABLES = 100
"""A bundle made by this module has about a dozen tables; one with more than this is not one."""
FEATURES = ["no_stamps", "inserted_ids", "store_full", "move_columns", "native_stored", "measure", "ready", "check_engines", "retry_hint", "measure_out", "partial_export", "priority_order", "limit_100mib", "receive_priority", "limit_in_answer", "ready_room", "left_reasons"]
"""What this engine's ``one_pack`` command line knows beyond the first contract (``store_full``: an import refuses the lines that do not fit under the Personal ceiling and ``check`` says how many (``wouldStoreFull``);
``move_columns``: a move keeps a line's confidence and sensitivity when they are in the closed sets, the old-record road does not; ``native_stored``: an import makes the original-wording table when the receiver has none and refuses, whole, a line whose original wording it cannot store; ``measure``: the command of that name; ``priority_order``: what is packed first is chosen by kind (``KIND_TIERS``), newest first inside a kind, and ``measure``/``export`` answer ``packedBy`` and ``leftBy``; ``receive_priority``: the same order decides which lines of a bundle find room under the receiver's Personal ceiling (``import``'s ``store_full`` and ``check``'s ``wouldStoreFull``; an engine without it takes the newest lines first whatever their kind); ``limit_100mib``: ``check`` and ``import`` take ``--limit-bytes`` too, and a declared limit is cut at ``LIMIT_100MIB`` (a caller that declares nothing gets ``BUNDLE_MAX_BYTES``, as before); ``limit_in_answer``: an ``invalid`` / ``too_large`` answer of ``check`` and ``import`` carries ``limitBytes`` (what the call can take), ``maxLimitBytes`` (the most a caller may declare) and ``bundleBytes``, and ``needs`` is ``smaller_bundle``; ``ready_room``: ``ready`` answers ``store_busy`` (``retryable``) for a store a writer holds and, given ``--need-bytes``, ``freeBytes`` / ``needBytes`` and ``disk_space_short``; ``left_reasons``: an import or purge that ends ``partial`` with ``views`` in ``left`` also answers ``leftReasons`` (``views_path_too_long`` | ``views_file_busy`` | ``views_retry``); ``partial_export``: ``export`` and ``measure`` take ``--limit-bytes`` and a store that does not fit is packed newest first up to it, the rest stay on the sender (``partial``)); every answer of the command line carries it (``features``) so a caller can tell an engine that knows ``--no-stamps`` and ``insertedIds`` from an older one
before it passes the flag. The ``memory_layout`` number (``ENGINE_STAMP_CAPABILITY``) is not changed."""
CLEAN_AUDIENCE = {"scope": "user_identity"}
SENDER_NAME = "one-pack-sender"
_NATIVE = "memory_entry_native"
_PERSONAL_KEY: str | None = None


def personal_key() -> str:
    """The revocation owner key of Personal lines: the same on every computer and under every owner namespace."""
    global _PERSONAL_KEY
    if _PERSONAL_KEY is None:
        _PERSONAL_KEY = ms.row_owner_keys({"scope": PERSONAL_SCOPE, "project_path": None, "project_id": None, "agent_id": None, "chat_id": None})[0]
    return _PERSONAL_KEY


def _json(value: Any) -> str:
    return split._json(value)


def _hash(text: str) -> str:
    from .memory_runtime import content_hash
    return content_hash(text)


def _is_personal(row: Any) -> bool:
    return row["scope"] == PERSONAL_SCOPE


def _kinds_of(rules: dict[str, Any] | None, kind: str) -> set[str]:
    """Every stored kind a stamp may carry for a Personal line of this kind (the kind as stored and the corrected kind with its equivalents)."""
    if rules is None:
        return {kind}
    corrected = memory_classify.read_kind(rules, PERSONAL_SCOPE, kind)
    return {kind, corrected, *memory_classify.equivalent_kinds(rules, PERSONAL_SCOPE, corrected)}


def _meta_set(db: sqlite3.Connection, key: str, value: str) -> None:
    db.execute("INSERT INTO memory_store_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def _ro(path: Path) -> sqlite3.Connection:
    return ms._connect_ro(path)


class _BundleRefused(ValueError):
    """A bundle file this module will not read; ``args[0]`` is the ``reason`` code."""


def personal_row_ceiling(rules: dict[str, Any] | None) -> int:
    """The most live lines a Personal store holds (the ruleset's ``ceilingRows``; 700 when the ruleset cannot be read). A bundle never has more rows than this."""
    ceiling = memory_classify.ceiling_of(rules, PERSONAL_SCOPE)
    return ceiling if ceiling is not None else PERSONAL_ROWS_FALLBACK


def counts_towards_ceiling(created_at: Any, rules: dict[str, Any] | None, every: bool = False) -> bool:
    """Whether a line meets the Personal ceiling. The ceiling counts only lines made on or after the ruleset's ``countsFrom`` (a store that already held more when the rules began is never cut: "the code never retires a
    line"), so on the MOVE road (the bundle comes from the computer the owner approved) a line dated before it does not count, in ``export``, ``check`` and ``import`` alike. ``every``: the OLD-RECORD road (a sender that is
    not trusted) counts every line, whatever its date: a forged old date must not get a line past the ceiling. A date that is not text counts (it is not provably old)."""
    if every:
        return True
    since = memory_classify.ceiling_counts_from(rules)
    return since is None or not isinstance(created_at, str) or created_at >= since


def _defend(db: sqlite3.Connection) -> None:
    """Settings of a connection that reads a file somebody else made. Each is best effort: an older sqlite or Python ignores the ones it has not got (the structure scan below does not depend on them)."""
    for pragma in ("PRAGMA trusted_schema=OFF", "PRAGMA cell_size_check=ON", "PRAGMA query_only=ON"):
        try:
            db.execute(pragma)
        except sqlite3.Error:
            pass
    setconfig = getattr(db, "setconfig", None)        # Python 3.12 and later
    if setconfig is not None:
        for name, value in (("SQLITE_DBCONFIG_DEFENSIVE", True), ("SQLITE_DBCONFIG_TRUSTED_SCHEMA", False), ("SQLITE_DBCONFIG_ENABLE_TRIGGER", False),
                            ("SQLITE_DBCONFIG_ENABLE_VIEW", False)):
            flag = getattr(sqlite3, name, None)
            if flag is not None:
                try:
                    setconfig(flag, value)
                except (sqlite3.Error, OverflowError, ValueError):
                    pass


def _structure_problem(db: sqlite3.Connection) -> str | None:
    """Reads only the schema (nothing of any table's rows, and nothing that evaluates a generated column), before ``quick_check`` or any SELECT. A reason code, or None.
    The three tables this module reads must be real tables (not views, not virtual tables such as fts5), and no table of the file may be virtual or have a generated column: a computed column can be made to need
    hundreds of MiB for one row, and ``quick_check`` computes it too."""
    master = db.execute("SELECT type,name,sql FROM sqlite_master WHERE type IN ('table','view')").fetchall()
    tables = [r for r in master if r[0] == "table"]
    if len(tables) > BUNDLE_MAX_TABLES:
        return "too_many_tables"
    kinds = {r[1]: r[0] for r in master}
    for name in ("memory_entries", "memory_identity_bindings", "memory_store_meta"):
        if name in kinds and kinds[name] != "table":
            return "not_a_table"
    for _type, name, sql in tables:
        if isinstance(sql, str) and re.match(r"\s*CREATE\s+VIRTUAL\s", sql, re.IGNORECASE):
            return "not_a_table"
        if name.startswith("sqlite_"):
            continue
        if name == "memory_entries" and isinstance(sql, str) and re.search(r"WITHOUT\s+ROWID", sql, re.IGNORECASE):
            return "not_a_table"                         # the import walks the lines by rowid
        for column in db.execute("SELECT hidden FROM pragma_table_xinfo(?)", (name,)):
            if column[0] in (2, 3):
                return "generated_column"
            if column[0] != 0:
                return "not_a_table"                     # a hidden column of a virtual table
    return None


def _open_bundle(path: Path) -> sqlite3.Connection:
    """The one way a bundle file is opened for reading (``check`` and ``import``): read-only, with the defenses above and the structure scan done. Raises ``_BundleRefused`` / ``sqlite3.Error``."""
    uri = long_path.file_uri(path)
    last: sqlite3.Error | None = None
    for suffix in ("?mode=ro", "?mode=ro&immutable=1"):
        db = sqlite3.connect(uri + suffix, uri=True, timeout=0.5)
        try:
            _defend(db)
            db.execute("SELECT count(*) FROM sqlite_master").fetchone()
            db.row_factory = sqlite3.Row
            problem = _structure_problem(db)
            if problem:
                raise _BundleRefused(problem)
            return db
        except sqlite3.OperationalError as error:
            db.close()
            last = error
        except BaseException:
            db.close()
            raise
    raise last if last else sqlite3.OperationalError("unable to open database file")


_ISO = re.compile(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?(?:Z|[+-]\d{2}:?\d{2})?)?")


def _created_ok(value: Any) -> bool:
    """An ISO 8601 date or date-time that is not later than now (plus ``FUTURE_SKEW``). A line's ``created_at`` orders it among the owner's lines; a forged far-future date would put it first for good."""
    if not isinstance(value, str) or not _ISO.fullmatch(value):
        return False
    text = value.replace(" ", "T", 1)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    text = re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text)
    text = re.sub(r"\.(\d{1,9})", lambda m: "." + (m.group(1) + "000000")[:6], text)
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when <= datetime.now(timezone.utc) + FUTURE_SKEW


class _Oversize:
    """Stands for a cell that is longer than the limit and was not read."""


OVERSIZE = _Oversize()


class _Admission:
    """The entry check of a Personal line, the one a normal Personal write gets (``memory_classify.stage1``): length, accepted kind (after the store's own kind correction), secret shape, host path;
    and what no line may be: an id outside the grammar the recall tools give the model (``memory_recall.ENTRY_ID_RE``), an id with the reserved stamp prefix, a text that is not text, a date that is not a past date.
    The original wording (``native``) gets what a normal write gives it: the ``memory_runtime._safe_summary`` check (secret shape, host path, role prefix, ``native_max_chars()`` characters at most); as a normal
    write refuses the whole proposal when its ``content_native`` fails that check, the whole line is refused here. Without a usable ruleset only the shape checks apply (an engine that cannot tell never blocks)."""

    def __init__(self, rules: dict[str, Any] | None, strict: bool = True):
        self.strict = strict           # the normal write's ``_safe_summary`` on the body and the original wording: only for a sender that is not the approved home (the old-record road)
        self.max_chars = self.kinds = self.secret = self.path = None
        self.remap: dict[str, str] = {}
        if rules is not None:
            block = rules["stores"][PERSONAL_SCOPE]
            limit = block.get("maxChars")
            self.max_chars = limit if isinstance(limit, int) and not isinstance(limit, bool) else None
            self.kinds = set(memory_classify.accepted_kinds(rules, PERSONAL_SCOPE))
            self.remap = memory_classify.remap_table(rules, PERSONAL_SCOPE)
            self.secret = memory_classify._regex(rules, "secretValueShapes")
            self.path = memory_classify._regex(rules, "hostAbsolutePath")

    @property
    def read_limit(self) -> int:
        """How many characters of a line's text are worth reading out of a bundle: more than this is refused as ``too_long`` without being read."""
        return self.max_chars if self.max_chars is not None else CONTENT_FALLBACK_MAX_CHARS

    def reason(self, ident: Any, kind: Any, content: Any, native: Any = None, created_at: Any = "2026-01-01T00:00:00Z") -> str | None:
        if not isinstance(ident, str) or not ident or len(ident) > ENTRY_ID_MAX_CHARS or not ENTRY_ID_RE.fullmatch(ident):
            return "bad_id"
        if ident.startswith(ms.ONE_PACK_STAMP_PREFIX):
            return "reserved_id"                       # the stamp source text must never be the id of a line: the id paths would reach it
        if content is OVERSIZE:
            return "too_long"
        if not isinstance(kind, str) or not isinstance(content, str):
            return "not_text"
        if self.max_chars is not None and len(content) > self.max_chars:
            return "too_long"
        if self.kinds is not None and self.remap.get(kind, kind) not in self.kinds:
            return "kind"
        if self.secret is not None and self.secret.search(content):
            return "secret"
        if self.path is not None and self.path.search(content):
            return "host_path"
        from .memory_runtime import _safe_summary
        if self.strict:
            try:
                _safe_summary(content)                  # the body gets what a normal write gives it (#10): a role prefix at a line start, a secret shape the ruleset's regex does not name, a host path
            except ValueError:
                return "body_unsafe"
        if native is not None:
            if native is OVERSIZE:
                return "native_too_long"
            if not isinstance(native, str):
                return "native_unsafe"
            if len(native) > native_max_chars():
                return "native_too_long"
            if self.strict:
                try:
                    _safe_summary(native)
                except ValueError:
                    return "native_unsafe"
            elif (self.secret is not None and self.secret.search(native)) or (self.path is not None and self.path.search(native)):
                return "native_unsafe"                  # the approved home's wording is taken as the desktop wrote it, but a secret shape or a host path is left out as in the line's own text above
        if not _created_ok(created_at):
            return "bad_created_at"
        return None


def _entry_select(db: sqlite3.Connection, extra: str = "") -> str:
    """The SELECT of a bundle's lines: the columns this module takes, named (no ``SELECT *``), the text read only when it is not longer than the limit (the length is asked first, so a huge cell is not copied out).
    The first ``?`` is that limit, the others are the ``extra`` clause's."""
    have = set(split._columns(db, "memory_entries"))
    cols = ("id,scope,kind,created_at,superseded_at," + ("confidence,sensitivity," if {"confidence", "sensitivity"} <= have else "NULL AS confidence,NULL AS sensitivity,")
            + ("".join(c + "," for c in EMBEDDING_COLS) if all(c in have for c in EMBEDDING_COLS) else ""))
    return f"SELECT {cols}length(content) AS content_len, CASE WHEN length(content)<=? THEN content END AS content FROM memory_entries {extra}"


def _entry_columns_present(db: sqlite3.Connection) -> bool:
    have = set(split._columns(db, "memory_entries"))
    return {"id", "scope", "kind", "content", "created_at", "superseded_at"} <= have


EMBEDDING_COLS = ("embedding_model", "embedding_adapter", "embedding_model_sha256", "embedding_content_hash", "embedding_dimensions", "embedding_json")
EMBEDDING_TEXT_MAX = 256
EMBEDDING_JSON_MAX = 200_000


def _text_cell(row: Any, ) -> Any:
    """The line's text as ``_Admission`` reads it: the text, or ``OVERSIZE`` when it was longer than the limit and not read."""
    content = row["content"]
    if content is None and (row["content_len"] or 0) > 0:
        return OVERSIZE
    return content


def _native_of(bundle: sqlite3.Connection, ident: str, has_native: bool) -> Any:
    """The original wording of a bundle line: None (none), the text, ``OVERSIZE`` (longer than the limit, not read) or the value as it is (not text)."""
    if not has_native:
        return None
    try:
        got = bundle.execute(f"SELECT length(content_native) AS n, CASE WHEN length(content_native)<=? THEN content_native END AS t FROM {_NATIVE} WHERE entry_id=? LIMIT 1",
                             (native_max_chars(), ident)).fetchone()
    except sqlite3.Error:
        return None                                     # a table of another shape holds no wording this module knows: nothing is taken from it
    if got is None:
        return None
    if got["t"] is None and (got["n"] or 0) > 0:
        return OVERSIZE
    return got["t"]


# --- export ---------------------------------------------------------------------------------------------------------

def _bundle_schema(src: sqlite3.Connection, dst: sqlite3.Connection) -> None:
    dst.execute("CREATE TABLE IF NOT EXISTS memory_store_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    dst.execute("INSERT OR IGNORE INTO memory_store_meta(key,value) VALUES('revision','0')")
    split._ensure_side_table(src, dst, "memory_entries")
    for table in ("memory_identity_bindings", _NATIVE, "memory_revocations"):
        split._ensure_side_table(src, dst, table)


def _walk_personal(src: sqlite3.Connection, rules: dict[str, Any] | None, admission: "_Admission", has_native: bool, no_stamps: bool, extra: str = ""):
    """The one selection of what a bundle carries, for ``export`` and ``measure``: the sender's live Personal lines, in the order of packing (by ``KIND_TIERS``, newest first inside a tier, then id), each with ``why`` (None: it is packed; else the code it is left out for). The lines that count
    towards the Personal ceiling (``counts_towards_ceiling``) are at most the ceiling in a bundle (its own ``check`` refuses more), so a sender over it (an import adds lines without asking for room) packs the first of
    them in that order and leaves the rest. On the move road the lines before ``countsFrom`` do not count and all go; on the old-record road (``no_stamps``) every line counts. ``extra``: more columns for the caller (a leading comma)."""
    ceiling = personal_row_ceiling(rules)
    placed = 0
    order = tier_order_sql()
    for r in src.execute(f"SELECT id,kind,content,created_at{extra} FROM memory_entries WHERE scope=? AND superseded_at IS NULL AND content<>'' ORDER BY {order},created_at DESC,id DESC", (PERSONAL_SCOPE,)):
        native = _native_of(src, r["id"], has_native)
        why = admission.reason(r["id"], r["kind"], r["content"], native, r["created_at"])
        counts_it = counts_towards_ceiling(r["created_at"], rules, every=no_stamps)
        if why is None and counts_it and placed >= ceiling:
            why = "over_ceiling"
        if why is None:
            placed += 1 if counts_it else 0
        yield r, why, native


def export(owner: str, out_path: str | os.PathLike[str], *, with_embeddings: bool = True, budget_bytes: int | None = None, no_stamps: bool = False, limit_bytes: int | None = None) -> dict[str, Any]:
    """Write the Personal bundle (a SQLite file) to ``out_path``. Reads the sender's root store read-only; replaces ``out_path`` if it exists.
    ``no_stamps``: the bundle carries no forget stamp (the old-record road: a stamp must not blank a line of the computer that takes the record over; B1).
    ``limit_bytes`` (default ``BUNDLE_MAX_BYTES``; the desktop gives the bytes the memory file may take): the file is never larger than this by the estimate of ``measure`` (the same ``_Sizer``, so the two agree). The newest lines are packed up to it
    and the rest stay on the sender (``notPackedBy.over_size_limit``, ``partial``); the lines that were packed are the ones ``ids_out`` lists, so a later ``purge`` of the list deletes nothing that was left."""
    from .memory_runtime import memory_path
    path = memory_path(owner)
    if not path.is_file():
        return {"schema": SCHEMA, "state": "no_store"}
    out = long_path.extended(Path(out_path), 24)  # the .part and its journal sit beside it
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_name(out.name + ".part")
    for stale in (part, out):
        for suffix in ("", "-journal", "-wal", "-shm"):
            try:
                Path(str(stale) + suffix).unlink()
            except FileNotFoundError:
                pass
    src = _ro(path)
    try:
        if "memory_entries" not in split._tables(src):
            return {"schema": SCHEMA, "state": "no_store"}
        # A line the receiver would refuse at the door (too long, secret-shaped, a kind a Personal store does not take) is not packed, and so is not in the list ``purge`` later gets: it stays here.
        rules = memory_classify.active()
        admission = _Admission(rules, strict=no_stamps)
        tables = split._tables(src)
        has_native = _NATIVE in tables
        sizer = _Sizer(src, tables, has_native, no_stamps, with_embeddings, budget_bytes)
        ids = []
        not_packed = 0
        not_packed_by: dict[str, int] = {}
        packed_by: dict[str, int] = {}
        left_by: dict[str, int] = {}
        for r, why, _native in _walk_cut(src, rules, admission, has_native, no_stamps, sizer, _limit(limit_bytes)):
            if why is None:
                ids.append(r["id"])
                packed_by[_tier_name(r["kind"])] = packed_by.get(_tier_name(r["kind"]), 0) + 1
            else:
                not_packed += 1
                not_packed_by[why] = not_packed_by.get(why, 0) + 1     # the count and the reason only: the text may be a secret
                if why == "over_size_limit":
                    left_by[_tier_name(r["kind"])] = left_by.get(_tier_name(r["kind"]), 0) + 1
        dst = sqlite3.connect(str(part))
        try:
            dst.row_factory = sqlite3.Row
            _bundle_schema(src, dst)
            split.copy_rows(src, dst, ids)
            # What a receiver must not get: the sender's tickets, project links and relations, and where the line was said, what it was based on (file paths, user names) and in which context, the audience
            # it was written for and the name of the sender's computer: the receiver makes those columns again for itself.
            for table in ("memory_project_links", "memory_origin_links", "memory_relation_edges", "memory_translation_jobs", "memory_decisions"):
                if table in split._tables(dst):
                    dst.execute(f"DELETE FROM {table}")
            dst.execute("UPDATE memory_entries SET project_id=NULL,project_path=NULL,chat_id=NULL,evidence_json='[]',context_json='{}'")
            dst.execute("UPDATE memory_identity_bindings SET origin_refs_json='[]',applicability_json=?,owner_namespace=?", (_json(CLEAN_AUDIENCE), SENDER_NAME))
            stamps = 0
            stamps_not_packed = 0
            if "memory_revocations" in split._tables(src) and not no_stamps:
                columns = [c for c in split._columns(src, "memory_revocations") if c in set(split._columns(dst, "memory_revocations"))]
                # At most STAMP_LIMIT stamps, the newest: a bundle with more would be refused by this module's own ``check`` and the move could never happen. The older stamps stay on the sender; what they
                # meant (that words the owner forgot long ago are not brought back) is lost for the new home: those words can be learned there again. The number left out is answered (``stampsNotPacked``).
                total = src.execute("SELECT COUNT(*) FROM memory_revocations WHERE owner_key=?", (personal_key(),)).fetchone()[0]
                rows = src.execute(f"SELECT {','.join(columns)} FROM memory_revocations WHERE owner_key=? ORDER BY revoked_epoch DESC, revoked_at DESC, revocation_id DESC LIMIT ?",
                                   (personal_key(), STAMP_LIMIT)).fetchall()
                dst.executemany(f"INSERT OR IGNORE INTO memory_revocations({','.join(columns)}) VALUES({split._marks(len(columns))})", [tuple(r) for r in rows])
                stamps = len(rows)
                stamps_not_packed = total - len(rows)
            dst.commit()
            dst.execute("VACUUM")          # the pages the cleared columns and deleted tables leave are rewritten: no earlier bytes of them stay in the file
            _meta_set(dst, "pack_schema", SCHEMA)
            _meta_set(dst, "pack_id", "pk_" + uuid.uuid4().hex)
            _meta_set(dst, "packed_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            _meta_set(dst, "personal_key", personal_key())
            dst.commit()
            size = part.stat().st_size if part.exists() else 0
            over = budget_bytes is not None and size > budget_bytes
            dropped = False
            if not with_embeddings or over:
                dst.execute("UPDATE memory_entries SET embedding_model=NULL,embedding_adapter=NULL,embedding_model_sha256=NULL,embedding_content_hash=NULL,"
                            "embedding_dimensions=NULL,embedding_json=NULL")
                dst.commit()
                dst.execute("VACUUM")
                dropped = True
            _meta_set(dst, "rows", str(len(ids)))
            _meta_set(dst, "stamps", str(stamps))
            _meta_set(dst, "embeddings", "0" if dropped else "1")
            dst.commit()
            dst.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst.close()
    finally:
        src.close()
    os.replace(part, out)
    for suffix in ("-journal", "-wal", "-shm"):
        try:
            Path(str(part) + suffix).unlink()
        except FileNotFoundError:
            pass
    answer: dict[str, Any] = {"schema": SCHEMA, "state": "packed", "rows": len(ids), "stamps": stamps, "bytes": out.stat().st_size,
                              "embeddings": not dropped, "ids": len(ids)}
    if over:
        answer["embeddingsDropped"] = True
    if not_packed:
        answer["notPacked"] = not_packed
        answer["notPackedBy"] = not_packed_by
    if packed_by:
        answer["packedBy"] = packed_by
    if not_packed_by.get("over_size_limit"):
        answer["partial"] = True
        answer["leftBy"] = left_by
    if stamps_not_packed:
        answer["stampsNotPacked"] = stamps_not_packed
    return answer


# --- measure --------------------------------------------------------------------------------------------------------

PAGE_BYTES = 4096
"""The page size of a bundle file (SQLite's default for a file made here)."""
INDEX_FILL = 0.95
"""How full the pages of a table's id index are in the bundle file: ``VACUUM`` (the last thing ``export`` does to the file) rebuilds the indexes in order, so they are nearly full (measured against real exports: evidence)."""
MEASURE_SAFETY = 1.05
"""``measure`` never answers less than ``export`` writes: the model of the pages is checked against real exports (``tests/test_one_pack_audit61.py``) and this is the margin over the worst of them."""
_ENTRY_BLANKED = {"project_id": 0, "project_path": 0, "chat_id": 0, "evidence_json": 2, "context_json": 2}
"""The columns of a line that ``export`` empties, with the bytes they then hold (nothing, or ``[]`` / ``{}``)."""


class _Pages:
    """The pages of one b-tree that is filled in order: add the size of each record, ask how many pages. ``index``: an index (the cell has no row number and the pages are only ``INDEX_FILL`` full).
    ``add`` says whether the answer of ``total`` can have changed; ``undo`` takes the last ``add`` back (the line that does not fit under a limit is not counted)."""

    def __init__(self, index: bool = False):
        self.index = index
        self.pages = 0
        self.free = 0.0
        self.overflow = 0
        self.rows = 0
        self._prev = (0, 0.0, 0, 0)

    def add(self, payload: int) -> bool:
        self._prev = (self.pages, self.free, self.overflow, self.rows)
        grown = (self.pages, self.overflow)
        usable = PAGE_BYTES - 12
        local = payload + (2 if self.index else 5)
        if not self.index and payload > usable - 35:      # SQLite keeps ``local`` bytes in the leaf and the rest in overflow pages of 4092 bytes (the rule of the file format)
            minimum = 489
            local = minimum + ((payload - minimum) % (PAGE_BYTES - 4))
            if local > usable - 35:
                local = minimum
            self.overflow += -(-(payload - local) // (PAGE_BYTES - 4))
            local += 4 + 5
        need = local + 2
        capacity = usable * (INDEX_FILL if self.index else 1.0)
        if self.pages == 0 or need > self.free:
            self.pages += 1
            self.free = capacity
        self.free -= need
        self.rows += 1
        return (self.pages, self.overflow) != grown

    def undo(self) -> None:
        self.pages, self.free, self.overflow, self.rows = self._prev

    def total(self) -> int:
        leaves = self.pages
        interior = 0 if leaves <= 1 else 1 + leaves // 100
        return max(0, leaves - 1) + self.overflow + interior      # the first page of a table or an index is its root, which the schema's own pages already hold


def _sum_expr(columns: list[str], skip: Iterable[str] = ()) -> str:
    skipped = set(skip)
    parts = [f'COALESCE(length(CAST("{c}" AS BLOB)),0)' for c in columns if c not in skipped]
    return "+".join(parts) if parts else "0"


def _chosen(with_emb: int, without_emb: int, with_embeddings: bool, budget_bytes: int | None) -> tuple[int, bool | None]:
    """The estimate of the file an export would write and whether the embeddings are dropped (None: the estimate cannot tell), by the export's rule: they go when asked, or when the file is over the budget."""
    if not with_embeddings:
        return without_emb, True
    if budget_bytes is None or with_emb <= budget_bytes:
        return with_emb, False
    return max(without_emb, min(with_emb, budget_bytes)), (True if without_emb >= budget_bytes else None)      # over the budget the export drops the embeddings, unless the file is really under it: the larger of the two outcomes


class _Sizer:
    """The model of the bundle file's pages that ``measure`` answers from and ``export`` cuts by, so the two can never disagree about which lines fit: the pages of every table and index the export makes, filled line by line in
    the order the export packs them (``_walk_personal``), plus the schema's own pages and the forget stamps (which do not depend on the lines). ``size`` is never smaller than the file (``MEASURE_SAFETY``) and never
    decreases as a line is added, so the lines that fit under a limit are a prefix of the newest-first order."""

    def __init__(self, src: sqlite3.Connection, tables: set[str], has_native: bool, no_stamps: bool, with_embeddings: bool, budget_bytes: int | None):
        self.with_embeddings = with_embeddings
        self.budget_bytes = budget_bytes
        entry_cols = split._columns(src, "memory_entries")
        emb_cols = [c for c in EMBEDDING_COLS if c in entry_cols]
        blanked = set(_ENTRY_BLANKED)
        base_expr = _sum_expr(entry_cols, blanked | set(emb_cols))
        emb_expr = _sum_expr(emb_cols) if emb_cols else "0"
        self.fixed_cells = len(entry_cols) + sum(_ENTRY_BLANKED[c] for c in _ENTRY_BLANKED if c in entry_cols)       # a header byte per column and what the emptied columns hold
        self.native_cols = split._columns(src, _NATIVE) if has_native else []
        self.native_expr = _sum_expr(self.native_cols)
        bind_cols = split._columns(src, "memory_identity_bindings") if "memory_identity_bindings" in tables else []
        # The binding of a packed line: its id, the sender name, the empty origin list and the audience (made by ``export``) and the other columns as the sender has them (the largest of them, so it is never less).
        self.bind_rest = len(bind_cols) + len(SENDER_NAME) + 2 + len(_json(CLEAN_AUDIENCE))
        if bind_cols:
            rest_cols = [c for c in bind_cols if c not in ("memory_id", "owner_namespace", "origin_refs_json", "applicability_json")]
            self.bind_rest += int(src.execute(f"SELECT COALESCE(MAX({_sum_expr(rest_cols)}),0) FROM memory_identity_bindings").fetchone()[0] or 0)
        # An index of the sender's own on a table the export copies comes along (``_ensure_side_table``): none is made by the engine or the desktop today, so each is counted as an entry of (id + 80 bytes) per packed line.
        own_indexes = src.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND sql IS NOT NULL AND tbl_name IN ('memory_entries','memory_identity_bindings',?)", (_NATIVE,)).fetchone()[0]
        self.own_index_pages = [_Pages(index=True) for _ in range(own_indexes)]
        self.rows_with, self.rows_without = _Pages(), _Pages()
        self.id_index, self.bind_rows, self.bind_index, self.native_rows, self.native_index = _Pages(index=True), _Pages(), _Pages(index=True), _Pages(), _Pages(index=True)
        self.extra = f", ({base_expr}) AS base_b, ({emb_expr}) AS emb_b"
        self.src = src
        self.stamps = 0
        stamps_bytes = 0
        if "memory_revocations" in tables and not no_stamps:
            rev_cols = split._columns(src, "memory_revocations")
            total = src.execute("SELECT COUNT(*) FROM memory_revocations WHERE owner_key=?", (personal_key(),)).fetchone()[0]
            self.stamps = min(total, STAMP_LIMIT)
            rev_rows, rev_pk, rev_unique = _Pages(), _Pages(index=True), _Pages(index=True)
            pk_len, unique_len = (int(v or 0) for v in src.execute("SELECT MAX(length(revocation_id)), MAX(length(owner_key)+length(memory_kind)+length(content_hash)) FROM memory_revocations WHERE owner_key=?", (personal_key(),)).fetchone())
            for (n,) in src.execute(f"SELECT {_sum_expr(rev_cols)} FROM memory_revocations WHERE owner_key=? ORDER BY revoked_epoch DESC, revoked_at DESC, revocation_id DESC LIMIT ?", (personal_key(), STAMP_LIMIT)):
                rev_rows.add(int(n or 0) + len(rev_cols) + 2)
                rev_pk.add(pk_len + 6)
                rev_unique.add(unique_len + 6)
            stamps_bytes = (rev_rows.total() + rev_pk.total() + rev_unique.total()) * PAGE_BYTES
        schema = sqlite3.connect(":memory:")
        try:
            _bundle_schema(src, schema)
            split.copy_rows(src, schema, [])                  # the side tables the export makes when it copies the lines
            schema_pages = schema.execute("PRAGMA page_count").fetchone()[0]
        finally:
            schema.close()
        self.constant = schema_pages * PAGE_BYTES + stamps_bytes
        self._all = [self.rows_with, self.rows_without, self.id_index, self.bind_rows, self.bind_index, self.native_rows, self.native_index, *self.own_index_pages]
        self._size = self._compute()

    def _compute(self) -> tuple[int, bool | None]:
        rest = (sum(p.total() for p in self.own_index_pages) + self.id_index.total() + self.bind_rows.total() + self.bind_index.total() + self.native_rows.total() + self.native_index.total()) * PAGE_BYTES
        with_emb = int((self.rows_with.total() * PAGE_BYTES + rest + self.constant) * MEASURE_SAFETY)
        without_emb = int((self.rows_without.total() * PAGE_BYTES + rest + self.constant) * MEASURE_SAFETY)
        return _chosen(with_emb, without_emb, self.with_embeddings, self.budget_bytes)

    def size(self) -> tuple[int, bool | None]:
        return self._size

    def add(self, r: sqlite3.Row, native: Any, limit: int) -> bool:
        """Count the line ``r`` (a row of ``_walk_personal`` with this sizer's ``extra`` columns); False, and the line is not counted, when the file would then be over ``limit``."""
        idlen = len(r["id"].encode("utf-8"))
        base = int(r["base_b"] or 0) + self.fixed_cells
        grew = self.rows_without.add(base)
        grew |= self.rows_with.add(base + int(r["emb_b"] or 0))
        grew |= self.id_index.add(idlen + 6)
        for extra_index in self.own_index_pages:
            grew |= extra_index.add(idlen + 80)
        grew |= self.bind_rows.add(idlen + self.bind_rest)
        grew |= self.bind_index.add(idlen + 6)
        if isinstance(native, str):
            nb = self.src.execute(f"SELECT {self.native_expr} FROM {_NATIVE} WHERE entry_id=?", (r["id"],)).fetchone()
            grew |= self.native_rows.add(int(nb[0] if nb and nb[0] is not None else len(native.encode("utf-8"))) + len(self.native_cols) + 2)
            grew |= self.native_index.add(idlen + 6)
        if not grew:
            return True                      # no page was added: the estimate is what it was, and it fitted
        before = self._size
        self._size = self._compute()
        if self._size[0] > limit:
            for pages in self._all:
                pages.undo()
            self._size = before
            return False
        return True


def _limit(value: int | None) -> int:
    """The size limit in force: the caller's declaration, cut to ``LIMIT_100MIB``, or ``BUNDLE_MAX_BYTES`` when it declares none."""
    return BUNDLE_MAX_BYTES if value is None else max(1, min(int(value), LIMIT_100MIB))


def _tier_name(kind: Any) -> str:
    return KIND_TIERS[kind_tier(kind)][0]


def _walk_cut(src: sqlite3.Connection, rules: dict[str, Any] | None, admission: "_Admission", has_native: bool, no_stamps: bool, sizer: _Sizer, limit: int):
    """``_walk_personal`` with the size limit applied: the lines that would be packed, newest first, are packed until the next one would take the file over ``limit`` (the estimate of ``sizer``); that line and every older
    one are left out as ``over_size_limit`` (a prefix, never a pick: which lines stay on the sender is the same on every call, whatever was done in between: by kind tier, then newest ``created_at`` first, then id). ``export`` and ``measure`` share it."""
    cut = False
    for r, why, native in _walk_personal(src, rules, admission, has_native, no_stamps, sizer.extra):
        if why is None and (cut or not sizer.add(r, native, limit)):
            cut = True
            why = "over_size_limit"
        yield r, why, native


def measure(owner: str, *, no_stamps: bool = False, with_embeddings: bool = True, budget_bytes: int | None = None, limit_bytes: int | None = None) -> dict[str, Any]:
    """What ``export`` with the same arguments would write, without writing it (the sender's store is only read; no file is made): how many lines it packs (``rows``), how many it leaves out and why (``notPacked``,
    ``notPackedBy``) and an estimate of the bundle file's size (``estimatedBytes``) against the limit (``limitBytes``, ``BUNDLE_MAX_BYTES`` unless the caller gives the room it really has), ``fits``. The estimate
    is made from the lines the export would take (the size of every column that stays, the pages a table and its id index take, the schema's own pages) and is never smaller than the file. With ``budget_bytes`` it follows the export's rule (the embeddings go when the file is over the
    budget); when the estimate cannot tell which way that goes it gives the larger file.
    A store that does not fit is not refused: the answer is what ``export`` would pack, the newest lines up to the limit: ``rows`` and ``estimatedBytes`` are of those, ``partial`` is true, ``notPackedBy.over_size_limit`` is how many
    lines stay on the sender, and ``fits`` (every line is packed and the file is under the limit) is false."""
    from .memory_runtime import memory_path
    path = memory_path(owner)
    if not path.is_file():
        return {"schema": SCHEMA, "state": "no_store"}
    src = _ro(path)
    try:
        if "memory_entries" not in split._tables(src):
            return {"schema": SCHEMA, "state": "no_store"}
        rules = memory_classify.active()
        admission = _Admission(rules, strict=no_stamps)
        tables = split._tables(src)
        has_native = _NATIVE in tables
        limit = _limit(limit_bytes)
        sizer = _Sizer(src, tables, has_native, no_stamps, with_embeddings, budget_bytes)
        packed = 0
        not_packed = 0
        not_packed_by: dict[str, int] = {}
        packed_by: dict[str, int] = {}
        left_by: dict[str, int] = {}
        for _r, why, _native in _walk_cut(src, rules, admission, has_native, no_stamps, sizer, limit):
            if why is not None:
                not_packed += 1
                not_packed_by[why] = not_packed_by.get(why, 0) + 1
                if why == "over_size_limit":
                    left_by[_tier_name(_r["kind"])] = left_by.get(_tier_name(_r["kind"]), 0) + 1
                continue
            packed += 1
            packed_by[_tier_name(_r["kind"])] = packed_by.get(_tier_name(_r["kind"]), 0) + 1
        stamps = sizer.stamps
        size, dropped = sizer.size()
    finally:
        src.close()
    over = not_packed_by.get("over_size_limit", 0)
    answer: dict[str, Any] = {"schema": SCHEMA, "state": "measured", "rows": packed, "stamps": stamps, "estimatedBytes": size, "limitBytes": limit, "fits": size <= limit and not over}
    if packed_by:
        answer["packedBy"] = packed_by
    if over:
        answer["partial"] = True
        answer["leftBy"] = left_by
    if dropped is not False and (not with_embeddings or budget_bytes is not None):
        answer["embeddingsDropped"] = dropped
    if not_packed:
        answer["notPacked"] = not_packed
        answer["notPackedBy"] = not_packed_by
    return answer


def out_room(out: str | os.PathLike[str], estimated: int) -> dict[str, Any]:
    """What the sender's ``export --out`` could not do for want of room, asked without writing (reads only; no folder is made): ``outWritable`` (the nearest folder that exists can be written in) and ``outFreeBytes``;
    ``outRoom`` is true when the folder has the room the export needs (the file, its ``.part`` while it is being made and the pages a ``VACUUM`` rewrites: three times the estimate) (home-D5)."""
    target = long_path.extended(Path(out), 24)
    folder = _nearest_dir(target.parent if not target.is_dir() else target)
    try:
        free = shutil.disk_usage(folder).free
    except OSError:
        return {"outWritable": False, "outRoom": False}
    writable = os.access(folder, os.W_OK)
    return {"outWritable": writable, "outFreeBytes": free, "outRoom": bool(writable and free >= 3 * estimated)}


def write_ids(owner: str, bundle: str | os.PathLike[str], ids_out: str | os.PathLike[str]) -> int:
    """The ids of the rows a bundle holds, as a JSON array: the list ``purge`` is later given (kept by the sender, never sent)."""
    db = _ro(long_path.extended(Path(bundle)))
    try:
        ids = [r["id"] for r in db.execute("SELECT id FROM memory_entries ORDER BY created_at,id")]
    finally:
        db.close()
    target = long_path.extended(Path(ids_out), 8)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")
    tmp.write_text(json.dumps(ids), encoding="utf-8")
    os.replace(tmp, target)
    return len(ids)


# --- check ----------------------------------------------------------------------------------------------------------

def check(bundle: str | os.PathLike[str], *, receiver: str | None = None, no_stamps: bool = False, engines: Iterable[str] | None = None, limit_bytes: int | None = None) -> dict[str, Any]:
    """Whether ``bundle`` is a bundle this module imports. The reason is a code. Reads only the file; with ``receiver`` (the owner namespace of the store this computer would import into) it also reads that store
    read-only and answers ``wouldBlank``: how many live Personal lines of the receiver the bundle's stamps match, the number an import blanks (and refuses above ``BLANK_LIMIT`` without a confirmation).
    ``no_stamps``: the import will not take the bundle's stamps (the old-record road), so ``wouldBlank`` is 0. Any shape of file answers a code, never an exception that is not a sqlite error.
    ``engines`` (None: not asked; the import calls ``check`` itself without it): the extra engine copies ``import`` is given (``--engine``). When it is given (a list, possibly empty) an ``ok`` answer also says what ``import`` would refuse
    before it writes anything, from the same reads and in the same order (the receiver's home mirror, then the engine copies; home-D4): ``enginesConfirmed`` and, when false, ``enginesNotConfirmed`` and ``engines``
    (``engine_fields``); ``homeState`` when the receiver's mirror denies a write; ``wouldRefuse`` (the reason ``import`` would answer: ``home_state_denied`` | ``engines_not_confirmed``; absent when neither would refuse);
    ``blankNeedsConfirm`` when ``wouldBlank`` is over the limit (an import without ``confirm_blank`` of exactly that number refuses).
    ``limit_bytes``: the largest file this call opens, as the caller declares it (the number the sender packed under; cut to ``LIMIT_100MIB``); without it ``BUNDLE_MAX_BYTES``."""
    path = long_path.extended(Path(bundle))
    limit = _limit(limit_bytes)
    if not path.is_file():
        return {"schema": SCHEMA, "state": "invalid", "reason": "missing"}
    try:
        size = path.stat().st_size
        if size > limit:
            # E-3: the answer says what this call can take, so the sender can pack again under it (partial) instead of packing the same size again; ``maxLimitBytes`` is the most a caller may declare.
            return {"schema": SCHEMA, "state": "invalid", "reason": "too_large", "limitBytes": limit, "maxLimitBytes": LIMIT_100MIB, "bundleBytes": size}      # looked at before the file is opened
    except OSError:
        return {"schema": SCHEMA, "state": "invalid", "reason": "missing"}
    try:
        db = _open_bundle(path)
    except _BundleRefused as refused:
        return {"schema": SCHEMA, "state": "invalid", "reason": str(refused)}
    except (sqlite3.Error, ValueError, OSError):
        return {"schema": SCHEMA, "state": "invalid", "reason": "not_sqlite"}
    try:
        try:
            answer = _check_open(db, receiver, no_stamps)
        except (sqlite3.Error, ValueError, TypeError, KeyError, OverflowError):
            return {"schema": SCHEMA, "state": "invalid", "reason": "bundle_unreadable"}     # a table that is not the shape this module wrote
        if engines is not None and answer.get("state") == "ok":
            answer.update(_before_write(receiver, engines))
            if isinstance(answer.get("wouldBlank"), int) and answer["wouldBlank"] > BLANK_LIMIT:
                answer["blankNeedsConfirm"] = True
        return answer
    finally:
        db.close()


def _before_write(receiver: str | None, extra: Iterable[str]) -> dict[str, Any]:
    """What ``import`` refuses before it writes a line, asked without importing (reads only): the receiver's home mirror first, then the engine copies, the order ``import_rows`` uses and with its own functions."""
    from .memory_runtime import memory_path
    rules = memory_classify.active()
    answer = engine_fields(extra)
    refused = _home_refusal(memory_path(receiver), rules) if receiver else None
    if refused:
        answer["homeState"] = refused["homeState"]
        answer["wouldRefuse"] = refused["reason"]
    elif not answer["enginesConfirmed"]:
        answer["wouldRefuse"] = "engines_not_confirmed"
    return answer


def _ceiling_room(db: sqlite3.Connection, bundle: sqlite3.Connection, rules: dict[str, Any] | None) -> int | None:
    """How many lines of this bundle the receiver has room for under its Personal ceiling: the ceiling minus the lines of the receiver that the normal write counts (``MemoryRuntime._store_count``), the bundle's own ids
    left out of that count (they take their place in the room as the import reaches them, whether they are here yet or not: an interrupted call that is called again then ends the same). None when the ruleset
    names no ceiling (nothing is refused)."""
    from .memory_runtime import MemoryRuntime
    cap = memory_classify.ceiling_of(rules, PERSONAL_SCOPE)
    if cap is None:
        return None
    ids = [r[0] for r in bundle.execute("SELECT id FROM memory_entries") if isinstance(r[0], str)]
    return max(0, cap - MemoryRuntime._store_count(db, rules, PERSONAL_SCOPE, CORE_ONE_ACTOR_ID, None, None, ids or None))


def _would_store_full(rdb: sqlite3.Connection, bundle: sqlite3.Connection, rules: dict[str, Any] | None, admission: _Admission, has_native: bool, every: bool = False) -> int:
    """How many lines of the bundle an import would refuse as ``store_full`` (reads only). It walks the bundle the way the import does (by kind, ``tier_order_sql``, newest first inside a kind), with the same decisions in the same order (the entry check, a line
    already here, a line the receiver forgot, the same words as a live line) and the same count (``_ceiling_room``: every line that reaches the point of being placed and counts (``counts_towards_ceiling``; ``every``: the
    old-record road, where every line counts) uses one place; on the move road a line before ``countsFrom`` uses none and is never refused). With no stamps
    (the old-record road) the number is what the import refuses. A move that carries stamps also blanks lines (freeing room) and drops forgotten words before it places any, so there the number can be larger than
    what is refused, never smaller."""
    room = _ceiling_room(rdb, bundle, rules)
    if room is None:
        return 0
    ledger = _Ledger(rdb, rules)
    live: dict[str, set[str]] = {}
    for kind, content in rdb.execute("SELECT kind,content FROM memory_entries WHERE scope=? AND superseded_at IS NULL AND content<>''", (PERSONAL_SCOPE,)):
        live.setdefault(_hash(content), set()).add(kind)
    used = over = 0
    for r in bundle.execute(_entry_select(bundle, f"ORDER BY {tier_order_sql()},created_at DESC,id DESC"), (admission.read_limit,)):
        if r["scope"] != PERSONAL_SCOPE or r["superseded_at"] is not None or r["content_len"] in (None, 0):
            continue
        text = _text_cell(r)
        if admission.reason(r["id"], r["kind"], text, _native_of(bundle, r["id"], has_native) if isinstance(r["id"], str) else None, r["created_at"]):
            continue
        takes = counts_towards_ceiling(r["created_at"], rules, every=every)
        if rdb.execute("SELECT 1 FROM memory_entries WHERE id=?", (r["id"],)).fetchone():
            used += 1 if takes else 0
            continue
        if ledger.matches(r["kind"], text):
            continue
        digest = _hash(text)
        if live.get(digest, set()) & _kinds_of(rules, r["kind"]):
            continue
        live.setdefault(digest, set()).add(r["kind"])
        if not takes:
            continue
        if used >= room:
            over += 1
        else:
            used += 1
    return over


def _check_open(db: sqlite3.Connection, receiver: str | None, no_stamps: bool) -> dict[str, Any]:
    try:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            return {"schema": SCHEMA, "state": "invalid", "reason": "quick_check_failed"}
    except sqlite3.Error:
        return {"schema": SCHEMA, "state": "invalid", "reason": "not_sqlite"}
    tables = split._tables(db)
    if not {"memory_entries", "memory_identity_bindings", "memory_store_meta"} <= tables:
        return {"schema": SCHEMA, "state": "invalid", "reason": "tables_missing"}
    if not _entry_columns_present(db):
        return {"schema": SCHEMA, "state": "invalid", "reason": "tables_missing"}
    meta = dict(db.execute("SELECT key,value FROM memory_store_meta").fetchall())
    if meta.get("pack_schema") != SCHEMA:
        return {"schema": SCHEMA, "state": "invalid", "reason": "schema_unknown"}
    if meta.get("personal_key") != personal_key():
        return {"schema": SCHEMA, "state": "invalid", "reason": "owner_key_unknown"}
    rules = memory_classify.active()
    rows = db.execute("SELECT COUNT(*) FROM memory_entries").fetchone()[0]
    # The lines that count towards the ceiling are at most the ceiling (a Personal store holds that many at most): a bundle with more is a forged one. On the move road a line dated before ``countsFrom`` does not
    # count (an owner's older lines are legitimate however many there are; the size of the file, ``BUNDLE_MAX_BYTES``, bounds the bundle); on the old-record road every row counts.
    since = None if no_stamps else memory_classify.ceiling_counts_from(rules)
    counted = rows if since is None else db.execute("SELECT COUNT(*) FROM memory_entries WHERE NOT (typeof(created_at)='text' AND created_at < ?)", (since,)).fetchone()[0]
    if counted > personal_row_ceiling(rules):
        return {"schema": SCHEMA, "state": "invalid", "reason": "too_many_rows"}
    if "memory_revocations" in tables and db.execute("SELECT COUNT(*) FROM memory_revocations").fetchone()[0] > STAMP_LIMIT:
        return {"schema": SCHEMA, "state": "invalid", "reason": "too_many_stamps"}
    foreign = db.execute("SELECT COUNT(*) FROM memory_entries WHERE scope IS NOT ? OR superseded_at IS NOT NULL OR COALESCE(length(content),0)=0", (PERSONAL_SCOPE,)).fetchone()[0]    # the rows the import refuses without a code (the same test as its ``_insert_batch``)
    stamps = db.execute("SELECT COUNT(*) FROM memory_revocations").fetchone()[0] if "memory_revocations" in tables else 0
    other_stamps = db.execute("SELECT COUNT(*) FROM memory_revocations WHERE owner_key<>?", (personal_key(),)).fetchone()[0] if "memory_revocations" in tables else 0
    answer = {"schema": SCHEMA, "state": "ok", "rows": rows, "stamps": stamps, "embeddings": meta.get("embeddings") == "1", "packId": meta.get("pack_id")}
    if foreign or other_stamps:   # these are never imported; the caller is told, the import still goes on with the rest
        answer["notPersonal"] = foreign + other_stamps
    admission = _Admission(rules, strict=no_stamps)
    has_native = _NATIVE in tables
    rejected: dict[str, int] = {}
    wants_native = False                 # a line that would come in carries original wording
    for r in db.execute(_entry_select(db, "WHERE scope=? AND superseded_at IS NULL AND COALESCE(length(content),0)>0"), (admission.read_limit, PERSONAL_SCOPE)):
        native = _native_of(db, r["id"], has_native) if isinstance(r["id"], str) else None
        why = admission.reason(r["id"], r["kind"], _text_cell(r), native, r["created_at"])
        if why:
            rejected[why] = rejected.get(why, 0) + 1
        elif isinstance(native, str):
            wants_native = True
    if rejected:                  # the entry check is the same one the import makes: these lines would not come in
        answer["rejected"] = sum(rejected.values())
        answer["rejectedBy"] = rejected
    if receiver:
        try:
            from .memory_runtime import memory_path
            target = memory_path(receiver)
            if target.is_file():
                rdb = _ro(target)
                try:
                    has_entries = "memory_entries" in split._tables(rdb)
                    if not no_stamps:
                        answer["wouldBlank"] = len(_hit_rows(rdb, _bundle_stamps(db), rules)) if has_entries else 0
                    answer["wouldStoreFull"] = _would_store_full(rdb, db, rules, admission, has_native, every=no_stamps) if has_entries else 0
                    # The import makes the receiver's original-wording table when the bundle carries original wording and the receiver has none (N-2).
                    answer["willCreateNativeTable"] = bool(wants_native and has_entries and _native_table(rdb) is None) or bool(wants_native and not has_entries)
                finally:
                    rdb.close()
            else:
                if not no_stamps:
                    answer["wouldBlank"] = 0
                answer["wouldStoreFull"] = 0
                answer["willCreateNativeTable"] = wants_native
        except (sqlite3.Error, OSError, ValueError):
            pass                  # the counts are only a help for the caller; an import counts them again itself
        if no_stamps:
            answer["wouldBlank"] = 0
    return answer


# --- ready ----------------------------------------------------------------------------------------------------------

def _nearest_dir(path: Path) -> Path:
    for candidate in (path, *path.parents):
        if candidate.is_dir():
            return candidate
    return path


def _store_lock_free(path: Path) -> bool:
    """Whether a writer could take the store now: a write lock is asked for and let go at once (nothing is written, no page is touched). A reader is not told by a read: the import takes the write lock (O-2)."""
    try:
        conn = sqlite3.connect(path, timeout=0.2, isolation_level=None)
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("ROLLBACK")
            return True
        finally:
            conn.close()
    except sqlite3.OperationalError as error:
        return not ("locked" in str(error).lower() or "busy" in str(error).lower())
    except sqlite3.Error:
        return True                              # not a lock: another code answers it


def ready(receiver: str | None, *, engines: Iterable[str] = (), owner_reason: str | None = None, need_bytes: int | None = None) -> dict[str, Any]:
    """Whether this computer can take an import, asked before a move starts and without a bundle (home-D4). Reads only: no file or database is written. It names every reason ``import`` can refuse or fail for
    that does not depend on the bundle's lines, each in ``blockers`` (``reason``, ``retryable`` false: the same question answers the same until something outside this call changes, ``needs``: what must change, and
    ``hosts`` for the engine copies): ``owner_unbound`` (or the registry reason ``owner_binding`` raised, ``owner_reason``), ``engines_not_confirmed`` (``engine_fields`` says which host and which number), ``store_unreadable``,
    ``store_unwritable`` and ``native_table_blocked`` (something that is not the original-wording table stands in its name: ``import`` would refuse every line that has original wording). ``state`` is ``ready`` when there is none.
    ``mayChange`` lists what is true now but that the move itself changes before the import (``home_state_denied``: the receiver's mirror is written ``home`` at the commit); it never blocks. Also: ``ownerBound``,
    ``storeState`` (``absent`` | ``readable`` | ``busy`` | ``unreadable`` | ``unknown``), ``canOpenStore``, ``nativeTable`` (``present`` | ``absent`` | ``blocked`` | ``unknown``), ``canStoreNative``, ``willCreateNativeTable``
    (the table is absent, so an import that carries original wording makes it), ``homeState`` (when the mirror denies a write).
 O-2: a store a writer holds right now is ``store_busy`` (``retryable`` true: asked again it answers differently; ``storeState`` ``busy``), not ``ready``. ``need_bytes`` (the room the import needs, e.g. the bundle's size; None: not asked): the answer
    then has ``freeBytes`` (free on the disk the store lives on) and ``needBytes``, and ``disk_space_short`` (``needs`` ``disk_space``) when the first is less than the second. Without it nothing about the disk is looked at."""
    from .memory_runtime import memory_path
    rules = memory_classify.active()
    answer: dict[str, Any] = {"schema": SCHEMA, **engine_fields(engines), "ownerBound": bool(receiver)}
    blockers: list[dict[str, Any]] = []
    may_change: list[str] = []
    if not receiver:
        reason = owner_reason or "owner_unbound"
        blockers.append({"reason": reason, "retryable": False, "needs": "owner_bind" if reason == "owner_unbound" else "owner_repair"})
    if not answer["enginesConfirmed"]:
        blockers.append({"reason": "engines_not_confirmed", "retryable": False, "needs": "plugin_update", "hosts": sorted({str(e["host"]) for e in answer["engines"]})})
    store, can_open, native = "unknown", False, "unknown"
    if receiver:
        path = memory_path(receiver)
        if not path.is_file():
            store = "absent"                                    # the import makes it (``MemoryRuntime``): it needs a folder it can write in
            can_open = os.access(_nearest_dir(path.parent), os.W_OK)
            native = "absent"
            if not can_open:
                blockers.append({"reason": "store_unwritable", "retryable": False, "needs": "permission"})
        else:
            try:
                rdb = _ro(path)
                try:
                    if rdb.execute("PRAGMA quick_check(1)").fetchone()[0] != "ok":
                        raise sqlite3.DatabaseError("quick_check")
                    state = _native_table(rdb)
                    native = "absent" if state is None else ("present" if state else "blocked")
                finally:
                    rdb.close()
                store = "readable"
                can_open = os.access(path, os.W_OK) and os.access(path.parent, os.W_OK)
                if not can_open:
                    blockers.append({"reason": "store_unwritable", "retryable": False, "needs": "permission"})
                elif not _store_lock_free(path):
                    store = "busy"
                    blockers.append({"reason": "store_busy", "retryable": True})
            except sqlite3.OperationalError as error:
                text = str(error).lower()
                if "locked" in text or "busy" in text:
                    store, can_open = "busy", True              # a writer holds it right now; the import waits for it
                    blockers.append({"reason": "store_busy", "retryable": True})
                else:
                    store = "unreadable"
            except (sqlite3.Error, OSError, ValueError):
                store = "unreadable"
            if store == "unreadable":
                blockers.append({"reason": "store_unreadable", "retryable": False, "needs": "store_repair"})
            if native == "blocked":
                blockers.append({"reason": "native_table_blocked", "retryable": False, "needs": "store_repair"})
        refused = _home_refusal(path, rules)
        if refused:
            answer["homeState"] = refused["homeState"]
            may_change.append("home_state_denied")
        if need_bytes is not None:
            try:
                free = int(shutil.disk_usage(_nearest_dir(path.parent)).free)
            except OSError:
                free = None                                   # the disk could not be asked: nothing is claimed about it
            if free is not None:
                need = max(0, int(need_bytes))
                answer.update(freeBytes=free, needBytes=need)
                if free < need:
                    blockers.append({"reason": "disk_space_short", "retryable": False, "needs": "disk_space", "freeBytes": free, "needBytes": need})
    answer.update(storeState=store, canOpenStore=can_open, nativeTable=native, canStoreNative=native in ("present", "absent") and can_open, willCreateNativeTable=native == "absent",
                  blockers=blockers, mayChange=may_change, state="not_ready" if blockers else "ready")
    return answer


# --- what to do with an answer ----------------------------------------------------------------------------------------

_INVALID_BUNDLE = {"missing", "too_large", "not_sqlite", "quick_check_failed", "tables_missing", "schema_unknown", "owner_key_unknown", "too_many_rows", "too_many_stamps", "bundle_unreadable"}


def retry_hint(answer: dict[str, Any]) -> dict[str, Any]:
    """For an answer that is not a success: ``retryable`` (true: the same call, called again, can end differently without anyone changing anything: a lock that is let go, a tail of work left; false: the same call answers
    the same until something outside it changes) and, when false, ``needs``: what must change (``plugin_update`` | ``owner_bind`` | ``owner_repair`` | ``new_bundle`` | ``home_state`` | ``confirm_blank`` | ``disk_space`` |
    ``permission`` | ``store_repair`` | ``ids_file`` | ``engine_update`` | ``store`` | ``unknown``). A machine value for the caller to decide whether to wait or to stop; the words of ``reason`` are not parsed. Success answers get none.
    ``check`` answers that name ``wouldRefuse`` get the hint of that reason."""
    state = answer.get("state")
    reason = answer.get("wouldRefuse") or answer.get("reason")
    if state in ("busy", "remaining", "partial"):
        return {"retryable": True}
    if state == "not_ready":
        stuck = [b for b in (answer.get("blockers") or []) if not b.get("retryable")]
        if answer.get("blockers") and not stuck:
            return {"retryable": True}      # only a lock a writer holds right now: the same question, asked again, answers differently (O-2)
        return {"retryable": False, "needs": (stuck or [{}])[0].get("needs", "unknown")}
    if state not in ("refused", "invalid", "deferred", "failed", "no_store", "ok") or (state == "ok" and "wouldRefuse" not in answer):
        return {}
    if reason == "engines_not_confirmed":
        needs = "plugin_update"
    elif reason == "home_state_denied":
        needs = "home_state"
    elif reason == "blank_over_limit":
        needs = "confirm_blank"
    elif reason == "owner_unbound":
        needs = "owner_bind"
    elif state == "deferred":
        needs = "owner_repair"
    elif reason == "too_large":
        needs = "smaller_bundle"            # E-3: not "pack it again" (the same size answers the same) but "pack it under ``limitBytes``"
    elif reason in _INVALID_BUNDLE:
        needs = "new_bundle"
    elif reason == "check_failed":
        needs = "engine_update"
    elif state == "no_store":
        needs = "store"
    elif reason in ("ids_unreadable", "keep_ids_unreadable"):
        needs = "ids_file"
    elif answer.get("cause") == "disk_full":
        needs = "disk_space"
    elif reason == "PermissionError":
        needs = "permission"
    elif reason == "sqlite_error" or reason == "DatabaseError":
        needs = "store_repair"
    else:
        needs = "unknown"
    return {"retryable": False, "needs": needs}


# --- import ---------------------------------------------------------------------------------------------------------

class _Ledger:
    """The receiver's stamps as they stand, for the filter of step 3 (the same decision as the curation's writer, ``memory_runtime.canonical_writer``)."""

    def __init__(self, db: sqlite3.Connection, rules: dict[str, Any] | None):
        self.rules = rules
        self.layout = ms.layout_of(db)
        self.switched = ms.layout_switch_epoch(db)
        self.by_hash: dict[str, list[tuple[str, str, int, bool]]] = {}
        for kind, digest, owner_key, epoch, source in db.execute("SELECT memory_kind,content_hash,owner_key,revoked_epoch,source_memory_id FROM memory_revocations"):
            self.by_hash.setdefault(digest, []).append((kind, owner_key, int(epoch), ms.stamp_is_personal_only(source)))

    _live: "dict[str, list[tuple[str, str]]] | None" = None

    def live_line(self, db: sqlite3.Connection, digest: str, kinds: set[str]) -> str | None:
        """The id of a live Personal line of the receiver with these words (``content_hash``) and one of these kinds; built once per import, kept up to date by ``note_live``."""
        if self._live is None:
            self._live = {}
            for ident, kind, content in db.execute("SELECT id,kind,content FROM memory_entries WHERE scope=? AND superseded_at IS NULL AND content<>'' ORDER BY created_at,id", (PERSONAL_SCOPE,)):
                self._live.setdefault(_hash(content), []).append((ident, kind))
        for ident, kind in self._live.get(digest, ()):
            if kind in kinds:
                return ident
        return None

    def note_live(self, digest: str, ident: str, kind: str) -> None:
        if self._live is not None:
            self._live.setdefault(digest, []).append((ident, kind))

    def matches(self, kind: str, text: str) -> bool:
        kinds = _kinds_of(self.rules, kind)
        for form in memory_classify.forget_forms(text, self.rules):
            for stamp_kind, owner_key, epoch, personal_only in self.by_hash.get(_hash(form), ()):
                if self.rules is not None and stamp_kind not in kinds:
                    continue
                if personal_only:                           # an imported stamp: the Personal key only, in every layout
                    if owner_key == personal_key():
                        return True
                elif self.layout == ms.CENTRAL:
                    if owner_key == personal_key():
                        return True
                elif self.switched > 0:
                    if epoch > self.switched or owner_key == personal_key():
                        return True
                else:
                    return True
        return False


def _stamp_epoch(db: sqlite3.Connection) -> int:
    """The number an imported stamp gets (the schema wants more than 0). What it holds for does not depend on it: the stamp's source marks it as Personal-only for every reader, and the
    switch boundary is not written here. With a boundary the number is the boundary (an engine copy that does not know the marker then still reads the stamp as that owner's words); otherwise the clock,
    and at least 1."""
    clock = ms._root_clock(db) or 0
    switched = ms.layout_switch_epoch(db)
    if switched > 0:
        epoch = switched
    else:
        epoch = max(clock, 1)
    if epoch > clock:
        db.execute("UPDATE memory_forget_clock SET epoch=? WHERE id=1", (epoch,))
    return epoch


def _bundle_stamps(bundle: sqlite3.Connection) -> list[tuple[str, str, str | None]]:
    """The bundle's Personal stamps that are well formed, as (kind, hash, time). Anything else in the ledger table is not read."""
    if "memory_revocations" not in split._tables(bundle):
        return []
    out = []
    for r in bundle.execute("SELECT memory_kind,content_hash,revoked_at FROM memory_revocations WHERE owner_key=?", (personal_key(),)):
        kind, digest, at = r["memory_kind"], r["content_hash"], r["revoked_at"]
        if not isinstance(kind, str) or not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            continue
        out.append((kind, digest, at if isinstance(at, str) else None))
    return out


def _merge_stamps(db: sqlite3.Connection, bundle: sqlite3.Connection) -> tuple[list[tuple[str, str]], int]:
    """Step 1. Returns the bundle's Personal stamps as (kind, hash) and how many were new to the receiver's ledger. The stamp's source is the fixed text of
    ``memory_stores.ONE_PACK_STAMP_SOURCE``, never the bundle's value: the stamp then holds for Personal lines only and no id of this computer can be named through it."""
    wanted = _bundle_stamps(bundle)
    new = 0
    db.execute("BEGIN IMMEDIATE")
    try:
        epoch = None
        for kind, digest, at in wanted:
            if epoch is None:
                epoch = _stamp_epoch(db)
            new += db.execute("INSERT INTO memory_revocations(revocation_id,owner_key,memory_kind,content_hash,source_memory_id,revoked_epoch,revoked_at) VALUES(?,?,?,?,?,?,?) "
                              "ON CONFLICT(owner_key,memory_kind,content_hash) DO NOTHING",
                              ("mrv_" + uuid.uuid4().hex, personal_key(), kind, digest, ms.ONE_PACK_STAMP_SOURCE, epoch, at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))).rowcount
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return [(k, d) for k, d, _a in wanted], new


def _scrub_tickets(db: sqlite3.Connection, ids: list[str], now: str) -> None:
    """What a forget also empties: the episode summaries, observed turns and continuation hints of the turns that carried a blanked line's words, as ``memory_split.forget`` does (that rule is not
    changed) but only for the personal agent's own turns (a ticket with no project and no agent): the owner moved the personal memory, not the sessions of a project or of another agent."""
    tables = split._tables(db)
    if "memory_tickets" not in tables:
        return                                   # no way to tell whose turn it was: nothing is emptied
    tickets: set[str] = set()
    for chunk in split._chunks(ids):
        marks = split._marks(len(chunk))
        if "memory_decisions" in tables:
            tickets.update(r[0] for r in db.execute(f"SELECT ticket_id FROM memory_decisions WHERE target_memory_id IN ({marks})", chunk))
        if "memory_origin_links" in tables:
            tickets.update(r[0] for r in db.execute(f"SELECT source_id FROM memory_origin_links WHERE source_kind='memory-ticket' AND memory_id IN ({marks})", chunk))
    if not tickets:
        return
    personal_turns: set[str] = set()
    for chunk in split._chunks(sorted(tickets)):
        personal_turns.update(r[0] for r in db.execute(
            f"SELECT ticket_id FROM memory_tickets WHERE ticket_id IN ({split._marks(len(chunk))}) AND COALESCE(project_id,'')='' AND COALESCE(agent_id,'')=''", chunk))
    tickets = personal_turns
    if not tickets:
        return
    for chunk in split._chunks(sorted(tickets)):
        marks = split._marks(len(chunk))
        if "memory_episodes" in tables:
            db.execute(f"UPDATE memory_episodes SET summary=NULL,summary_hash=NULL,embedding_model=NULL,embedding_adapter=NULL,embedding_model_sha256=NULL,"
                       f"embedding_content_hash=NULL,embedding_dimensions=NULL,embedding_json=NULL WHERE ticket_id IN ({marks})", chunk)
        if "memory_session_checkpoints" in tables:
            db.execute(f"DELETE FROM memory_session_checkpoints WHERE json_valid(payload_json) AND json_extract(payload_json,'$.ticket_ref') IN ({marks})", chunk)
        if "memory_operations" in tables:
            db.execute(f"UPDATE memory_operations SET payload_json='{{}}' WHERE payload_json<>'{{}}' AND operation_id IN ({marks})", chunk)
    if "memory_session_checkpoint_heads" in tables and "memory_session_checkpoints" in tables:
        db.execute("DELETE FROM memory_session_checkpoint_heads WHERE checkpoint_id NOT IN (SELECT checkpoint_id FROM memory_session_checkpoints)")


def _hit_rows(db: sqlite3.Connection, stamps: list[tuple[Any, ...]], rules: dict[str, Any] | None) -> list[Any]:
    """The receiver's live Personal lines that the stamps (kind, hash, ...) match: what step 2 blanks. Reads only."""
    wanted: dict[str, set[str]] = {}
    for stamp in stamps:
        wanted.setdefault(stamp[1], set()).add(stamp[0])
    hit: list[Any] = []
    if not wanted:
        return hit
    for row in db.execute("SELECT id,scope,kind,content,project_id,project_path,agent_id,chat_id FROM memory_entries WHERE scope=? AND superseded_at IS NULL AND content<>''", (PERSONAL_SCOPE,)):
        if not isinstance(row["content"], str) or not isinstance(row["kind"], str):
            continue
        kinds = _kinds_of(rules, row["kind"])
        for form in memory_classify.forget_forms(row["content"], rules):
            stamped = wanted.get(_hash(form))
            if stamped and (rules is None or stamped & kinds):
                hit.append(row)
                break
    return hit


def _blank_matched(db: sqlite3.Connection, stamps: list[tuple[str, str]], rules: dict[str, Any] | None) -> tuple[int, int]:
    """Step 2. The receiver's live Personal lines that a stamp matches are blanked (and the older versions they replaced, by id, the same owner only). Returns (lines, older versions)."""
    if not stamps:
        return 0, 0
    hit = _hit_rows(db, stamps, rules)
    if not hit:
        return 0, 0
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    older: dict[str, Any] = {}
    for row in hit:
        found, _left = split._supersede_ancestors([(None, db)], row)
        for old in found:
            older[old["id"]] = old
    ids = sorted({r["id"] for r in hit} | set(older))
    db.execute("PRAGMA secure_delete=ON")   # the pages the words leave are overwritten, not just unlinked
    db.execute("BEGIN IMMEDIATE")
    try:
        _scrub_tickets(db, ids, now)
        ms._blank(db, ids, now)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return len(hit), len(older)


def _note_rejected(counts: dict[str, Any], ident: Any) -> None:
    """Remember the id of a refused line, for the sender's purge (``rejectedIds``): a line that never arrived must not be deleted there. Capped; past the cap the answer says it is incomplete."""
    if not isinstance(ident, str) or len(ident) > ENTRY_ID_MAX_CHARS:
        return                                   # no purge list holds an id that is not text or is longer than any id (and the answer must not carry a hostile megabyte)
    listed = counts.setdefault("rejectedIds", [])
    if len(listed) < REJECTED_IDS_CAP:
        listed.append(ident)
    else:
        counts["rejectedIdsTruncated"] = True


def _taken_embedding(row: Any, names: list[str]) -> dict[str, Any]:
    """The embedding columns of a bundle line that look like an embedding (short names, a dimension number, a JSON text of bounded size); anything else is left empty and the receiver builds the vector again."""
    out = {c: None for c in EMBEDDING_COLS}
    if not all(c in names for c in EMBEDDING_COLS):
        return out
    model, adapter, sha, content_hash, dims, blob = (row[c] for c in EMBEDDING_COLS)
    texts_ok = all(v is None or (isinstance(v, str) and len(v) <= EMBEDDING_TEXT_MAX) for v in (model, adapter, sha, content_hash))
    dims_ok = dims is None or (isinstance(dims, int) and not isinstance(dims, bool) and 0 < dims <= 8192)
    blob_ok = blob is None or (isinstance(blob, str) and len(blob) <= EMBEDDING_JSON_MAX)
    if texts_ok and dims_ok and blob_ok:
        out.update(embedding_model=model, embedding_adapter=adapter, embedding_model_sha256=sha, embedding_content_hash=content_hash, embedding_dimensions=dims, embedding_json=blob)
    return out


_NATIVE_COLUMNS = {"entry_id", "content_native", "created_at"}


def _native_table(db: sqlite3.Connection) -> bool | None:
    """The receiver's original-wording table: True (a table with the three columns this module writes), False (something of that name that is not one: a view, a table of another shape), None (nothing)."""
    row = db.execute("SELECT type FROM sqlite_master WHERE name=?", (_NATIVE,)).fetchone()
    if row is None:
        return None
    if row[0] != "table":
        return False
    return _NATIVE_COLUMNS <= {r[1] for r in db.execute(f"PRAGMA table_info({_NATIVE})")}


def _ensure_native_table(db: sqlite3.Connection) -> bool:
    """Whether the receiver can store original wording now; makes the table with the engine's one DDL (``memory_runtime.NATIVE_TABLE_DDL``) when there is none (N-2). Runs inside the batch's transaction."""
    state = _native_table(db)
    if state is None:
        try:
            db.execute(NATIVE_TABLE_DDL)
        except sqlite3.Error:
            return False
        state = _native_table(db)
    return state is True


def _same_line(db: sqlite3.Connection, ident: str, taken: Any, text: str, native: Any, rules: dict[str, Any] | None = None) -> bool:
    """Whether the receiver's row with this id says what the bundle's line says: the same words (``content_hash``), or the same original wording (the receiver may have translated the line, or the bundle's text
    may be the translation, since an earlier call put it there)."""
    if isinstance(taken, str) and taken != "" and _hash(taken) in {_hash(form) for form in memory_classify.forget_forms(text, rules)}:
        return True                                         # the same words, one trailing mark more or less (the forms a stamp of these words matches)
    if isinstance(native, str) and isinstance(taken, str) and taken == native:
        return True
    if _native_table(db) is True:
        got = db.execute(f"SELECT content_native FROM {_NATIVE} WHERE entry_id=?", (ident,)).fetchone()
        if got is not None and isinstance(got[0], str) and (got[0] == text or (isinstance(native, str) and got[0] == native)):
            return True
    return False


def _attach_native(db: sqlite3.Connection, counts: dict[str, Any], target: str, native: Any, created_at: Any) -> str:
    """The original wording of a bundle line whose words the receiver already holds (a line of the same id, or another id with the same words): attached to the receiver's line, so the sender's purge does not take the
    only copy of it. The receiver's line itself is not touched, and a wording it already has is never overwritten. ``attached`` | ``has`` (the receiver's line has one) | ``same`` (it is the receiver's own text: the desktop
    stores no wording equal to the text) | ``none`` (nothing to attach) | ``failed`` (the receiver cannot store it: the caller refuses the line, the sender keeps it). The id of the receiver's line is listed in
    ``nativeAttachedIds``, not in ``insertedIds``: it is the home's own line, not one this import added."""
    if not isinstance(native, str):
        return "none"
    row = db.execute("SELECT content FROM memory_entries WHERE id=?", (target,)).fetchone()
    if row is None:
        return "failed"
    if native.strip() == (row[0] or "").strip():
        return "same"
    if _native_table(db) is True and db.execute(f"SELECT 1 FROM {_NATIVE} WHERE entry_id=?", (target,)).fetchone():
        return "has"
    if not _ensure_native_table(db):
        return "failed"
    db.execute("SAVEPOINT one_pack_attach")
    try:
        db.execute(f"INSERT INTO {_NATIVE}(entry_id,content_native,created_at) VALUES(?,?,?)", (target, native, created_at if isinstance(created_at, str) else "1970-01-01T00:00:00Z"))
    except sqlite3.Error:
        db.execute("ROLLBACK TO one_pack_attach")
        db.execute("RELEASE one_pack_attach")
        return "failed"
    db.execute("RELEASE one_pack_attach")
    counts["nativeAttached"] = counts.get("nativeAttached", 0) + 1
    listed = counts.setdefault("nativeAttachedIds", [])
    if len(listed) < INSERTED_IDS_CAP:
        listed.append(target)
    else:
        counts["nativeAttachedIdsTruncated"] = True
    return "attached"


def _refuse(counts: dict[str, Any], ident: Any, why: str) -> None:
    counts["rejected"] += 1
    by = counts.setdefault("rejectedBy", {})
    by[why] = by.get(why, 0) + 1
    _note_rejected(counts, ident)


def _insert_batch(db: sqlite3.Connection, owner: str, bundle: sqlite3.Connection, batch: list[sqlite3.Row], ledger: _Ledger, live: dict[str, set[str]],
                  counts: dict[str, Any], has_native: bool, names: list[str], trusted: bool = False, plan: dict[str, Any] | None = None) -> None:
    """One transaction of an import. ``trusted``: the bundle comes from the computer the owner approved as the home (a move); then a line's ``confidence`` and ``sensitivity`` are kept when they are in the closed sets
    of ``memory_runtime`` (``CONFIDENCE_VALUES``, ``SENSITIVITY_VALUES``), and are this computer's usual values when they are not. Without it (the old-record road) they are always the usual values: a sender that is
    not trusted must not raise the rank of its own lines. The batch is taken in the order of the bundle (``tier_order_sql``, newest first inside a kind). ``plan`` is the ceiling (``_ceiling_room``): ``room`` lines may come in and every line that reaches the point of being placed and counts towards the ceiling uses one, a line already here (``idTaken``) included;
    the rest are refused as ``store_full``. On the move road a line dated before the ruleset's ``countsFrom`` does not count (it is never refused and uses no room: the normal write's own rule, so an owner's older
    lines all move); on the old-record road (``plan["every"]``) every line counts, whatever its date (a forged old date must not get a line past the ceiling). Newest first, so which lines come in does not depend on
    how the calls were cut, and ``check`` (``_would_store_full``) makes the same count."""
    from .memory_runtime import CONFIDENCE_VALUES, SENSITIVITY_VALUES
    rules = ledger.rules
    admission = _Admission(rules, strict=not trusted)
    from .memory_curation_decisions import POLICY
    # The columns of the two tables are asked once per batch, not once per line (E-4: the per-line PRAGMA table_info was 76 % of an import's time). Neither table changes inside the transaction.
    entry_have = set(split._columns(db, "memory_entries"))
    bind_have = set(split._columns(db, "memory_identity_bindings"))
    native_ready = False                                    # the original-wording table, once it is known to be usable in this transaction
    db.execute("BEGIN IMMEDIATE")
    try:
        for row in batch:
            if row["scope"] != PERSONAL_SCOPE or row["superseded_at"] is not None or row["content_len"] in (None, 0):
                counts["rejected"] += 1
                _note_rejected(counts, row["id"])
                continue
            text = _text_cell(row)
            native = _native_of(bundle, row["id"], has_native) if isinstance(row["id"], str) else None
            why = admission.reason(row["id"], row["kind"], text, native, row["created_at"])   # the entry check of a normal Personal write; a BLOB text or kind is refused here, before anything is hashed
            if why:
                counts["rejected"] += 1
                by = counts.setdefault("rejectedBy", {})
                by[why] = by.get(why, 0) + 1
                _note_rejected(counts, row["id"])
                continue
            takes = plan is not None and counts_towards_ceiling(row["created_at"], rules, every=plan["every"])
            taken = db.execute("SELECT content FROM memory_entries WHERE id=?", (row["id"],)).fetchone()
            if taken is not None:
                if plan is not None and takes:
                    plan["used"] += 1                       # it was left out of the receiver's count (``_ceiling_room``): it takes its place in the room here
                # A row of the receiver (or this same line from an earlier call) is never overwritten. The sender may delete its line only if the receiver holds THIS line (#7): the same words
                # (``idTaken``, as before), or the receiver forgot it (a blank row whose words the receiver's ledger holds: the rule of step 3). Another text under the id is refused (``id_taken``).
                if _same_line(db, row["id"], taken[0], text, native, rules):
                    if _attach_native(db, counts, row["id"], native, row["created_at"]) == "failed":
                        _refuse(counts, row["id"], "native_not_stored")       # the receiver's line has no wording and cannot take this one: the sender keeps the only copy
                    else:
                        counts["idTaken"] += 1
                elif taken[0] == "" and ledger.matches(row["kind"], text):
                    counts["skippedForgotten"] += 1
                else:
                    _refuse(counts, row["id"], "id_taken")
                continue
            if ledger.matches(row["kind"], text):
                counts["skippedForgotten"] += 1             # step 3
                continue
            digest = _hash(text)
            if live.get(digest, set()) & _kinds_of(rules, row["kind"]):
                if isinstance(native, str):                  # step 4 drops the line, so its original wording goes onto the receiver's line with the same words (follow-up)
                    target = ledger.live_line(db, digest, _kinds_of(rules, row["kind"]))
                    if target is None or _attach_native(db, counts, target, native, row["created_at"]) == "failed":
                        _refuse(counts, row["id"], "native_not_stored")
                        continue
                counts["skippedSame"] += 1                  # step 4
                continue
            if plan is not None and takes and plan["room"] is not None and plan["used"] >= plan["room"]:
                counts["rejected"] += 1                     # the receiver's Personal ceiling: the line does not come in, so the sender keeps it (``rejectedIds``)
                by = counts.setdefault("rejectedBy", {})
                by["store_full"] = by.get("store_full", 0) + 1
                _note_rejected(counts, row["id"])
                continue
            keep_native = isinstance(native, str)
            if keep_native and not native_ready:
                native_ready = _ensure_native_table(db)
            if keep_native and not native_ready:
                _refuse(counts, row["id"], "native_not_stored")      # no original wording is dropped silently: the line stays on the sender whole (N-2)
                continue
            # Only id, kind, text, date and the embedding are the bundle's (and, from a trusted sender, confidence and sensitivity inside their closed sets). Everything else is this computer's: the Personal scope, a
            # medium-confidence internal line the way a normal write makes it, no project, no agent, no chat, no evidence, no context.
            values = {"id": row["id"], "scope": PERSONAL_SCOPE, "kind": row["kind"], "content": text, "created_at": row["created_at"],
                      "project_id": None, "project_path": None, "agent_id": None, "chat_id": None,
                      "confidence": row["confidence"] if trusted and row["confidence"] in CONFIDENCE_VALUES else "medium",
                      "sensitivity": row["sensitivity"] if trusted and row["sensitivity"] in SENSITIVITY_VALUES else "internal",
                      "evidence_json": "[]", "context_json": "{}", "superseded_at": None,
                      **(_taken_embedding(row, names) if trusted else {c: None for c in EMBEDDING_COLS})}       # the old-record road takes no vector: the receiver builds its own
            cols = [c for c in values if c in entry_have]
            db.execute("SAVEPOINT one_pack_line")
            inserted = db.execute(f"INSERT OR IGNORE INTO memory_entries({','.join(cols)}) VALUES({split._marks(len(cols))})", [values[c] for c in cols]).rowcount
            if not inserted:
                db.execute("RELEASE one_pack_line")
                counts["idTaken"] += 1
                if plan is not None and takes:
                    plan["used"] += 1
                continue
            # The binding is made here and read from nowhere: this computer's owner name, the personal agent as the actor (so a forget can name an owner for the line), the curation a normal write records.
            b = {"memory_id": row["id"], "owner_namespace": owner, "actor_id": CORE_ONE_ACTOR_ID, "origin_refs_json": "[]", "applicability_json": _json(CLEAN_AUDIENCE),
                 "curation_actor": "model_curated", "policy_version": POLICY}
            bcols = [c for c in b if c in bind_have]
            db.execute(f"INSERT OR IGNORE INTO memory_identity_bindings({','.join(bcols)}) VALUES({split._marks(len(bcols))})", [b[c] for c in bcols])
            if keep_native:
                try:
                    db.execute(f"INSERT OR REPLACE INTO {_NATIVE}(entry_id,content_native,created_at) VALUES(?,?,?)", (row["id"], native, row["created_at"]))
                    counts["nativeInserted"] = counts.get("nativeInserted", 0) + 1
                except sqlite3.Error:
                    db.execute("ROLLBACK TO one_pack_line")          # the line, its binding and its original wording go together or not at all
                    db.execute("RELEASE one_pack_line")
                    _refuse(counts, row["id"], "native_not_stored")
                    continue
            db.execute("RELEASE one_pack_line")
            if plan is not None and takes:
                plan["used"] += 1
            live.setdefault(digest, set()).add(row["kind"])
            ledger.note_live(digest, row["id"], row["kind"])
            counts["inserted"] += 1
            listed = counts.setdefault("insertedIds", [])
            if len(listed) < INSERTED_IDS_CAP:
                listed.append(row["id"])
            else:
                counts["insertedIdsTruncated"] = True
        db.commit()
    except BaseException:
        db.rollback()
        raise


def _home_refusal(path: Path, rules: dict[str, Any] | None) -> dict[str, Any] | None:
    """An import is a Personal write: a store whose home mirror (``one_home_state``) says ``away`` or ``sealed`` (the ruleset's ``deniedHomeStates``; without a readable ruleset the two known words) is not
    written, and neither is a store whose mirror is PRESENT but is not one of the known words (``home``, ``away``, ``sealed``, lower case, text): a mirror that cannot be read is not a home. The normal
    write reads the same mirror the same way (``memory_classify.home_state``; F-16).
    No mirror (no table, no key: every install today), a mirror that says ``home`` or a file that cannot be opened: not refused. Reads the file read-only, so a refusal writes nothing. ``purge`` does not
    ask: the old home is ``away`` after a move and is where the old lines are deleted."""
    if not path.is_file():
        return None
    try:
        db = _ro(path)
        try:
            return _home_refusal_db(db, rules)
        finally:
            db.close()
    except (sqlite3.Error, KeyError, TypeError, ValueError, OSError):
        return None


def _home_refusal_db(db: sqlite3.Connection, rules: dict[str, Any] | None) -> dict[str, Any] | None:
    """``_home_refusal`` on a connection that is already open (the import asks again inside the lock with its own connection, so a mirror written between the first read and the lock is seen)."""
    try:
        denied = (rules["stores"][PERSONAL_SCOPE]["admission"].get("deniedHomeStates") if rules is not None else None) or ["away", "sealed"]
        row = db.execute("SELECT value FROM memory_store_meta WHERE key=?", (memory_classify.home_state_key(rules),)).fetchone()
    except (sqlite3.Error, KeyError, TypeError, ValueError):
        return None
    if row is None:
        return None
    state = row[0]
    if isinstance(state, str) and state in denied:
        return {"schema": SCHEMA, "state": "refused", "reason": "home_state_denied", "homeState": state}
    if not isinstance(state, str) or state not in memory_classify.HOME_STATES:
        return {"schema": SCHEMA, "state": "refused", "reason": "home_state_denied", "homeState": "unknown"}
    return None


def _engine_report(extra: Iterable[str]) -> tuple[int, list[dict[str, Any]]]:
    """Reads only. ``(copies counted, the copies that do not declare memory_layout >= ENGINE_STAMP_CAPABILITY)``: the one reading of the engine copies that ``import`` (``_engines_refusal``), ``check`` and ``ready`` all use,
    so their answers cannot differ (home-D4). An inventory that cannot be made confirms nothing."""
    try:
        copies = split.engine_inventory(list(extra))["copies"]
    except Exception:  # noqa: BLE001 - an inventory that cannot be made confirms nothing
        return 0, [{"host": "inventory", "state": "unconfirmed", "reason": "inventory_unreadable"}]
    low = []
    for copy in copies:
        layout = copy.get("memoryLayout")
        if isinstance(layout, int) and not isinstance(layout, bool) and layout >= ENGINE_STAMP_CAPABILITY:
            continue
        item = {k: copy[k] for k in ("host", "state", "memoryLayout", "reason") if k in copy}       # never the path: it can hold a user name
        if "memoryLayout" in item:
            item["state"] = "old"                                                                   # declared, but below this module's number
        low.append(item)
    return len(copies), low


def _engines_refusal(extra: Iterable[str]) -> dict[str, Any] | None:
    """Reads only. None when every engine copy on this computer declares ``memory_layout >= ENGINE_STAMP_CAPABILITY``."""
    total, low = _engine_report(extra)
    if not low:
        return None
    return {"schema": SCHEMA, "state": "refused", "reason": "engines_not_confirmed", "engines": {"total": total, "notConfirmed": low[:20], "notConfirmedCount": len(low)}}


def engine_fields(extra: Iterable[str]) -> dict[str, Any]:
    """What ``check`` and ``ready`` say about the engine copies, from the same reading as ``import``'s refusal: ``enginesConfirmed``; when it is false ``enginesNotConfirmed`` (the number) and ``engines``: one item
    per copy that is not confirmed (at most 20): ``host``, ``layout`` (the number the copy declares, null when it declares none or cannot be read), ``required`` (what this module needs), ``state`` (``old`` | ``unconfirmed``)
    and, when the copy could not be read, ``reason``. Hosts and numbers only, never a path."""
    total, low = _engine_report(extra)
    answer: dict[str, Any] = {"enginesConfirmed": not low, "enginesTotal": total}
    if low:
        answer["enginesNotConfirmed"] = len(low)
        answer["engines"] = [{"host": c.get("host"), "layout": c.get("memoryLayout"), "required": ENGINE_STAMP_CAPABILITY, "state": c.get("state"), **({"reason": c["reason"]} if "reason" in c else {})} for c in low[:20]]
    return answer


def import_rows(owner: str, bundle_path: str | os.PathLike[str], *, pause: float = PAUSE_SECONDS, batch_rows: int = BATCH_ROWS,
                confirm_blank: int | None = None, engines: Iterable[str] = (), check_engines: bool = True, no_stamps: bool = False, limit_bytes: int | None = None) -> dict[str, Any]:
    """Merge a bundle into the receiving root (steps 1 to 5 in the module text). Safe to call again after any interruption.

    ``confirm_blank``: the number of live Personal lines the stamps would blank, as ``check`` answered it. When that number is above ``BLANK_LIMIT`` and the call does not give exactly it, nothing is
    written and the answer is ``refused`` / ``blank_over_limit`` with ``wouldBlank``. A call that repeats after a crash finds the lines already blank (the count is then small): it goes on.

    ``engines``: more engine copies to count (the desktop's bundled engine). Before anything is written every engine copy on this computer must declare ``memory_layout >= ENGINE_STAMP_CAPABILITY``; one that
    declares less, nothing, or cannot be read makes the answer ``refused`` / ``engines_not_confirmed`` (host labels and numbers only, never a path), in every layout. The answer lists ``rejectedIds`` (the ids of the
    lines this call refused, at most ``REJECTED_IDS_CAP``; ``rejectedIdsTruncated`` when there were more): the sender's ``purge`` must leave those. It also lists ``insertedIds`` (the ids of the lines this call
    added, at most ``INSERTED_IDS_CAP``; ``insertedIdsTruncated`` when there were more): the caller marks where they came from by that list, not by the shape of an id. A line that an earlier, interrupted call
    added is not in the list of the call that finishes the job.

    ``no_stamps``: take no forget stamp from the bundle and blank no line of this computer (the old-record road: the sender is a computer that was not the home, and what it forgot is not the owner's word on this
    one; B1). Steps 1 and 2 are skipped, ``blanked`` and ``wouldBlank`` are 0; step 3 still uses this computer's own stamps. Without it (a move) the behaviour is what it was."""
    verdict = check(bundle_path, no_stamps=no_stamps, limit_bytes=limit_bytes)
    if verdict["state"] != "ok":
        return {"schema": SCHEMA, "state": "invalid", "reason": verdict["reason"], **{k: verdict[k] for k in ("limitBytes", "maxLimitBytes", "bundleBytes") if k in verdict}}
    from .memory_runtime import MemoryRuntime, memory_path
    rules = memory_classify.active()
    refused = _home_refusal(memory_path(owner), rules)
    if refused:
        return refused
    if check_engines:
        refused = _engines_refusal(engines)
        if refused:
            return refused
    rt = MemoryRuntime(owner, timeout=5.0)
    try:
        folder = rt.path.parent
        with split.SplitLock(folder) as free:
            if not free:
                return {"schema": SCHEMA, "state": "busy"}
            db = rt.db
            refused = _home_refusal_db(db, rules)          # the mirror again, inside the lock: a home that moved away since the first read is not written to
            if refused:
                return refused
            bundle = _open_bundle(long_path.extended(Path(bundle_path)))
            try:
                if no_stamps:
                    stamps, new_stamps, blanked, older = [], 0, 0, 0
                else:
                    would = len(_hit_rows(db, _bundle_stamps(bundle), rules))                   # read only: nothing is written before the number is known
                    if would > BLANK_LIMIT and would != confirm_blank:
                        return {"schema": SCHEMA, "state": "refused", "reason": "blank_over_limit", "wouldBlank": would, "limit": BLANK_LIMIT}
                    stamps, new_stamps = _merge_stamps(db, bundle)                              # 1
                    blanked, older = _blank_matched(db, stamps, rules)                          # 2
                ledger = _Ledger(db, rules)
                plan = {"room": _ceiling_room(db, bundle, rules), "used": 0, "every": no_stamps}
                live: dict[str, set[str]] = {}
                for kind, content in db.execute("SELECT kind,content FROM memory_entries WHERE scope=? AND superseded_at IS NULL AND content<>''", (PERSONAL_SCOPE,)):
                    live.setdefault(_hash(content), set()).add(kind)
                counts: dict[str, Any] = {"inserted": 0, "skippedForgotten": 0, "skippedSame": 0, "idTaken": 0, "rejected": 0, "nativeInserted": 0, "nativeAttached": 0, "nativeAttachedIds": [], "insertedIds": []}
                names = split._columns(bundle, "memory_entries")
                has_native = _NATIVE in split._tables(bundle)
                # By kind, newest first inside a kind (see ``_insert_batch``). The order is read once, as row numbers, and the lines are fetched in slices of it: a walk that continues "after the last line seen" by (date, id) loses every line
                # after one whose date is NULL or of another type, and a line never visited is in no ``rejectedIds`` and is deleted by the sender's purge (#10).
                order = [r[0] for r in bundle.execute(f"SELECT rowid FROM memory_entries ORDER BY {tier_order_sql()},created_at DESC,id DESC")]
                first = True
                admission = _Admission(rules, strict=no_stamps)
                for start in range(0, len(order), max(1, batch_rows)):
                    batch = bundle.execute(_entry_select(bundle, f"WHERE rowid IN (SELECT value FROM json_each(?)) ORDER BY {tier_order_sql()},created_at DESC,id DESC"),
                                           (admission.read_limit, json.dumps(order[start:start + max(1, batch_rows)]))).fetchall()
                    if not batch:
                        break
                    if not first and pause > 0:
                        time.sleep(pause)   # a writer waiting for the root's lock comes back inside this gap
                    first = False
                    _insert_batch(db, owner, bundle, batch, ledger, live, counts, has_native, names, trusted=not no_stamps, plan=plan)
            finally:
                bundle.close()
            left: list[str] = []
            left_reasons: dict[str, str] = {}
            if not split.drop_recall_index(folder):
                left.append("recall_index")
            why = split.refresh_views_reason(rt, owner)
            if why:
                left.append("views")
                left_reasons["views"] = why
        answer = {"schema": SCHEMA, "state": "partial" if left else "imported", "stampsInBundle": len(stamps), "stampsNew": new_stamps,
                  "blanked": blanked, "blankedOlder": older, **counts}
        if left:
            answer["left"] = left
            if left_reasons:
                answer["leftReasons"] = left_reasons
        return answer
    finally:
        rt.close()


# --- purge ----------------------------------------------------------------------------------------------------------

def purge(owner: str, ids: Iterable[str], keep: Iterable[str] = ()) -> dict[str, Any]:
    """Delete the Personal rows named in ``ids`` from the sender's root store and nothing else. Safe to call again (an id already gone counts as gone).
    ``keep``: ids that are not deleted although listed (the lines the receiver refused, so they never arrived); the answer says how many (``kept``)."""
    from .memory_runtime import memory_path, MemoryRuntime
    kept_ids = {i for i in keep if isinstance(i, str)}
    listed = list(dict.fromkeys(i for i in ids if isinstance(i, str) and i and len(i) <= ENTRY_ID_MAX_CHARS))
    wanted = [i for i in listed if i not in kept_ids]
    kept_count = len(listed) - len(wanted)
    if not memory_path(owner).is_file():
        return {"schema": SCHEMA, "state": "no_store"}
    rt = MemoryRuntime(owner, timeout=5.0)
    try:
        folder = rt.path.parent
        with split.SplitLock(folder) as free:
            if not free:
                return {"schema": SCHEMA, "state": "busy"}
            purged = gone = 0
            skipped: list[dict[str, str]] = []
            skipped_total = 0
            first = True
            for chunk in split._chunks(wanted, PURGE_BATCH):
                found = {r["id"]: r["scope"] for r in rt.db.execute(f"SELECT id,scope FROM memory_entries WHERE id IN ({split._marks(len(chunk))})", chunk)}
                mine: list[str] = []
                for ident in chunk:
                    if ident not in found:
                        gone += 1
                    elif found[ident] != PERSONAL_SCOPE:
                        skipped_total += 1
                        if len(skipped) < SKIPPED_LIST_CAP:
                            skipped.append({"id": ident, "reason": "not_personal"})
                    else:
                        mine.append(ident)
                if mine:
                    if not first:
                        time.sleep(PAUSE_SECONDS)
                    first = False
                    split.purge_entries(rt, mine)
                    purged += len(mine)
            left: list[str] = []
            left_reasons: dict[str, str] = {}
            if not split.drop_recall_index(folder):
                left.append("recall_index")
            why = split.refresh_views_reason(rt, owner)
            if why:
                left.append("views")
                left_reasons["views"] = why
        answer: dict[str, Any] = {"schema": SCHEMA, "state": "partial" if left else "purged", "purged": purged, "alreadyGone": gone, "skippedTotal": skipped_total, "kept": kept_count}
        if skipped:
            answer["skipped"] = skipped
        if left:
            answer["left"] = left
            if left_reasons:
                answer["leftReasons"] = left_reasons
        return answer
    finally:
        rt.close()


# --- command line ---------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="one_pack", description="Pack, check, import and purge the personal agent's memory (Agentlas 2.0 O-M2); one JSON line per call")
    commands = parser.add_subparsers(dest="command", required=True)
    export_p = commands.add_parser("export", help="write the Personal bundle (a SQLite file); the sender's store is only read")
    export_p.add_argument("--out", required=True)
    export_p.add_argument("--ids-out", default=None, help="also write the list of ids the bundle holds, for a later purge")
    export_p.add_argument("--no-embeddings", action="store_true")
    export_p.add_argument("--no-stamps", action="store_true", help="carry no forget stamp (the old-record road, where the receiver must not blank its own lines)")
    export_p.add_argument("--budget-bytes", type=int, default=None, help="leave the embeddings out when the bundle is larger than this")
    export_p.add_argument("--limit-bytes", type=int, default=None, help="the most the bundle file may be (default: the size check's limit); the newest lines are packed up to it and the rest stay on this computer (partial)")
    measure_p = commands.add_parser("measure", help="what export (with the same arguments) would pack and how large the bundle file would be, without writing anything")
    measure_p.add_argument("--no-embeddings", action="store_true")
    measure_p.add_argument("--no-stamps", action="store_true")
    measure_p.add_argument("--budget-bytes", type=int, default=None)
    measure_p.add_argument("--limit-bytes", type=int, default=None, help="the room the bundle file has (default: the size check's limit)")
    measure_p.add_argument("--out", default=None, help="the file export will write: also answer whether its folder can take it (outWritable, outFreeBytes, outRoom); nothing is made")
    ready_p = commands.add_parser("ready", help="whether this computer can take an import, asked before a move starts and without a bundle (read only): engine copies, owner, store, original-wording table")
    ready_p.add_argument("--engine", action="append", default=[], metavar="ROOT", help="another engine copy to count (the desktop's bundled engine); give the same ones as to import")
    ready_p.add_argument("--need-bytes", type=int, default=None, help="the room the import needs (the bundle's size is a fair number): the answer then says the free bytes and refuses a disk that has less")
    check_p = commands.add_parser("check", help="whether a bundle can be imported; also how many of this computer's Personal lines its stamps would blank")
    check_p.add_argument("--bundle", required=True)
    check_p.add_argument("--no-stamps", action="store_true", help="the import will take no stamp (old-record road): wouldBlank is 0")
    check_p.add_argument("--limit-bytes", type=int, default=None, help="the largest bundle file to open (default: 8 MiB + 64 KiB; at most 100 MiB + 64 KiB); give the number the sender packed under")
    check_p.add_argument("--engine", action="append", default=[], metavar="ROOT", help="another engine copy to count (the desktop's bundled engine); give the same ones as to import: the answer then says what import would refuse before it writes")
    import_p = commands.add_parser("import", help="merge a bundle into this computer's store")
    import_p.add_argument("--bundle", required=True)
    import_p.add_argument("--no-stamps", action="store_true", help="the old-record road, for a sender that is not the approved home: take no forget stamp (blank no line of this computer) and no confidence or sensitivity from the bundle; a move does not pass it")
    import_p.add_argument("--engine", action="append", default=[], metavar="ROOT", help="another engine copy to count (the desktop's bundled engine)")
    import_p.add_argument("--limit-bytes", type=int, default=None, help="the largest bundle file to open (default: 8 MiB + 64 KiB; at most 100 MiB + 64 KiB); give the same number as to check")
    import_p.add_argument("--confirm-blank", type=int, default=None, help="the exact number of Personal lines the owner agreed to blank, when it is over the limit")
    purge_p = commands.add_parser("purge", help="delete the listed Personal rows from this computer's store")
    purge_p.add_argument("--ids-file", required=True, help="a JSON array of ids")
    purge_p.add_argument("--keep-ids-file", default=None, help="a JSON array of ids that are NOT deleted (the lines the receiver refused)")
    args = parser.parse_args(argv)
    from .memory_runtime import owner_binding

    def say(result: dict[str, Any]) -> int:
        print(_json({**result, **retry_hint(result), "features": FEATURES}))
        return 0

    def bound() -> tuple[str | None, str | None]:
        """The owner this computer's store belongs to, or the reason there is none: the one question every command that needs the store asks first (so ``measure`` and ``export`` can never answer differently)."""
        try:
            return owner_binding(create=False) or None, None
        except ValueError as error:
            return None, str(error)

    if args.command == "check":
        receiver, _why = bound()           # no owner yet: the file is checked, there is nothing to count against
        try:
            result = check(args.bundle, receiver=receiver, no_stamps=args.no_stamps, engines=args.engine, limit_bytes=args.limit_bytes)
        except Exception as error:  # noqa: BLE001 - whatever the file is, the answer is a code (a traceback is no answer)
            result = {"schema": SCHEMA, "state": "invalid", "reason": "check_failed", "error": type(error).__name__}
        return say(result)
    if args.command == "ready":
        receiver, why = bound()
        try:
            result = ready(receiver, engines=args.engine, owner_reason=why, need_bytes=args.need_bytes)
        except Exception as error:  # noqa: BLE001 - a question that cannot be answered is not "ready"
            result = {"schema": SCHEMA, "state": "failed", "reason": type(error).__name__}
        return say(result)
    owner, why = bound()
    if not owner:
        return say({"schema": SCHEMA, "state": "deferred", "reason": why or "owner_unbound"})
    try:
        if args.command == "export":
            result = export(owner, args.out, with_embeddings=not args.no_embeddings, budget_bytes=args.budget_bytes, no_stamps=args.no_stamps, limit_bytes=args.limit_bytes)
            if result.get("state") == "packed" and args.ids_out:
                write_ids(owner, args.out, args.ids_out)
        elif args.command == "measure":
            result = measure(owner, no_stamps=args.no_stamps, with_embeddings=not args.no_embeddings, budget_bytes=args.budget_bytes, limit_bytes=args.limit_bytes)
            if args.out and result.get("state") == "measured":
                result.update(out_room(args.out, int(result["estimatedBytes"])))
        elif args.command == "import":
            result = import_rows(owner, args.bundle, confirm_blank=args.confirm_blank, engines=args.engine, no_stamps=args.no_stamps, limit_bytes=args.limit_bytes)
        else:
            try:
                listed = json.loads(Path(args.ids_file).read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return say({"schema": SCHEMA, "state": "failed", "reason": "ids_unreadable"})
            if not isinstance(listed, list):
                return say({"schema": SCHEMA, "state": "failed", "reason": "ids_unreadable"})
            keep: list[Any] = []
            if args.keep_ids_file:
                try:
                    keep = json.loads(Path(args.keep_ids_file).read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    keep = None                                    # type: ignore[assignment]
                if not isinstance(keep, list):
                    return say({"schema": SCHEMA, "state": "failed", "reason": "keep_ids_unreadable"})
            result = purge(owner, listed, keep)
    except sqlite3.OperationalError as error:
        text = str(error).lower()
        result = {"schema": SCHEMA, "state": "remaining" if ("locked" in text or "busy" in text) else "failed", "reason": "locked" if ("locked" in text or "busy" in text) else "sqlite_error"}
        if "full" in text and result["state"] == "failed":
            result["cause"] = "disk_full"
    except (sqlite3.Error, OSError, ValueError) as error:
        result = {"schema": SCHEMA, "state": "failed", "reason": type(error).__name__}
        if getattr(error, "errno", None) == 28:                    # ENOSPC
            result["cause"] = "disk_full"
    return say(result)


if __name__ == "__main__":
    raise SystemExit(main())
