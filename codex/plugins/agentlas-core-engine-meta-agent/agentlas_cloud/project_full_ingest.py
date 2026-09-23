"""Project full ingest — migration ``project-full-ingest.v1`` (plan M4, §9-6).

Measured 2026-09-22: every project ontology on the pilot machine held exactly
ONE source — the auto-generated ``agentlas-project-index.md`` — and zero
relations. The ingest itself worked; it simply had nothing else to eat.
``CLAUDE.md``, ``DEPLOY.md``, ``HANDOFF-*``, ``docs/**`` and the project's own
``.agentlas/pm/learnings`` never reached recall. Owner decision: a project's
knowledge goes in, all of it. Caps exist for SAFETY (secrets, credential
stores, binaries, build output, other projects), never for size.

Why snapshots instead of ingesting the live files
-------------------------------------------------
``OntologyRuntime.query`` refuses to answer (``status: stale_index``) when ANY
registered source file's bytes differ from what was ingested. Registering live
documents that other sessions edit all day would blank the whole project layer
the moment someone saved a markdown file, until the next re-ingest. So each
document is copied into ``.agentlas/ontology-project-docs/`` and THAT copy is
ingested — the copy changes only when this module rewrites it, and each rewrite
is ingested in its own short transaction right after. The copy keeps the
original's mtime, so recall's age labels still describe the real document.

Hook budget
-----------
Nothing here runs inside a hook. ``memory_hook`` only calls :func:`spawn_reason`
(one small JSON read) and then launches ``agentlas project ingest`` detached,
the same shape ``_spawn_project_ensure`` and ``project_index_backstop`` use.

Resumable and idempotent
------------------------
Every document is committed on its own. The runtime keys a source by its URI
and skips any whose content hash is unchanged, so a killed run resumes where it
stopped and a repeated run writes nothing. The migration receipt lands in
``migrations.jsonl`` exactly once; a failure lands there as
``kind: migration-failed`` with its reason, never as silence.
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

MIGRATION_ID = "project-full-ingest.v1"
SCHEMA = "agentlas.project-full-ingest.v1"
MIGRATION_LEDGER = "migrations.jsonl"
STATE_FILE = "project-full-ingest.json"
LOCK_FILE = ".project-full-ingest.lock"
SNAPSHOT_DIR = "ontology-project-docs"
ONTOLOGY_DB_FILE = "ontology-runtime.sqlite"
# The project's own durable memory. It lives under `.agentlas/`, which the walk
# skips as a dot-directory, so until 2026-09-23 no project soul ever reached
# its project's recall layer. It is ingested like any other document (as a
# snapshot), first, so it always owns its plain snapshot name.
PROJECT_SOUL_RELATIVE = ".agentlas/project-soul-memory.md"
SOUL_REFRESH_STATE_FILE = "project-soul-refresh.json"
SOUL_REFRESH_LOCK_WAIT_SECONDS = 120

# Scheduling (read by the hook through spawn_reason; all cheap).
REFRESH_AFTER_SECONDS = 6 * 60 * 60
SPAWN_GRACE_SECONDS = 15 * 60
RUNNING_STALE_SECONDS = 3 * 60 * 60
FAILURE_BACKOFF_SECONDS = 60 * 60
FAILURE_BACKOFF_MAX_SECONDS = 24 * 60 * 60

# Runaway guards, not size budgets. A run that hits one stops cleanly, keeps
# everything it already committed, and the next run continues from there.
RUN_DEADLINE_SECONDS = 30 * 60
MAX_DOCUMENTS = 50_000
MAX_CODE_FILES = 200_000
MAX_WALK_DEPTH = 24
PM_MAX_DEPTH = 8

# Source-comment digests: the leading doc comment of each source file, grouped
# by directory. Reading a bounded head keeps this cheap on large trees.
CODE_HEAD_BYTES = 16 * 1024
MIN_COMMENT_CHARS = 120
MAX_COMMENT_CHARS = 2_000
DIGEST_MAX_CHARS = 200_000
MAX_RECORDED_PATHS = 50

DOC_SUFFIXES = {".md", ".mdx", ".markdown", ".rst", ".adoc"}
TEXT_SUFFIXES = {".txt", ".text"}
NAMED_DOC_PREFIXES = ("README", "HANDOFF", "DEPLOY", "CLAUDE", "AGENTS", "GEMINI", "CHANGELOG")
DOC_DIRECTORY_NAMES = {"docs", "doc"}

# Build output, dependency trees and test data: never a project's own
# knowledge. Dot-directories are excluded wholesale (VCS internals, caches,
# worktrees, recovery copies); the project's own `.agentlas/pm` is read
# separately below.
EXCLUDED_DIR_NAMES = {
    "node_modules",
    "dist",
    "build",
    "out",
    "target",
    "release",
    "release-local",
    "coverage",
    "vendor",
    "node-runtime",
    "python-runtime",
    "__pycache__",
    "fixtures",
    "__fixtures__",
    "__snapshots__",
    "testdata",
    "signing",
    # Scratch and log trees: measured on the desktop tree, `tmp/dino/log/*.md`
    # outranked the real design notes for a product question.
    "tmp",
    "temp",
    "logs",
    # Deleted or superseded copies (measured on the Agentlas_F copy: trash/
    # and backups/ carried old duplicates of live documents).
    "trash",
    "backup",
    "backups",
}
VCS_MARKERS = (".git", ".hg", ".svn")


def _test_corpus_directory(name: str) -> bool:
    """Sample corpora a product's own tests ingest (``examples/ontology-corpus``).

    Measured 2026-09-23: 2 of the 5 relations in Agentlas-OS's project graph
    came from that corpus's fictional company ("Atlas Robotics owns Project
    Helios"). A corpus is input to a test, not knowledge about the project.
    """

    lowered = name.lower()
    return lowered == "corpus" or lowered.endswith(("-corpus", "_corpus", ".corpus"))

HASH_COMMENT_SUFFIXES = {".py", ".sh", ".bash", ".zsh", ".rb"}
SLASH_COMMENT_SUFFIXES = {
    ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts",
    ".go", ".rs", ".swift", ".kt", ".kts", ".java", ".c", ".cc", ".cpp",
    ".h", ".hpp", ".m", ".mm", ".cs", ".dart", ".scala", ".vue",
}
COMMENT_SUFFIXES = HASH_COMMENT_SUFFIXES | SLASH_COMMENT_SUFFIXES
_LICENSE_HINT = re.compile(r"copyright|spdx-license|licensed under|all rights reserved", re.I)
_PY_DOCSTRING = re.compile(r'\A[rRuUbB]{0,2}("""|\'\'\')(.*?)\1', re.S)
# High-precision secret classes from the public-boundary detector. The broad
# `credential_assignment` / `bearer_token` shapes are left out on purpose:
# engineering docs say "token = getToken()" and "Bearer <token>" constantly,
# and a whole-document skip on those would drop the docs this migration exists
# to ingest. The backstop's SECRET_PATTERNS still catch real assignments.
_STRICT_SECRET_KINDS = {"provider_token", "private_key", "jwt", "credential_url"}


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_stamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# State and ledger (cheap reads; the hook side uses only these)
# ---------------------------------------------------------------------------


def _agentlas(root: Path) -> Path:
    return root / ".agentlas"


def read_state(root: Path) -> dict[str, Any]:
    path = _agentlas(root) / STATE_FILE
    try:
        if not path.is_file() or path.is_symlink():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_state(root: Path, state: dict[str, Any]) -> None:
    path = _agentlas(root) / STATE_FILE
    temporary = path.with_name(f".{STATE_FILE}.tmp.{os.getpid()}.{time.time_ns()}")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        os.chmod(temporary, 0o600)
    except OSError:
        pass
    temporary.replace(path)


def _ledger_records(root: Path) -> list[dict[str, Any]]:
    path = _agentlas(root) / MIGRATION_LEDGER
    records: list[dict[str, Any]] = []
    try:
        if not path.is_file() or path.is_symlink():
            return records
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    records.append(record)
    except OSError:
        return records
    return records


def migration_applied(root: Path) -> bool:
    return any(
        record.get("id") == MIGRATION_ID and record.get("kind") != "migration-failed"
        for record in _ledger_records(root)
    )


def _append_ledger(root: Path, record: dict[str, Any]) -> None:
    path = _agentlas(root) / MIGRATION_LEDGER
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def record_migration_failure(root: Path, reason: str) -> None:
    """Leave a visible failure receipt. Never raises."""

    try:
        _append_ledger(
            root,
            {"id": MIGRATION_ID, "at": utc_now(), "kind": "migration-failed", "reason": _bounded_reason(reason)},
        )
    except OSError:
        pass


def _bounded_reason(reason: str) -> str:
    text = " ".join(str(reason or "unknown").split())
    home = str(Path.home())
    if home and home != "/":
        text = text.replace(home, "~")
    return text[:300]


def _pid_alive(pid: Any) -> bool:
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) on Windows sends CTRL_C_EVENT (0) rather than probing.
        # The RUNNING_STALE_SECONDS window alone bounds a dead run there.
        return True
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def spawn_reason(root: Path, *, migration_pending: bool, now: float | None = None) -> str | None:
    """Should the hook launch a detached ingest now? Returns the reason or None.

    Reads one small JSON file. A run already in flight, a recent failure still
    in backoff, or a recent completion all answer None.
    """

    current = time.time() if now is None else now
    state = read_state(root)
    status = state.get("status")
    if status == "spawned":
        spawned = _parse_stamp(state.get("spawnedAt"))
        if spawned is not None and current - spawned < SPAWN_GRACE_SECONDS:
            return None
    if status == "running":
        started = _parse_stamp(state.get("startedAt"))
        if (
            started is not None
            and current - started < RUNNING_STALE_SECONDS
            and _pid_alive(state.get("pid"))
        ):
            return None
    if status == "failed":
        failed = _parse_stamp(state.get("finishedAt"))
        failures = max(1, int(state.get("consecutiveFailures") or 1))
        backoff = min(FAILURE_BACKOFF_MAX_SECONDS, FAILURE_BACKOFF_SECONDS * (2 ** (failures - 1)))
        if failed is not None and current - failed < backoff:
            return None
    if migration_pending:
        return "migration"
    if status in {"complete", "partial"}:
        finished = _parse_stamp(state.get("finishedAt"))
        if finished is None or current - finished >= REFRESH_AFTER_SECONDS:
            return "refresh"
        return None
    if status in {"failed", "running", "spawned"}:
        # A refresh that failed (or died) after the migration landed: retry
        # once its backoff/grace has elapsed, which the checks above enforce.
        return "refresh"
    return None


def mark_spawned(root: Path, reason: str) -> None:
    state = read_state(root)
    state.update({"schema": SCHEMA, "status": "spawned", "spawnedAt": utc_now(), "reason": reason})
    _write_state(root, state)


# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------


def _boundary_guarded(pattern: "re.Pattern[str]") -> "re.Pattern[str]":
    # SECRET_PATTERNS' provider-key shape is `sk-...` with no left boundary, so
    # it fires inside ordinary hyphenated prose: measured on the desktop tree,
    # "risk-estimation-…", "task-inheritance-…" and "desk-…" each dropped a
    # whole document (8 of 10 secret skips were this). A key never starts in
    # the middle of a word.
    source = pattern.pattern
    if source.startswith("sk-"):
        return re.compile(r"(?<![A-Za-z0-9_-])" + source, pattern.flags)
    return pattern


def looks_secret(text: str) -> bool:
    """The backstop's looksSecret plus the strict public-boundary classes."""

    from .runtime import SECRET_PATTERNS

    if any(_boundary_guarded(pattern).search(text) for pattern in SECRET_PATTERNS):
        return True
    try:
        from .experience_privacy import secret_like_kinds

        return bool(_STRICT_SECRET_KINDS.intersection(secret_like_kinds(text)))
    except Exception:
        return False


def _credential_segment(name: str) -> bool:
    from .runtime import CREDENTIAL_STORE_DIRS

    return name in CREDENTIAL_STORE_DIRS


def _nested_project(path: Path) -> bool:
    """Another project's root: it owns its own ontology, so the parent skips it."""

    try:
        if (path / ".agentlas").is_dir():
            return True
        return any((path / marker).exists() for marker in VCS_MARKERS)
    except OSError:
        return False


def _decode_text(raw: bytes) -> str | None:
    if b"\x00" in raw[:8192]:
        return None
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _localize(text: str, root: Path) -> str:
    """Host-absolute paths become portable placeholders.

    ``$PROJECT_ROOT`` is the placeholder the privacy layer already recognises;
    the home directory becomes ``~``. The snapshot is local-only, but recall
    text is shown to models, and a machine-specific prefix adds nothing there.
    """

    for spelling in {str(root), os.path.realpath(str(root))}:
        if spelling and spelling != "/":
            text = text.replace(spelling, "$PROJECT_ROOT")
    home = str(Path.home())
    if home and home != "/":
        text = text.replace(home, "~")
    return text


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _is_named_doc(name: str) -> bool:
    upper = name.upper()
    return any(upper.startswith(prefix) for prefix in NAMED_DOC_PREFIXES)


def _document_kind(relative_parts: tuple[str, ...]) -> bool:
    name = relative_parts[-1]
    suffix = Path(name).suffix.lower()
    if suffix in DOC_SUFFIXES:
        return True
    if suffix in TEXT_SUFFIXES or suffix == "":
        if _is_named_doc(name):
            return True
        return suffix in TEXT_SUFFIXES and any(part.lower() in DOC_DIRECTORY_NAMES for part in relative_parts[:-1])
    return False


def _project_soul(root: Path) -> Path | None:
    agentlas = _agentlas(root)
    soul = root / PROJECT_SOUL_RELATIVE
    try:
        if agentlas.is_symlink() or not agentlas.is_dir() or soul.is_symlink():
            return None
        return soul if stat.S_ISREG(soul.lstat().st_mode) else None
    except OSError:
        return None


def discover(root: Path, *, deadline: float | None = None) -> dict[str, Any]:
    """Walk the project once. Returns documents, code files and skip counts."""

    documents: list[tuple[str, Path]] = []
    code_files: list[tuple[str, Path]] = []
    skipped: dict[str, int] = {}
    stop: str | None = None

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    soul = _project_soul(root)
    if soul is not None:
        documents.append((PROJECT_SOUL_RELATIVE, soul))

    root_str = str(root)
    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        relative_dir = () if current == root_str else current_path.relative_to(root).parts
        kept: list[str] = []
        for name in sorted(dirnames):
            candidate = current_path / name
            if name.startswith("."):
                skip("hidden_directory")
                continue
            if name in EXCLUDED_DIR_NAMES or name.startswith(".tmp-") or name.lower().endswith(".app"):
                skip("excluded_directory")
                continue
            if _test_corpus_directory(name):
                skip("test_corpus")
                continue
            if _credential_segment(name):
                skip("credential_store")
                continue
            if candidate.is_symlink():
                skip("symlink")
                continue
            if len(relative_dir) + 1 > MAX_WALK_DEPTH:
                skip("depth")
                continue
            if _nested_project(candidate):
                skip("nested_project")
                continue
            kept.append(name)
        dirnames[:] = kept
        for name in sorted(filenames):
            if name.startswith("."):
                # Covers .env, .env.* and every other dotfile.
                skip("hidden_file")
                continue
            parts = (*relative_dir, name)
            suffix = Path(name).suffix.lower()
            is_doc = _document_kind(parts)
            is_code = not is_doc and suffix in COMMENT_SUFFIXES
            if not is_doc and not is_code:
                continue
            path = current_path / name
            try:
                info = path.lstat()
            except OSError:
                skip("unreadable")
                continue
            if not stat.S_ISREG(info.st_mode):
                skip("not_regular_file")
                continue
            relative = "/".join(parts)
            if is_doc:
                if len(documents) >= MAX_DOCUMENTS:
                    stop = stop or "document_limit"
                    continue
                documents.append((relative, path))
            elif len(code_files) < MAX_CODE_FILES:
                code_files.append((relative, path))
            else:
                stop = stop or "code_file_limit"
        if deadline is not None and time.monotonic() >= deadline:
            stop = stop or "deadline"
            break

    pm_root = _agentlas(root) / "pm"
    if pm_root.is_dir() and not pm_root.is_symlink():
        stack: list[tuple[Path, int]] = [(pm_root, 0)]
        while stack:
            directory, depth = stack.pop()
            try:
                entries = sorted(directory.iterdir(), key=lambda item: item.name)
            except OSError:
                continue
            for entry in entries:
                if entry.name.startswith(".") or entry.is_symlink():
                    continue
                if entry.is_dir():
                    if depth < PM_MAX_DEPTH and not _credential_segment(entry.name):
                        stack.append((entry, depth + 1))
                    continue
                suffix = entry.suffix.lower()
                if suffix not in DOC_SUFFIXES and suffix not in TEXT_SUFFIXES:
                    continue
                if not entry.is_file():
                    continue
                relative = ".agentlas/pm/" + entry.relative_to(pm_root).as_posix()
                documents.append((relative, entry))
    return {"documents": documents, "code_files": code_files, "skipped": skipped, "stop": stop}


# ---------------------------------------------------------------------------
# Source-comment extraction
# ---------------------------------------------------------------------------


def _clean_comment(lines: Iterable[str]) -> str:
    text = "\n".join(line.rstrip() for line in lines).strip()
    return re.sub(r"\n{3,}", "\n\n", text)


def extract_leading_comment(text: str, suffix: str) -> str | None:
    """The file's leading doc comment, or None when it has none worth keeping."""

    lines = text.splitlines()
    index = 0
    # Preamble that precedes a header comment.
    while index < len(lines):
        stripped = lines[index].strip()
        if (
            not stripped
            or stripped.startswith("#!")
            or stripped.startswith("# -*-")
            or stripped.startswith("# coding")
            or stripped in {"'use strict';", '"use strict";', "'use strict'", '"use strict"'}
        ):
            index += 1
            continue
        break
    remainder = "\n".join(lines[index:])
    comment: str | None = None
    if suffix == ".py":
        match = _PY_DOCSTRING.match(remainder.lstrip())
        if match:
            comment = _clean_comment(line for line in match.group(2).splitlines())
    if comment is None and suffix in HASH_COMMENT_SUFFIXES:
        block: list[str] = []
        for line in lines[index:]:
            stripped = line.strip()
            if stripped.startswith("#"):
                block.append(stripped.lstrip("#").strip())
                continue
            break
        comment = _clean_comment(block) if block else None
    if comment is None and suffix in SLASH_COMMENT_SUFFIXES:
        stripped_rest = remainder.lstrip()
        if stripped_rest.startswith("/*"):
            end = stripped_rest.find("*/")
            if end != -1:
                body = stripped_rest[2:end]
                comment = _clean_comment(
                    re.sub(r"^\s*\*\s?", "", line).rstrip() for line in body.lstrip("*").splitlines()
                )
        elif stripped_rest.startswith("//"):
            block = []
            for line in lines[index:]:
                stripped = line.strip()
                if stripped.startswith("//"):
                    block.append(re.sub(r"^//[/!]?\s?", "", stripped))
                    continue
                break
            comment = _clean_comment(block)
    if not comment:
        return None
    if _LICENSE_HINT.search(comment[:300]):
        return None
    if len(comment) < MIN_COMMENT_CHARS:
        return None
    return comment[:MAX_COMMENT_CHARS].rstrip()


def _read_head(path: Path) -> str | None:
    try:
        with path.open("rb") as handle:
            raw = handle.read(CODE_HEAD_BYTES)
    except OSError:
        return None
    if b"\x00" in raw:
        return None
    return raw.decode("utf-8", errors="ignore")


# ---------------------------------------------------------------------------
# Snapshot naming and writing
# ---------------------------------------------------------------------------


def snapshot_name(relative: str) -> str:
    """Deterministic flat file name that still reads as the original path."""

    import hashlib

    parts = [part.lstrip(".") or "_" for part in relative.split("/") if part]
    stem_parts = parts[:-1] + [Path(parts[-1]).stem or parts[-1]] if parts else ["document"]
    stem = "__".join(stem_parts)
    stem = re.sub(r"[^\w.\-]+", "_", stem).strip("._") or "document"
    suffix = Path(parts[-1]).suffix.lower() if parts else ""
    extension = ".txt" if suffix in TEXT_SUFFIXES else ".md"
    if len(stem.encode("utf-8")) > 160:
        digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:10]
        encoded = stem.encode("utf-8")[:140].decode("utf-8", errors="ignore").rstrip("._")
        stem = f"{encoded}-{digest}"
    return stem + extension


def _write_snapshot(target: Path, body: bytes, mtime: float) -> bool:
    """Write only when bytes differ. Returns True when the file changed."""

    changed = True
    try:
        if target.is_file() and not target.is_symlink():
            changed = target.read_bytes() != body
    except OSError:
        changed = True
    if changed:
        temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}")
        temporary.write_bytes(body)
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(target)
    try:
        os.utime(target, (mtime, mtime))
    except OSError:
        pass
    return changed


def _purge_sources(runtime: Any, uris: list[str]) -> int:
    """Drop ontology rows for snapshots that no longer exist."""

    if not uris:
        return 0
    removed = 0
    with closing(runtime.connect()) as conn, conn:
        for uri in uris:
            row = conn.execute("SELECT source_id FROM sources WHERE uri = ?", (uri,)).fetchone()
            if row is None:
                continue
            source_id = str(row["source_id"])
            runtime._delete_source_derivatives(conn, source_id)
            conn.execute(
                "DELETE FROM source_lineage WHERE parent_source_id = ? OR child_source_id = ?",
                (source_id, source_id),
            )
            conn.execute("DELETE FROM sources WHERE source_id = ?", (source_id,))
            removed += 1
        runtime._prune_orphan_entities(conn)
    return removed


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


def _open_runtime(root: Path) -> Any:
    from ontology import OntologyRuntime, RuntimeConfig

    try:
        from ontology.cli import ensure_runtime_files

        ensure_runtime_files(root)
    except Exception:
        # Activation files are a convenience; the database below is the contract.
        pass
    return OntologyRuntime(RuntimeConfig(db_path=_agentlas(root) / ONTOLOGY_DB_FILE))


def _source_counts(runtime: Any, snapshot_root: Path) -> dict[str, int]:
    prefix = snapshot_root.resolve().as_uri() + "/"
    with closing(runtime.connect()) as conn:
        total_sources = conn.execute("SELECT count(*) FROM sources").fetchone()[0]
        total_chunks = conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
        project_sources = conn.execute(
            "SELECT count(*) FROM sources WHERE uri LIKE ?", (prefix + "%",)
        ).fetchone()[0]
        project_chunks = conn.execute(
            "SELECT count(*) FROM chunks WHERE source_id IN (SELECT source_id FROM sources WHERE uri LIKE ?)",
            (prefix + "%",),
        ).fetchone()[0]
    return {
        "sources": int(total_sources),
        "chunks": int(total_chunks),
        "projectDocSources": int(project_sources),
        "projectDocChunks": int(project_chunks),
    }


def _plan_digests(root: Path, code_files: list[tuple[str, Path]], counters: dict[str, int]) -> list[tuple[str, str, float]]:
    """(relative label, body, mtime) for each source-comment digest part."""

    groups: dict[str, list[tuple[str, str, float]]] = {}
    for relative, path in code_files:
        head = _read_head(path)
        if head is None:
            counters["code_unreadable"] = counters.get("code_unreadable", 0) + 1
            continue
        comment = extract_leading_comment(head, path.suffix.lower())
        if comment is None:
            continue
        if looks_secret(comment):
            counters["code_comment_secret"] = counters.get("code_comment_secret", 0) + 1
            continue
        parts = relative.split("/")[:-1]
        group = "/".join(parts[:2]) if parts else "(root)"
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = time.time()
        groups.setdefault(group, []).append((relative, _localize(comment, root), mtime))
    digests: list[tuple[str, str, float]] = []
    for group in sorted(groups):
        entries = groups[group]
        heading = f"Project source notes: {group} (leading doc comments of source files)\n"
        part = 1
        body = [heading]
        size = len(heading)
        newest = 0.0
        for relative, comment, mtime in entries:
            section = f"\n## {relative}\n\n{comment}\n"
            if size + len(section) > DIGEST_MAX_CHARS and len(body) > 1:
                digests.append((f"{group}/source-notes-{part}", "".join(body), newest))
                part += 1
                body = [heading]
                size = len(heading)
                newest = 0.0
            body.append(section)
            size += len(section)
            newest = max(newest, mtime)
        digests.append((f"{group}/source-notes-{part}", "".join(body), newest))
    return digests


def run_full_ingest(project: str | Path, *, reason: str = "explicit") -> dict[str, Any]:
    """Snapshot and ingest every eligible project document. Idempotent."""

    from .project_bootstrap import _project_root, _release_advisory_lock, _try_advisory_lock

    root = _project_root(project)
    agentlas = _agentlas(root)
    if not agentlas.is_dir() or agentlas.is_symlink():
        return {"action": "project_full_ingest", "status": "skipped", "detail": "project_not_initialized"}
    runtime_root = os.environ.get("HEPHAESTUS_RUNTIME_ROOT")
    if runtime_root and root == Path(runtime_root).expanduser().resolve():
        return {"action": "project_full_ingest", "status": "skipped", "detail": "installed_runtime_root"}

    lock_path = agentlas / LOCK_FILE
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    if not _try_advisory_lock(descriptor):
        os.close(descriptor)
        return {"action": "project_full_ingest", "status": "busy"}
    migration_pending = not migration_applied(root)
    previous = read_state(root)
    started_monotonic = time.monotonic()
    state: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "running",
        "reason": reason,
        "pid": os.getpid(),
        "startedAt": utc_now(),
        "consecutiveFailures": int(previous.get("consecutiveFailures") or 0),
    }
    try:
        _write_state(root, state)
        receipt = _ingest(root, started_monotonic)
    except Exception as exc:  # recorded, never swallowed
        failure = f"{type(exc).__name__}: {exc}"
        state.update(
            {
                "status": "failed",
                "finishedAt": utc_now(),
                "error": _bounded_reason(failure),
                "consecutiveFailures": int(state.get("consecutiveFailures") or 0) + 1,
                "durationSeconds": round(time.monotonic() - started_monotonic, 3),
            }
        )
        try:
            _write_state(root, state)
        except OSError:
            pass
        if migration_pending:
            record_migration_failure(root, failure)
        return {"action": "project_full_ingest", **state}
    finally:
        try:
            _release_advisory_lock(descriptor)
        finally:
            os.close(descriptor)

    deadline_hit = receipt.get("stop") == "deadline"
    run_status = "partial" if (receipt["errors"] or receipt.get("stop")) else "complete"
    state.update(
        {
            "status": "failed" if deadline_hit else run_status,
            "finishedAt": utc_now(),
            "durationSeconds": round(time.monotonic() - started_monotonic, 3),
            "consecutiveFailures": int(state.get("consecutiveFailures") or 0) + 1 if deadline_hit else 0,
            **{key: value for key, value in receipt.items() if key != "stop"},
            "stop": receipt.get("stop"),
        }
    )
    _write_state(root, state)
    if migration_pending:
        if deadline_hit:
            # Progress is committed per document; the next run resumes it.
            record_migration_failure(root, "deadline_exceeded: resumable, progress kept")
        else:
            _append_ledger(
                root,
                {
                    "id": MIGRATION_ID,
                    "at": state["finishedAt"],
                    "kind": "migration",
                    "status": run_status,
                    "sources": state["counts"]["sources"],
                    "projectDocSources": state["counts"]["projectDocSources"],
                    "chunks": state["counts"]["chunks"],
                    "durationSeconds": state["durationSeconds"],
                },
            )
    return {"action": "project_full_ingest", **state}


def _prepare_document(root: Path, relative: str, path: Path) -> tuple[str, float, str] | str:
    """(snapshot body, mtime, raw digest) for one document, or a skip reason."""

    import hashlib

    from ontology.runtime import MAX_INGEST_FILE_BYTES

    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            return "not_regular_file"
        if info.st_size > MAX_INGEST_FILE_BYTES:
            return "file_too_large"
        raw = path.read_bytes()
    except OSError:
        return "unreadable"
    text = _decode_text(raw)
    if text is None:
        return "binary_or_not_utf8"
    if not text.strip():
        return "empty"
    if looks_secret(text):
        return "secret"
    body = f"Project document: {relative}\n\n{_localize(text, root)}"
    return body, info.st_mtime, hashlib.sha256(raw).hexdigest()


def refresh_project_soul(project: str | Path, *, wait_seconds: float = SOUL_REFRESH_LOCK_WAIT_SECONDS) -> dict[str, Any]:
    """Re-snapshot and re-ingest ONLY the project soul — seconds, not minutes.

    Called detached by the One stop hook right after it appends a project
    learning, so the next session's project-layer recall already sees it
    instead of waiting for the 6-hour full refresh. Shares the full ingest's
    lock (one writer per ontology) and its snapshot name, so a later full run
    finds the snapshot unchanged. Records its own small receipt.
    """

    from .project_bootstrap import _project_root, _release_advisory_lock, _try_advisory_lock

    root = _project_root(project)
    agentlas = _agentlas(root)
    base = {"action": "project_soul_refresh"}
    if not agentlas.is_dir() or agentlas.is_symlink():
        return {**base, "status": "skipped", "detail": "project_not_initialized"}
    db = agentlas / ONTOLOGY_DB_FILE
    if not db.is_file() or db.is_symlink():
        # Never create a project's ontology from here; `project ensure` owns that.
        return {**base, "status": "skipped", "detail": "no_ontology"}
    soul = _project_soul(root)
    if soul is None:
        return {**base, "status": "skipped", "detail": "no_soul"}
    started = time.monotonic()
    descriptor = os.open(agentlas / LOCK_FILE, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        deadline = started + max(0.0, wait_seconds)
        while True:
            if _try_advisory_lock(descriptor):
                acquired = True
                break
            if time.monotonic() >= deadline:
                break
            time.sleep(0.25)
        if not acquired:
            receipt = {**base, "status": "busy"}
        else:
            try:
                receipt = {**base, **_refresh_soul_locked(root, soul)}
            finally:
                _release_advisory_lock(descriptor)
    except Exception as exc:  # recorded, never swallowed
        receipt = {**base, "status": "failed", "error": _bounded_reason(f"{type(exc).__name__}: {exc}")}
    finally:
        os.close(descriptor)
    receipt["finishedAt"] = utc_now()
    receipt["durationSeconds"] = round(time.monotonic() - started, 3)
    try:
        target = agentlas / SOUL_REFRESH_STATE_FILE
        temporary = target.with_name(f".{target.name}.tmp.{os.getpid()}")
        temporary.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
        temporary.replace(target)
    except OSError:
        pass
    return receipt


def _refresh_soul_locked(root: Path, soul: Path) -> dict[str, Any]:
    snapshot_root = _agentlas(root) / SNAPSHOT_DIR
    snapshot_root.mkdir(mode=0o700, exist_ok=True)
    target = snapshot_root / snapshot_name(PROJECT_SOUL_RELATIVE)
    runtime = _open_runtime(root)
    prepared = _prepare_document(root, PROJECT_SOUL_RELATIVE, soul)
    if isinstance(prepared, str):
        # Same verdict the full run would reach: the snapshot must not keep
        # serving content the live file no longer passes (e.g. a secret).
        removed = 0
        if target.is_file() and not target.is_symlink():
            uri = target.resolve().as_uri()
            try:
                target.unlink()
            except OSError:
                pass
            removed = _purge_sources(runtime, [uri])
        return {"status": "skipped", "detail": prepared, "removed": removed}
    body, mtime, _digest = prepared
    _write_snapshot(target, body.encode("utf-8"), mtime)
    result = runtime.ingest_path(target, refresh_graph=False)
    return {
        "status": "complete",
        "chunksWritten": int(result.get("chunks_written") or 0),
        "unchanged": int(result.get("idempotent_skips") or 0) >= 1,
    }


def _ingest(root: Path, started_monotonic: float) -> dict[str, Any]:
    deadline = started_monotonic + RUN_DEADLINE_SECONDS
    runtime = _open_runtime(root)
    snapshot_root = _agentlas(root) / SNAPSHOT_DIR
    snapshot_root.mkdir(mode=0o700, exist_ok=True)
    before = _source_counts(runtime, snapshot_root)

    found = discover(root, deadline=deadline)
    skipped: dict[str, int] = dict(found["skipped"])
    secret_paths: list[str] = []
    errors: list[dict[str, str]] = []
    written = unchanged = 0
    chunks_written = 0
    expected: set[str] = set()
    seen_content: set[str] = set()
    stop = found["stop"]

    def count(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    def ingest_one(label: str, name: str, body_text: str, mtime: float) -> None:
        nonlocal written, unchanged, chunks_written
        target = snapshot_root / name
        expected.add(name)
        _write_snapshot(target, body_text.encode("utf-8"), mtime)
        # One corpus-level entity refresh at the end, not one per document.
        result = runtime.ingest_path(target, refresh_graph=False)
        chunks_written += int(result.get("chunks_written") or 0)
        if int(result.get("idempotent_skips") or 0) >= 1:
            unchanged += 1
        else:
            written += 1

    import hashlib

    names_taken: dict[str, str] = {}

    def unique_name(relative: str) -> str:
        name = snapshot_name(relative)
        owner = names_taken.get(name)
        if owner is not None and owner != relative:
            digest = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:8]
            name = f"{Path(name).stem}-{digest}{Path(name).suffix}"
        names_taken[name] = relative
        return name

    for relative, path in found["documents"]:
        if time.monotonic() >= deadline:
            stop = "deadline"
            break
        prepared = _prepare_document(root, relative, path)
        if isinstance(prepared, str):
            count(prepared)
            if prepared == "secret" and len(secret_paths) < MAX_RECORDED_PATHS:
                secret_paths.append(relative)
            continue
        body, mtime, digest = prepared
        if digest in seen_content:
            count("duplicate_content")
            continue
        seen_content.add(digest)
        try:
            ingest_one(relative, unique_name(relative), body, mtime)
        except Exception as exc:
            if len(errors) < 20:
                errors.append({"path": relative, "error": _bounded_reason(f"{type(exc).__name__}: {exc}")})
            count("ingest_error")

    if stop != "deadline":
        for label, body, mtime in _plan_digests(root, found["code_files"], skipped):
            if time.monotonic() >= deadline:
                stop = "deadline"
                break
            name = unique_name(f"source-notes/{label}.md")
            try:
                ingest_one(label, name, body, mtime or time.time())
            except Exception as exc:
                if len(errors) < 20:
                    errors.append({"path": label, "error": _bounded_reason(f"{type(exc).__name__}: {exc}")})
                count("ingest_error")

    removed = 0
    if stop is None:
        # Only a complete walk may decide what no longer exists.
        orphans: list[str] = []
        for entry in snapshot_root.iterdir():
            if entry.name.startswith(".") and ".tmp." in entry.name:
                try:
                    entry.unlink()
                except OSError:
                    pass
                continue
            if entry.name in expected or not entry.is_file() or entry.is_symlink():
                continue
            orphans.append(entry.resolve().as_uri())
            try:
                entry.unlink()
            except OSError:
                continue
        removed = _purge_sources(runtime, orphans)

    entity_graph = _refresh_entity_graph(runtime)
    after = _source_counts(runtime, snapshot_root)
    return {
        "counts": after,
        "countsBefore": before,
        "documentsFound": len(found["documents"]),
        "codeFilesScanned": len(found["code_files"]),
        "written": written,
        "unchanged": unchanged,
        "chunksWritten": chunks_written,
        "removed": removed,
        "skipped": dict(sorted(skipped.items())),
        "secretSkippedPaths": secret_paths,
        "errors": errors,
        "entityGraph": entity_graph,
        "stop": stop,
    }


def _refresh_entity_graph(runtime: Any) -> dict[str, Any]:
    """Code-map / ledger / co-occurrence edges, once per run. Fail-open: the
    documents are already committed and stay queryable without it."""

    refresh = getattr(runtime, "refresh_entity_graph", None)
    if refresh is None:
        return {"status": "skipped", "reason": "runtime_without_entity_layer"}
    try:
        report = refresh()
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": _bounded_reason(f"{type(exc).__name__}: {exc}")}
    return {key: value for key, value in report.items() if key in {"status", "changed", "seconds", "error", "reason"}}


def status(project: str | Path) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    return {
        "action": "project_full_ingest_status",
        "migration": MIGRATION_ID,
        "migrationApplied": migration_applied(root),
        "state": read_state(root),
    }


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin wrapper
    import argparse

    parser = argparse.ArgumentParser(description="Snapshot and ingest every eligible project document")
    parser.add_argument("--project", default=".")
    parser.add_argument("--reason", default="explicit")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--soul-only", action="store_true", help="re-ingest only .agentlas/project-soul-memory.md")
    args = parser.parse_args(argv)
    if args.soul_only:
        payload = refresh_project_soul(args.project)
    else:
        payload = status(args.project) if args.status else run_full_ingest(args.project, reason=args.reason)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if payload.get("status") not in {"failed"} else 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
