"""What the 2.0 first-run migration would do to one owner's memory, reported without touching it.

``plan`` reads the root store, the One drawer file and the agent folders and answers in counts: which rows are
personal, which the One drawer brought in and which project each was learned in, which agents have a folder for their
memory, how many turn records left no memory and can go, how many rows the move would take, and which engine copies on
this computer are older than the split. Nothing here writes: every SQLite file is opened read-only in a way that
creates no ``-wal``/``-shm``/journal file (see ``open_readonly``), no lock file is made, no meta key is set, no model is
called. A part that cannot be read (locked, damaged, missing) is reported as ``unreadable`` with a code and the rest
goes on.

The report carries counts and hashed identifiers only: no memory text, no path, no project name. A path or a project
label appears as the first 8 hex digits of its sha256; an agent appears as its id.

Later packages reuse this module instead of counting a second way: ``empty_turn_condition`` is the definition of "a
turn that left no memory" for the cleanup, and ``read_drawer`` / ``ProjectFolders`` / ``EntryScan`` are the
source-project lookup for the reclassification.

Command line: ``python3 -m agentlas_cloud.first_run plan [--pretty] [--project [ID=]FOLDER]... [--projects-under DIR]...
[--agent-routes FILE]`` prints one JSON line (``--pretty``: a table for people).

The commands ``steps`` and ``vacuum`` are answered by ``first_run_steps``, and ``reclassify``, ``undo``, ``label_candidates``,
``apply_labels`` and ``llm_state`` by ``first_run_classify``; they do the writing. This module stays the read-only half and has no way to
write (a test holds it to that); it also holds the one definition of where a line was learned (``EntryScan``) that the preview counts with and 5a moves by.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, NamedTuple

from . import agent_home
from . import long_path
from . import memory_stores as ms
from .memory_actor_family import DESKTOP_ONE_ACTOR_ID, is_one_memory_actor
from .memory_scopes import contract, owner_scope_of
from .project_identity import MARKER_RELATIVE

SCHEMA = "agentlas.first-run-plan.v1"
STEPS_SCHEMA = "agentlas.first-run-steps.v1"
STEP_NAMES = ("engine_copies", "empty_turns", "tidy", "memory_move")
KEEP_EMPTY_TURN_DAYS = 30        # the one-line summary of a turn that left no memory lives 30 days
STALE_TURN_DAYS = 7              # a turn still `received` / `deferred` after this long is never finished by anyone
WORK_ROW_GRACE_HOURS = 24        # an empty turn's operation row only guards against the same turn arriving again
RECLASSIFY_MIN_SHARE = 0.20      # §11.2: below this share of drawer rows with one project, do not reclassify
LIST_LIMIT = 200                 # agents / projects listed one by one; the rest is a count
META_ONE_IMPORT_RETIRED = "one-import:retired"
META_CLASSIFIED = "first_run_classified"
META_LLM = "first_run_llm"
LABEL_KINDS = ("fact", "decision", "procedure", "risk")   # a resident row of these kinds may be offered for the person labelling (5b); a preference is already Personal's kind
LABEL_TEXT_CHARS = 400                                    # what one row sends to the model
PERSON = re.compile(r"\b(?:user|owner)(?:'s)?\b|사용자|오너", re.IGNORECASE)
_PERSON_LIKE = ("%user%", "%owner%", "%사용자%", "%오너%")
_ONE_SOUL = re.compile(r'"one-soul:([0-9a-f]{16})"')
_SUPERSEDES = re.compile(r'"supersedes:([^"\\]+)"')
_BLOCK_HASH = re.compile(r"<!--\s*h:([0-9a-f]{16})\s*-->")
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:_.@-]{0,79}$")
_PHOTO = re.compile(r"^one-avatar\.(?:png|jpe?g|webp)$", re.IGNORECASE)
_CLOUD_MARKER = ".agentlas-cloud-package.json"
# Rows that nothing points at; the preview counts them and ``first_run_steps`` removes them, from this one definition.
ORPHAN_SOURCES = ("reader_contract='core.memory-operation.v1' AND logical_key NOT IN "
                  "(SELECT operation_id FROM memory_operations WHERE operation_id IS NOT NULL)")
ORPHAN_VERSIONS = "source_id NOT IN (SELECT source_id FROM memory_source_catalogue WHERE source_id IS NOT NULL)"
RECEIPTS = "target_table<>'memory_entries'"
_VERSION = re.compile(r"^v?\d+\.\d+\.\d+[\w.+-]*$")
# Bytes of a text column without loading it where SQLite can (3.43+); the character count is close enough before that.
_LEN = "octet_length" if sqlite3.sqlite_version_info >= (3, 43) else "length"


def _h8(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:8]


_SHOW_AGENT_IDS = False  # set for the length of one ``plan`` call (``--show-agent-ids``); the default report names no agent


def _agent_label(agent_id: str) -> str:
    """An agent as the first 8 hex digits of its id's sha256; the id itself only when the caller asked for ids (and it is shaped like one)."""
    return agent_id if _SHOW_AGENT_IDS and _SAFE_ID.match(agent_id) else "sha8:" + _h8(agent_id)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _size(column: str) -> str:
    return f"COALESCE({_LEN}({column}),0)"


_ENTRY_BYTES = "+".join((_size("content"), _size("embedding_json"), _size("evidence_json"), _size("context_json"), "200"))


class Unreadable(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _code(error: BaseException) -> str:
    """A machine code for a failure. The message itself is never reported (it can hold a path)."""
    if isinstance(error, Unreadable):
        return error.code
    if isinstance(error, FileNotFoundError):
        return "missing"
    if isinstance(error, PermissionError):
        return "permission_denied"
    text = str(error).lower()
    for word, code in (("epoch_changed", "locked"), ("binding_changed", "locked"),("locked", "locked"), ("busy", "locked"), ("disk is full", "disk_full"), ("disk i/o", "disk_io"), ("malformed", "corrupt"), ("not a database", "corrupt"),
                       ("corrupt", "corrupt"), ("readonly", "needs_recovery"), ("unable to open", "cannot_open"),
                       ("no such table", "table_missing"), ("no such column", "column_missing")):
        if word in text:
            return code
    return type(error).__name__


# --- opening a store without changing anything ---------------------------------------------------------------------

def _store_stamp(store: Path) -> list[tuple[str, int, int]]:
    """Name, size and mtime of the store file and of whatever sits beside it under its name (``-wal``, ``-shm``, ``-journal``)."""
    stamp = []
    try:
        for entry in sorted(store.parent.iterdir()):
            if not entry.name.startswith(store.name):
                continue
            try:
                info = entry.lstat()
            except OSError:
                continue
            stamp.append((entry.name, info.st_size, info.st_mtime_ns))
    except OSError:
        pass
    return stamp


def open_readonly(path: Path, timeout: float = 2.0) -> tuple[sqlite3.Connection, str]:
    """A connection that cannot write and whose opening creates no file. Returns ``(connection, mode)``.

    ``mode=ro`` alone is not enough: on a WAL database with no ``-wal``/``-shm`` beside it SQLite creates both, even for a
    read-only connection (measured, SQLite 3.50). So the file header decides:

    * rollback journal (the engine's and the desktop's root store): ``mode=ro``. A hot journal cannot be rolled back by a
      reader, so that store is reported as ``needs_recovery`` instead of being repaired here;
    * WAL with both side files present (another process has it open): ``mode=ro``, an ordinary reader;
    * WAL with no log, or an empty one: the main file is the whole database, opened ``immutable`` (no lock, no side file);
    * WAL with a log but no index: reading it would mean building the index file, so it is ``unreadable``.
    """
    try:
        with open(path, "rb") as handle:
            head = handle.read(20)
    except OSError as error:
        raise Unreadable(_code(error)) from None
    if len(head) < 20 or not head.startswith(b"SQLite format 3\x00"):
        raise Unreadable("empty_store" if not head else "corrupt")
    mode = "ro"
    if head[18] == 2 or head[19] == 2:
        wal, shm = Path(str(path) + "-wal"), Path(str(path) + "-shm")
        try:
            wal_bytes = wal.stat().st_size if wal.is_file() else -1
            has_index = shm.is_file()
        except OSError as error:
            raise Unreadable(_code(error)) from None
        if wal_bytes >= 0 and has_index:
            mode = "ro"
        elif wal_bytes > 0:
            raise Unreadable("wal_without_index")
        else:
            mode = "immutable"
    uri = long_path.file_uri(path) + ("?mode=ro&immutable=1" if mode == "immutable" else "?mode=ro")
    try:
        db = sqlite3.connect(uri, uri=True, timeout=timeout)
    except sqlite3.Error as error:
        raise Unreadable(_code(error)) from None
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("PRAGMA temp_store=MEMORY")  # a large GROUP BY must not spill into a temp file
        db.execute("SELECT count(*) FROM sqlite_master").fetchone()
    except sqlite3.Error as error:
        db.close()
        raise Unreadable(_code(error)) from None
    return db, mode


def _tables(db: sqlite3.Connection) -> set[str]:
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _meta(db: sqlite3.Connection, key: str) -> str | None:
    row = db.execute("SELECT value FROM memory_store_meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def _count(db: sqlite3.Connection, table: str, where: str = "1=1", params: Any = ()) -> int:
    return int(db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0])


# --- actors --------------------------------------------------------------------------------------------------------

def actor_family(agent_id: Any) -> str:
    """``one`` | ``host`` | ``system`` (the resident actors, which have no folder) | ``special`` | ``hub`` | ``agent`` | ``none``."""
    if not isinstance(agent_id, str) or not agent_id.strip():
        return "none"
    agent = agent_id.strip()
    low = agent.casefold()
    if is_one_memory_actor(agent):
        return "one"
    try:
        special = {str(item).casefold() for item in contract().get("specialAgentIds", [])}
    except Exception:  # noqa: BLE001 - a missing contract file must not stop a read-only report
        special = set()
    if low in special:
        return "special"
    if low.startswith("host:"):
        return "host"
    if low.startswith("hub:"):
        return "hub"
    if low.startswith("builtin-agentlas-"):
        return "system"
    return "agent"


RESIDENT = ("one", "host", "system")


# --- the One drawer -------------------------------------------------------------------------------------------------

def one_root() -> Path:
    """The One workspace the desktop imports from: ``AGENTLAS_ONE_DIR``, else ``<agentlas home>/one``."""
    override = (os.environ.get("AGENTLAS_ONE_DIR") or "").strip()
    return Path(override).expanduser() if override else agent_home.agentlas_home() / "one"


def _read_json_dict(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8").lstrip("\ufeff"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def read_drawer(root: Path | None = None) -> dict[str, Any]:
    """The drawer's blocks by their ``h:`` hash, each with the project label the engine wrote for it.

    ``blocks[hash] = (label, "inline" | "sidecar" | None)``: the label is the block's own ``Project:`` line, else the sidecar
    (``ticket-slugs.json``) entry of its ticket; ``unknown`` and empty are no label. ``superseded`` are the hashes the
    engine retired, ``translated`` maps an original-language block to its English successor. Reads three files."""
    from . import one_workspace as ow
    base = Path(root) if root else one_root()
    meta = base / ow.META_DIR
    soul = meta / ow.PROJECT_SOUL_FILE
    try:
        text = soul.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"state": "missing", "blocks": {}, "superseded": set(), "translated": {}, "on": False}
    except (OSError, ValueError) as error:
        return {"state": "unreadable", "reason": _code(error), "blocks": {}, "superseded": set(), "translated": {}, "on": False}
    sidecar = _read_json_dict(meta / ow.TICKET_SLUGS_FILE)
    blocks: dict[str, tuple[str, str | None]] = {}
    total = 0
    for match in ow._DURABLE_BLOCK_RE.finditer(text):
        total += 1
        found = _BLOCK_HASH.search(match.group(0))
        digest = found.group(1) if found else ow._content_hash(match.group("content").strip())
        label, source = (match.group("project") or "").strip(), "inline"
        if not label:
            entry = sidecar.get(match.group("ticket"))
            label, source = (str(entry.get("slug") or "") if isinstance(entry, dict) else ""), "sidecar"
        if not label or label == "unknown":
            label, source = "", None
        blocks.setdefault(digest, (sys.intern(label), source))
    translated = {old: new for old, new in _read_json_dict(meta / ow.TRANSLATION_MAP_FILE).items() if isinstance(new, str)}
    return {"state": "ok", "blocks": blocks, "blockCount": total, "superseded": set(_read_json_dict(meta / ow.SUPERSEDED_MAP_FILE)),
            "translated": translated, "on": bool(_read_json_dict(base / "state.json").get("on"))}


def _terminal(digest: str, translated: dict[str, str]) -> str:
    seen = {digest}
    while digest in translated and translated[digest] not in seen:
        digest = translated[digest]
        seen.add(digest)
    return digest


# --- project folders -----------------------------------------------------------------------------------------------

class ProjectFolders:
    """Which folder a path or a drawer label means. Only reads: ``stat`` and the same small marker files the hooks read.

    Known folders come from the caller (``--project [id=]folder``, ``--projects-under dir``) and from the paths the store
    itself recorded. A path is turned into its project root with the function the hooks' read side uses, so a turn that
    ran in a subfolder counts for its project; a folder the caller named is a project as given."""

    def __init__(self, explicit: Iterable[str] = (), under: Iterable[str] = (), names: Iterable[str] = ()):
        self.by_id: dict[str, str] = {}
        self.names: dict[str, str] = {}       # registered folder -> the project's name in the app (--project-name ID=NAME; the folder's own name when none was given)
        self.source: dict[str, str] = {}      # folder -> how it became known: named (--project) | recorded (a path the store holds) | scanned (--projects-under)
        self.scan_notes: list[str] = []       # why the scan saw less than it was asked to
        self.explicit: set[str] = set()
        self._roots: dict[str, tuple[str, str | None]] = {}
        self._labels: dict[str, set[str]] | None = None
        self.known: set[str] = set()
        for item in explicit:
            ident, found, folder = item.partition("=")
            if not found or os.sep in ident or (os.altsep and os.altsep in ident):
                ident, folder = "", item  # a bare folder (its name may hold '=')
            try:
                real = os.path.realpath(os.path.abspath(os.path.expanduser(folder)))
            except (OSError, ValueError):
                continue
            if ident:
                self.by_id[ident] = real
            if os.path.isdir(real):
                self.explicit.add(real)
                self.known.add(real)
                self.source[real] = "named"
        for base in under:
            self._scan(Path(os.path.abspath(os.path.expanduser(base))))
        for folder in self.explicit:
            self.names[folder] = os.path.basename(folder)
        for item in names:
            ident, found, name = item.partition("=")
            if found and ident in self.by_id and self.by_id[ident] in self.explicit and name.strip():
                self.names[self.by_id[ident]] = name.strip()

    def _scan(self, base: Path, depth: int = 3, budget: int = 5000) -> None:
        stack = [(base, 0)]
        seen = 0
        try:
            never = {os.path.realpath(Path.home()), os.path.realpath(agent_home.agentlas_home())}
        except (OSError, RuntimeError):
            never = set()
        while stack and seen < budget:
            folder, level = stack.pop()
            seen += 1
            try:
                names = {entry.name: entry for entry in os.scandir(folder) if entry.is_dir(follow_symlinks=False) or entry.name == ".git"}
            except PermissionError:
                if "folder_scan_permission_denied" not in self.scan_notes:
                    self.scan_notes.append("folder_scan_permission_denied")
                continue
            except OSError:
                continue
            if (".agentlas" in names or ".git" in names) and os.path.realpath(folder) not in never:
                self.known.add(os.path.realpath(folder))
                self.source.setdefault(os.path.realpath(folder), "scanned")
            if level < depth:
                stack.extend((Path(entry.path), level + 1) for name, entry in names.items() if not name.startswith(".") and name != "node_modules")
        if stack and seen >= budget:
            self.scan_notes.append("folder_scan_budget_exhausted")

    def root_of(self, path: str | None) -> tuple[str, str | None]:
        """``("ok", root)`` | ``("folder_gone", None)`` | ``("not_project_root", None)`` for a path a row or a turn recorded."""
        if not isinstance(path, str) or not path.strip():
            return "none", None
        cached = self._roots.get(path)
        if cached is not None:
            return cached
        answer: tuple[str, str | None]
        try:
            real = os.path.realpath(path)
            if not os.path.isdir(real):
                answer = ("folder_gone", None)
            else:
                named = next((root for root in sorted(self.explicit, key=len, reverse=True) if real == root or real.startswith(root + os.sep)), None)
                if named is None:
                    from .memory_hook import _agentlas_project_root
                    found = _agentlas_project_root(Path(real))
                    named = os.path.realpath(found) if found is not None else None
                answer = ("ok", named) if named else ("not_project_root", None)
        except (OSError, ValueError, RuntimeError):
            answer = ("folder_gone", None)
        self._roots[path] = answer
        if answer[1] and answer[1] not in self.known:
            self.known.add(answer[1])
            self.source[answer[1]] = "recorded"
            self._labels = None
        return answer

    def for_label(self, label: str) -> set[str]:
        """Known folders whose project label (the engine's ``resolve_project_slug``) is ``label``."""
        if self._labels is None:
            from .one_workspace import resolve_project_slug
            self._labels = {}
            for folder in self.known:
                try:
                    slug = resolve_project_slug(folder)
                except Exception:  # noqa: BLE001 - an unreadable folder is simply not a match
                    continue
                if slug:
                    self._labels.setdefault(slug, set()).add(folder)
        return self._labels.get(label, set())

    @staticmethod
    def _alnum(text: str) -> str:
        """Letters and digits only, compared without case, so "My-Project" and "my project" are one name."""
        return "".join(char for char in unicodedata.normalize("NFKC", text).casefold() if char.isalnum())

    def resolve_label(self, label: str) -> tuple[str, str | None, str | None]:
        """``(state, folder, via)`` for a drawer project label. ``via``: ``label`` (exactly one known folder has this label), ``tie1`` (several
        folders have it and exactly one of them is a project the caller registered), ``tie2`` (no folder settles it, and exactly one registered
        project has this label as its name, letters and digits only, and its folder exists now). Otherwise ``label_ambiguous`` / ``label_unknown``."""
        matches = self.for_label(label)
        if len(matches) == 1:
            return "ok", next(iter(matches)), "label"
        registered = matches & self.explicit
        if len(matches) > 1 and len(registered) == 1:
            return "ok", next(iter(registered)), "tie1"
        wanted = self._alnum(label)
        named = {folder for folder, name in self.names.items() if wanted and self._alnum(name) == wanted and os.path.isdir(folder)}
        if len(named) == 1:
            return "ok", next(iter(named)), "tie2"
        return ("label_ambiguous" if matches else "label_unknown"), None, None

    @staticmethod
    def has_uid(folder: str) -> bool:
        uid = _read_json_dict(Path(folder).joinpath(*MARKER_RELATIVE)).get("projectUid")
        return isinstance(uid, str) and bool(uid.strip())


def prime_folders(db: sqlite3.Connection, tables: set[str], folders: "ProjectFolders") -> None:
    """The folders the hooks worked in are project candidates for the drawer's labels: ask each one's project root once, so ``folders.known`` holds them."""
    if "memory_operations" not in tables:
        return
    seen: set[str] = set()
    for (cwd,) in scan_chunks(db, "memory_operations", "json_extract(payload_json,'$.project_path')", "json_valid(payload_json)"):
        if isinstance(cwd, str) and cwd not in seen:
            seen.add(cwd)
            folders.root_of(cwd)


# --- one pass over the rows: who owns each, and where each resident row was learned ----------------------------------

_SUBJECT = re.compile(r"^\W*(?:the\s+)?(?:user|owner)(?:'s)?\b(?!\s+(?:interface|input|story|stories|guide|manual|id|account|name|data|agent|experience|flow|facing|settings?|profile|prompt|message))|(?:사용자|오너)(?:는|가|께서|은|이|의)", re.IGNORECASE)
_SOURCE_TAIL = re.compile(r"[—–-]\s*(?:오너|owner)\s*(?:결정|지시|승인|요청|확인)\s*$", re.IGNORECASE)
SCAN_CHUNK = 2000                # rows per statement of the big scans: a read lock is held for one chunk, not for the whole table


def narrow_person(text: str) -> bool:
    """The narrower reading of "this line is about a person": the word is in subject position and is not the tail that names who decided."""
    return bool(_SUBJECT.search(_SOURCE_TAIL.sub("", text.strip())))


_HOST_PATH_DEFAULT = r"(?:/Users/|/home/|[A-Za-z]:\\Users\\|file://)"
_SECRET_DEFAULT = (r"\b(sk-(?:ant-)?[A-Za-z0-9_-]{20,}|gh[opsu]_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[A-Za-z0-9-]{10,})\b"
                   r"|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
_SECRET_KV_DEFAULT = r"\b(api[_-]?key|secret|token|password|passwd|cookie|bearer)\b\s*[:=]\s*\S{16,}"   # the shared rule (admission): a plain word boundary
# The migration-only gate (what step 5b may send to a model): the same ruleset file, three more patterns that the admission gate never reads (defect A, C).
_MIGRATION_DEFAULTS = {
    "migrationSecretKeyValue": r'''(?<![A-Za-z0-9])(api[_-]?key|secret|token|password|passwd|cookie|bearer)\b\s*[:=]\s*\S{16,}''',
    "migrationSecretCredentials": r'''(?<![A-Za-z0-9])[A-Za-z0-9_-]*(?:api[_-]?key|secret|token|password|passwd)[A-Za-z0-9_-]*\s*[:=]\s*["']?\S{8,}|\bBearer\s+[A-Za-z0-9._~+/=-]{8,}|\b[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@''',
    "migrationHostPath": r'''(?:^|[\s"'`(\[=:,])(?:\\\\[A-Za-z0-9_.$-]+\\[A-Za-z0-9_.$-]+|/(?:etc|var|opt|private|tmp|Volumes|mnt|srv|media|root)/)''',
}
_GATE_PATTERNS = ("secretValueShapes", "secretKeyValue", "hostAbsolutePath", *_MIGRATION_DEFAULTS)
_patterns_cache: list[Any] = []


def _secret_and_path_patterns() -> tuple["re.Pattern[str]", ...]:
    """What the person labelling (5b) may not send: the ruleset's ``secretValueShapes``, ``secretKeyValue`` and ``hostAbsolutePath`` patterns and the three
    migration-only ones (``migrationSecretKeyValue``, ``migrationSecretCredentials``, ``migrationHostPath``), ASCII like the executors, compiled once;
    the same expressions as defaults when the ruleset file cannot be read (or is older and has no migration-only entry)."""
    if _patterns_cache:
        return _patterns_cache[0]
    found: dict[str, str] = {"secretValueShapes": _SECRET_DEFAULT, "secretKeyValue": _SECRET_KV_DEFAULT, "hostAbsolutePath": _HOST_PATH_DEFAULT, **_MIGRATION_DEFAULTS}
    flags = {"secretKeyValue": re.IGNORECASE, "migrationSecretKeyValue": re.IGNORECASE, "migrationSecretCredentials": re.IGNORECASE}
    try:
        from .one_workspace import load_ruleset
        spec = load_ruleset()[0].get("patterns") or {}
        for name in found:
            item = spec.get(name)
            if isinstance(item, dict) and isinstance(item.get("regex"), str):
                re.compile(item["regex"])
                found[name] = item["regex"]
                flags[name] = re.IGNORECASE if "i" in str(item.get("flags") or "") else 0
    except Exception:  # noqa: BLE001 - a missing or damaged ruleset leaves the defaults
        pass
    compiled = tuple(re.compile(found[name], re.ASCII | flags.get(name, 0)) for name in _GATE_PATTERNS)
    _patterns_cache.append(compiled)
    return compiled


def label_text_ok(text: str) -> bool:
    """A line the person labelling may send to a model: no credential shape, no ``key: value`` secret (the migration gate reads more of them than the admission gate does), no host path."""
    return not any(pattern.search(text) for pattern in _secret_and_path_patterns())


def scan_chunks(db: sqlite3.Connection, table: str, columns: str, where: str = "1=1", params: dict[str, Any] | None = None, size: int = SCAN_CHUNK) -> Iterator[Any]:
    """``SELECT columns FROM table WHERE where`` in ranges of ``size`` rows by rowid, one statement per range, so no read lock outlives a range
    (a hook that writes meanwhile waits for one range, not for the table). Rows come in rowid order."""
    last = -1
    while True:
        rows = db.execute(f"SELECT rowid AS _rid, {columns} FROM {table} WHERE rowid > :_last AND ({where}) ORDER BY rowid LIMIT {int(size)}",
                          {**(params or {}), "_last": last}).fetchall()
        if not rows:
            return
        last = rows[-1][0]
        for row in rows:
            yield tuple(row)[1:]


def _import_receipt_prefix(owner: str) -> str:
    """The desktop's receipt key prefix for a drawer block (electron/memory/import-source-receipt.ts)."""
    digest = hashlib.sha256(json.dumps([owner, DESKTOP_ONE_ACTOR_ID], ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    return f"one-soul-receipt:v1:{digest}:"


class Entry(NamedTuple):
    """One memory row as the migration sees it. ``origin`` / ``signal`` / ``root`` / ``person`` are set only for an
    ``agent_repo`` row of a resident actor (One family, ``host:*``, ``builtin-agentlas-*``)."""
    id: str
    scope: str
    agent_id: str | None
    project_path: str | None
    has_project_id: bool
    has_chat: bool
    live: bool
    kind: str
    bytes: int
    family: str
    origin: str | None = None      # oneSoul | dreaming | engine | desktopTurn
    signal: str | None = None      # ok = exactly one project root that exists now; else why not (a code)
    root: str | None = None        # that project root (real path) when signal == ok
    person: bool = False           # the text names the user / the owner (a candidate for personal memory)
    person_narrow: bool = False    # ... and does so as a subject ("the user asked", "사용자는"), not as a source tail ("— 오너 결정")
    via: str | None = None         # how a drawer row's project label became one folder: label | tie1 | tie2 (see ProjectFolders.resolve_label)
    person_chars: int = 0          # characters of the text when it names the user / the owner
    offered: bool = False          # a live resident row the person labelling (5b) would offer: person_narrow, no secret, no host path, a kind of LABEL_KINDS


class EntryScan:
    """Every row of ``memory_entries`` in ONE table scan (a row carries its embedding, so each scan reads the whole table).

    For a resident actor's ``agent_repo`` row it also answers where the row came from and which single project it was
    learned in, as §11.4 fixes it:

    * ``oneSoul``  the desktop imported a One drawer block (evidence ``one-soul:<h>``): the block's project label, turned
      into a folder by asking every known folder for its label (two folders with one label = no answer);
    * ``engine``   written by the engine's curator (id ``core-memory:``): the working folder stored with each turn's operation;
    * ``desktopTurn`` the rest: the row's own project path, else its ``project`` origin link through the caller's id table;
    * ``dreaming`` the desktop's idle consolidation: the rows it replaced (``supersedes:<id>``), when they all agree.

    A row goes to a project only when exactly one project root results and that folder exists now. Rows are yielded as they
    are read; consolidated rows come last (they need the rows they replaced). ``drawer_stats`` is filled while iterating.
    Keeps no row: memory is the lookup tables (receipts, turn folders) plus the verdicts of retired rows."""

    def __init__(self, db: sqlite3.Connection, tables: set[str], owner: str, drawer: dict[str, Any], folders: ProjectFolders):
        self.db, self.tables, self.owner, self.drawer, self.folders = db, tables, owner, drawer, folders
        self.drawer_stats: Counter = Counter()
        self._verdicts: dict[str, tuple[str, str | None]] = {}
        self._seen_hashes: set[str] = set()
        self._receipts: set[str] = set()
        self._turn_paths: dict[str, set[str]] = {}
        self._project_refs: dict[str, set[str]] = {}

    def _load(self) -> None:
        db, tables = self.db, self.tables
        prefix = _import_receipt_prefix(self.owner)
        for (key,) in db.execute("SELECT key FROM memory_store_meta WHERE key >= ? AND key < ?", (prefix, prefix + "\uffff")):
            self._receipts.add(key[len(prefix):])
        if "memory_origin_links" in tables:
            if "memory_operations" in tables:
                for memory_id, path in db.execute(
                        "SELECT l.memory_id, json_extract(o.payload_json,'$.project_path') FROM memory_origin_links l "
                        "JOIN memory_operations o ON o.operation_id=l.source_id WHERE l.source_kind='memory-ticket' AND json_valid(o.payload_json)"):
                    if isinstance(path, str) and path:
                        self._turn_paths.setdefault(memory_id, set()).add(path)
            for memory_id, ref in db.execute("SELECT memory_id, source_id FROM memory_origin_links WHERE source_kind='project'"):
                self._project_refs.setdefault(memory_id, set()).add(ref)

    @staticmethod
    def _settle(outcomes: set[tuple[str, str | None]]) -> tuple[str, str | None]:
        if not outcomes:
            return "none", None
        return next(iter(outcomes)) if len(outcomes) == 1 else ("many", None)

    def _verdict(self, ident: str, evidence: str, project_path: str | None, live: bool, person: bool, preference: bool) -> tuple[str, str, str | None, list[str], str | None]:
        """``(origin, signal, root, replaced ids, via)`` for one resident row; counts the drawer cross-check for live drawer rows."""
        folders = self.folders
        hashes = _ONE_SOUL.findall(evidence)
        if hashes:
            blocks, stats = self.drawer["blocks"], self.drawer_stats
            self._seen_hashes.update(hashes)
            present = [h for h in hashes if h in blocks]
            labelled = [blocks[h] for h in present if blocks[h][0]]
            labels = {block[0] for block in labelled}
            via = None
            if not present:
                verdict: tuple[str, str | None] = ("block_gone", None)
            elif not labels:
                verdict = ("none", None)
            elif len(labels) > 1:
                verdict = ("many", None)
            else:
                state, folder, via = folders.resolve_label(next(iter(labels)))
                verdict = (state, folder)
            if live:
                inline = any(block[1] == "inline" for block in labelled)
                for key, hit in (("imported", True), ("blockPresent", bool(present)), ("blockGone", not present), ("withProjectLabel", bool(labels)),
                                 ("labelFromBlock", inline), ("labelFromSidecar", bool(labels) and not inline), ("labelResolvesOne", verdict[0] == "ok"),
                                 ("labelResolvesMany", verdict[0] == "label_ambiguous"), ("labelUnknownFolder", verdict[0] == "label_unknown"),
                                 ("engineSuperseded", all(_terminal(h, self.drawer["translated"]) in self.drawer["superseded"] for h in hashes)),
                                 ("withoutReceipt", not any(h in self._receipts for h in hashes)), ("personCandidates", person and not preference)):
                    stats[key] += hit
            return "oneSoul", verdict[0], verdict[1], [], via
        if '"dreaming:' in evidence:
            return "dreaming", "none", None, _SUPERSEDES.findall(evidence), None
        if ident.startswith("core-memory:"):
            verdict = self._settle({folders.root_of(path) for path in self._turn_paths.get(ident, ())})
            return "engine", verdict[0], verdict[1], [], None
        if project_path:
            verdict = folders.root_of(project_path)
        else:
            verdict = self._settle({folders.root_of(folders.by_id[ref]) if ref in folders.by_id else ("project_id_unknown", None)
                                    for ref in self._project_refs.get(ident, ())})
        return "desktopTurn", verdict[0], verdict[1], [], None

    def _replaced(self, ident: str) -> tuple[str, str | None]:
        """The verdict of a row a consolidation replaced: remembered if it was retired, else looked up by its id."""
        known = self._verdicts.get(ident)
        if known is not None:
            return known
        row = self.db.execute("SELECT agent_id, evidence_json, project_path FROM memory_entries WHERE id=? AND scope='agent_repo'", (ident,)).fetchone()
        if row is None or actor_family(row[0]) not in RESIDENT or '"dreaming:' in (row[1] or ""):
            return "none", None
        _origin, signal, root, _, _via = self._verdict(ident, row[1] or "", row[2], False, False, False)
        return signal, root

    def __iter__(self) -> Iterator[Entry]:
        self._load()
        dreams: list[tuple[Entry, list[str]]] = []
        like_params = {f"p{n}": value for n, value in enumerate(_PERSON_LIKE)}
        like = " OR ".join(f"content LIKE :p{n}" for n in range(len(_PERSON_LIKE)))
        for ident, scope, agent, stored, has_pid, has_chat, live, kind, size, evidence, text, secret in scan_chunks(
                self.db, "memory_entries",
                f"id, scope, agent_id, project_path, project_id IS NOT NULL, chat_id IS NOT NULL, superseded_at IS NULL, kind, {_ENTRY_BYTES}, "
                f"CASE WHEN scope='agent_repo' AND agent_id IS NOT NULL THEN evidence_json END, "
                f"CASE WHEN scope='agent_repo' AND superseded_at IS NULL AND kind<>'preference' AND ({like}) THEN content END, sensitivity='secret'", params=like_params):
            family = actor_family(agent)
            entry = Entry(ident, scope, agent, stored, bool(has_pid), bool(has_chat), bool(live), kind, int(size), family)
            if scope != "agent_repo" or family not in RESIDENT:
                yield entry
                continue
            person = bool(text) and PERSON.search(text) is not None
            origin, signal, root, replaced, via = self._verdict(ident, evidence or "", stored, bool(live), person, kind == "preference")
            narrow = person and narrow_person(text)
            entry = entry._replace(origin=origin, signal=signal, root=root, person=person, person_narrow=narrow, via=via,
                                   person_chars=len(text) if person else 0,
                                   offered=bool(live) and narrow and not secret and kind in LABEL_KINDS and label_text_ok(text))
            if origin == "dreaming":
                dreams.append((entry, replaced))
                continue
            if not live:
                self._verdicts[ident] = (signal, root)
            yield entry
        for entry, replaced in dreams:
            found = {self._replaced(source) for source in replaced}
            signal, root = self._settle(found)
            if signal == "many":
                signal = "mixed_sources"
            yield entry._replace(signal=signal, root=root)
        blocks, have = self.drawer["blocks"], self._seen_hashes | self._receipts
        successor_of = {new: old for old, new in self.drawer["translated"].items()}
        self.drawer_stats["blocksNotImported"] = sum(1 for digest in blocks if digest not in have and successor_of.get(digest) not in have)


# --- turns that left no memory -----------------------------------------------------------------------------------------

def empty_turn_condition(tables: set[str], alias: str = "t") -> str:
    """SQL condition on ``memory_tickets <alias>``: the turn is over (or abandoned), left no memory and nothing still needs it.

    Named parameter ``:stale`` (an ISO time ``STALE_TURN_DAYS`` ago). This is conditions 1-6 of §11.3; the age
    of the ticket itself (condition 7) is the caller's, because the operation row may go earlier than the summary.
    Every subquery filters NULLs so ``NOT IN`` cannot turn the whole condition unknown."""
    t = alias
    parts = [f"({t}.state IN ('completed','read_only','failed') OR ({t}.state='received' AND {t}.updated_at < :stale))",
             f"{t}.written_count=0 AND {t}.deduped_count=0"]
    if "memory_decisions" in tables:
        parts.append(f"{t}.ticket_id NOT IN (SELECT ticket_id FROM memory_decisions WHERE action IN ('written','deduped') AND ticket_id IS NOT NULL)")
    if "memory_origin_links" in tables:
        parts.append(f"{t}.ticket_id NOT IN (SELECT source_id FROM memory_origin_links WHERE source_kind IN ('ticket','memory-ticket') AND source_id IS NOT NULL)")
    if "memory_operations" in tables:
        parts.append(f"{t}.ticket_id NOT IN (SELECT operation_id FROM memory_operations WHERE operation_id IS NOT NULL AND "
                     "(state IN ('queued','processing') OR (state='deferred' AND updated_at >= :stale)))")
    if "memory_curation_jobs" in tables:
        parts.append(f"{t}.ticket_id NOT IN (SELECT ticket_id FROM memory_curation_jobs WHERE state IN ('queued','retry','processing','deferred') AND ticket_id IS NOT NULL)")
    if "memory_episode_quarantines" in tables:
        parts.append(f"{t}.ticket_id NOT IN (SELECT ticket_id FROM memory_episode_quarantines WHERE ticket_id IS NOT NULL)")
    if "memory_revocation_cleanup_targets" in tables:
        parts.append(f"{t}.ticket_id NOT IN (SELECT target_ref FROM memory_revocation_cleanup_targets WHERE target_ref IS NOT NULL)")
    if "memory_session_checkpoints" in tables:
        parts.append(f"{t}.ticket_id NOT IN (SELECT json_extract(payload_json,'$.ticket_ref') FROM memory_session_checkpoints "
                     "WHERE json_valid(payload_json) AND json_extract(payload_json,'$.ticket_ref') IS NOT NULL)")
    return " AND ".join(parts)


def _iso(seconds: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(seconds))


def _in_chunks(db: sqlite3.Connection, sql: str, ids: list[str], size: int = 500) -> Iterator[Any]:
    """Rows of ``sql`` (one ``{marks}`` placeholder) for ``ids``, 500 ids per statement: no statement runs long enough to matter to a writer."""
    for start in range(0, len(ids), size):
        chunk = ids[start:start + size]
        yield from db.execute(sql.format(marks=",".join("?" * len(chunk))), chunk)


def empty_turns(db: sqlite3.Connection, tables: set[str], now: float) -> dict[str, Any]:
    """Counts for the empty-turn cleanup. The condition is evaluated ONCE (one pass over the tickets, by rowid ranges); every other number is
    a lookup of those ids in chunks. ``first_run_steps.prune_empty_turns`` removes exactly what this counts."""
    if "memory_tickets" not in tables:
        return {"state": "no_table"}
    args = {"stale": _iso(now - STALE_TURN_DAYS * 86400), "keep": _iso(now - KEEP_EMPTY_TURN_DAYS * 86400),
            "grace": _iso(now - WORK_ROW_GRACE_HOURS * 3600)}
    cond = empty_turn_condition(tables)
    total = wrote = 0
    gone: list[str] = []
    kept: list[str] = []
    for ident, created, empty, left in scan_chunks(db, "memory_tickets t", f"t.ticket_id, t.created_at, ({cond}), (t.written_count>0 OR t.deduped_count>0)",
                                                    params={"stale": args["stale"]}):
        total += 1
        wrote += bool(left)
        if empty:
            (gone if created < args["keep"] else kept).append(ident)
    empty_n, deletable = len(gone) + len(kept), len(gone)
    reclaim: dict[str, int] = {}
    counts: dict[str, int] = {}

    def add(name: str, table: str, key: str, size: str, ids: list[str], where: str = "", extra: tuple[Any, ...] = ()) -> list[str]:
        """Count and size the rows of ``table`` whose ``key`` is in ``ids`` (and ``where``); returns their ``key`` values."""
        if table not in tables:
            return []
        found: list[str] = []
        n = size_sum = 0
        for start in range(0, len(ids), 500):
            chunk = ids[start:start + 500]
            for row_key, row_size in db.execute(f"SELECT {key}, {size} FROM {table} WHERE {key} IN ({','.join('?' * len(chunk))}) {where}", [*chunk, *extra]):
                n += 1
                size_sum += row_size
                found.append(row_key)
        counts[name] = counts.get(name, 0) + n
        reclaim[name] = reclaim.get(name, 0) + size_sum
        return found

    add("tickets", "memory_tickets", "ticket_id", "+".join(_size(c) for c in ("ticket_id", "turn_key", "turn_id", "chat_id", "agent_id", "project_id")) + "+160", gone)
    add("episodes", "memory_episodes", "ticket_id", _size("summary") + "+" + _size("embedding_json") + "+240", gone)
    add("decisions", "memory_decisions", "ticket_id", "260", gone)
    add("curationJobs", "memory_curation_jobs", "ticket_id", _size("payload_json") + "+" + _size("result_json") + "+260", gone)
    operation = _size("payload_json") + "+" + _size("receipt_json") + "+320"
    add("operations", "memory_operations", "operation_id", operation, gone)
    # Kept 30 days for their summary, but the operation row and its source registration go a day after the turn ended.
    early = add("operations", "memory_operations", "operation_id", operation, kept, "AND updated_at < ?", (args["grace"],))
    catalogue_size = _size("address_json") + "+420"
    for ids in (gone, early):                                  # an old turn's registration, an early work row's
        add("sourceCatalogue", "memory_source_catalogue", "logical_key", catalogue_size, ids)
    orphan_sources = orphan_versions = 0
    if "memory_source_catalogue" in tables and "memory_operations" in tables:
        gone_set = set(gone)
        orphan_bytes = 0
        for source_id, key, size in scan_chunks(db, "memory_source_catalogue", f"source_id, logical_key, {catalogue_size}", ORPHAN_SOURCES):
            if key not in gone_set:
                orphan_sources += 1
                orphan_bytes += size
        reclaim["orphanSources"] = orphan_bytes
    if "memory_source_versions" in tables and "memory_source_catalogue" in tables:
        orphan_versions = _count(db, "memory_source_versions", ORPHAN_VERSIONS)
        going: set[str] = set()
        for ids in (gone, early):
            going.update(row[0] for row in _in_chunks(db, "SELECT source_id FROM memory_source_catalogue WHERE logical_key IN ({marks})", ids))
        going.update(row[0] for row in scan_chunks(db, "memory_source_catalogue", "source_id", ORPHAN_SOURCES))
        versions = version_bytes = 0
        for _n, size in _in_chunks(db, f"SELECT 1, {_size('address_json')}+160 FROM memory_source_versions WHERE source_id IN ({{marks}})", sorted(going)):
            versions += 1
            version_bytes += size
        counts["sourceVersions"], reclaim["sourceVersions"] = versions, version_bytes
    receipts = 0
    if "memory_source_mappings" in tables:
        receipts, receipt_bytes = db.execute(
            f"SELECT COUNT(*), COALESCE(SUM({_size('source_id')}+{_size('target_id')}+{_size('source_digest')}+120),0) FROM memory_source_mappings WHERE {RECEIPTS}").fetchone()
        reclaim["migrationReceipts"] = int(receipt_bytes)
    report: dict[str, Any] = {
        "state": "ok", "turns": total, "leftMemory": wrote, "empty": empty_n, "deletableNow": deletable,
        "keptWithin30Days": empty_n - deletable, "notEmptyNotWritten": total - wrote - empty_n,
        "emptyShare": round(empty_n / total, 4) if total else 0.0,
        "workRowsDeletableEarly": len(early), "deleteCounts": counts,
        "orphanSourceRows": orphan_sources, "orphanSourceVersions": int(orphan_versions), "migrationReceiptRows": int(receipts),
        # What the receipts are: the older desktop's record of which of its own rows (tickets, episodes...) it copied into this store. Only rows
        # of target_table 'memory_entries' are ever read again (the cutover purge); the rest are what 11.3 lists as removable.
        "migrationReceiptsAre": "older desktop's copy records; only target memory_entries is read again; others removable",
        "stuckReceived": _count(db, "memory_tickets", "state='received' AND updated_at < :stale", {"stale": args["stale"]}),
        "reclaimBytesEstimate": sum(reclaim.values()), "reclaimBytesByTable": reclaim,
    }
    if "memory_operations" in tables:
        report["deferredOperationsStale"] = _count(db, "memory_operations", "state='deferred' AND updated_at < :stale", {"stale": args["stale"]})
    if "memory_curation_jobs" in tables:
        report["finishedCurationJobs"] = _count(db, "memory_curation_jobs", "state NOT IN ('queued','retry','processing','deferred')")
    return report


# --- agents -----------------------------------------------------------------------------------------------------------

def _read_routes(path: str | None) -> tuple[dict[str, dict[str, Any]] | None, Path | None]:
    """The desktop's ``agent-routes.json`` (the caller names it; the engine does not know the app's data folder)."""
    if not path:
        return None, None
    file = Path(os.path.abspath(os.path.expanduser(path)))
    data = _read_json_dict(file)
    return {key: value for key, value in data.items() if isinstance(value, dict)}, file.parent


def _agent_state(agent_id: str, routes: dict[str, dict[str, Any]] | None, user_data: Path | None, agents_root: Path) -> dict[str, Any]:
    """Whether this agent's rows have somewhere to go, the way the move decides it (``memory_split.scan``), and why not."""
    if actor_family(agent_id) == "hub":
        return {"folder": "none", "movable": False, "reason": "hub_agent_keeps_no_memory"}
    home = ms.find_agent_home(agent_id)
    if home is not None and not (home.parent == agents_root or home == ms._env_agent_home(agent_id)):
        home = None
    if home is not None:
        origin = _read_json_dict(home / agent_home.AGENT_LOCAL_STATE_FOLDER / "origin.json")
        return {"folder": "user-owned" if origin.get("kind") == "registered" else "app-owned", "movable": True}
    if routes is None:
        return {"folder": "unknown", "movable": False, "reason": "no_agent_home"}
    route = routes.get(agent_id)
    if route is None:
        return {"folder": "missing", "movable": False, "reason": "no_route_deleted_or_stub"}
    path = route.get("path")
    if route.get("missingSince") or not isinstance(path, str) or not os.path.isdir(path):
        return {"folder": "missing", "movable": False, "reason": "folder_gone"}
    app_roots = [os.path.realpath(root) for root in ((user_data / "agents") if user_data else None, (user_data / "generated-agent-os") if user_data else None,
                                                    agent_home.legacy_agents_home()) if root is not None]
    real = os.path.realpath(path)
    owned = "app-owned" if any(real == root or real.startswith(root + os.sep) for root in app_roots) else "user-owned"
    try:
        names = os.listdir(path)
    except OSError:
        return {"folder": owned, "movable": False, "reason": "folder_unreadable"}
    # These stay where they are until the desktop gives them a state folder (§3.2): their rows stay in the root.
    if route.get("source") in ("agent-cloud", "hub") or _CLOUD_MARKER in names:
        return {"folder": owned, "movable": False, "reason": "cloud_managed"}
    if any(_PHOTO.match(name) for name in names):
        return {"folder": owned, "movable": False, "reason": "has_photo"}
    return {"folder": owned, "movable": False, "reason": "home_not_made_yet"}


# --- engine copies ------------------------------------------------------------------------------------------------------

def _copy_version(root: str | None) -> str | None:
    if not root:
        return None
    base = Path(root)
    try:
        marker = base / "RELEASE"
        if marker.is_file():
            value = marker.read_text(encoding="utf-8").strip()
            if _VERSION.match(value):
                return value
        for name in ("plugin.json", ".claude-plugin/plugin.json", ".codex-plugin/plugin.json"):
            version = _read_json_dict(base / name).get("version")
            if isinstance(version, str) and _VERSION.match(version):
                return version
    except OSError:
        pass
    return base.name if _VERSION.match(base.name) else None


def engines(extra: Iterable[str] = ()) -> dict[str, Any]:
    """Engine copies that can run a memory hook on this computer: host name, version, and whether it knows the split."""
    from .memory_split import engine_inventory
    inventory = engine_inventory(extra)
    copies = [{key: value for key, value in (("host", copy.get("host")), ("state", copy.get("state")), ("memoryLayout", copy.get("memoryLayout")),
                                              ("reason", copy.get("reason")), ("version", _copy_version(copy.get("path")))) if value is not None}
              for copy in inventory["copies"]]
    return {"allDeclared": bool(inventory["allDeclared"]), "copies": copies, "old": sum(1 for copy in copies if copy["state"] != "declared"),
            "belowCurrent": len(inventory.get("belowCurrent", []))}  # Agentlas 2.0: a count for a status line, never a door


# --- the plan ---------------------------------------------------------------------------------------------------------

@contextlib.contextmanager
def _no_temp_probe() -> Iterator[None]:
    """``tempfile.gettempdir()`` (reached through the hooks' project-root check) creates and deletes a probe file in the temp
    folder the first time it is asked. Naming the folder first skips the probe, so the preview creates no file anywhere, not
    even a passing one."""
    import tempfile
    if tempfile.tempdir is not None:
        yield
        return
    names = [os.environ.get(name) for name in ("TMPDIR", "TEMP", "TMP")] + ([] if os.name == "nt" else ["/tmp", "/var/tmp", "/usr/tmp"]) + [os.getcwd()]
    tempfile.tempdir = next((os.path.abspath(name) for name in names if name and os.path.isdir(name)), None)
    try:
        yield
    finally:
        tempfile.tempdir = None


def plan(owner: str, *, projects: Iterable[str] = (), projects_under: Iterable[str] = (), agent_routes: str | None = None,
         now: float | None = None, show_agent_ids: bool = False, project_names: Iterable[str] = ()) -> dict[str, Any]:
    """The whole preview for one owner. Never writes; a part that cannot be read is ``{"state": "unreadable", "reason": code}``.

    A store opened ``immutable`` (a WAL store nobody has open) is read twice at most: if its file changed while it was read, the numbers are
    thrown away and read again, and if it changes again the answer is ``root: unreadable / changed_during_read`` instead of a wrong sum."""
    global _SHOW_AGENT_IDS
    projects, projects_under, project_names = list(projects), list(projects_under), list(project_names)
    _SHOW_AGENT_IDS = bool(show_agent_ids)
    try:
        with _no_temp_probe():
            for attempt in (1, 2):
                report = _plan(owner, projects, projects_under, agent_routes, now, project_names)
                if not report.pop("_immutableChanged", False):
                    return report
            return {"schema": SCHEMA, "readOnly": True, "owner": report["owner"], "engines": report.get("engines"),
                    "root": {"state": "unreadable", "reason": "changed_during_read"}, "notes": ["root:changed_during_read"],
                    "elapsedMs": report.get("elapsedMs", 0)}
    finally:
        _SHOW_AGENT_IDS = False


def _plan(owner: str, projects: Iterable[str], projects_under: Iterable[str], agent_routes: str | None, now: float | None, project_names: Iterable[str] = ()) -> dict[str, Any]:
    from .memory_runtime import memory_path
    started = time.monotonic()
    now = time.time() if now is None else now
    notes: list[str] = []
    report: dict[str, Any] = {"schema": SCHEMA, "readOnly": True, "owner": {"kind": owner.split(":", 1)[0] if ":" in owner else "account", "id8": _h8(owner)}}

    def part(name: str, build: Callable[[], Any]) -> Any:
        try:
            report[name] = build()
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError, Unreadable) as error:
            report[name] = {"state": "unreadable", "reason": _code(error)}
            notes.append(f"{name}:{_code(error)}")
        return report[name]

    part("engines", engines)
    path = memory_path(owner)
    if path.is_symlink() or not path.is_file():
        report["root"] = {"state": "unreadable", "reason": "store_symlink"} if path.is_symlink() else {"state": "no_store"}
        report.update(notes=notes, elapsedMs=int((time.monotonic() - started) * 1000))
        return report
    before = _store_stamp(path)
    try:
        db, mode = open_readonly(path)
    except Unreadable as error:
        report["root"] = {"state": "unreadable", "reason": error.code}
        report.update(notes=[*notes, "root:" + error.code], elapsedMs=int((time.monotonic() - started) * 1000))
        return report
    try:
        try:
            tables = _tables(db)
        except sqlite3.Error as error:  # the writer took the file between the open and the first read
            code = "changed_during_read" if mode == "immutable" else _code(error)
            report["root"] = {"state": "unreadable", "reason": code}
            report.update(notes=[*notes, "root:" + code], elapsedMs=int((time.monotonic() - started) * 1000))
            if mode == "immutable":
                report["_immutableChanged"] = True
            return report

        def root_part() -> dict[str, Any]:
            layout = _meta(db, ms.LAYOUT_KEY)
            page, pages, free = (int(db.execute(f"PRAGMA {name}").fetchone()[0]) for name in ("page_size", "page_count", "freelist_count"))
            return {"state": "ok", "openMode": mode, "journalMode": str(db.execute("PRAGMA journal_mode").fetchone()[0]),
                    "bytes": page * pages, "freePageBytes": page * free, "layout": ms.layout_of(db),
                    "layoutValue": layout if layout is None or re.fullmatch(r"[a-z0-9_-]{1,24}", layout) else "sha8:" + _h8(layout),
                    "ownerMatches": _meta(db, "owner_namespace") in (None, owner),
                    "meta": {"oneImportRetired": _meta(db, META_ONE_IMPORT_RETIRED) is not None, "classified": _meta(db, META_CLASSIFIED) is not None,
                             "chipAbsorbDone": _meta(db, "chip-absorb:v1") is not None, "moveSwept": _meta(db, "drain_swept_revision") is not None},
                    "store8": path.parent.name[:8],
                    "otherOwnerStores": [{"store8": other.parent.name[:8], "bytes": other.stat().st_size}
                                         for other in sorted(path.parent.parent.glob("*/" + ms.STORE_FILE)) if other != path]}

        root = part("root", root_part)
        if root.get("layout") not in (None, ms.CENTRAL):
            notes.append("root:layout_not_central_sub_stores_not_read")  # the preview is for a store that has not been split yet

        def table_part() -> dict[str, int]:
            names = ("memory_entries", "memory_tickets", "memory_episodes", "memory_decisions", "memory_operations", "memory_curation_jobs",
                     "memory_source_catalogue", "memory_source_versions", "memory_source_mappings", "memory_origin_links", "memory_project_links",
                     "memory_relation_edges", "memory_revocations", "memory_session_checkpoints", "memory_translation_jobs")
            return {name: _count(db, name) for name in names if name in tables}

        part("tables", table_part)

        agents_root = agent_home.agents_root()
        routes, user_data = _read_routes(agent_routes)
        folders = ProjectFolders(projects, projects_under, project_names)
        notes.extend(folders.scan_notes)
        from . import memory_scopes
        if memory_scopes._active() is memory_scopes._FALLBACK:  # the contract file is missing or unusable: every row would read as legacy-shared
            notes.append("scope_contract_missing_no_row_would_move")
        agents: dict[str, dict[str, Any]] = {}
        project_rows: dict[str, dict[str, int]] = {}
        states: dict[str, dict[str, Any]] = {}
        incoming: Counter = Counter()
        totals = {"candidateBytes": 0, "entryBytes": 0}

        def state_of(agent_id: str) -> dict[str, Any]:
            if agent_id not in states:
                states[agent_id] = _agent_state(agent_id, routes, user_data, agents_root)
            return states[agent_id]

        def scan_parts() -> dict[str, Any]:
            """``rows``, ``personal``, ``drawer`` and ``reclassify`` from one pass over the rows (see ``EntryScan``)."""
            from .memory_split import CANDIDATE_SCOPES
            drawer = read_drawer()
            prime_folders(db, tables, folders)
            scan = EntryScan(db, tables, owner, drawer, folders)
            by_scope, by_family, by_kind, cells, preferences = Counter(), Counter(), Counter(), Counter(), Counter()
            by_origin, signals, destinations, to_project, person_by_origin = Counter(), Counter(), Counter(), Counter(), Counter()
            live = retired = identity = no_key = 0
            person_kinds, person_with_project, person_narrow, root_sources = Counter(), 0, 0, Counter()
            identity_kinds, tie_rows, offered, offered_chars, offered_input = Counter(), Counter(), 0, 0, 0
            owners: dict[tuple, tuple[str, str | None, str]] = {}
            for entry in scan:
                key = (entry.scope, entry.agent_id, entry.project_path, entry.has_chat)
                known = owners.get(key)
                if known is None:
                    owned = owner_scope_of({"scope": entry.scope, "agent_id": entry.agent_id, "project_path": entry.project_path,
                                            "chat_id": "chat" if entry.has_chat else None})
                    family = entry.family
                    if family == "agent":
                        state = state_of(entry.agent_id)
                        family = "agentWithFolder" if state["movable"] else "agentDeleted" if state.get("reason") == "no_route_deleted_or_stub" else "agentNoFolder"
                    owner_id = owned.owner_id if owned is not None else None
                    if owned is not None and owned.kind == ms.PROJECT and entry.project_path:
                        # One project is one line even when rows spell its folder differently (a link, /var and /private/var).
                        owner_id = os.path.realpath(entry.project_path)
                    known = owners[key] = (owned.kind if owned is not None else "never-stored", owner_id, family)
                kind, owner_id, family = known
                totals["entryBytes"] += entry.bytes
                if entry.scope in CANDIDATE_SCOPES:
                    totals["candidateBytes"] += entry.bytes
                bucket = agents if kind == ms.AGENT and owner_id else project_rows if kind == ms.PROJECT and owner_id else None
                if bucket is not None:
                    line = bucket.setdefault(owner_id, {"rows": 0, "retired": 0, "bytes": 0})
                    line["rows" if entry.live else "retired"] += 1
                    line["bytes"] += entry.bytes
                elif entry.scope == "project":
                    no_key += 1
                if not entry.live:
                    retired += 1
                    continue
                live += 1
                by_scope[entry.scope] += 1
                by_family[family] += 1
                by_kind[kind] += 1
                cells[(entry.scope, family, bool(entry.project_path or entry.has_project_id))] += 1
                if entry.scope == "user_identity":
                    identity += 1
                    identity_kinds[entry.kind] += 1
                if entry.origin is None:
                    continue
                by_origin[entry.origin] += 1
                if entry.kind == "preference":
                    preferences[entry.family] += 1
                    destinations["personalPreference"] += 1
                    continue
                signals["oneProject" if entry.signal == "ok" else entry.signal] += 1
                if entry.offered:
                    offered += 1
                    offered_chars += entry.person_chars
                    offered_input += min(entry.person_chars, LABEL_TEXT_CHARS)
                if entry.person:
                    destinations["personCandidate"] += 1
                    person_by_origin[entry.origin] += 1
                    person_kinds[entry.kind] += 1
                    person_with_project += entry.signal == "ok"
                    person_narrow += entry.person_narrow
                elif entry.signal == "ok":
                    destinations["toProject"] += 1
                    to_project[entry.origin] += 1
                    tie_rows[entry.via] += 1
                    incoming[entry.root] += 1
                    root_sources[folders.source.get(entry.root, "recorded")] += 1
                else:
                    destinations["stayInRoot"] += 1
            blocks, stats = drawer["blocks"], scan.drawer_stats
            labels = Counter(label for label, _source in blocks.values() if label)
            share = stats["labelResolvesOne"] / stats["imported"] if stats["imported"] else 0.0
            drawer_part: dict[str, Any] = {
                "state": drawer["state"], "oneOn": drawer["on"], "blocks": drawer.get("blockCount", 0), "distinctBlocks": len(blocks),
                "blocksWithProjectInBlock": sum(1 for _label, source in blocks.values() if source == "inline"),
                "blocksWithProjectInSidecar": sum(1 for _label, source in blocks.values() if source == "sidecar"),
                "blocksWithoutProject": sum(1 for label, _source in blocks.values() if not label),
                "blocksEngineSuperseded": sum(1 for digest in blocks if digest in drawer["superseded"]),
                "blocksTranslated": sum(1 for digest in blocks if digest in drawer["translated"]),
                "blocksNotImported": int(stats["blocksNotImported"]),
                "projectLabels": len(labels),
                "labelsWithOneFolder": sum(1 for label in labels if len(folders.for_label(label)) == 1),
                "labelsWithManyFolders": sum(1 for label in labels if len(folders.for_label(label)) > 1),
                "labelsWithoutFolder": sum(1 for label in labels if not folders.for_label(label)),
                "knownProjectFolders": len(folders.known),
                "rows": {name: int(stats[name]) for name in ("imported", "blockPresent", "blockGone", "withProjectLabel", "labelFromBlock", "labelFromSidecar",
                                                             "labelResolvesOne", "labelResolvesMany", "labelUnknownFolder", "engineSuperseded",
                                                             "withoutReceipt", "personCandidates")},
                "oneProjectShare": round(share, 4), "meetsReclassifyThreshold": share >= RECLASSIFY_MIN_SHARE,
                # The share is only as good as the folder set the caller gave (4.3): read it with these.
                "oneProjectShareDependsOnFolderSet": True,
                "foldersBySource": dict(Counter(folders.source.get(folder, "recorded") for folder in folders.known)),
                "rowsToProjectByFolderSource": dict(root_sources),
                # Labels no known folder answers to, largest first, as sha256(label)[:8]: which --project the caller has not named yet.
                "unresolvedLabels": [{"label8": _h8(label), "blocks": n} for label, n in labels.most_common() if not folders.for_label(label)][:20],
            }
            if drawer.get("reason"):
                drawer_part["reason"] = drawer["reason"]
            return {
                "rows": {"live": live, "retired": retired, "byScope": dict(by_scope), "byActorFamily": dict(by_family), "byOwnerKind": dict(by_kind),
                         "projectRowsWithoutFolderKey": no_key,
                         "table": [{"scope": scope, "family": family, "project": project, "rows": n}
                                   for (scope, family, project), n in sorted(cells.items(), key=lambda kv: -kv[1])]},
                # Two readings of "personal": the owner-decision one (user_identity + the One family's preferences) and the audit's
                # (preferences of every resident actor, because hooks have written as host:* since).
                "personal": {"userIdentity": identity, "oneFamilyPreferences": preferences["one"], "hostPreferences": preferences["host"],
                             "systemPreferences": preferences["system"], "rowsOneFamilyRule": identity + preferences["one"],
                             "rowsResidentRule": identity + sum(preferences.values()),
                             "personCandidates": destinations["personCandidate"], "personCandidatesByOrigin": dict(person_by_origin),
                             # A word check, so a RANGE (4.2): the wide count is any line with user/owner/사용자/오너 anywhere; the narrow one
                             # needs the word as a subject and not as the tail that says who decided. The truth for question 2 lies between them.
                             "personCandidatesByKind": dict(person_kinds), "personCandidatesWithOneProject": person_with_project,
                             "personCandidatesNarrow": person_narrow, "personCandidatesIsARange": True,
                             # What the person labelling (5b) would offer a model: narrow, no secret shape, no host path, a kind it may relabel.
                             "labelOfferedRows": offered, "labelOfferedChars": offered_chars, "labelInputChars": offered_input,
                             "userIdentityByKind": dict(identity_kinds)},
                "drawer": drawer_part,
                "reclassify": {"residentRows": sum(by_origin.values()), "byOrigin": dict(by_origin), "signals": dict(signals), "destinations": dict(destinations),
                               "toProjectByOrigin": dict(to_project), "projects": len(incoming), "toProjectByFolderSource": dict(root_sources),
                               # Rows the two tie-breaks settle (12-7); they are part of toProject, not extra.
                               "tieBreak1Rows": tie_rows["tie1"], "tieBreak2Rows": tie_rows["tie2"],
                               "blockedUntilOneImportRetired": _meta(db, META_ONE_IMPORT_RETIRED) is None},
            }

        scanned = ("rows", "personal", "drawer", "reclassify")
        try:
            report.update(scan_parts())
        except (sqlite3.Error, OSError, ValueError, KeyError, TypeError, Unreadable) as error:
            report.update({name: {"state": "unreadable", "reason": _code(error)} for name in scanned})
            notes.append("rows:" + _code(error))

        def agents_part() -> dict[str, Any]:
            listed = []
            for agent_id, entry in sorted(agents.items(), key=lambda kv: (-kv[1]["rows"], kv[0])):
                listed.append({"agent": _agent_label(agent_id), "family": actor_family(agent_id), "rows": entry["rows"], "retired": entry["retired"], **state_of(agent_id)})
            reasons = Counter(item.get("reason", "movable") for item in listed)
            rows_by_reason = Counter()
            for item in listed:
                rows_by_reason[item.get("reason", "movable")] += item["rows"] + item["retired"]
            return {"agents": len(listed), "withFolder": sum(1 for item in listed if item["movable"]), "byState": dict(reasons), "rowsByState": dict(rows_by_reason),
                    "routesRead": routes is not None, "list": listed[:LIST_LIMIT], "more": max(0, len(listed) - LIST_LIMIT)}

        part("agents", agents_part)

        def projects_part() -> dict[str, Any]:
            listed = []
            for stored in sorted(set(project_rows) | set(incoming), key=lambda p: (-(project_rows.get(p, {}).get("rows", 0) + incoming.get(p, 0)), p)):
                entry = project_rows.get(stored, {"rows": 0, "retired": 0})
                exists = os.path.isdir(stored)
                listed.append({"project8": _h8(stored), "rows": entry["rows"], "retired": entry["retired"], "incoming": int(incoming.get(stored, 0)),
                               "folderExists": exists, "projectUid": exists and folders.has_uid(stored), "key": "uid" if exists and folders.has_uid(stored) else "path-hash"})
            return {"projects": len(listed), "withProjectUid": sum(1 for item in listed if item["projectUid"]), "folderGone": sum(1 for item in listed if not item["folderExists"]),
                    "list": listed[:LIST_LIMIT], "more": max(0, len(listed) - LIST_LIMIT)}

        part("projects", projects_part)
        turns = part("emptyTurns", lambda: empty_turns(db, tables, now))

        def bytes_part() -> dict[str, int]:
            """Where the root file's bytes are, by table (text and embeddings; index pages are not counted)."""
            sizes = {"memory_entries": totals["entryBytes"]}
            for name, size in (("memory_episodes", _size("summary") + "+" + _size("embedding_json") + "+240"),
                               ("memory_operations", _size("payload_json") + "+" + _size("receipt_json") + "+320"),
                               ("memory_source_catalogue", _size("address_json") + "+420"), ("memory_source_versions", _size("address_json") + "+160"),
                               ("memory_curation_jobs", _size("payload_json") + "+" + _size("result_json") + "+260")):
                if name in tables:
                    sizes[name] = int(db.execute(f"SELECT COALESCE(SUM({size}),0) FROM {name}").fetchone()[0])
            return sizes

        part("tableBytesEstimate", bytes_part)

        def forecast_part() -> dict[str, Any]:
            from . import memory_split as split
            found = split.scan(db, owner)  # the move's own classifier, on this read-only connection
            move_bytes = sum(line["bytes"] for agent_id, line in agents.items() if state_of(agent_id)["movable"]) + sum(line["bytes"] for line in project_rows.values())
            by_store = Counter(move.ref.kind for move in found.moves)
            after = len(found.moves) + sum(incoming.values())
            total_rows = _count(db, "memory_entries")
            stay = Counter(found.stuck)
            stay["not_a_move_candidate"] = total_rows - found.candidates  # user_identity, session: the root is their store
            need = max(split.MIN_FREE_BYTES, 2 * totals["candidateBytes"])  # the rule of memory_split.start, from the sizes read in the pass
            free = shutil.disk_usage(path.parent).free
            file_bytes, free_pages = root.get("bytes", 0), root.get("freePageBytes", 0)
            freed = free_pages + move_bytes + (turns.get("reclaimBytesEstimate", 0) if isinstance(turns, dict) else 0)
            threshold = max(split.VACUUM_MIN_FREE_PAGES_BYTES, file_bytes // 4)
            return {"moveRows": len(found.moves), "moveBytesEstimate": move_bytes, "moveByStore": dict(by_store), "moveRowsAfterReclassify": after,
                    "stayRows": total_rows - len(found.moves), "stayRowsAfterReclassify": total_rows - after, "stayReasons": dict(stay),
                    "disk": {"freeBytes": int(free), "needBytes": int(need), "enough": free >= need},
                    "vacuum": {"fileBytes": file_bytes, "freeBytesNow": free_pages, "freeBytesAfterEstimate": freed, "thresholdBytes": threshold,
                               "wouldRunNow": free_pages >= threshold, "wouldRunAfter": freed >= threshold}}

        part("forecast", forecast_part)
    finally:
        db.close()
    if _store_stamp(path) != before:
        if mode == "immutable":
            report["_immutableChanged"] = True  # no lock was held, so what was read can be torn: ``plan`` reads again
        notes.append("root:store_changed_during_read")  # another process wrote meanwhile; the counts are from one moment of it
    report.update(notes=notes, elapsedMs=int((time.monotonic() - started) * 1000))
    return report


# --- command line -------------------------------------------------------------------------------------------------------

def _pretty(report: dict[str, Any]) -> str:
    lines: list[str] = []

    def section(title: str, value: Any, skip: tuple[str, ...] = ()) -> None:
        lines.append(f"\n== {title}")
        if not isinstance(value, dict):
            lines.append(f"  {value}")
            return
        for key, item in value.items():
            if key in skip:
                continue
            if isinstance(item, dict):
                lines.append(f"  {key}:")
                lines.extend(f"    {sub:<32} {text}" for sub, text in item.items())
            elif isinstance(item, list):
                lines.append(f"  {key}: {len(item)}")
            else:
                lines.append(f"  {key:<34} {item}")

    def table(title: str, rows: list[dict[str, Any]], columns: tuple[str, ...]) -> None:
        if not rows:
            return
        lines.append(f"\n-- {title}")
        widths = [max(len(column), *(len(str(row.get(column, ""))) for row in rows)) for column in columns]
        lines.append("  " + "  ".join(column.ljust(width) for column, width in zip(columns, widths)))
        lines.extend("  " + "  ".join(str(row.get(column, "")).ljust(width) for column, width in zip(columns, widths)) for row in rows)

    lines.append(f"first-run plan (read-only)  owner {report.get('owner', {}).get('kind')}:{report.get('owner', {}).get('id8')}  {report.get('elapsedMs')} ms")
    for name, title in (("root", "root store"), ("tables", "table rows")):
        if name in report:
            section(title, report[name])
    if isinstance(report.get("rows"), dict):
        section("memory rows (live)", report["rows"], skip=("table",))
        table("scope x actor family x has project", report["rows"].get("table", [])[:40], ("scope", "family", "project", "rows"))
    for name, title in (("personal", "personal"), ("drawer", "One drawer vs imported rows"), ("reclassify", "reclassification forecast")):
        if name in report:
            section(title, report[name], skip=("unresolvedLabels",))
    if isinstance(report.get("drawer"), dict):
        table("drawer labels with no known folder (sha256(label)[:8])", report["drawer"].get("unresolvedLabels", []), ("label8", "blocks"))
    if isinstance(report.get("agents"), dict):
        section("agents", report["agents"], skip=("list",))
        table("per agent", report["agents"].get("list", [])[:60], ("agent", "family", "rows", "retired", "folder", "movable", "reason"))
    if isinstance(report.get("projects"), dict):
        section("projects", report["projects"], skip=("list",))
        table("per project (sha256(path)[:8])", report["projects"].get("list", [])[:60], ("project8", "rows", "retired", "incoming", "folderExists", "projectUid", "key"))
    for name, title in (("emptyTurns", "turn records that left no memory"), ("tableBytesEstimate", "bytes by table (estimate)"), ("forecast", "move forecast")):
        if name in report:
            section(title, report[name])
    if isinstance(report.get("engines"), dict):
        section("engine copies", report["engines"], skip=("copies",))
        table("copies", report["engines"].get("copies", []), ("host", "state", "version", "memoryLayout", "reason"))
    lines.append("\nnotes: " + (", ".join(report.get("notes") or []) or "none"))
    return "\n".join(lines)


def _owner_of_store(store8: str) -> str | None:
    """The owner namespace a store names in its own meta, for the one store folder whose name starts with ``store8``."""
    from .memory_runtime import memory_io_root
    if not re.fullmatch(r"[0-9a-f]{8,64}", store8):
        raise ValueError("owner_store_invalid")
    found = [path for path in (memory_io_root() / "owners").glob(store8 + "*/" + ms.STORE_FILE) if not path.is_symlink()]
    if len(found) != 1:
        raise ValueError("owner_store_not_found" if not found else "owner_store_ambiguous")
    db, _mode = open_readonly(found[0])
    try:
        owner = _meta(db, "owner_namespace")
    finally:
        db.close()
    if not owner or hashlib.sha256(owner.encode("utf-8")).hexdigest() != found[0].parent.name:
        raise ValueError("owner_store_unnamed")
    return owner


PROJECTS_STDIN_BYTES = 8 << 20   # the project list on standard input (`reclassify --projects-stdin`)

_CLASSIFY_COMMANDS = {"reclassify": "agentlas.first-run-classify.v1", "undo": "agentlas.first-run-undo.v1", "label_candidates": "agentlas.first-run-labels.v1",
                      "apply_labels": "agentlas.first-run-labels.v1", "llm_state": "agentlas.first-run-labels.v1"}


def _schema_of(argv: list[str]) -> str:
    """The schema name an answer carries, from the command the arguments name (a wrong argument is still one JSON line)."""
    for word in argv:
        if word in _CLASSIFY_COMMANDS:
            return _CLASSIFY_COMMANDS[word]
    return STEPS_SCHEMA if "steps" in argv else SCHEMA


class _JsonArgumentParser(argparse.ArgumentParser):
    """A wrong argument is still one JSON line on stdout (a machine reason, exit 2); the usage goes to stderr as before."""

    argv: list[str] = []

    def error(self, message: str) -> Any:
        self.print_usage(sys.stderr)
        print(_json({"schema": _schema_of(self.argv), "state": "failed", "reason": "bad_arguments"}))
        raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stdin):   # the answers carry memory text (Korean among it): UTF-8 whatever the console's code page is
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError, OSError):
            pass
    _JsonArgumentParser.argv = list(sys.argv[1:] if argv is None else argv)
    parser = _JsonArgumentParser(prog="first_run", description="What the 2.0 first-run migration would do. Reads only; one JSON line per call.")
    commands = parser.add_subparsers(dest="command", required=True)
    plan_p = commands.add_parser("plan", help="counts and hashed identifiers only: no memory text, no path")
    plan_p.add_argument("--json", action="store_true", help="one JSON line (the default)")
    plan_p.add_argument("--pretty", action="store_true", help="a table for people instead of the JSON line")
    plan_p.add_argument("--project", action="append", default=[], metavar="[ID=]FOLDER", help="a project folder the app knows (repeat)")
    plan_p.add_argument("--projects-under", action="append", default=[], metavar="DIR", help="look for project folders up to 3 levels under DIR (repeat)")
    plan_p.add_argument("--agent-routes", default=None, metavar="FILE", help="the desktop's agent-routes.json, to tell why an agent has no folder")
    plan_p.add_argument("--project-name", action="append", default=[], metavar="ID=NAME", help="a registered project's name in the app (repeat); the folder's name when none")
    plan_p.add_argument("--show-agent-ids", action="store_true", help="name agents by id (default: first 8 hex digits of the id's sha256)")
    plan_p.add_argument("--owner-store", default=None, metavar="STORE8", help="another owner's store on this computer, by the store8 the report lists")
    steps_p = commands.add_parser("steps", help="the engine's steps of the migration, in order, one JSON line; safe to call again")
    steps_p.add_argument("--only", action="append", default=[], choices=STEP_NAMES, help="run just these steps (repeat)")
    steps_p.add_argument("--homes-ready", action="store_true", help="the desktop has made the agent folders: memory_move may turn the split layout on")
    steps_p.add_argument("--engine", action="append", default=[], metavar="ROOT", help="another engine copy to count (the desktop's bundled engine)")
    steps_p.add_argument("--budget-seconds", type=float, default=2.0, help="time per step before it answers `remaining` (0 = no limit for empty_turns and memory_move)")
    steps_p.add_argument("--no-updater", action="store_true", help="engine_copies only reads; it does not run the installed engine's updater")
    steps_p.add_argument("--check", action="store_true", help="read only: report what is left, run nothing")
    steps_p.add_argument("--removed-agents-stdin", action="store_true", help='tidy: the agent ids the app says are removed, as {"agents":["ID"]} on standard input')
    steps_p.add_argument("--owner-store", default=None, metavar="STORE8")
    reclassify_p = commands.add_parser("reclassify", help="5a: move the lines learned in exactly one project folder to that project; one JSON line; safe to call again")
    reclassify_p.add_argument("--project", action="append", default=[], metavar="[ID=]FOLDER", help="a project folder the app knows (repeat)")
    reclassify_p.add_argument("--projects-under", action="append", default=[], metavar="DIR")
    reclassify_p.add_argument("--project-name", action="append", default=[], metavar="ID=NAME", help="a registered project's name in the app (repeat)")
    reclassify_p.add_argument("--projects-stdin", action="store_true", help='the project list as one JSON object on standard input ({"projects":["ID=FOLDER"],"under":["DIR"],"names":["ID=NAME"]}), '
                              'added to the flags above: a command line cannot carry a long list (an engine without this flag answers bad_arguments)')
    reclassify_p.add_argument("--budget-seconds", type=float, default=2.0, help="time before it answers `remaining`/`budget` (0 = no limit)")
    reclassify_p.add_argument("--owner-store", default=None, metavar="STORE8")
    undo_p = commands.add_parser("undo", help="put one reclassified line back as it was")
    undo_p.add_argument("--memory-id", required=True)
    undo_p.add_argument("--owner-store", default=None, metavar="STORE8")
    cand_p = commands.add_parser("label_candidates", help="5b: the next lines about the owner as a person, as numbered text for a model (starts one attempt)")
    cand_p.add_argument("--limit", type=int, default=40, help="lines per call (10 for a local model)")
    cand_p.add_argument("--owner-store", default=None, metavar="STORE8")
    apply_p = commands.add_parser("apply_labels", help="5b: apply the model's answers (JSON on stdin or --answers FILE) in one transaction with the progress key")
    apply_p.add_argument("--answers", default="-", metavar="FILE", help="a JSON file, `-` for stdin")
    apply_p.add_argument("--owner-store", default=None, metavar="STORE8")
    state_p = commands.add_parser("llm_state", help="5b: the progress key, whether 5a is finished, whether this computer is the personal agent's home (read only)")
    state_p.add_argument("--owner-store", default=None, metavar="STORE8")
    vacuum_p = commands.add_parser("vacuum", help="one VACUUM of the root when it is worth it (the app runs it as it ends)")
    vacuum_p.add_argument("--timeout-seconds", type=float, default=5.0)
    vacuum_p.add_argument("--owner-store", default=None, metavar="STORE8")
    args = parser.parse_args(argv)
    schema = _CLASSIFY_COMMANDS.get(args.command) or (STEPS_SCHEMA if args.command == "steps" else SCHEMA)
    try:
        answer = _dispatch(args, schema)
        print(_pretty(answer) if args.command == "plan" and args.pretty and "root" in answer else _json(answer))  # a refusal (no ``root``) stays JSON
    except Exception as error:  # noqa: BLE001 - the caller reads one JSON line and an exit code of 0 whatever happens: a trace would be neither
        code = _code(error)
        # A store another process holds for a moment, or a forget by another process during the call (its binding number changed), is "stand aside and call again", not a failure
        # (defect 4); every other code is a machine code and never the message, which can hold a path.
        print(_json({"schema": schema, "state": "remaining" if code == "locked" and args.command in (*_CLASSIFY_COMMANDS, "steps") else "failed", "reason": code}))
    return 0


def _dispatch(args: argparse.Namespace, schema: str) -> dict[str, Any]:
    """The answer of one command (``main`` prints it, and turns anything raised here into a ``failed`` line with a reason code)."""
    from .memory_runtime import owner_binding
    try:
        owner = _owner_of_store(args.owner_store) if args.owner_store else owner_binding(create=False)
    except (ValueError, OSError, sqlite3.Error, Unreadable) as error:
        return {"schema": schema, "state": "deferred", "reason": str(error) if re.fullmatch(r"[a-z_]+", str(error)) else _code(error)}
    if not owner:
        return {"schema": schema, "state": "deferred", "reason": "owner_unbound"}
    if args.command == "steps":
        from .first_run_steps import run_steps
        removed: list[str] = []
        if args.removed_agents_stdin:
            raw = sys.stdin.read(PROJECTS_STDIN_BYTES + 1)
            try:
                given = json.loads(raw) if len(raw) <= PROJECTS_STDIN_BYTES else None
            except ValueError:
                given = None
            if not isinstance(given, dict):
                return {"schema": schema, "state": "failed", "reason": "bad_arguments"}
            removed = [item for item in given.get("agents", []) if isinstance(item, str) and item and "\0" not in item] if isinstance(given.get("agents"), list) else []
        return run_steps(owner, only=args.only, homes_ready=args.homes_ready, extra_engines=args.engine, budget_seconds=args.budget_seconds,
                         run_updater=not args.no_updater, check_only=args.check, removed_agents=removed)
    if args.command in _CLASSIFY_COMMANDS:
        from . import first_run_classify as classify
        if args.command == "reclassify":
            projects, under, names = list(args.project), list(args.projects_under), list(args.project_name)
            if args.projects_stdin:
                raw = sys.stdin.read(PROJECTS_STDIN_BYTES + 1)
                try:
                    given = json.loads(raw) if len(raw) <= PROJECTS_STDIN_BYTES else None
                except ValueError:
                    given = None
                if not isinstance(given, dict):
                    return {"schema": schema, "state": "failed", "reason": "bad_arguments"}
                for key, target in (("projects", projects), ("under", under), ("names", names)):
                    value = given.get(key)
                    if isinstance(value, list):
                        target.extend(item for item in value if isinstance(item, str) and "\0" not in item)
            return classify.reclassify(owner, projects=projects, projects_under=under, project_names=names,
                                       budget_seconds=args.budget_seconds if args.budget_seconds > 0 else None)
        if args.command == "undo":
            return classify.undo(owner, args.memory_id)
        if args.command == "label_candidates":
            return classify.label_candidates(owner, limit=args.limit)
        if args.command == "llm_state":
            return classify.llm_state(owner)
        raw = sys.stdin.read(classify.MAX_ANSWER_BYTES + 1) if args.answers == "-" else Path(args.answers).read_text(encoding="utf-8")
        answers = json.loads(raw) if len(raw) <= classify.MAX_ANSWER_BYTES else None
        if not isinstance(answers, dict):
            return {"schema": schema, "state": "failed", "reason": "bad_arguments"}
        return classify.apply_labels(owner, answers)
    if args.command == "vacuum":
        from .memory_split import vacuum_root
        return vacuum_root(owner, timeout_seconds=args.timeout_seconds)
    report = plan(owner, projects=args.project, projects_under=args.projects_under, agent_routes=args.agent_routes, show_agent_ids=args.show_agent_ids,
                  project_names=args.project_name)
    return report


if __name__ == "__main__":
    raise SystemExit(main())
