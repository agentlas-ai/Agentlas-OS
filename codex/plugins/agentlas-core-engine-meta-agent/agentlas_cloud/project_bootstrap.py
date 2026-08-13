"""Canonical first-contact project bootstrap for every Agentlas host.

Desktop, Terminal, Codex, Claude Code, and MCP adapters call this module instead
of maintaining host-local copies of the project memory architecture.  The
bootstrap is deliberately merge-only: it creates missing files, never replaces
user content, and installs a managed privacy block before generating local
memory or indexes.
"""

from __future__ import annotations

import hashlib
import fnmatch
import json
import os
import queue
import re
import secrets
import stat
import subprocess
import threading
import time
from collections import Counter, defaultdict
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


BOOTSTRAP_SCHEMA = "agentlas.project-bootstrap.v1"
MANAGED_GITIGNORE_START = "# >>> agentlas local project state >>>"
MANAGED_GITIGNORE_END = "# <<< agentlas local project state <<<"
MAX_CODE_FILES = 12_000
MAX_LOCAL_TEST_FILES = 4_000
MAX_CODE_FILE_BYTES = 1_500_000
MAX_CODE_TOTAL_READ_BYTES = 32 * 1024 * 1024
MAX_CODE_SCAN_SECONDS = 12.0
MAX_CODE_MAP_BYTES = 24 * 1024 * 1024
MAX_GIT_FILE_LIST_BYTES = 8 * 1024 * 1024
MAX_GIT_PREFIX_BYTES = 64 * 1024
MAX_GITIGNORE_BYTES = 1024 * 1024
MAX_TRACKED_PATH_BYTES = 1024 * 1024
MAX_TRACKED_PATHS = 10_000
MAX_PERMISSION_PATHS = 20_000
MAX_DISCOVERED_FILES = MAX_CODE_FILES * 3
MAX_SYMBOLS_PER_FILE = 1_000
MAX_TOTAL_SYMBOLS = 100_000
MAX_UNIQUE_TOKENS = 50_000
MAX_TOKEN_OCCURRENCES = 2_000_000
MAX_REF_FILES_PER_SYMBOL = 1_024
POSIX_PRIVATE_MODE_ENFORCEMENT = os.name != "nt"
AUTO_BOOTSTRAP_ENV = "AGENTLAS_PROJECT_BOOTSTRAP_AUTO"
MCP_AUTO_BOOTSTRAP_ENV = "AGENTLAS_MCP_PROJECT_BOOTSTRAP_AUTO"
AUTO_ALLOWED_ROOTS_ENV = "AGENTLAS_PROJECT_BOOTSTRAP_ALLOWED_ROOTS"
CODE_MAP_CACHE_SCHEMA = "agentlas.code-map-cache.v4"
CODE_MAP_POLICY_VERSION = "content-snapshot-precision-index.v3"
VERIFICATION_MAP_SCHEMA = "agentlas.verification-map.v2"
CONTEXT_INDEX_POLICY_SCHEMA = "agentlas.context-index-policy.v1"
CODE_MAP_MANIFEST_SCHEMA = "agentlas.code-map-manifest.v3"

PRIVACY_PATTERNS = (
    ".agentlas/",
    ".agentlas/project-soul-memory.md",
    ".agentlas/sitemap.json",
    ".agentlas/memory-map.json",
    ".agentlas/memory-tickets.jsonl",
    ".agentlas/vault-references.json",
    ".agentlas/local-credentials.map.json",
    ".agentlas/activation.json",
    ".agentlas/skill-registry.json",
    ".agentlas/skill-trials.jsonl",
    ".agentlas/curator-decisions.jsonl",
    ".agentlas/code-map/",
    ".agentlas/ontology-runtime.json",
    ".agentlas/ontology-sources.json",
    ".agentlas/ontology-inbox/",
    ".agentlas/ontology-runtime.sqlite*",
    ".agentlas/career-graph.json",
    ".agentlas/career-graph-sources.json",
    ".agentlas/career-graph-inbox/",
    ".agentlas/career-graph.sqlite*",
    ".agentlas/experience-relations.jsonl",
    ".agentlas/stormbreaker/",
    ".agentlas/pipeline/",
    ".agentlas/*.lock",
    ".agentlas/*.sqlite*",
    ".agentlas/*.jsonl",
    ".env",
    ".env.*",
    "!.env.example",
    ".env.local",
    "signing/*",
    "!signing/README.md",
    "credentials/*",
    "!credentials/README.md",
)

CODE_EXTENSIONS = {
    ".c": "c",
    ".cc": "cpp",
    ".cjs": "javascript",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".css": "css",
    ".cts": "typescript",
    ".dart": "dart",
    ".ex": "elixir",
    ".exs": "elixir",
    ".go": "go",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".m": "objective-c",
    ".mjs": "javascript",
    ".mm": "objective-cpp",
    ".mts": "typescript",
    ".php": "php",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".sh": "shell",
    ".sql": "sql",
    ".swift": "swift",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".vue": "vue",
}

ENTRY_NAMES = {
    "main.py",
    "app.py",
    "server.py",
    "manage.py",
    "index.js",
    "index.ts",
    "index.tsx",
    "main.js",
    "main.ts",
    "main.tsx",
    "package.json",
    "pyproject.toml",
    "Cargo.toml",
    "go.mod",
}

TEST_DIRECTORY_NAMES = {"test", "tests", "__tests__", "spec", "specs"}
TEST_NAME_PATTERN = re.compile(
    r"(^test[_-]|[_-](?:test|spec)\.|[.-](?:test|spec)\.|^(?:test|verify|check|smoke)[_-])",
    re.IGNORECASE,
)
CI_WORKFLOW_SUFFIXES = {".yml", ".yaml"}
VERSION_CONTRACT_NAMES = {
    "package.json",
    "package-lock.json",
    "manifest.json",
    "pyproject.toml",
    "cargo.toml",
    "gemini-extension.json",
}
MAX_VERIFICATION_FILE_BYTES = 512 * 1024
MAX_VERIFICATION_NODES = 2_000
# The Desktop repository currently produces more than 50k legitimate
# source-to-test links. Keep the graph bounded, but high enough that the
# completion gate can represent that real product instead of failing its own
# refresh as incomplete. The 24 MiB serialized-map limit remains the final
# memory/output guard.
MAX_VERIFICATION_EDGES = 50_000
MAX_DEPENDENCY_EDGES = 50_000
MAX_SNAPSHOT_READ_BYTES = 1024 * 1024 * 1024
TEST_PATH_REFERENCE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.-])"
    r"((?:test|tests|scripts)/[A-Za-z0-9_./@+-]+"
    r"\.(?:cjs|mjs|js|jsx|ts|tsx|py|sh|json))(?![A-Za-z0-9])"
)

SKIP_DIRS = {
    ".agentlas",
    ".data",
    ".git",
    ".hg",
    ".svn",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".turbo",
    ".venv",
    ".vercel",
    "__pycache__",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
}

# Generic directory names such as ``build`` are valid source-route segments
# (for example ``src/components/build``). Only treat them as generated output
# when they are rooted directly under the selected project.
ROOT_OUTPUT_DIRS = {"build", "out", "release", "release-local"}

DEFAULT_CONTEXT_INDEX_POLICY = {
    "schemaVersion": CONTEXT_INDEX_POLICY_SCHEMA,
    "excludeRoots": [],
    "mirrorRoots": [],
    "testRoots": ["test", "tests", "__tests__", "spec", "specs"],
    "testGlobs": [
        "**/*.test.*",
        "**/*-spec.*",
        "**/*-test.*",
        "**/*_test.*",
        "**/test_*.*",
        "scripts/audit-*",
        "scripts/check-*",
        "scripts/compare-*",
        "scripts/proof-*",
        "scripts/qa-*",
        "scripts/smoke-*",
        "scripts/test-*",
        "scripts/validate-*",
        "scripts/verify-*",
    ],
}

JS_IMPORT_SPECIFIER_PATTERNS = (
    re.compile(r"(?m)^\s*import\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"(?ms)^\s*(?:import|export)\s+[^;]{0,2000}?\s+from\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"\brequire\(\s*['\"]([^'\"]+)['\"]\s*\)"),
    re.compile(r"\bimport\(\s*['\"]([^'\"]+)['\"]\s*\)"),
)
PYTHON_IMPORT_SPECIFIER_PATTERNS = (
    re.compile(r"(?m)^\s*from\s+([.]*[A-Za-z_][\w.]*)\s+import\s+"),
    re.compile(r"(?m)^\s*import\s+([A-Za-z_][\w.]*)"),
)

SYMBOL_PATTERNS = (
    ("class", re.compile(r"^\s*(?:export\s+)?(?:default\s+)?class\s+([A-Za-z_$][\w$]*)")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:def|function|func|fn)\s+([A-Za-z_$][\w$]*)")),
    ("type", re.compile(r"^\s*(?:export\s+)?(?:interface|type|enum|struct|trait)\s+([A-Za-z_$][\w$]*)")),
    ("function", re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(")),
)
TOKEN_PATTERN = re.compile(r"[A-Za-z_$][\w$]{2,}")


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _project_root(project: str | Path) -> Path:
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("project_directory_does_not_exist")
    unsafe = {Path.home().resolve(), Path(root.anchor).resolve()}
    if root in unsafe:
        raise ValueError("unsafe_project_root")
    return root


def _context_index_policy(root: Path) -> dict[str, Any]:
    """Load a tracked, project-owned indexing policy without consulting private state."""

    path = root / "agentlas-context-map.json"
    if not path.exists():
        return dict(DEFAULT_CONTEXT_INDEX_POLICY)
    payload = _read_json_object(path)
    if payload.get("schemaVersion") != CONTEXT_INDEX_POLICY_SCHEMA:
        raise ValueError("context_index_policy_invalid")
    policy = dict(DEFAULT_CONTEXT_INDEX_POLICY)
    for field in ("excludeRoots", "mirrorRoots", "testRoots", "testGlobs"):
        values = payload.get(field, policy[field])
        if not isinstance(values, list) or any(
            not isinstance(value, str)
            or not value.strip()
            or value.startswith(("/", "./"))
            or ".." in Path(value).parts
            for value in values
        ):
            raise ValueError("context_index_policy_invalid")
        policy[field] = sorted({value.strip().strip("/") for value in values})
    policy["schemaVersion"] = CONTEXT_INDEX_POLICY_SCHEMA
    return policy


def _policy_digest(policy: Mapping[str, Any]) -> str:
    return _canonical_json_digest(dict(policy))


def _matches_root(relative: str, roots: Sequence[str]) -> bool:
    return any(relative == root or relative.startswith(root + "/") for root in roots)


def _matches_test_policy(relative: str, policy: Mapping[str, Any]) -> bool:
    return _matches_root(relative, policy.get("testRoots") or ()) or any(
        fnmatch.fnmatchcase(relative, pattern)
        for pattern in policy.get("testGlobs") or ()
    )


def _policy_allows(relative: str, policy: Mapping[str, Any]) -> bool:
    return not _matches_root(relative, policy.get("excludeRoots") or ()) and not _matches_root(
        relative,
        policy.get("mirrorRoots") or (),
    )


def _file_role(relative: str) -> str:
    path = Path(relative)
    suffix = path.suffix.lower()
    if _is_ci_workflow_path(relative):
        return "workflow"
    if _is_test_path(relative):
        return "test"
    if _is_version_contract_path(relative):
        return "version_contract"
    if suffix in CODE_EXTENSIONS:
        return "source"
    if suffix in {".md", ".mdx", ".rst", ".txt"}:
        return "documentation"
    if suffix in {".json", ".jsonc", ".toml", ".yaml", ".yml", ".ini", ".cfg", ".xml"}:
        return "config"
    return "asset"


def _content_snapshot(
    root: Path,
    relative_files: Sequence[str],
    policy: Mapping[str, Any],
) -> tuple[str, dict[str, str], int]:
    """Return a content-addressed snapshot; stat timestamps are cache hints only."""

    digest = hashlib.sha256()
    content_hashes: dict[str, str] = {}
    read_bytes = 0
    digest.update(_policy_digest(policy).encode("ascii"))
    digest.update(b"\0")
    for relative in sorted(relative_files):
        path = root / relative
        file_digest = hashlib.sha256()
        try:
            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    read_bytes += len(chunk)
                    if read_bytes > MAX_SNAPSHOT_READ_BYTES:
                        raise OSError("context_snapshot_read_budget_exceeded")
                    file_digest.update(chunk)
        except OSError:
            raise
        value = "sha256:" + file_digest.hexdigest()
        content_hashes[relative] = value
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(_file_role(relative).encode("ascii"))
        digest.update(b"\0")
        digest.update(value.encode("ascii"))
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest(), content_hashes, read_bytes


def _truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def auto_bootstrap_enabled(*, mcp: bool = False) -> bool:
    """Return trusted host policy; MCP and ordinary CLI use separate gates."""

    return _truthy_env(MCP_AUTO_BOOTSTRAP_ENV if mcp else AUTO_BOOTSTRAP_ENV)


def _project_marker_present(root: Path) -> bool:
    """Automatic writes require a real workspace marker, never a random cwd."""

    return any((root / marker).exists() for marker in (".git", ".hg", ".svn", ".agentlas"))


def _auto_allowed_roots() -> list[Path]:
    raw = os.environ.get(AUTO_ALLOWED_ROOTS_ENV, "").strip()
    candidates = [Path(item).expanduser() for item in raw.split(os.pathsep) if item.strip()] if raw else [Path.cwd()]
    unsafe = {Path.home().resolve(), Path(Path.cwd().anchor).resolve()}
    allowed: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_dir() and resolved not in unsafe:
            allowed.append(resolved)
    return allowed


def _within_auto_boundary(root: Path) -> bool:
    for allowed in _auto_allowed_roots():
        try:
            root.relative_to(allowed)
            return True
        except ValueError:
            continue
    return False


def _redacted_error(exc: BaseException) -> str:
    if isinstance(exc, TimeoutError):
        return "project_bootstrap_lock_timeout"
    if isinstance(exc, PermissionError):
        return "project_bootstrap_permission_denied"
    if isinstance(exc, ValueError):
        return str(exc) if str(exc) in {"project_directory_does_not_exist", "unsafe_project_root"} else "invalid_project_root"
    return "project_bootstrap_io_error"


def _ensure_dir(path: Path, mode: int) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=mode)
    os.chmod(path, mode)


def _existing_mode(path: Path, fallback: int) -> int:
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            return fallback
        return stat.S_IMODE(metadata.st_mode)
    except OSError:
        return fallback


def _template_root() -> Path | None:
    candidates = [Path(__file__).resolve().parent.parent / "templates"]
    runtime_raw = os.environ.get("HEPHAESTUS_RUNTIME_ROOT", "").strip()
    if runtime_raw:
        runtime_root = Path(runtime_raw).expanduser()
        if runtime_root.is_absolute():
            candidates.append(runtime_root.resolve() / "templates")
    return next((path for path in candidates if path.is_dir()), None)


def _render_template(name: str, replacements: dict[str, str]) -> str | None:
    base = _template_root()
    path = base / name if base else None
    if path is None or not path.is_file():
        return None
    rendered = path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered if rendered.endswith("\n") else rendered + "\n"


def _atomic_write(path: Path, content: str, *, mode: int = 0o600, parent_mode: int = 0o700) -> None:
    _ensure_dir(path.parent, parent_mode)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    descriptor = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
        os.chmod(path, mode)
    except BaseException:
        try:
            temp.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_missing(path: Path, content: str, created: list[str], root: Path) -> None:
    if path.exists():
        return
    relative = path.relative_to(root)
    private = relative.parts[0] in {".agentlas", "credentials", "signing"}
    _atomic_write(
        path,
        content,
        mode=0o600 if private else 0o644,
        parent_mode=0o700 if private else 0o755,
    )
    created.append(relative.as_posix())


def _read_lock(lock: Path) -> dict[str, Any]:
    try:
        payload = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _try_advisory_lock(descriptor: int) -> bool:
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        return False
    return True


def _release_advisory_lock(descriptor: int) -> None:
    if os.name == "nt":
        import msvcrt

        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def _project_lock(root: Path, timeout_seconds: float = 15.0) -> Iterable[None]:
    agentlas = root / ".agentlas"
    _ensure_dir(agentlas, 0o700)
    lock = agentlas / ".project-bootstrap.lock"
    deadline = time.monotonic() + timeout_seconds
    token = secrets.token_hex(16)
    payload = json.dumps({"pid": os.getpid(), "token": token, "createdAt": utc_now()}, separators=(",", ":")) + "\n"
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
    os.chmod(lock, 0o600)
    while True:
        if _try_advisory_lock(descriptor):
            break
        if time.monotonic() >= deadline:
            os.close(descriptor)
            raise TimeoutError("project_bootstrap_lock_timeout")
        time.sleep(0.05)
    os.ftruncate(descriptor, 0)
    os.lseek(descriptor, 0, os.SEEK_SET)
    os.write(descriptor, payload.encode("utf-8"))
    os.fsync(descriptor)
    try:
        yield
    finally:
        try:
            _release_advisory_lock(descriptor)
        finally:
            os.close(descriptor)


def _managed_gitignore_block() -> str:
    return "\n".join((MANAGED_GITIGNORE_START, *PRIVACY_PATTERNS, MANAGED_GITIGNORE_END))


def _read_bounded_regular_text(path: Path, max_bytes: int) -> str:
    """Read one local regular file without following links or unbounded growth."""

    try:
        before = path.lstat()
    except FileNotFoundError:
        return ""
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ValueError("unsafe_gitignore_file")
    if before.st_size > max_bytes:
        raise ValueError("gitignore_too_large")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("unsafe_gitignore_file") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("gitignore_changed_during_bootstrap")
        chunks: list[bytes] = []
        total = 0
        while total <= max_bytes:
            chunk = os.read(descriptor, min(64 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if total > max_bytes:
            raise ValueError("gitignore_too_large")
        try:
            return b"".join(chunks).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("gitignore_not_utf8") from exc
    finally:
        os.close(descriptor)


def _ensure_gitignore(root: Path) -> tuple[bool, str]:
    path = root / ".gitignore"
    existing = _read_bounded_regular_text(path, MAX_GITIGNORE_BYTES)
    block = _managed_gitignore_block()
    if MANAGED_GITIGNORE_START in existing and MANAGED_GITIGNORE_END in existing:
        start = existing.index(MANAGED_GITIGNORE_START)
        end = existing.index(MANAGED_GITIGNORE_END, start) + len(MANAGED_GITIGNORE_END)
        updated = existing[:start] + block + existing[end:]
    else:
        prefix = existing.rstrip("\n")
        updated = f"{prefix}\n\n{block}\n" if prefix else f"{block}\n"
    if updated == existing:
        return False, ".gitignore"
    _atomic_write(
        path,
        updated,
        mode=_existing_mode(path, 0o644),
        parent_mode=_existing_mode(root, 0o755),
    )
    return True, ".gitignore"


def _seed_project_files(root: Path) -> tuple[list[str], list[str]]:
    created: list[str] = []
    warnings: list[str] = []
    project_id = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip("-") or "project"
    replacements = {
        "project_id": project_id,
        "projectId": project_id,
        "PROJECT_NAME": root.name,
        "draft_id": "local-first-contact",
        "intent": "Preserve project continuity across Agentlas hosts.",
        "audience": "Project operators and authorized local agents.",
        "promise": "Merge-only local memory, code-map, and ontology context.",
        "decision": "Use Agentlas Core as the canonical project bootstrap owner.",
        "open_loop": "Replace seed statements with verified project decisions as work progresses.",
        "acceptance_criterion": "Every durable memory write remains evidence-linked and locally controlled.",
    }

    builtins = {
        ".agentlas/sitemap.json": json.dumps(
            {
                "schemaVersion": "1.0",
                "kind": "agentlas-ai-sitemap",
                "projectId": project_id,
                "state": "active",
                "memoryRoots": [".agentlas/project-soul-memory.md", ".agentlas/memory-tickets.jsonl"],
                "codeMap": ".agentlas/code-map/project-map.json",
                "ontologyRuntime": ".agentlas/ontology-runtime.json",
                "careerGraph": ".agentlas/career-graph.json",
                "mergeOnly": True,
                "nodes": [
                    {
                        "id": f"project:{project_id}",
                        "type": "project",
                        "kind": "project",
                        "title": root.name,
                        "status": "active",
                        "source": "project-bootstrap",
                    },
                    {
                        "id": "goal:global-coherence",
                        "type": "goal",
                        "kind": "goal",
                        "title": "Keep decomposed tasks globally coherent and integration-ready.",
                        "status": "active",
                        "source": "project-bootstrap",
                    },
                    {
                        "id": "constraint:project-local",
                        "type": "constraint",
                        "kind": "constraint",
                        "title": "Project source, memory, and context-map details remain local.",
                        "status": "validated",
                        "source": "project-bootstrap",
                    },
                    {
                        "id": "requirement:impact-check",
                        "type": "requirement",
                        "kind": "requirement",
                        "title": "Review reverse references before mutation and verify change impact before completion.",
                        "status": "active",
                        "source": "project-bootstrap",
                    },
                ],
                "edges": [
                    {
                        "from": "goal:global-coherence",
                        "to": f"project:{project_id}",
                        "type": "contributes_to",
                    },
                    {
                        "from": "goal:global-coherence",
                        "to": "constraint:project-local",
                        "type": "constrained_by",
                    },
                    {
                        "from": "requirement:impact-check",
                        "to": "goal:global-coherence",
                        "type": "contributes_to",
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        ".agentlas/vault-references.json": json.dumps(
            {
                "schemaVersion": "1.0",
                "kind": "agentlas-vault-references",
                "projectId": project_id,
                "secretsStoredHere": False,
                "references": [],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        ".agentlas/context-map.json": json.dumps(
            {
                "schemaVersion": "agentlas.context-map.v1",
                "projectId": project_id,
                "nodes": [],
                "edges": [],
                "statuses": [
                    "active",
                    "deprecated",
                    "superseded",
                    "tentative",
                    "validated",
                    "rejected",
                ],
                "mergeOnly": True,
                "note": "Add explicit goals, requirements, decisions, interfaces, and change events here. Generated code dependencies stay in code-map/project-map.json.",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        ".agentlas/memory-tickets.jsonl": "",
        ".agentlas/skill-trials.jsonl": "",
        ".agentlas/curator-decisions.jsonl": "",
    }
    for relative, content in builtins.items():
        _write_missing(root / relative, content, created, root)

    template_targets = {
        "activation.json.tpl": ".agentlas/activation.json",
        "memory-map.json.tpl": ".agentlas/memory-map.json",
        "project-soul-memory.md.tpl": ".agentlas/project-soul-memory.md",
        "skill-registry.json.tpl": ".agentlas/skill-registry.json",
        "local-credentials.map.json.tpl": ".agentlas/local-credentials.map.json",
        "env.example.tpl": ".env.example",
        "signing.README.md.tpl": "signing/README.md",
        "credentials.README.md.tpl": "credentials/README.md",
    }
    for template_name, relative in template_targets.items():
        rendered = _render_template(template_name, replacements)
        if rendered is None:
            warnings.append(f"template_missing:{template_name}")
            continue
        _write_missing(root / relative, rendered, created, root)

    return created, warnings


def _apply_additive_memory_migrations(root: Path) -> tuple[list[str], list[str]]:
    """Add missing declared fields to known memory-schema files. Never touch values.

    MISSING-ONLY seeds whole files, so a file created at schema 1.0 never
    received later fields — the live corpus proved it (schemaVersion 1.0 with
    five canonical roots absent while the template declared 1.1). This is the
    approved repair (owner, 2026-08-08): a second, field-level layer that ONLY
    adds keys that are absent, with defaults, and bumps schemaVersion
    monotonically. An existing value — including a user-customized one — is
    never rewritten, which is what `activationPolicy.mergeOnly` promised all
    along. The wizard contract's `merge_not_overwrite` targets (`sources[]`,
    `activations[]`) become real fields here instead of pointing at keys no
    file has.
    """

    migrated: list[str] = []
    warnings: list[str] = []

    def load(path: Path) -> dict[str, Any] | None:
        try:
            payload = json.loads(_read_bounded_regular_text(path, 4 * 1024 * 1024))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def bump_version(payload: dict[str, Any], floor: str) -> None:
        current = str(payload.get("schemaVersion") or "0")
        def parts(value: str) -> tuple[int, ...]:
            try:
                return tuple(int(p) for p in value.split("."))
            except ValueError:
                return (0,)
        if parts(current) < parts(floor):
            payload["schemaVersion"] = floor

    def save(path: Path, payload: dict[str, Any], label: str) -> None:
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            migrated.append(label)
        except OSError as exc:
            warnings.append(f"memory_migration_write_failed:{label}:{exc}")

    memory_map_path = root / ".agentlas" / "memory-map.json"
    payload = load(memory_map_path)
    if payload is not None:
        changed = False
        roots = payload.get("canonicalMemoryRoots")
        owners = payload.get("writeOwners")
        if isinstance(roots, dict) and isinstance(owners, dict):
            # 1.0 -> 1.1: the five roots the 1.1 template declares.
            additions: dict[str, tuple[list[str], str]] = {
                "curator_decisions": ([".agentlas/curator-decisions.jsonl"], "memory-curator"),
                "code_map": ([".agentlas/code-map/project-map.json"], "project bootstrap"),
                "context_map": ([".agentlas/context-map.json"], "context map authoring (derived)"),
                "recall_index": ([".agentlas/ontology-runtime.sqlite"], "ontology runtime"),
                "experience": ([".agentlas/experience-relations.jsonl"], "experience intake"),
            }
            for key, (paths, owner) in additions.items():
                if key not in roots:
                    roots[key] = paths
                    changed = True
                if key not in owners:
                    owners[key] = owner
                    changed = True
            if "promotionPath" not in payload:
                payload["promotionPath"] = [
                    "session ticket",
                    "curator decision",
                    "durable memory entry",
                    "experience candidate",
                    "experience pack",
                ]
                changed = True
            if "runtimeOwned" not in payload:
                payload["runtimeOwned"] = ["code_map", "context_map", "recall_index", "experience"]
                changed = True
            # 1.1 -> 1.2: the product-registration list the wizard contract
            # merges into ({product, scopes} rows, union by product).
            if "sources" not in payload:
                payload["sources"] = []
                changed = True
            if changed:
                bump_version(payload, "1.2")
                save(memory_map_path, payload, "memory-map.json")
        else:
            warnings.append("memory_migration_skipped:memory-map.json:unrecognized_shape")

    activation_path = root / ".agentlas" / "activation.json"
    payload = load(activation_path)
    if payload is not None:
        if payload.get("kind") == "agentlas-auto-activation":
            if "activations" not in payload:
                payload["activations"] = []
                bump_version(payload, "1.1")
                save(activation_path, payload, "activation.json")
        else:
            warnings.append("memory_migration_skipped:activation.json:unrecognized_shape")

    return migrated, warnings


def _merge_managed_sitemap_context(
    root: Path,
    code_map: dict[str, Any] | None = None,
) -> str | None:
    """Merge project intent and a bounded functional projection without replacing user data."""

    path = root / ".agentlas" / "sitemap.json"
    try:
        raw = _read_bounded_regular_text(path, 32 * 1024 * 1024)
        payload = json.loads(raw)
    except (OSError, ValueError, json.JSONDecodeError):
        return "sitemap_context_merge_deferred"
    if not isinstance(payload, dict):
        return "sitemap_context_merge_deferred"
    project_id = re.sub(r"[^A-Za-z0-9._-]+", "-", root.name).strip("-") or "project"
    managed_nodes = [
        {
            "id": f"project:{project_id}",
            "type": "project",
            "kind": "project",
            "title": root.name,
            "status": "active",
            "source": "project-bootstrap",
        },
        {
            "id": "goal:global-coherence",
            "type": "goal",
            "kind": "goal",
            "title": "Keep decomposed tasks globally coherent and integration-ready.",
            "status": "active",
            "source": "project-bootstrap",
        },
        {
            "id": "constraint:project-local",
            "type": "constraint",
            "kind": "constraint",
            "title": "Project source, memory, and context-map details remain local.",
            "status": "validated",
            "source": "project-bootstrap",
        },
        {
            "id": "requirement:impact-check",
            "type": "requirement",
            "kind": "requirement",
            "title": "Review reverse references before mutation and verify change impact before completion.",
            "status": "active",
            "source": "project-bootstrap",
        },
    ]
    managed_edges = [
        {
            "from": "goal:global-coherence",
            "to": f"project:{project_id}",
            "type": "contributes_to",
        },
        {
            "from": "goal:global-coherence",
            "to": "constraint:project-local",
            "type": "constrained_by",
        },
        {
            "from": "requirement:impact-check",
            "to": "goal:global-coherence",
            "type": "contributes_to",
        },
    ]
    if isinstance(code_map, dict):
        module_ids: dict[str, str] = {}
        for module in code_map.get("modules") or []:
            if not isinstance(module, dict):
                continue
            module_path = str(module.get("path") or module.get("id") or "").strip()
            if not module_path:
                continue
            node_id = f"surface:module:{module_path}"
            module_ids[module_path] = node_id
            managed_nodes.append(
                {
                    "id": node_id,
                    "type": "surface",
                    "kind": "surface",
                    "title": str(module.get("role") or module_path),
                    "path": module_path,
                    "status": "active",
                    "source": "code-map",
                    "generated": True,
                    "codeFiles": int(module.get("codeFiles") or 0),
                }
            )
            managed_edges.append(
                {
                    "from": node_id,
                    "to": f"project:{project_id}",
                    "type": "contributes_to",
                    "source": "code-map",
                    "generated": True,
                }
            )
        for entry in code_map.get("entryPoints") or []:
            if not isinstance(entry, dict):
                continue
            entry_path = str(entry.get("path") or "").strip()
            if not entry_path:
                continue
            entry_id = f"artifact:entry:{entry_path}"
            managed_nodes.append(
                {
                    "id": entry_id,
                    "type": "artifact",
                    "kind": "artifact",
                    "title": str(entry.get("why") or "Application entry point"),
                    "path": entry_path,
                    "status": "active",
                    "source": "code-map",
                    "generated": True,
                }
            )
            entry_module = Path(entry_path).parts[0] if len(Path(entry_path).parts) > 1 else "."
            managed_edges.append(
                {
                    "from": entry_id,
                    "to": module_ids.get(entry_module, f"project:{project_id}"),
                    "type": "belongs_to",
                    "source": "code-map",
                    "generated": True,
                }
            )
        for dependency in code_map.get("moduleEdges") or []:
            if not isinstance(dependency, dict):
                continue
            source = str(dependency.get("from") or "").strip()
            target = str(dependency.get("to") or "").strip()
            if source not in module_ids or target not in module_ids:
                continue
            managed_edges.append(
                {
                    "from": module_ids[source],
                    "to": module_ids[target],
                    "type": "depends_on",
                    "source": "code-map",
                    "generated": True,
                    "weight": int(dependency.get("weight") or 0),
                }
            )
        verification_graph = code_map.get("verificationGraph")
        verification_node_ids: dict[str, str] = {}
        if isinstance(verification_graph, dict):
            for verification_node in verification_graph.get("nodes") or []:
                if not isinstance(verification_node, dict):
                    continue
                raw_id = str(verification_node.get("id") or "").strip()
                relative = str(verification_node.get("path") or "").strip()
                kind = str(verification_node.get("kind") or "verification").strip()
                if not raw_id or not relative:
                    continue
                node_id = f"verification:{raw_id}"
                verification_node_ids[raw_id] = node_id
                managed_nodes.append(
                    {
                        "id": node_id,
                        "type": "verification",
                        "kind": kind,
                        "title": (
                            str(verification_node.get("name") or "").strip()
                            or relative
                        ),
                        "path": relative,
                        "status": "active",
                        "source": "code-map",
                        "generated": True,
                        **(
                            {"version": verification_node.get("value")}
                            if kind == "version_contract" and verification_node.get("value")
                            else {}
                        ),
                    }
                )
                module_path = Path(relative).parts[0] if len(Path(relative).parts) > 1 else "."
                managed_edges.append(
                    {
                        "from": node_id,
                        "to": module_ids.get(module_path, f"project:{project_id}"),
                        "type": "verifies",
                        "source": "code-map",
                        "generated": True,
                    }
                )
            for verification_edge in verification_graph.get("edges") or []:
                if not isinstance(verification_edge, dict):
                    continue
                source = str(verification_edge.get("from") or "").strip()
                target = str(verification_edge.get("to") or "").strip()
                relation = str(verification_edge.get("relation") or "verifies").strip()
                source_id = verification_node_ids.get(source)
                if source_id is None and source:
                    source_module = Path(source).parts[0] if len(Path(source).parts) > 1 else "."
                    source_id = module_ids.get(source_module, f"project:{project_id}")
                target_id = verification_node_ids.get(target)
                if source_id and target_id:
                    managed_edges.append(
                        {
                            "from": source_id,
                            "to": target_id,
                            "type": relation,
                            "source": "code-map",
                            "generated": True,
                        }
                    )
    nodes = payload.get("nodes")
    edges = payload.get("edges")
    if not isinstance(nodes, list):
        nodes = []
        payload["nodes"] = nodes
    if not isinstance(edges, list):
        edges = []
        payload["edges"] = edges
    before_node_count = len(nodes)
    before_edge_count = len(edges)
    nodes[:] = [
        node
        for node in nodes
        if not (
            isinstance(node, dict)
            and node.get("source") == "code-map"
            and node.get("generated") is True
        )
    ]
    edges[:] = [
        edge
        for edge in edges
        if not (
            isinstance(edge, dict)
            and edge.get("source") == "code-map"
            and edge.get("generated") is True
        )
    ]
    existing_ids = {
        str(node.get("id") or "")
        for node in nodes
        if isinstance(node, dict)
    }
    changed = len(nodes) != before_node_count or len(edges) != before_edge_count
    for node in managed_nodes:
        if node["id"] not in existing_ids:
            nodes.append(node)
            changed = True
    existing_edges = {
        (
            str(edge.get("from") or ""),
            str(edge.get("to") or ""),
            str(edge.get("type") or ""),
        )
        for edge in edges
        if isinstance(edge, dict)
    }
    for edge in managed_edges:
        key = (edge["from"], edge["to"], edge["type"])
        if key not in existing_edges:
            edges.append(edge)
            existing_edges.add(key)
            changed = True
    if isinstance(code_map, dict):
        next_projection = {
            "schemaVersion": "agentlas.functional-sitemap-projection.v1",
            "source": "code-map",
            "mapSchemaVersion": str(code_map.get("schemaVersion") or ""),
            "mapFingerprint": str(code_map.get("fingerprintHash") or ""),
            "generatedAt": str(code_map.get("generatedAt") or utc_now()),
            "surfaceNodes": sum(
                1
                for node in managed_nodes
                if isinstance(node, dict) and node.get("type") == "surface"
            ),
            "entryPointNodes": sum(
                1
                for node in managed_nodes
                if isinstance(node, dict) and node.get("type") == "artifact"
            ),
            "dependencyEdges": sum(
                1
                for edge in managed_edges
                if isinstance(edge, dict) and edge.get("type") == "depends_on"
            ),
            "verificationNodes": sum(
                1
                for node in managed_nodes
                if isinstance(node, dict) and node.get("type") == "verification"
            ),
            "verificationEdges": sum(
                1
                for edge in managed_edges
                if isinstance(edge, dict)
                and edge.get("type") in {
                    "verified_by",
                    "verified_by_name",
                    "invoked_by",
                    "executed_by",
                    "versioned_by",
                    "released_by",
                }
            ),
        }
        if payload.get("functionalProjection") != next_projection:
            payload["functionalProjection"] = next_projection
            changed = True
    if changed:
        _atomic_write(
            path,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
            mode=_existing_mode(path, 0o600),
        )
    return None


def _ensure_graph_runtimes(root: Path) -> tuple[list[str], list[str]]:
    created: list[str] = []
    warnings: list[str] = []
    before = {path for path in (root / ".agentlas").rglob("*")}
    try:
        from ontology.cli import auto_activate_project

        auto_activate_project(root, scope="internal", no_ingest=True)
    except Exception as exc:  # runtime setup must not prevent the remaining safe seed
        warnings.append(f"ontology_setup_failed:{type(exc).__name__}")
    try:
        from career_graph.runtime import CareerGraphRuntime, RuntimeConfig

        runtime = CareerGraphRuntime(RuntimeConfig(project=root))
        runtime.ensure_files()
        with closing(runtime.connect()) as connection:
            with connection:
                pass
    except Exception as exc:
        warnings.append(f"career_graph_setup_failed:{type(exc).__name__}")
    after = {path for path in (root / ".agentlas").rglob("*") if path.is_file()}
    created.extend(sorted(path.relative_to(root).as_posix() for path in after - before))
    return created, warnings


def _harden_private_tree(root: Path) -> list[str]:
    """Make local memory unreadable to other local accounts.

    The bootstrap owns `.agentlas` as private state. Existing user content is
    never rewritten, but its filesystem mode is tightened to the documented
    privacy boundary.
    """

    agentlas = root / ".agentlas"
    issues: list[str] = []
    if not agentlas.exists():
        return issues
    for path in sorted(agentlas.rglob("*")):
        try:
            if path.is_symlink():
                issues.append(path.relative_to(root).as_posix() + ":symlink")
            elif path.is_dir():
                os.chmod(path, 0o700)
            elif path.is_file():
                os.chmod(path, 0o600)
        except OSError:
            issues.append(path.relative_to(root).as_posix() + ":chmod_failed")
    try:
        os.chmod(agentlas, 0o700)
    except OSError:
        issues.append(".agentlas:chmod_failed")
    return issues


def _safe_file(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
        if _should_skip_relative_path(relative):
            return False
        if path.is_symlink():
            return False
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        return stat.S_ISREG(os.stat(path, follow_symlinks=False).st_mode)
    except (OSError, RuntimeError, ValueError):
        return False


def _should_skip_relative_path(relative: Path) -> bool:
    parts = relative.parts
    if not parts or any(
        part == ".." or part in SKIP_DIRS or part.lower().endswith(".app")
        for part in parts
    ):
        return True
    return parts[0] in ROOT_OUTPUT_DIRS


def _prune_walk_directories(root: Path, current: Path, dirnames: list[str]) -> None:
    dirnames[:] = [
        name
        for name in dirnames
        if not _should_skip_relative_path((current / name).relative_to(root))
    ]


def _run_bounded_stdout(
    command: list[str],
    *,
    deadline: float,
    max_bytes: int,
) -> tuple[bytes | None, str | None]:
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None, "unavailable"
    if process.stdout is None:
        process.kill()
        return None, "unavailable"

    chunks: queue.Queue[bytes | None] = queue.Queue(maxsize=1)
    stop_reading = threading.Event()

    def offer(chunk: bytes | None) -> bool:
        while not stop_reading.is_set():
            try:
                chunks.put(chunk, timeout=0.05)
                return True
            except queue.Full:
                continue
        return False

    def read_stdout() -> None:
        try:
            while True:
                chunk = process.stdout.read(64 * 1024)
                if not offer(chunk or None) or not chunk:
                    return
        except (OSError, ValueError):
            offer(None)

    reader = threading.Thread(target=read_stdout, name="agentlas-bounded-stdout", daemon=True)
    reader.start()
    stop: str | None = None
    output = bytearray()
    terminated = False
    while True:
        remaining_time = deadline - time.monotonic()
        if remaining_time <= 0:
            stop = stop or "timeout"
            terminated = True
            break
        try:
            chunk = chunks.get(timeout=min(0.1, remaining_time))
        except queue.Empty:
            if process.poll() is not None and not reader.is_alive():
                break
            continue
        if chunk is None:
            break
        remaining_bytes = max_bytes - len(output)
        accepted = chunk[: max(0, remaining_bytes)]
        output.extend(accepted)
        if len(chunk) > len(accepted):
            stop = stop or "output_bytes"
            terminated = True
            break
    stop_reading.set()
    if terminated and process.poll() is None:
        process.kill()
    try:
        returncode = process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        process.kill()
        returncode = process.wait(timeout=1.0)
        stop = stop or "timeout"
    try:
        process.stdout.close()
    except OSError:
        pass
    reader.join(timeout=0.2)
    if returncode != 0 and stop is None:
        return None, "command_failed"
    return bytes(output), stop


def _complete_nul_items(raw_output: bytes) -> list[bytes]:
    items = raw_output.split(b"\0")
    if raw_output and not raw_output.endswith(b"\0"):
        items = items[:-1]
    return [item for item in items if item]


def _git_file_list(root: Path, deadline: float) -> tuple[list[Path] | None, str | None, int]:
    raw_prefix, prefix_stop = _run_bounded_stdout(
        ["git", "-C", str(root), "rev-parse", "--show-prefix"],
        deadline=deadline,
        max_bytes=MAX_GIT_PREFIX_BYTES,
    )
    if raw_prefix is None:
        return None, "file_list_" + str(prefix_stop or "unavailable"), 0
    if prefix_stop is not None:
        return None, "file_list_prefix_" + str(prefix_stop), 0
    if raw_prefix.strip(b"\r\n"):
        # The explicit Agentlas project boundary is authoritative. A parent
        # repository must not make an ignored or untracked nested project look
        # like a complete, empty Git listing.
        return None, "outside_git_root", 0
    raw_output, process_stop = _run_bounded_stdout(
        ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
        deadline=deadline,
        max_bytes=MAX_GIT_FILE_LIST_BYTES,
    )
    if raw_output is None:
        return None, "file_list_" + str(process_stop or "unavailable"), 0
    stop = {
        "output_bytes": "file_list_bytes",
        "timeout": "file_list_timeout",
    }.get(str(process_stop), None)
    files: list[Path] = []
    skipped_unsafe = 0
    for raw in _complete_nul_items(raw_output):
        relative = Path(os.fsdecode(raw))
        path = root / relative
        if _safe_file(root, path):
            files.append(path)
        else:
            skipped_unsafe += 1
        if len(files) >= MAX_DISCOVERED_FILES:
            stop = stop or "file_count"
            break
        if time.monotonic() >= deadline:
            stop = stop or "scan_time"
            break
    return files, stop, skipped_unsafe


def _walk_file_list(root: Path, deadline: float) -> tuple[list[Path], str | None, int]:
    files: list[Path] = []
    skipped_unsafe = 0
    stop: str | None = None
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        _prune_walk_directories(root, current_path, dirnames)
        for name in filenames:
            path = current_path / name
            if _safe_file(root, path):
                files.append(path)
            else:
                skipped_unsafe += 1
            if len(files) >= MAX_DISCOVERED_FILES:
                return files, "file_count", skipped_unsafe
            if time.monotonic() >= deadline:
                return files, "scan_time", skipped_unsafe
    return files, stop, skipped_unsafe


def _walk_local_test_files(
    root: Path,
    deadline: float,
    policy: Mapping[str, Any] | None = None,
) -> tuple[list[Path], str | None, int]:
    """Discover local test code even when Git intentionally ignores it.

    Public release policy may exclude tests while a developer still runs those
    files locally. The local Context Map must see that execution channel; Git's
    tracked/untracked listing alone cannot represent it.
    """

    files: list[Path] = []
    skipped_unsafe = 0
    selected_policy = policy or DEFAULT_CONTEXT_INDEX_POLICY
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        _prune_walk_directories(root, current_path, dirnames)
        dirnames[:] = [
            name
            for name in dirnames
            if _policy_allows(
                (current_path / name).relative_to(root).as_posix(),
                selected_policy,
            )
        ]
        for name in filenames:
            path = current_path / name
            try:
                relative = path.relative_to(root).as_posix()
            except ValueError:
                skipped_unsafe += 1
                continue
            if not _policy_allows(relative, selected_policy):
                continue
            if (
                not _matches_test_policy(relative, selected_policy)
                or Path(relative).suffix.lower() not in CODE_EXTENSIONS
            ):
                continue
            if _safe_file(root, path):
                files.append(path)
            else:
                skipped_unsafe += 1
            if len(files) >= MAX_LOCAL_TEST_FILES:
                return files, "local_test_file_count", skipped_unsafe
            if time.monotonic() >= deadline:
                return files, "local_test_scan_time", skipped_unsafe
    return files, None, skipped_unsafe


def _extract_symbols(text: str, limit: int) -> tuple[list[dict[str, Any]], bool]:
    effective_limit = min(MAX_SYMBOLS_PER_FILE, max(0, limit))
    if effective_limit <= 0:
        return [], any(pattern.search(line) for line in text.splitlines() for _kind, pattern in SYMBOL_PATTERNS)
    symbols: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in SYMBOL_PATTERNS:
            match = pattern.search(line)
            if match:
                if len(symbols) >= effective_limit:
                    return symbols, True
                symbols.append({"n": match.group(1), "k": kind, "l": line_number})
                break
    return symbols, False


def _fingerprint_hash(files: dict[str, dict[str, int]]) -> str:
    digest = hashlib.sha256()
    for relative, fingerprint in sorted(files.items()):
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(str(fingerprint["mtimeNs"]).encode("ascii"))
        digest.update(b":")
        digest.update(str(fingerprint["ctimeNs"]).encode("ascii"))
        digest.update(b":")
        digest.update(str(fingerprint["size"]).encode("ascii"))
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        metadata = path.stat(follow_symlinks=False)
    except OSError:
        return {}
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size <= 0
        or metadata.st_size > MAX_CODE_MAP_BYTES
    ):
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _canonical_json_digest(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _project_root_hash(project: Path) -> str:
    return "sha256:" + hashlib.sha256(str(project).encode("utf-8")).hexdigest()


def _code_map_binding_complete(
    project: Path,
    project_map: dict[str, Any],
    cache: dict[str, Any],
) -> bool:
    stats = project_map.get("stats") if isinstance(project_map.get("stats"), dict) else {}
    expected_root_hash = _project_root_hash(project)
    manifest = _read_json_object(project / ".agentlas" / "code-map" / "manifest.json")
    return (
        project_map.get("schemaVersion") == "agentlas.code-map.v2"
        and project_map.get("projectRootHash") == expected_root_hash
        and isinstance(project_map.get("defIndex"), dict)
        and isinstance(project_map.get("refIndex"), dict)
        and cache.get("schemaVersion") == CODE_MAP_CACHE_SCHEMA
        and cache.get("policyVersion") == CODE_MAP_POLICY_VERSION
        and cache.get("projectRootHash") == expected_root_hash
        and cache.get("fingerprintHash") == project_map.get("fingerprintHash")
        and cache.get("snapshotId") == project_map.get("snapshotId")
        and cache.get("policyDigest") == project_map.get("policyDigest")
        and cache.get("mapPayloadDigest") == _canonical_json_digest(project_map)
        and manifest.get("schemaVersion") == CODE_MAP_MANIFEST_SCHEMA
        and manifest.get("projectRootHash") == expected_root_hash
        and manifest.get("snapshotId") == project_map.get("snapshotId")
        and manifest.get("policyDigest") == project_map.get("policyDigest")
        and manifest.get("complete") is True
        and isinstance(manifest.get("compatibilityMap"), dict)
        and manifest["compatibilityMap"].get("path") == "project-map.json"
        and manifest["compatibilityMap"].get("schemaVersion") == project_map.get("schemaVersion")
        and manifest["compatibilityMap"].get("digest") == _canonical_json_digest(project_map)
        and cache.get("completeMap") is True
        and stats.get("coverageComplete") is True
        and stats.get("incompleteReasons") == []
        and stats.get("scanComplete") is True
        and not stats.get("budgetStop")
        and stats.get("outputTruncated") is False
        and int(stats.get("candidateCodeFiles") or 0) == int(stats.get("codeFiles") or 0)
    )


def _code_map_incomplete_reasons(stats: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if stats.get("budgetStop"):
        reasons.append("budget_stop")
    if stats.get("scanComplete") is not True:
        reasons.append("scan_incomplete")
    if int(stats.get("skippedLarge") or 0) > 0:
        reasons.append("large_code_files")
    if int(stats.get("skippedUnreadable") or 0) > 0:
        reasons.append("unreadable_code_files")
    if int(stats.get("fingerprintFailures") or 0) > 0:
        reasons.append("fingerprint_failures")
    if int(stats.get("candidateCodeFiles") or 0) != int(stats.get("codeFiles") or 0):
        reasons.append("code_file_coverage")
    if stats.get("refIndexTruncated") is True:
        reasons.append("reference_index_truncated")
    if stats.get("outputTruncated") is True:
        reasons.append("output_truncated")
    if stats.get("verificationGraphTruncated") is True:
        reasons.append("verification_graph_truncated")
    if stats.get("dependencyEdgesTruncated") is True:
        reasons.append("dependency_graph_truncated")
    if stats.get("snapshotComplete") is not True:
        reasons.append("snapshot_incomplete")
    return sorted(set(reasons))


def _functional_sitemap_summary(root: Path) -> dict[str, Any]:
    payload = _read_json_object(root / ".agentlas" / "sitemap.json")
    nodes = [node for node in payload.get("nodes") or [] if isinstance(node, dict)]
    edges = [edge for edge in payload.get("edges") or [] if isinstance(edge, dict)]
    functional_nodes = [
        node
        for node in nodes
        if str(node.get("type") or node.get("kind") or "").lower() not in {"file", "directory"}
    ]
    generated_nodes = [
        node
        for node in functional_nodes
        if node.get("source") == "code-map" and node.get("generated") is True
    ]
    dependency_edges = [
        edge
        for edge in edges
        if str(edge.get("type") or edge.get("relation") or "").lower() == "depends_on"
    ]
    return {
        "schemaVersion": "agentlas.functional-sitemap-receipt.v1",
        "functionalNodes": len(functional_nodes),
        "generatedFunctionalNodes": len(generated_nodes),
        "dependencyEdges": len(dependency_edges),
        "mapFingerprint": str((payload.get("functionalProjection") or {}).get("mapFingerprint") or ""),
    }


def _bounded_project_map(project_map: dict[str, Any]) -> tuple[str, int]:
    raw = json.dumps(project_map, ensure_ascii=False, separators=(",", ":")) + "\n"
    original_files = len(project_map.get("fileSymbols") or {})
    while len(raw.encode("utf-8")) > MAX_CODE_MAP_BYTES and project_map.get("fileSymbols"):
        items = list(project_map["fileSymbols"].items())
        project_map["fileSymbols"] = dict(items[: max(0, len(items) // 2)])
        project_map["stats"]["outputTruncated"] = True
        project_map["stats"]["fileSymbolFilesOmitted"] = original_files - len(project_map["fileSymbols"])
        raw = json.dumps(project_map, ensure_ascii=False, separators=(",", ":")) + "\n"
    ref_index = project_map.get("refIndex")
    if isinstance(ref_index, dict):
        for cap in (32, 16, 8):
            if len(raw.encode("utf-8")) <= MAX_CODE_MAP_BYTES:
                break
            project_map["refIndex"] = {
                key: values[:cap] if isinstance(values, list) else []
                for key, values in ref_index.items()
            }
            project_map["stats"]["outputTruncated"] = True
            project_map["stats"]["refFilesPerSymbolCap"] = cap
            raw = json.dumps(project_map, ensure_ascii=False, separators=(",", ":")) + "\n"
    if len(raw.encode("utf-8")) > MAX_CODE_MAP_BYTES and isinstance(project_map.get("refIndex"), dict):
        ref_counts = project_map.get("refCount") if isinstance(project_map.get("refCount"), dict) else {}
        ordered = sorted(
            project_map["refIndex"],
            key=lambda key: (-int(ref_counts.get(key) or 0), key),
        )
        original_refs = len(ordered)
        # The byte budget is the contract; "keep at least 1,000" is only a
        # heuristic. Since the per-file symbol cap was raised, that floor has
        # deadlocked against a small budget and lost the whole map (budget
        # exceeded = OSError = no map). ordered is sorted by reference
        # frequency, so lowering the floor to 1 still keeps as many of the
        # hottest symbols as the budget allows.
        while len(raw.encode("utf-8")) > MAX_CODE_MAP_BYTES and len(ordered) > 1:
            ordered = ordered[: max(1, len(ordered) // 2)]
            allowed = set(ordered)
            project_map["refIndex"] = {
                key: value for key, value in project_map["refIndex"].items() if key in allowed
            }
            project_map["refCount"] = {
                key: value for key, value in ref_counts.items() if key in allowed
            }
            project_map["stats"]["outputTruncated"] = True
            project_map["stats"]["refIndexSymbolsOmitted"] = original_refs - len(allowed)
            raw = json.dumps(project_map, ensure_ascii=False, separators=(",", ":")) + "\n"
    # Since the per-file symbol cap was raised, defIndex/topSymbols alone can
    # now exceed a small budget too. This step comes last in the ladder so the
    # definition index survives longest, but the byte budget is still the
    # final contract, so keep halving until it converges here too.
    if len(raw.encode("utf-8")) > MAX_CODE_MAP_BYTES and isinstance(project_map.get("defIndex"), dict) and project_map["defIndex"]:
        def_counts = project_map.get("refCount") if isinstance(project_map.get("refCount"), dict) else {}
        ordered_defs = sorted(
            project_map["defIndex"],
            key=lambda key: (-int(def_counts.get(key) or 0), key),
        )
        original_defs = len(ordered_defs)
        while len(raw.encode("utf-8")) > MAX_CODE_MAP_BYTES and len(ordered_defs) > 1:
            ordered_defs = ordered_defs[: max(1, len(ordered_defs) // 2)]
            allowed_defs = set(ordered_defs)
            project_map["defIndex"] = {
                key: value for key, value in project_map["defIndex"].items() if key in allowed_defs
            }
            project_map["stats"]["outputTruncated"] = True
            project_map["stats"]["defIndexSymbolsOmitted"] = original_defs - len(allowed_defs)
            raw = json.dumps(project_map, ensure_ascii=False, separators=(",", ":")) + "\n"
    if len(raw.encode("utf-8")) > MAX_CODE_MAP_BYTES and isinstance(project_map.get("topSymbols"), list) and project_map["topSymbols"]:
        original_top = len(project_map["topSymbols"])
        while len(raw.encode("utf-8")) > MAX_CODE_MAP_BYTES and len(project_map["topSymbols"]) > 1:
            project_map["topSymbols"] = project_map["topSymbols"][: max(1, len(project_map["topSymbols"]) // 2)]
            project_map["stats"]["outputTruncated"] = True
            project_map["stats"]["topSymbolsOmitted"] = original_top - len(project_map["topSymbols"])
            raw = json.dumps(project_map, ensure_ascii=False, separators=(",", ":")) + "\n"
    if len(raw.encode("utf-8")) > MAX_CODE_MAP_BYTES:
        raise OSError("code_map_output_budget_exceeded")
    return raw, len(raw.encode("utf-8"))


def _is_test_path(relative: str) -> bool:
    path = Path(relative)
    lowered_parts = {part.lower() for part in path.parts[:-1]}
    name = path.name.lower()
    return (
        bool(lowered_parts.intersection(TEST_DIRECTORY_NAMES))
        or bool(TEST_NAME_PATTERN.search(name))
    )


def _is_ci_workflow_path(relative: str) -> bool:
    path = Path(relative)
    return (
        len(path.parts) >= 3
        and path.parts[0] == ".github"
        and path.parts[1] == "workflows"
        and path.suffix.lower() in CI_WORKFLOW_SUFFIXES
    )


def _is_version_contract_path(relative: str) -> bool:
    path = Path(relative)
    return (
        path.name.lower() in VERSION_CONTRACT_NAMES
        or path.name.lower() in {"build.gradle", "build.gradle.kts"}
    )


def _read_verification_text(root: Path, relative: str) -> str:
    path = root / relative
    try:
        metadata = os.stat(path, follow_symlinks=False)
        if metadata.st_size <= 0 or metadata.st_size > MAX_VERIFICATION_FILE_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _version_value(relative: str, text: str) -> str | None:
    name = Path(relative).name.lower()
    if name.endswith(".json"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict):
            value = payload.get("version")
            if isinstance(value, str) and value.strip():
                return value.strip()
            packages = payload.get("packages")
            if isinstance(packages, dict):
                root_package = packages.get("")
                if isinstance(root_package, dict):
                    value = root_package.get("version")
                    if isinstance(value, str) and value.strip():
                        return value.strip()
        return None
    if name in {"pyproject.toml", "cargo.toml"}:
        match = re.search(r'(?m)^\s*version\s*=\s*["\']([^"\']+)["\']', text)
        return match.group(1).strip() if match else None
    if name in {"build.gradle", "build.gradle.kts"}:
        match = re.search(r'(?m)^\s*version\s*=\s*["\']([^"\']+)["\']', text)
        return match.group(1).strip() if match else None
    return None


def _package_test_commands(relative: str, text: str) -> list[dict[str, str]]:
    if Path(relative).name.lower() != "package.json":
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    scripts = payload.get("scripts") if isinstance(payload, dict) else None
    if not isinstance(scripts, dict):
        return []
    rows: list[dict[str, str]] = []
    for name, command in sorted(scripts.items()):
        if not isinstance(name, str) or not isinstance(command, str):
            continue
        lowered = name.lower()
        if not any(marker in lowered for marker in ("test", "verify", "check", "smoke", "audit", "gate")):
            continue
        rows.append(
            {
                "id": f"command:{relative}#{name}",
                "path": relative,
                "name": name,
                "command": command[:1_000],
            }
        )
    def command_priority(row: Mapping[str, str]) -> tuple[int, str]:
        name = row["name"].lower()
        broad = name in {"test", "typecheck", "check", "verify", "e2e:smoke"}
        return (0 if broad else 1, name)

    return sorted(rows, key=command_priority)[:256]


def _resolve_import_specifier(
    importer: str,
    specifier: str,
    source_files: set[str],
) -> str | None:
    specifier = specifier.strip()
    if not specifier:
        return None
    importer_parent = Path(importer).parent
    importer_suffix = Path(importer).suffix.lower()
    raw_candidates: list[Path] = []
    if importer_suffix == ".py":
        leading_dots = len(specifier) - len(specifier.lstrip("."))
        module = specifier[leading_dots:].replace(".", "/")
        if leading_dots:
            base = importer_parent
            for _ in range(max(0, leading_dots - 1)):
                base = base.parent
            raw_candidates.append(base / module)
        else:
            raw_candidates.extend((Path(module), Path("src") / module))
    elif specifier.startswith("."):
        raw_candidates.append(importer_parent / specifier)
    elif specifier.startswith("@/"):
        alias_path = specifier[2:]
        raw_candidates.extend((Path(alias_path), Path("src") / alias_path))
    else:
        # Bare JS/TS specifiers name external packages unless a project alias
        # explicitly says otherwise. Treating `react` as local `src/react.ts`
        # creates authoritative false edges.
        return None
    if importer_suffix == ".py" and not raw_candidates:
        dotted = specifier.replace(".", "/")
        raw_candidates.extend((Path(specifier), Path(dotted), Path("src") / dotted))
    candidates: list[str] = []
    extensions = tuple(sorted(CODE_EXTENSIONS))
    for raw in raw_candidates:
        normalized = Path(os.path.normpath(raw.as_posix())).as_posix()
        if normalized.startswith("../") or normalized == "..":
            continue
        candidates.append(normalized)
        if not Path(normalized).suffix:
            candidates.extend(normalized + extension for extension in extensions)
            candidates.extend((Path(normalized) / ("index" + extension)).as_posix() for extension in extensions)
            candidates.extend((Path(normalized) / ("__init__" + extension)).as_posix() for extension in extensions)
    exact = sorted({candidate for candidate in candidates if candidate in source_files})
    return exact[0] if len(exact) == 1 else None


def _import_specifiers(importer: str, text: str) -> list[str]:
    suffix = Path(importer).suffix.lower()
    if suffix == ".py":
        # Python comments end at the line boundary; import strings are not
        # meaningful dependency declarations.
        searchable = re.sub(r"(?m)#.*$", "", text)
        patterns = PYTHON_IMPORT_SPECIFIER_PATTERNS
    elif suffix in {".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"}:
        # Remove comments before scanning require()/import() so examples and
        # disabled code never become blocking dependency edges.
        searchable = re.sub(r"/\*[\s\S]*?\*/", "", text)
        searchable = re.sub(r"(?m)//.*$", "", searchable)
        patterns = JS_IMPORT_SPECIFIER_PATTERNS
    else:
        return []
    return sorted(
        {
            match.group(1).strip()
            for pattern in patterns
            for match in pattern.finditer(searchable)
            if match.group(1).strip()
        }
    )


def _exact_dependency_edges(
    *,
    scanned_files: Sequence[str],
    file_texts: Mapping[str, str],
) -> tuple[list[dict[str, str]], bool]:
    """Build authoritative reverse dependencies from exact import paths only."""

    source_files = set(scanned_files)
    rows: set[tuple[str, str, str]] = set()
    truncated = False
    for importer in sorted(scanned_files):
        text = file_texts.get(importer, "")
        for specifier in _import_specifiers(importer, text):
            target = _resolve_import_specifier(importer, specifier, source_files)
            if target is None or target == importer:
                continue
            rows.add((target, importer, "imports"))
            if len(rows) > MAX_DEPENDENCY_EDGES:
                truncated = True
                break
        if truncated:
            break
    ordered = sorted(rows)[:MAX_DEPENDENCY_EDGES]
    return [
        {"from": source, "to": target, "relation": relation}
        for source, target, relation in ordered
    ], truncated


def _verification_graph(
    root: Path,
    *,
    relative_files: Sequence[str],
    scanned_files: Sequence[str],
    test_files: Sequence[str],
    dependency_edges: Sequence[Mapping[str, str]],
) -> dict[str, Any]:
    test_files = sorted(set(test_files))
    workflow_files = sorted(relative for relative in relative_files if _is_ci_workflow_path(relative))
    version_files = sorted(relative for relative in relative_files if _is_version_contract_path(relative))
    texts = {
        relative: _read_verification_text(root, relative)
        for relative in sorted(set(workflow_files + version_files))
    }
    commands: list[dict[str, str]] = []
    for relative in version_files:
        commands.extend(_package_test_commands(relative, texts.get(relative, "")))

    nodes: list[dict[str, Any]] = []
    for relative in test_files:
        nodes.append(
            {
                "id": f"test:{relative}",
                "kind": "test",
                "path": relative,
                "verificationChannel": "local",
            }
        )
    for command in commands:
        nodes.append(
            {
                "id": command["id"],
                "kind": "test_command",
                "path": command["path"],
                "name": command["name"],
                "verificationChannel": "local",
            }
        )
    for relative in workflow_files:
        nodes.append(
            {
                "id": f"ci:{relative}",
                "kind": "ci_workflow",
                "path": relative,
                "verificationChannel": "ci",
            }
        )
    version_contracts: list[dict[str, Any]] = []
    for relative in version_files:
        value = _version_value(relative, texts.get(relative, ""))
        row = {
            "id": f"version:{relative}",
            "kind": "version_contract",
            "path": relative,
            "value": value,
            "verificationChannel": "release",
        }
        nodes.append(row)
        version_contracts.append(row)
    node_count = len(nodes)
    nodes = nodes[:MAX_VERIFICATION_NODES]
    allowed_node_ids = {str(node["id"]) for node in nodes}

    edges: list[dict[str, str]] = []
    edge_keys: set[tuple[str, str, str]] = set()
    edge_limit_hit = False

    def add_edge(source: str, target: str, relation: str) -> None:
        nonlocal edge_limit_hit
        key = (source, target, relation)
        if key in edge_keys:
            return
        if len(edges) >= MAX_VERIFICATION_EDGES:
            edge_limit_hit = True
            return
        if (
                (source.startswith(("test:", "command:", "ci:", "version:")) and source not in allowed_node_ids)
                or (target.startswith(("test:", "command:", "ci:", "version:")) and target not in allowed_node_ids)
        ):
            return
        edge_keys.add(key)
        edges.append({"from": source, "to": target, "relation": relation})

    test_set = set(test_files)
    source_files = [relative for relative in scanned_files if relative not in test_set]
    source_set = set(source_files)
    for dependency in dependency_edges:
        source = str(dependency.get("from") or "")
        target = str(dependency.get("to") or "")
        if source in source_set and target in test_set:
            add_edge(source, f"test:{target}", "verified_by_import")

    source_by_stem: dict[str, list[str]] = defaultdict(list)
    for relative in source_files:
        source_by_stem[Path(relative).stem.lower()].append(relative)
    for test in test_files:
        stem = Path(test).stem.lower()
        normalized_stems = {
            re.sub(r"^(?:test|spec)[_-]", "", stem),
            re.sub(r"[_-](?:test|spec)$", "", stem),
            re.sub(r"[.-](?:test|spec)$", "", stem),
        }
        for normalized in sorted(normalized_stems):
            for source in source_by_stem.get(normalized, ()):
                add_edge(source, f"test:{test}", "advisory_by_name")

    broad_command_names = {"test", "typecheck", "check", "verify", "e2e:smoke"}
    commands_by_scope: dict[str, list[dict[str, str]]] = defaultdict(list)
    for command in commands:
        name = command["name"].lower()
        if name in broad_command_names or name.endswith((":typecheck", ":check")):
            commands_by_scope[Path(command["path"]).parent.as_posix()].append(command)
    for source in source_files:
        source_parts = Path(source).parts
        matching_scopes = [
            scope
            for scope in commands_by_scope
            if scope == "."
            or Path(scope).parts == source_parts[: len(Path(scope).parts)]
        ]
        if not matching_scopes:
            continue
        nearest_scope = max(matching_scopes, key=lambda scope: len(Path(scope).parts))
        def command_rank(row: Mapping[str, str]) -> tuple[int, str, str]:
            name = row["name"].lower()
            rank = 0 if name == "test" else 1 if name == "typecheck" else 2 if name == "check" else 3
            return rank, name, row["id"]

        for command in sorted(commands_by_scope[nearest_scope], key=command_rank)[:1]:
            add_edge(source, command["id"], "verified_by_command")

    for test in test_files:
        test_name = Path(test).name
        conventional_test_dirs = {
            part
            for part in Path(test).parts[:-1]
            if part.lower() in TEST_DIRECTORY_NAMES
        }
        for command in commands:
            command_text = command["command"]
            if (
                test in command_text
                or test_name in command_text
                or any(
                    re.search(
                        rf"(?<![A-Za-z0-9_.-]){re.escape(directory)}(?:/|\b)",
                        command_text,
                    )
                    for directory in conventional_test_dirs
                )
            ):
                add_edge(f"test:{test}", command["id"], "invoked_by")

    for command in commands:
        invocations = {
            f"npm run {command['name']}",
            f"pnpm run {command['name']}",
            f"yarn {command['name']}",
            f"bun run {command['name']}",
        }
        for workflow in workflow_files:
            workflow_text = texts.get(workflow, "")
            if any(invocation in workflow_text for invocation in invocations):
                add_edge(command["id"], f"ci:{workflow}", "executed_by")

    for test in test_files:
        test_name = Path(test).name
        for workflow in workflow_files:
            workflow_text = texts.get(workflow, "")
            if test in workflow_text or test_name in workflow_text:
                add_edge(f"test:{test}", f"ci:{workflow}", "executed_by")

    contracts_by_scope: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for contract in version_contracts:
        parent = Path(str(contract["path"])).parent.as_posix()
        contracts_by_scope[parent].append(contract)
    for source in source_files:
        source_parts = Path(source).parts
        matching_scopes = [
            scope
            for scope in contracts_by_scope
            if scope == "."
            or Path(scope).parts == source_parts[: len(Path(scope).parts)]
        ]
        if not matching_scopes:
            continue
        nearest_scope = max(matching_scopes, key=lambda scope: len(Path(scope).parts))
        contract_priority = {
            "package.json": 0,
            "pyproject.toml": 1,
            "cargo.toml": 2,
            "manifest.json": 3,
            "gemini-extension.json": 4,
            "package-lock.json": 5,
        }
        authoritative_contract = min(
            contracts_by_scope[nearest_scope],
            key=lambda row: (
                contract_priority.get(Path(str(row["path"])).name.lower(), 99),
                str(row["path"]),
            ),
        )
        # Version ownership is a release obligation, not evidence that source
        # code was executed. Advisory edges remain visible in the graph while
        # ordinary verification traversal intentionally skips them.
        add_edge(
            source,
            str(authoritative_contract["id"]),
            "advisory_versioned_by",
        )
    for workflow in workflow_files:
        lowered = texts.get(workflow, "").lower()
        if any(marker in lowered for marker in ("release", "publish", "deploy", "tag")):
            for contract in version_contracts:
                add_edge(str(contract["id"]), f"ci:{workflow}", "released_by")

    node_paths = sorted(
        {
            str(node.get("path") or "")
            for node in nodes
            if str(node.get("path") or "")
        }
    )
    existing_files = set(relative_files)
    issues: list[dict[str, str]] = []
    for source, text, base in [
        *((workflow, texts.get(workflow, ""), Path(".")) for workflow in workflow_files),
        *(
            (command["id"], command["command"], Path(command["path"]).parent)
            for command in commands
        ),
    ]:
        for match in TEST_PATH_REFERENCE_PATTERN.finditer(text):
            referenced = match.group(1).rstrip(".,:;)")
            candidates = {
                Path(base, referenced).as_posix(),
                referenced,
                *(
                    relative
                    for relative in existing_files
                    if relative.endswith("/" + referenced)
                ),
            }
            resolved = sorted(candidate for candidate in candidates if candidate in existing_files)
            if resolved:
                continue
            missing_path = Path(base, referenced).as_posix()
            issue = {
                "code": "missing_verification_target",
                "source": source,
                "missingPath": missing_path,
            }
            if issue not in issues:
                issues.append(issue)
            if len(issues) >= 256:
                break
        if len(issues) >= 256:
            break
    payload = {
        "schemaVersion": VERIFICATION_MAP_SCHEMA,
        "nodes": nodes,
        "edges": edges,
        "mappedFiles": node_paths,
        "versionContracts": version_contracts,
        "issues": issues,
        "stats": {
            "tests": len(test_files),
            "testCommands": len(commands),
            "ciWorkflows": len(workflow_files),
            "versionContracts": len(version_contracts),
            "edges": len(edges),
            "issues": len(issues),
            "truncated": (
                node_count > MAX_VERIFICATION_NODES
                or edge_limit_hit
                or len(issues) >= 256
            ),
        },
    }
    payload["graphDigest"] = _canonical_json_digest(payload)
    return payload


def generate_code_map(root: str | Path, *, force: bool = False) -> dict[str, Any]:
    project = _project_root(root)
    policy = _context_index_policy(project)
    policy_digest = _policy_digest(policy)
    out_dir = project / ".agentlas" / "code-map"
    json_path = out_dir / "project-map.json"
    md_path = out_dir / "project-map.md"
    seed_path = out_dir / "project-seed.json"
    cache_path = out_dir / ".cache.json"
    manifest_path = out_dir / "manifest.json"
    started = time.monotonic()
    deadline = started + MAX_CODE_SCAN_SECONDS
    all_files, list_stop, skipped_unsafe = _git_file_list(project, deadline)
    source = "git" if all_files is not None else "filesystem"
    fallback_reason: str | None = None
    if all_files is None:
        fallback_reason = list_stop
        all_files, fallback_stop, fallback_unsafe = _walk_file_list(project, deadline)
        # A failed Git probe is only the reason the filesystem fallback ran.
        # Once that fallback completes, its own stop state is authoritative.
        list_stop = fallback_stop
        skipped_unsafe += fallback_unsafe
    listed_relative_files = {
        path.relative_to(project).as_posix()
        for path in all_files
        if _safe_file(project, path)
        and _policy_allows(path.relative_to(project).as_posix(), policy)
    }
    local_test_files, local_test_stop, local_test_skipped_unsafe = (
        _walk_local_test_files(project, deadline, policy)
    )
    skipped_unsafe += local_test_skipped_unsafe
    if local_test_stop:
        list_stop = list_stop or local_test_stop
    local_test_relative_files = {
        path.relative_to(project).as_posix()
        for path in local_test_files
        if _safe_file(project, path)
    }
    local_test_code_files = {
        relative
        for relative in local_test_relative_files
        if Path(relative).suffix.lower() in CODE_EXTENSIONS
    }
    relative_files = sorted(listed_relative_files | local_test_relative_files)
    verification_test_code_files = sorted(
        relative
        for relative in relative_files
        if Path(relative).suffix.lower() in CODE_EXTENSIONS
        and (_is_test_path(relative) or relative in local_test_code_files)
    )
    source_code_candidates = [
        relative
        for relative in relative_files
        if Path(relative).suffix.lower() in CODE_EXTENSIONS
        and not _is_test_path(relative)
        and relative not in local_test_code_files
    ]
    code_files = source_code_candidates[:MAX_CODE_FILES]
    if len(source_code_candidates) > MAX_CODE_FILES:
        list_stop = list_stop or "code_file_count"
    verification_files = [
        relative
        for relative in relative_files
        if (
            _is_ci_workflow_path(relative)
            or _is_version_contract_path(relative)
            or relative in local_test_relative_files
        )
    ]
    fingerprint_files = relative_files
    fingerprints: dict[str, dict[str, int]] = {}
    fingerprint_failures = 0
    for relative in fingerprint_files:
        try:
            file_stat = os.stat(project / relative, follow_symlinks=False)
        except OSError:
            fingerprint_failures += 1
            continue
        fingerprints[relative] = {
            "mtimeNs": file_stat.st_mtime_ns,
            "ctimeNs": file_stat.st_ctime_ns,
            "size": file_stat.st_size,
        }
    fingerprint = _fingerprint_hash(fingerprints)
    snapshot_complete = False
    try:
        snapshot_id, content_hashes, snapshot_read_bytes = _content_snapshot(
            project,
            relative_files,
            policy,
        )
        snapshot_complete = True
    except OSError:
        snapshot_id, content_hashes, snapshot_read_bytes = "", {}, 0
        list_stop = list_stop or "snapshot_read_incomplete"

    cache = _read_json_object(cache_path)
    existing_map = _read_json_object(json_path)
    complete_listing = list_stop is None
    cache_current = (
        _code_map_binding_complete(project, existing_map, cache)
        and cache.get("snapshotId") == snapshot_id
        and existing_map.get("snapshotId") == snapshot_id
        and cache.get("policyDigest") == policy_digest
        and int(cache.get("candidateCodeFiles", -1)) == len(code_files)
        and int(cache.get("candidateMappedFiles", -1)) == len(fingerprints)
        and cache.get("completeListing") is True
        and cache.get("listingSource") == source
        and complete_listing
    )
    if json_path.exists() and md_path.exists() and seed_path.exists() and manifest_path.exists() and not force and cache_current:
        sitemap_warning = _merge_managed_sitemap_context(project, _read_json_object(json_path))
        return {
            "status": "existing",
            "path": ".agentlas/code-map/project-map.json",
            "created": [],
            "refresh": "fingerprint_current",
            "source": source,
            **({"fallbackReason": fallback_reason} if fallback_reason else {}),
            "stats": existing_map.get("stats") or {},
            "coverageComplete": True,
            "functionalSitemap": _functional_sitemap_summary(project),
            **({"warning": sitemap_warning} if sitemap_warning else {}),
        }
    if json_path.exists() and md_path.exists() and seed_path.exists() and not force and not complete_listing:
        sitemap_warning = _merge_managed_sitemap_context(project, _read_json_object(json_path))
        return {
            "status": "existing",
            "path": ".agentlas/code-map/project-map.json",
            "created": [],
            "refresh": "deferred",
            "budgetStop": list_stop,
            "source": source,
            **({"fallbackReason": fallback_reason} if fallback_reason else {}),
            "functionalSitemap": _functional_sitemap_summary(project),
            **({"warning": sitemap_warning} if sitemap_warning else {}),
        }

    file_symbols: dict[str, list[dict[str, Any]]] = {}
    definitions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    display_names: dict[str, str] = {}
    file_tokens: dict[str, set[str]] = {}
    token_counts: Counter[str] = Counter()
    by_extension: Counter[str] = Counter()
    skipped_large = 0
    skipped_unreadable = 0
    read_bytes = 0
    token_occurrences = 0
    scanned_files: list[str] = []
    file_texts: dict[str, str] = {}
    budget_stop = list_stop
    total_symbols = 0
    for relative in code_files:
        path = project / relative
        try:
            file_stat = os.stat(path, follow_symlinks=False)
            if not _safe_file(project, path):
                skipped_unsafe += 1
                continue
            if file_stat.st_size > MAX_CODE_FILE_BYTES:
                skipped_large += 1
                continue
            if time.monotonic() >= deadline:
                budget_stop = budget_stop or "scan_time"
                break
            if read_bytes + file_stat.st_size > MAX_CODE_TOTAL_READ_BYTES:
                budget_stop = budget_stop or "total_read_bytes"
                break
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped_unreadable += 1
            continue
        read_bytes += file_stat.st_size
        scanned_files.append(relative)
        file_texts[relative] = text
        symbols, symbols_truncated = _extract_symbols(text, MAX_TOTAL_SYMBOLS - total_symbols)
        total_symbols += len(symbols)
        if symbols_truncated:
            budget_stop = budget_stop or "symbol_count"
        if symbols:
            file_symbols[relative] = symbols
            for symbol in symbols:
                normalized = symbol["n"].lower()
                definitions[normalized].append({"f": relative, "l": symbol["l"]})
                display_names.setdefault(normalized, symbol["n"])
        tokens_in_file: set[str] = set()
        for match in TOKEN_PATTERN.finditer(text):
            if token_occurrences >= MAX_TOKEN_OCCURRENCES:
                budget_stop = budget_stop or "token_occurrences"
                break
            token = match.group(0).lower()
            if token in token_counts or len(token_counts) < MAX_UNIQUE_TOKENS:
                token_counts[token] += 1
                tokens_in_file.add(token)
            else:
                budget_stop = budget_stop or "unique_tokens"
            token_occurrences += 1
        file_tokens[relative] = tokens_in_file
        by_extension[Path(relative).suffix.lower()] += 1

    modules: list[dict[str, Any]] = []
    module_counts: Counter[str] = Counter()
    for relative in scanned_files:
        parts = Path(relative).parts
        module_counts[parts[0] if len(parts) > 1 else "."] += 1
    modules = [
        {
            "id": name,
            "path": name,
            "role": f"source module ({count} code files)",
            "codeFiles": count,
        }
        for name, count in sorted(module_counts.items(), key=lambda item: (-item[1], item[0]))[:50]
    ]
    entry_points = [
        {"path": relative, "why": "conventional entry point"}
        for relative in relative_files
        if Path(relative).name in ENTRY_NAMES
    ][:40]
    ref_index: dict[str, list[str]] = defaultdict(list)
    ref_count: Counter[str] = Counter()
    truncated_ref_symbols: set[str] = set()
    definition_keys = set(definitions)
    module_dependencies: Counter[tuple[str, str]] = Counter()
    for relative, tokens in file_tokens.items():
        source_module = Path(relative).parts[0] if len(Path(relative).parts) > 1 else "."
        for normalized in tokens.intersection(definition_keys):
            ref_count[normalized] += 1
            if len(ref_index[normalized]) < MAX_REF_FILES_PER_SYMBOL:
                ref_index[normalized].append(relative)
            else:
                truncated_ref_symbols.add(normalized)
            first_definition = definitions[normalized][0]
            target_file = str(first_definition["f"])
            target_module = Path(target_file).parts[0] if len(Path(target_file).parts) > 1 else "."
            if source_module != target_module:
                module_dependencies[(source_module, target_module)] += 1

    scanned_verification_test_files: list[str] = []
    verification_test_bytes = 0
    for relative in verification_test_code_files:
        path = project / relative
        try:
            file_stat = os.stat(path, follow_symlinks=False)
            if (
                not _safe_file(project, path)
                or file_stat.st_size > MAX_VERIFICATION_FILE_BYTES
            ):
                continue
            if time.monotonic() >= deadline:
                budget_stop = budget_stop or "local_test_scan_time"
                break
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        verification_test_bytes += file_stat.st_size
        scanned_verification_test_files.append(relative)
        file_texts[relative] = text
        tokens = {
            match.group(0).lower()
            for match in TOKEN_PATTERN.finditer(text)
        }
        for normalized in tokens.intersection(definition_keys):
            ref_count[normalized] += 1
            if len(ref_index[normalized]) < MAX_REF_FILES_PER_SYMBOL:
                ref_index[normalized].append(relative)
            else:
                truncated_ref_symbols.add(normalized)

    top_symbols: list[dict[str, Any]] = []
    for normalized, refs in ref_count.most_common():
        first = definitions[normalized][0]
        top_symbols.append(
            {
                "name": display_names.get(normalized, normalized),
                "key": normalized,
                "refs": max(0, refs - len(definitions[normalized])),
                "defAt": f"{first['f']}:{first['l']}",
            }
        )
        if len(top_symbols) >= 100:
            break
    module_edges = [
        {"from": source_module, "to": target_module, "weight": weight}
        for (source_module, target_module), weight in module_dependencies.most_common(100)
    ]
    all_scanned_files = sorted(set(scanned_files + scanned_verification_test_files))
    dependency_edges, dependency_edges_truncated = _exact_dependency_edges(
        scanned_files=all_scanned_files,
        file_texts=file_texts,
    )
    verification_graph = _verification_graph(
        project,
        relative_files=relative_files,
        scanned_files=all_scanned_files,
        test_files=scanned_verification_test_files,
        dependency_edges=dependency_edges,
    )

    generated_at = utc_now()
    scan_complete = (
        budget_stop is None
        and skipped_large == 0
        and skipped_unreadable == 0
        and fingerprint_failures == 0
        and snapshot_complete
        and not dependency_edges_truncated
        and len(scanned_files) == len(code_files)
        and len(scanned_verification_test_files) == len(verification_test_code_files)
    )
    ref_files_omitted = sum(
        max(0, int(ref_count.get(key) or 0) - len(ref_index.get(key) or []))
        for key in truncated_ref_symbols
    )
    project_root_hash = _project_root_hash(project)
    previous_roles = (
        existing_map.get("fileRoles")
        if isinstance(existing_map.get("fileRoles"), dict)
        else {}
    )
    previous_tombstones = (
        existing_map.get("tombstones")
        if isinstance(existing_map.get("tombstones"), dict)
        else {}
    )
    current_files = set(relative_files)
    tombstones = {
        str(path): dict(row) if isinstance(row, dict) else {"role": "unknown"}
        for path, row in previous_tombstones.items()
        if isinstance(path, str)
        and path not in current_files
        and not (project / path).exists()
    }
    for path, role in previous_roles.items():
        if (
            isinstance(path, str)
            and path not in current_files
            and not (project / path).exists()
        ):
            tombstones[path] = {
                "role": str(role or "unknown"),
                "resolution": "deleted",
            }
    project_map = {
        "schemaVersion": "agentlas.code-map.v2",
        "project": project.name,
        "projectRootHash": project_root_hash,
        "fingerprintHash": fingerprint,
        "snapshotId": snapshot_id,
        "policyDigest": policy_digest,
        "generatedAt": generated_at,
        "source": source,
        "stats": {
            "totalFiles": len(relative_files),
            "candidateCodeFiles": len(code_files),
            "candidateMappedFiles": len(fingerprint_files),
            "codeFiles": len(scanned_files),
            "symbols": len(definitions),
            "refIndexSymbols": len(ref_index),
            "refsEdges": sum(ref_count.values()),
            "entryPoints": len(entry_points),
            "skippedLarge": skipped_large,
            "skippedUnreadable": skipped_unreadable,
            "fingerprintFailures": fingerprint_failures,
            "snapshotReadBytes": snapshot_read_bytes,
            "snapshotComplete": snapshot_complete,
            "skippedUnsafe": skipped_unsafe,
            "bytesRead": read_bytes,
            "readByteLimit": MAX_CODE_TOTAL_READ_BYTES,
            "scanTimeLimitMs": int(MAX_CODE_SCAN_SECONDS * 1000),
            "budgetStop": budget_stop,
            "scanComplete": scan_complete,
            "refIndexTruncated": bool(truncated_ref_symbols),
            "refSymbolsTruncated": len(truncated_ref_symbols),
            "refFilesOmitted": ref_files_omitted,
            "outputTruncated": bool(truncated_ref_symbols),
            "coverageComplete": False,
            "incompleteReasons": [],
            "listingSource": source,
            "localTestFiles": len(local_test_code_files),
            "localVerificationFiles": len(local_test_relative_files),
            "verificationTestBytes": verification_test_bytes,
            "verificationGraphTruncated": verification_graph["stats"]["truncated"],
            "dependencyEdges": len(dependency_edges),
            "dependencyEdgesTruncated": dependency_edges_truncated,
            "fallbackReason": fallback_reason,
            "genMs": int((time.monotonic() - started) * 1000),
        },
        "modules": modules,
        "moduleEdges": module_edges,
        "entryPoints": entry_points,
        "topSymbols": top_symbols,
        "byExt": dict(by_extension.most_common(30)),
        "indexedFiles": scanned_files,
        "mappedFiles": sorted(
            set(relative_files)
        ),
        "fileRoles": {
            relative: (
                "test" if relative in verification_test_code_files else _file_role(relative)
            )
            for relative in relative_files
        },
        "tombstones": tombstones,
        "contentHashes": content_hashes,
        "fileSymbols": file_symbols,
        "defIndex": dict(definitions),
        "refIndex": dict(ref_index),
        "refCount": dict(ref_count),
        "dependencyEdges": dependency_edges,
        "verificationGraph": verification_graph,
    }
    markdown = "\n".join(
        [
            f"# Code map — {project.name}",
            "",
            f"Generated {generated_at}; {project_map['stats']['codeFiles']} code files; {project_map['stats']['symbols']} symbols.",
            "",
            "## Entry points",
            *([f"- `{item['path']}` — {item['why']}" for item in entry_points[:20]] or ["- None detected yet."]),
            "",
            "## Central symbols",
            *([f"- `{item['name']}` — {item['refs']} refs · {item['defAt']}" for item in top_symbols[:20]] or ["- None detected yet."]),
            "",
            "## Modules",
            *([f"- `{item['path']}` — {item['codeFiles']} code files" for item in modules[:30]] or ["- None detected yet."]),
            "",
        ]
    )
    project_map["stats"]["outputLimitBytes"] = MAX_CODE_MAP_BYTES
    serialized_map = ""
    output_bytes = 0
    for _ in range(3):
        serialized_map, output_bytes = _bounded_project_map(project_map)
        incomplete_reasons = _code_map_incomplete_reasons(project_map["stats"])
        coverage_complete = not incomplete_reasons
        if (
            project_map["stats"].get("coverageComplete") is coverage_complete
            and project_map["stats"].get("incompleteReasons") == incomplete_reasons
        ):
            break
        project_map["stats"]["coverageComplete"] = coverage_complete
        project_map["stats"]["incompleteReasons"] = incomplete_reasons
    serialized_map, output_bytes = _bounded_project_map(project_map)
    coverage_complete = project_map["stats"].get("coverageComplete") is True
    map_payload_digest = _canonical_json_digest(project_map)
    existed = {path for path in (json_path, md_path, seed_path, cache_path, manifest_path) if path.exists()}
    _ensure_dir(out_dir, 0o700)
    _atomic_write(json_path, serialized_map)
    _atomic_write(md_path, markdown)
    _atomic_write(
        seed_path,
        json.dumps(
            {
                "schemaVersion": project_map["schemaVersion"],
                "project": project_map["project"],
                "generatedAt": project_map["generatedAt"],
                "fingerprintHash": project_map["fingerprintHash"],
                "stats": project_map["stats"],
                "modules": modules,
                "moduleEdges": module_edges[:50],
                "entryPoints": entry_points,
                "topSymbols": top_symbols,
                "verificationGraph": {
                    "schemaVersion": verification_graph["schemaVersion"],
                    "graphDigest": verification_graph["graphDigest"],
                    "stats": verification_graph["stats"],
                    "versionContracts": verification_graph["versionContracts"][:20],
                },
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n",
    )
    _atomic_write(
        manifest_path,
        json.dumps(
            {
                "schemaVersion": CODE_MAP_MANIFEST_SCHEMA,
                "project": project.name,
                "projectRootHash": project_root_hash,
                "snapshotId": snapshot_id,
                "policyDigest": policy_digest,
                "complete": coverage_complete,
                "compatibilityMap": {
                    "path": "project-map.json",
                    "schemaVersion": project_map["schemaVersion"],
                    "digest": map_payload_digest,
                },
                "indexes": {
                    "inventoryCount": len(relative_files),
                    "dependencyEdgeCount": len(dependency_edges),
                    "verificationGraphDigest": verification_graph["graphDigest"],
                    "tombstoneCount": len(tombstones),
                },
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
    )
    _atomic_write(
        cache_path,
        json.dumps(
            {
                "schemaVersion": CODE_MAP_CACHE_SCHEMA,
                "policyVersion": CODE_MAP_POLICY_VERSION,
                "generatedAt": generated_at,
                "fingerprintHash": fingerprint,
                "snapshotId": snapshot_id,
                "policyDigest": policy_digest,
                "candidateCodeFiles": len(code_files),
                "candidateMappedFiles": len(fingerprints),
                "completeListing": complete_listing,
                "completeMap": coverage_complete,
                "listingSource": source,
                "projectRootHash": project_root_hash,
                "mapPayloadDigest": map_payload_digest,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    sitemap_warning = _merge_managed_sitemap_context(project, project_map)
    return {
        "status": "refreshed" if json_path in existed else "generated",
        "path": ".agentlas/code-map/project-map.json",
        "created": [
            path.relative_to(project).as_posix()
            for path in (json_path, md_path, seed_path, cache_path, manifest_path)
            if path not in existed
        ],
        "stats": project_map["stats"],
        "coverageComplete": coverage_complete,
        "source": source,
        **({"fallbackReason": fallback_reason} if fallback_reason else {}),
        "outputBytes": output_bytes,
        "functionalSitemap": _functional_sitemap_summary(project),
        **({"warning": sitemap_warning} if sitemap_warning else {}),
    }


def _tracked_sensitive_paths(root: Path) -> tuple[list[str], bool]:
    raw_output, stop = _run_bounded_stdout(
        ["git", "-C", str(root), "ls-files", "-z", ".agentlas", ".env", ".env.local", "signing", "credentials"],
        deadline=time.monotonic() + 5.0,
        max_bytes=MAX_TRACKED_PATH_BYTES,
    )
    if raw_output is None:
        return [], False
    tracked = [os.fsdecode(item) for item in _complete_nul_items(raw_output)]
    private_prefixes = (
        ".agentlas/",
        ".env",
        "signing/",
        "credentials/",
    )
    sensitive = sorted(path for path in tracked if path.startswith(private_prefixes))
    complete = stop is None and len(sensitive) <= MAX_TRACKED_PATHS
    return sensitive[:MAX_TRACKED_PATHS], complete


def project_status(project: str | Path) -> dict[str, Any]:
    root = _project_root(project)
    agentlas = root / ".agentlas"
    required = (
        "project-soul-memory.md",
        "sitemap.json",
        "context-map.json",
        "memory-map.json",
        "memory-tickets.jsonl",
        "vault-references.json",
        "activation.json",
        "code-map/project-map.json",
        "code-map/project-map.md",
        "code-map/project-seed.json",
        "code-map/.cache.json",
        "ontology-runtime.json",
        "ontology-runtime.sqlite",
        "career-graph.json",
        "career-graph.sqlite",
    )
    missing = [f".agentlas/{relative}" for relative in required if not (agentlas / relative).exists()]
    privacy_warnings: list[str] = []
    try:
        gitignore_text = _read_bounded_regular_text(root / ".gitignore", MAX_GITIGNORE_BYTES)
    except ValueError as exc:
        gitignore_text = ""
        warning = str(exc)
        privacy_warnings.append(
            warning
            if warning in {
                "unsafe_gitignore_file",
                "gitignore_too_large",
                "gitignore_changed_during_bootstrap",
                "gitignore_not_utf8",
            }
            else "gitignore_unreadable"
        )
    permission_issues: list[str] = []
    if agentlas.exists():
        permission_paths = [agentlas]
        for index, path in enumerate(agentlas.rglob("*"), start=1):
            if index > MAX_PERMISSION_PATHS:
                privacy_warnings.append("permission_scan_truncated")
                break
            permission_paths.append(path)
        for path in permission_paths:
            try:
                if path.is_symlink():
                    permission_issues.append(path.relative_to(root).as_posix() + ":symlink")
                elif POSIX_PRIVATE_MODE_ENFORCEMENT and (path.is_file() or path.is_dir()):
                    if stat.S_IMODE(path.stat().st_mode) & 0o077:
                        permission_issues.append(path.relative_to(root).as_posix() + ":group_or_world_access")
            except OSError:
                permission_issues.append(path.relative_to(root).as_posix() + ":stat_failed")
    privacy_block = MANAGED_GITIGNORE_START in gitignore_text and MANAGED_GITIGNORE_END in gitignore_text
    tracked_sensitive, tracked_scan_complete = _tracked_sensitive_paths(root)
    if not tracked_scan_complete:
        privacy_warnings.append("tracked_sensitive_scan_incomplete")
    code_map_payload = _read_json_object(agentlas / "code-map" / "project-map.json")
    code_map_cache = _read_json_object(agentlas / "code-map" / ".cache.json")
    code_map_complete = _code_map_binding_complete(root, code_map_payload, code_map_cache)
    if missing:
        status = "incomplete"
    elif not privacy_block or permission_issues or tracked_sensitive or privacy_warnings:
        status = "privacy_warning"
    else:
        status = "active"
    code_map_incomplete_reasons = (
        []
        if code_map_complete
        else _code_map_incomplete_reasons(
            code_map_payload.get("stats")
            if isinstance(code_map_payload.get("stats"), dict)
            else {}
        )
    )
    if not code_map_complete and not code_map_incomplete_reasons:
        code_map_incomplete_reasons = ["integrity_or_cache_binding"]
    return {
        "schemaVersion": BOOTSTRAP_SCHEMA,
        "status": status,
        "missing": missing,
        "privacyBlockInstalled": privacy_block,
        "privateModeCompliant": not permission_issues,
        "permissionIssues": permission_issues,
        "trackedSensitivePaths": tracked_sensitive,
        "trackedSensitiveScanComplete": tracked_scan_complete,
        "codeMapComplete": code_map_complete,
        "codeMapIncompleteReasons": code_map_incomplete_reasons,
        "privacyWarnings": privacy_warnings,
    }


def ensure_project(project: str | Path, *, reason: str = "host-first-contact", force_code_map: bool = False) -> dict[str, Any]:
    root = _project_root(project)
    with _project_lock(root):
        gitignore_changed, gitignore_path = _ensure_gitignore(root)
        seed_created, seed_warnings = _seed_project_files(root)
        migrated, migration_warnings = _apply_additive_memory_migrations(root)
        if migrated:
            seed_created.extend(f"migrated:{name}" for name in migrated)
        seed_warnings.extend(migration_warnings)
        graph_created, graph_warnings = _ensure_graph_runtimes(root)
        code_map = generate_code_map(root, force=force_code_map)
        if code_map.get("warning"):
            seed_warnings.append(str(code_map["warning"]))
        # The seed above writes context-map.json with an empty node list and a
        # note asking a human to fill it. Nothing ever did, on any machine, so
        # the declared half of every context slice was boilerplate. Derive it
        # from the ledgers this project already keeps, right after the seed.
        from .context_map_authoring import refresh_declared_context

        declared_context = refresh_declared_context(root)
        permission_warnings = _harden_private_tree(root)
        status = project_status(root)
    created = list(dict.fromkeys(seed_created + graph_created + list(code_map.get("created") or [])))
    return {
        **status,
        "action": "project_bootstrap",
        "reason": reason,
        "created": created,
        "gitignore": {"path": gitignore_path, "changed": gitignore_changed},
        "codeMap": code_map,
        "declaredContext": declared_context,
        "warnings": list(dict.fromkeys(seed_warnings + graph_warnings + permission_warnings)),
        "mergeOnly": True,
        "overwritten": [],
    }


def _redact_automatic_receipt(result: dict[str, Any]) -> dict[str, Any]:
    code_map = result.get("codeMap") if isinstance(result.get("codeMap"), dict) else {}
    return {
        "schemaVersion": result.get("schemaVersion", BOOTSTRAP_SCHEMA),
        "action": "project_bootstrap",
        "status": result.get("status"),
        "reason": result.get("reason"),
        "createdCount": len(result.get("created") or []),
        "missingCount": len(result.get("missing") or []),
        "privacyBlockInstalled": bool(result.get("privacyBlockInstalled")),
        "privateModeCompliant": bool(result.get("privateModeCompliant")),
        "permissionIssueCount": len(result.get("permissionIssues") or []),
        "trackedSensitivePathCount": len(result.get("trackedSensitivePaths") or []),
        "gitignoreChanged": bool((result.get("gitignore") or {}).get("changed")),
        "codeMapComplete": result.get("codeMapComplete") is True,
        "codeMapIncompleteReasons": list(result.get("codeMapIncompleteReasons") or []),
        "codeMap": {
            "status": code_map.get("status"),
            "stats": code_map.get("stats") or {},
            "refresh": code_map.get("refresh"),
            "budgetStop": code_map.get("budgetStop"),
            "coverageComplete": code_map.get("coverageComplete"),
        },
        "warningCount": len(result.get("warnings") or []),
        "mergeOnly": True,
        "writeAttempted": True,
    }


def maybe_ensure_project(
    project: str | Path,
    *,
    reason: str,
    enabled: bool = False,
    trusted_target: bool = False,
    allow_unmarked_current_root: bool = False,
) -> dict[str, Any]:
    """Gate host first-contact writes behind explicit host consent.

    Workload/tool arguments never enable this function on their own. Trusted
    hosts opt in with a CLI flag or process environment. Automatic mode
    requires a workspace marker, except for the exact MCP process cwd when the
    host starts the plugin server with its dedicated bootstrap gate enabled.
    """

    if not enabled:
        return {
            "action": "project_bootstrap",
            "status": "disabled",
            "reason": reason,
            "writeAttempted": False,
        }
    try:
        root = _project_root(project)
    except (OSError, ValueError) as exc:
        return {
            "action": "project_bootstrap",
            "status": "skipped",
            "reason": reason,
            "detail": _redacted_error(exc),
            "writeAttempted": False,
        }
    current_root_is_host_workspace = False
    if allow_unmarked_current_root:
        try:
            current_root_is_host_workspace = root == Path.cwd().resolve()
        except OSError:
            current_root_is_host_workspace = False
    if not _project_marker_present(root) and not current_root_is_host_workspace:
        return {
            "action": "project_bootstrap",
            "status": "skipped",
            "reason": reason,
            "detail": "workspace_marker_missing",
            "writeAttempted": False,
        }
    if not trusted_target and not _within_auto_boundary(root):
        return {
            "action": "project_bootstrap",
            "status": "skipped",
            "reason": reason,
            "detail": "outside_host_approved_roots",
            "writeAttempted": False,
        }
    try:
        result = ensure_project(root, reason=reason)
    except (OSError, TimeoutError, ValueError) as exc:
        return {
            "action": "project_bootstrap",
            "status": "skipped",
            "reason": reason,
            "detail": _redacted_error(exc),
            "writeAttempted": True,
        }
    result["writeAttempted"] = True
    return result if trusted_target else _redact_automatic_receipt(result)
