"""Stale project-index backstop — host-independent regeneration.

The recall corpus ``.agentlas/ontology-inbox/agentlas-project-index.md`` had a
single producer: Desktop's working-folder materializer
(``electron/ontology/project-runtime.ts``). A machine driven only through
terminal or plugin sessions froze at its last Desktop visit — measured
2026-07-29: 12 days — while every session's recall kept citing the snapshot as
if it were current. The consumer-side guard (staleness labels, v1.1.84) makes
the lie visible; this module removes the lie: whenever the index is missing or
older than :data:`STALE_AFTER_SECONDS`, any surface that touches the runtime
with a project cwd regenerates a bounded, secret-filtered index and starts a
detached ingest.

Contract with Desktop: Desktop's richer materializer stays authoritative. It
overwrites this file on its next visit, and a fresh file — whoever wrote it —
disables the backstop for the TTL window, so the two producers never flap.
Bounds deliberately mirror Desktop's (``PROJECT_INDEX_MAX_SITEMAP_NODES``
etc. in ``project-runtime.ts``) so neither producer's output starves the
other's consumers.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .runtime import SECRET_PATTERNS
from .safe_launch import module_command
from .windows_console import no_console_window

STALE_AFTER_SECONDS = 7 * 24 * 60 * 60
INBOX_DIR = "ontology-inbox"
INDEX_FILE = "agentlas-project-index.md"
PRIVATE_INDEX_PREFIX = "agentlas-project-index-nomemory-"
PRIVATE_INDEX_LIMIT = 1024
ONTOLOGY_DB_FILE = "ontology-runtime.sqlite"

# Mirrors Desktop electron/ontology/project-runtime.ts:61-76 and the PM read
# limits Desktop passes at its call site (maxFiles 24, 128KB/file, 512KB total,
# 8000-char slice; discovery depth 8).
MAX_SITEMAP_NODES = 1_200
MAX_DOCUMENT_CHARS = 48_000
FIXED_DOCUMENTS = ("README.md", "README", "package.json", "pyproject.toml", "Cargo.toml", "go.mod")
PM_DIR = "pm"
PM_MAX_FILES = 24
PM_MAX_FILE_BYTES = 128 * 1024
PM_MAX_TOTAL_BYTES = 512 * 1024
PM_DOC_SLICE_CHARS = 8_000
PM_MAX_DEPTH = 8
MAX_PROJECT_ROOT_ASCENT = 12


def _looks_secret(text: str) -> bool:
    return any(pattern.search(text) for pattern in SECRET_PATTERNS)


def _safe_markdown_path(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ").strip()


def find_project_root(cwd: Path) -> Path | None:
    current = cwd
    for _ in range(MAX_PROJECT_ROOT_ASCENT):
        marker = current / ".agentlas"
        if marker.is_dir() and not marker.is_symlink():
            return current
        if current.parent == current:
            return None
        current = current.parent
    return None


def _index_is_fresh(index_path: Path) -> bool:
    try:
        return time.time() - index_path.stat().st_mtime < STALE_AFTER_SECONDS
    except OSError:
        return False


def _database_lags_index(project_root: Path, index_path: Path, *, missing_source_is_lag: bool = False) -> bool:
    """True when the index file on disk is not what the ontology last ingested.

    The query engine fails closed on a changed source (stale_index), so a fresh
    index file whose detached re-ingest was killed or failed left project recall
    empty until the file itself aged past STALE_AFTER_SECONDS — the freshness
    check only looked at the file, never at the database (measured 2026-09-23 on
    Agentlas-OS: stale_index persisted; one manual `ontology auto` cleared it).
    One indexed row read; any doubt counts as "not lagging" so this never adds
    ingest churn on its own.
    """
    import hashlib
    import sqlite3

    db_path = project_root / ".agentlas" / ONTOLOGY_DB_FILE
    if not index_path.exists():
        return False
    if not db_path.exists():
        return missing_source_is_lag
    try:
        digest = hashlib.sha256(index_path.read_bytes()).hexdigest()
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.2)
        try:
            row = conn.execute(
                "SELECT content_hash FROM sources WHERE uri = ?", (index_path.resolve().as_uri(),)
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return False
    return missing_source_is_lag if row is None else str(row[0] or "") != digest


def _pm_layer_newer_than_index(project_root: Path, index_path: Path) -> bool:
    """True when any bounded ``.agentlas/pm`` document outdates the index.

    The pm layer is the cross-host emission surface: sessions record durable
    project learnings there, and both this backstop's index and Desktop's
    materializer embed it. Without this check a learning written today would
    wait out the full staleness TTL before entering recall; with it, the next
    session start folds it in.
    """

    try:
        index_mtime = index_path.stat().st_mtime
    except OSError:
        return False
    pm_root = project_root / ".agentlas" / PM_DIR
    if not pm_root.is_dir() or pm_root.is_symlink():
        return False
    stack: list[tuple[Path, int]] = [(pm_root, 0)]
    scanned = 0
    while stack and scanned < 512:
        directory, depth = stack.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            scanned += 1
            if scanned >= 512 or entry.is_symlink():
                continue
            if entry.is_dir():
                if depth < PM_MAX_DEPTH:
                    stack.append((entry, depth + 1))
                continue
            try:
                if entry.stat().st_mtime > index_mtime:
                    return True
            except OSError:
                continue
    return False


def _sitemap_lines(project_root: Path) -> list[str]:
    sitemap_path = project_root / ".agentlas" / "sitemap.json"
    try:
        payload = json.loads(sitemap_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        return []
    lines: list[str] = []
    for node in nodes[:MAX_SITEMAP_NODES]:
        if not isinstance(node, dict):
            continue
        relative = _safe_markdown_path(str(node.get("relative_path") or ""))
        kind = _safe_markdown_path(str(node.get("kind") or "file"))
        if not relative:
            continue
        size = node.get("size_bytes")
        suffix = f" ({size} bytes)" if isinstance(size, int) else ""
        lines.append(f"- {kind}: {relative}{suffix}")
    return lines


def _read_bounded_text(path: Path, max_bytes: int) -> str | None:
    try:
        info = path.lstat()
        if not path.is_file() or path.is_symlink() or info.st_size > max_bytes:
            return None
        return path.read_text(encoding="utf-8", errors="strict")
    except (OSError, ValueError, UnicodeDecodeError):
        return None


def _discover_pm_files(project_root: Path) -> list[tuple[str, str]]:
    """Bounded pm documents, session learnings first and newest first.

    Measured 2026-07-29: a name-ordered, root-first traversal let a large
    mid-July HANDOFF document exhaust the 48K-character budget first, so a
    learning recorded moments earlier never made it into the index at all.
    Recall value is highest for the newest and the learnings documents, so
    the budget is spent in that order.
    """

    pm_root = project_root / ".agentlas" / PM_DIR
    if not pm_root.is_dir() or pm_root.is_symlink():
        return []
    candidates: list[Path] = []
    stack: list[tuple[Path, int]] = [(pm_root, 0)]
    while stack and len(candidates) < 512:
        directory, depth = stack.pop()
        try:
            entries = sorted(directory.iterdir(), key=lambda item: item.name)
        except OSError:
            continue
        for entry in entries:
            if len(candidates) >= 512 or entry.is_symlink():
                continue
            if entry.is_dir():
                if depth < PM_MAX_DEPTH:
                    stack.append((entry, depth + 1))
                continue
            candidates.append(entry)

    learnings_root = pm_root / "learnings"

    def priority(path: Path) -> tuple[int, float]:
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        in_learnings = learnings_root == path.parent or learnings_root in path.parents
        return (0 if in_learnings else 1, -mtime)

    collected: list[tuple[str, str]] = []
    total_bytes = 0
    for entry in sorted(candidates, key=priority):
        if len(collected) >= PM_MAX_FILES or total_bytes >= PM_MAX_TOTAL_BYTES:
            break
        content = _read_bounded_text(entry, PM_MAX_FILE_BYTES)
        if not content or _looks_secret(content):
            continue
        total_bytes += len(content.encode("utf-8", errors="ignore"))
        collected.append((str(entry.relative_to(pm_root)), content))
    return collected


def _inbox_fingerprint(inbox_path: Path) -> str:
    digest = hashlib.sha256()
    try:
        entries = sorted(inbox_path.iterdir(), key=lambda item: item.name)
    except OSError:
        entries = []
    for entry in entries:
        if (entry.name == INDEX_FILE or entry.name.startswith(PRIVATE_INDEX_PREFIX)
                or entry.is_symlink() or not entry.is_file()):
            continue
        try:
            digest.update(f"{entry.name}:{entry.stat().st_size}\n".encode("utf-8"))
        except OSError:
            continue
    return digest.hexdigest()


def build_project_index(project_root: Path, *, include_memory: bool = True) -> str:
    inbox_path = project_root / ".agentlas" / INBOX_DIR
    lines = [
        "# Agentlas project ontology index",
        "",
        f"Project: {_safe_markdown_path(project_root.name or 'Project')}",
        "Scope: local project only",
        ("Source policy: deterministic sitemap, fixed root documents, and bounded .agentlas/pm documents"
         if include_memory else "Source policy: deterministic sitemap and fixed root documents; project memory excluded"),
        f"Inbox fingerprint: sha256:{_inbox_fingerprint(inbox_path)}",
        "Producer: core-backstop (Desktop materializer supersedes on its next visit)",
        "",
        "## Project file map",
        *_sitemap_lines(project_root),
    ]
    document_chars = 0

    def written_stamp(path: Path) -> str:
        # The index file itself is fresh the moment it is regenerated, which
        # would otherwise erase every embedded document's age from recall.
        # Carry each document's own last-written date so a reader can tell a
        # today's learning from a two-week-old handoff note.
        try:
            return time.strftime("%Y-%m-%d", time.localtime(path.stat().st_mtime))
        except OSError:
            return "unknown"

    def append_document(label: str, content: str, source_path: Path) -> None:
        nonlocal document_chars
        if not content or document_chars >= MAX_DOCUMENT_CHARS:
            return
        bounded = content[: MAX_DOCUMENT_CHARS - document_chars].strip()
        if not bounded:
            return
        heading = f"## Document: {_safe_markdown_path(label)} (last written {written_stamp(source_path)})"
        lines.extend(["", heading, "", bounded])
        document_chars += len(bounded)

    for relative in FIXED_DOCUMENTS:
        source_path = project_root / relative
        content = _read_bounded_text(source_path, PM_MAX_FILE_BYTES)
        if content and not _looks_secret(content):
            append_document(relative, content, source_path)
    pm_root = project_root / ".agentlas" / PM_DIR
    for relative, content in (_discover_pm_files(project_root) if include_memory else []):
        append_document(f".agentlas/{PM_DIR}/{relative}", content[:PM_DOC_SLICE_CHARS], pm_root / relative)
    return "\n".join(lines).rstrip() + "\n"


def _private_index_matches(project_root: Path, index_path: Path, expected_digest: str) -> bool:
    """Verify the content-addressed memory-excluding index and its current inputs."""
    try:
        if index_path.is_symlink() or not index_path.is_file():
            return False
        expected = build_project_index(project_root, include_memory=False).encode("utf-8")
        if hashlib.sha256(expected).hexdigest() != expected_digest:
            return False
        if index_path.stat().st_size != len(expected):
            return False
        return index_path.read_bytes() == expected
    except (OSError, UnicodeError, ValueError):
        return False


def _guarded_private_ingest(project_root: Path, digest: str) -> int:
    """Recheck preferences and index content in the worker before ingestion."""
    from .feature_preferences import feature_enabled

    if (len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest)
            or not feature_enabled("project-index") or feature_enabled("memory-hooks")):
        return 2
    agentlas_dir = project_root / ".agentlas"
    inbox_path = agentlas_dir / INBOX_DIR
    if agentlas_dir.is_symlink() or inbox_path.is_symlink():
        return 2
    index_path = inbox_path / f"{PRIVATE_INDEX_PREFIX}{digest}.md"
    if not _private_index_matches(project_root, index_path, digest):
        return 2
    if not feature_enabled("project-index") or feature_enabled("memory-hooks"):
        return 2
    from ontology.cli import main as ontology_main

    db_path = project_root / ".agentlas" / ONTOLOGY_DB_FILE
    if (not feature_enabled("project-index") or feature_enabled("memory-hooks")
            or not _private_index_matches(project_root, index_path, digest)):
        return 2
    return ontology_main(["--db", str(db_path), "ingest", str(index_path)])


def _file_digest(path: Path) -> str | None:
    try:
        if path.is_symlink() or not path.is_file():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _guarded_auto_ingest(project_root: Path, digest: str) -> int:
    """Preserve legacy auto-ingest only while its options and index match."""
    from .feature_preferences import feature_enabled

    inbox = project_root / ".agentlas" / INBOX_DIR
    index_path = inbox / INDEX_FILE
    if (len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest)
            or (project_root / ".agentlas").is_symlink() or inbox.is_symlink()
            or not feature_enabled("project-index") or not feature_enabled("memory-hooks")
            or _file_digest(index_path) != digest):
        return 2
    from ontology.cli import main as ontology_main

    if (not feature_enabled("project-index") or not feature_enabled("memory-hooks")
            or _file_digest(index_path) != digest):
        return 2
    db_path = project_root / ".agentlas" / ONTOLOGY_DB_FILE
    return ontology_main(["--db", str(db_path), "auto", str(project_root)])


def _spawn_detached_ingest(project_root: Path, *, include_memory: bool = True,
                           private_digest: str | None = None) -> None:
    runtime_root = Path(__file__).resolve().parent.parent
    env = os.environ.copy()
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(runtime_root) + (os.pathsep + existing if existing else "")
    with open(os.devnull, "rb") as stdin, open(os.devnull, "wb") as out:
        digest = (_file_digest(project_root / ".agentlas" / INBOX_DIR / INDEX_FILE)
                  if include_memory else private_digest)
        if not digest:
            return
        operation = "--guarded-auto-ingest" if include_memory else "--guarded-private-ingest"
        command = module_command("agentlas_cloud.project_index_backstop",
                                 [operation, str(project_root), digest], root=runtime_root)
        subprocess.Popen(
            command,
            cwd=str(project_root),
            env=env,
            stdin=stdin,
            stdout=out,
            stderr=out,
            close_fds=True,
            start_new_session=True,
            **no_console_window(),
        )


def _remove_private_indexes(inbox_path: Path, keep: str | None = None) -> None:
    """Drop memory-excluding index generations other than ``keep``.

    Each content change writes a new content-addressed file. Without this the
    inbox kept every generation (each one an ingest source) until the
    PRIVATE_INDEX_LIMIT stopped refreshes altogether.
    """

    try:
        entries = list(inbox_path.iterdir())
    except OSError:
        return
    for entry in entries:
        if not entry.name.startswith(PRIVATE_INDEX_PREFIX) or entry.name == keep:
            continue
        try:
            if entry.is_symlink() or not entry.is_file():
                continue
            entry.unlink()
        except OSError:
            continue


def maybe_refresh_project_index(cwd: Path | str | None) -> bool:
    """Regenerate a missing/stale project index for ``cwd``'s project, fail-silent.

    Returns True only when a fresh index was written (used by tests; every
    caller treats this as fire-and-forget). Never raises, never prints.
    """

    try:
        from .feature_preferences import feature_enabled

        if not feature_enabled("project-index"):
            return False
        if cwd is None:
            return False
        project_root = find_project_root(Path(cwd).resolve())
        if project_root is None:
            return False
        runtime_root = os.environ.get("HEPHAESTUS_RUNTIME_ROOT")
        if runtime_root and project_root == Path(runtime_root).expanduser().resolve():
            # A packaged runtime may contain its own .agentlas metadata, but it
            # is immutable product code rather than the user's active project.
            # Never generate project memory inside an installed/signed runtime.
            return False
        inbox_path = project_root / ".agentlas" / INBOX_DIR
        if inbox_path.is_symlink():
            return False
        index_path = inbox_path / INDEX_FILE
        include_memory = feature_enabled("memory-hooks")
        if not include_memory:
            content = build_project_index(project_root, include_memory=False).encode("utf-8")
            digest = hashlib.sha256(content).hexdigest()
            private_path = inbox_path / f"{PRIVATE_INDEX_PREFIX}{digest}.md"
            if not feature_enabled("project-index") or feature_enabled("memory-hooks"):
                return False
            inbox_path.mkdir(parents=True, exist_ok=True)
            created = False
            if not private_path.exists() and sum(
                1 for entry in inbox_path.iterdir() if entry.name.startswith(PRIVATE_INDEX_PREFIX)
            ) >= PRIVATE_INDEX_LIMIT:
                return False
            try:
                fd = os.open(private_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
            except FileExistsError:
                pass
            else:
                created = True
                with os.fdopen(fd, "wb") as output:
                    output.write(content)
            if not _private_index_matches(project_root, private_path, digest):
                return False
            _remove_private_indexes(inbox_path, keep=private_path.name)
            if (feature_enabled("project-index") and not feature_enabled("memory-hooks")
                    and (created or _database_lags_index(project_root, private_path, missing_source_is_lag=True))):
                _spawn_detached_ingest(project_root, include_memory=False, private_digest=digest)
            return created
        _remove_private_indexes(inbox_path)
        if _index_is_fresh(index_path) and not _pm_layer_newer_than_index(project_root, index_path):
            if (feature_enabled("project-index") and feature_enabled("memory-hooks")
                    and _database_lags_index(project_root, index_path)
                    and feature_enabled("project-index") and feature_enabled("memory-hooks")):
                _spawn_detached_ingest(project_root, include_memory=True)
            return False
        content = build_project_index(project_root, include_memory=include_memory)
        if not feature_enabled("project-index") or feature_enabled("memory-hooks") != include_memory:
            return False
        inbox_path.mkdir(parents=True, exist_ok=True)
        temporary = index_path.with_name(f".{INDEX_FILE}.tmp.{os.getpid()}.{time.time_ns()}")
        temporary.write_text(content, encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(index_path)
        if feature_enabled("project-index") and feature_enabled("memory-hooks") == include_memory:
            _spawn_detached_ingest(project_root, include_memory=include_memory)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--guarded-private-ingest":
        raise SystemExit(_guarded_private_ingest(Path(sys.argv[2]), sys.argv[3]))
    if len(sys.argv) == 4 and sys.argv[1] == "--guarded-auto-ingest":
        raise SystemExit(_guarded_auto_ingest(Path(sys.argv[2]), sys.argv[3]))
    raise SystemExit(2)
