"""Canonical first-contact project bootstrap for every Agentlas host.

Desktop, Terminal, Codex, Claude Code, and MCP adapters call this module instead
of maintaining host-local copies of the project memory architecture.  The
bootstrap is deliberately merge-only: it creates missing files, never replaces
user content, and installs a managed privacy block before generating local
memory or indexes.
"""

from __future__ import annotations

import hashlib
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
from typing import Any, Iterable


BOOTSTRAP_SCHEMA = "agentlas.project-bootstrap.v1"
MANAGED_GITIGNORE_START = "# >>> agentlas local project state >>>"
MANAGED_GITIGNORE_END = "# <<< agentlas local project state <<<"
MAX_CODE_FILES = 12_000
MAX_CODE_FILE_BYTES = 1_500_000
MAX_CODE_TOTAL_READ_BYTES = 32 * 1024 * 1024
MAX_CODE_SCAN_SECONDS = 12.0
MAX_CODE_MAP_BYTES = 4 * 1024 * 1024
MAX_GIT_FILE_LIST_BYTES = 8 * 1024 * 1024
MAX_GITIGNORE_BYTES = 1024 * 1024
MAX_TRACKED_PATH_BYTES = 1024 * 1024
MAX_TRACKED_PATHS = 10_000
MAX_PERMISSION_PATHS = 20_000
MAX_DISCOVERED_FILES = MAX_CODE_FILES * 3
MAX_SYMBOLS_PER_FILE = 200
MAX_TOTAL_SYMBOLS = 20_000
MAX_UNIQUE_TOKENS = 50_000
MAX_TOKEN_OCCURRENCES = 2_000_000
POSIX_PRIVATE_MODE_ENFORCEMENT = os.name != "nt"
AUTO_BOOTSTRAP_ENV = "AGENTLAS_PROJECT_BOOTSTRAP_AUTO"
MCP_AUTO_BOOTSTRAP_ENV = "AGENTLAS_MCP_PROJECT_BOOTSTRAP_AUTO"
AUTO_ALLOWED_ROOTS_ENV = "AGENTLAS_PROJECT_BOOTSTRAP_ALLOWED_ROOTS"
CODE_MAP_CACHE_SCHEMA = "agentlas.code-map-cache.v2"
CODE_MAP_POLICY_VERSION = "bounded-scan.v3"

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
    ".agentlas/super-ontology-*",
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
    ".cpp": "cpp",
    ".cs": "csharp",
    ".css": "css",
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
    ".mm": "objective-cpp",
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

SKIP_DIRS = {
    ".agentlas",
    ".git",
    ".hg",
    ".svn",
    ".next",
    ".nuxt",
    ".pytest_cache",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
}

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

    template_root = _template_root()
    if template_root:
        for template in sorted(template_root.glob("super-ontology-*.tpl")):
            relative = ".agentlas/" + template.name.removesuffix(".tpl")
            rendered = _render_template(template.name, replacements)
            if rendered is not None:
                _write_missing(root / relative, rendered, created, root)
    else:
        warnings.append("template_root_missing:super_ontology_not_seeded")
    return created, warnings


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
        if any(part in SKIP_DIRS or part == ".." for part in relative.parts):
            return False
        if path.is_symlink():
            return False
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
        return stat.S_ISREG(os.stat(path, follow_symlinks=False).st_mode)
    except (OSError, RuntimeError, ValueError):
        return False


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
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        current_path = Path(current)
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


def _extract_symbols(text: str, limit: int) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in SYMBOL_PATTERNS:
            match = pattern.search(line)
            if match:
                symbols.append({"n": match.group(1), "k": kind, "l": line_number})
                break
        if len(symbols) >= min(MAX_SYMBOLS_PER_FILE, max(0, limit)):
            break
    return symbols


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
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _bounded_project_map(project_map: dict[str, Any]) -> tuple[str, int]:
    raw = json.dumps(project_map, ensure_ascii=False, indent=2) + "\n"
    original_files = len(project_map.get("fileSymbols") or {})
    while len(raw.encode("utf-8")) > MAX_CODE_MAP_BYTES and project_map.get("fileSymbols"):
        items = list(project_map["fileSymbols"].items())
        project_map["fileSymbols"] = dict(items[: max(0, len(items) // 2)])
        project_map["stats"]["outputTruncated"] = True
        project_map["stats"]["fileSymbolFilesOmitted"] = original_files - len(project_map["fileSymbols"])
        raw = json.dumps(project_map, ensure_ascii=False, indent=2) + "\n"
    if len(raw.encode("utf-8")) > MAX_CODE_MAP_BYTES:
        raise OSError("code_map_output_budget_exceeded")
    return raw, len(raw.encode("utf-8"))


def generate_code_map(root: str | Path, *, force: bool = False) -> dict[str, Any]:
    project = _project_root(root)
    out_dir = project / ".agentlas" / "code-map"
    json_path = out_dir / "project-map.json"
    md_path = out_dir / "project-map.md"
    cache_path = out_dir / ".cache.json"
    started = time.monotonic()
    deadline = started + MAX_CODE_SCAN_SECONDS
    all_files, list_stop, skipped_unsafe = _git_file_list(project, deadline)
    source = "git" if all_files is not None else "filesystem"
    if all_files is None:
        all_files, fallback_stop, fallback_unsafe = _walk_file_list(project, deadline)
        list_stop = list_stop or fallback_stop
        skipped_unsafe += fallback_unsafe
    relative_files = sorted(
        {path.relative_to(project).as_posix()
        for path in all_files
        if _safe_file(project, path)}
    )
    code_files = [relative for relative in relative_files if Path(relative).suffix.lower() in CODE_EXTENSIONS][
        :MAX_CODE_FILES
    ]
    if len([relative for relative in relative_files if Path(relative).suffix.lower() in CODE_EXTENSIONS]) > MAX_CODE_FILES:
        list_stop = list_stop or "code_file_count"
    fingerprints: dict[str, dict[str, int]] = {}
    for relative in code_files:
        try:
            file_stat = os.stat(project / relative, follow_symlinks=False)
        except OSError:
            continue
        fingerprints[relative] = {
            "mtimeNs": file_stat.st_mtime_ns,
            "ctimeNs": file_stat.st_ctime_ns,
            "size": file_stat.st_size,
        }
    fingerprint = _fingerprint_hash(fingerprints)

    cache = _read_json_object(cache_path)
    complete_listing = list_stop is None
    cache_current = (
        cache.get("schemaVersion") == CODE_MAP_CACHE_SCHEMA
        and cache.get("policyVersion") == CODE_MAP_POLICY_VERSION
        and cache.get("fingerprintHash") == fingerprint
        and int(cache.get("candidateCodeFiles") or -1) == len(fingerprints)
        and cache.get("completeListing") is True
        and complete_listing
    )
    if json_path.exists() and md_path.exists() and not force and cache_current:
        return {
            "status": "existing",
            "path": ".agentlas/code-map/project-map.json",
            "created": [],
            "refresh": "fingerprint_current",
        }
    if json_path.exists() and md_path.exists() and not force and not complete_listing:
        return {
            "status": "existing",
            "path": ".agentlas/code-map/project-map.json",
            "created": [],
            "refresh": "deferred",
            "budgetStop": list_stop,
        }

    file_symbols: dict[str, list[dict[str, Any]]] = {}
    definitions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    token_counts: Counter[str] = Counter()
    by_extension: Counter[str] = Counter()
    skipped_large = 0
    read_bytes = 0
    token_occurrences = 0
    scanned_files: list[str] = []
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
            continue
        read_bytes += file_stat.st_size
        scanned_files.append(relative)
        symbols = _extract_symbols(text, MAX_TOTAL_SYMBOLS - total_symbols)
        total_symbols += len(symbols)
        if symbols:
            file_symbols[relative] = symbols
            for symbol in symbols:
                definitions[symbol["n"].lower()].append({"f": relative, "l": symbol["l"]})
        for match in TOKEN_PATTERN.finditer(text):
            if token_occurrences >= MAX_TOKEN_OCCURRENCES:
                budget_stop = budget_stop or "token_occurrences"
                break
            token = match.group(0).lower()
            if token in token_counts or len(token_counts) < MAX_UNIQUE_TOKENS:
                token_counts[token] += 1
            token_occurrences += 1
        by_extension[Path(relative).suffix.lower()] += 1

    modules: list[dict[str, Any]] = []
    module_counts: Counter[str] = Counter()
    for relative in scanned_files:
        parts = Path(relative).parts
        module_counts[parts[0] if len(parts) > 1 else "."] += 1
    modules = [
        {"path": name, "codeFiles": count}
        for name, count in sorted(module_counts.items(), key=lambda item: (-item[1], item[0]))[:50]
    ]
    entry_points = [
        {"path": relative, "why": "conventional entry point"}
        for relative in relative_files
        if Path(relative).name in ENTRY_NAMES
    ][:40]
    top_symbols: list[dict[str, Any]] = []
    for normalized, refs in token_counts.most_common():
        defs = definitions.get(normalized)
        if not defs:
            continue
        first = defs[0]
        display = next(
            symbol["n"]
            for symbol in file_symbols.get(first["f"], [])
            if symbol["n"].lower() == normalized
        )
        top_symbols.append(
            {"name": display, "key": normalized, "refs": max(0, refs - len(defs)), "defAt": f"{first['f']}:{first['l']}"}
        )
        if len(top_symbols) >= 100:
            break

    generated_at = utc_now()
    project_map = {
        "schemaVersion": "agentlas.code-map.v1",
        "project": project.name,
        "projectRootHash": "sha256:" + hashlib.sha256(str(project).encode("utf-8")).hexdigest(),
        "generatedAt": generated_at,
        "source": source,
        "stats": {
            "totalFiles": len(relative_files),
            "candidateCodeFiles": len(code_files),
            "codeFiles": len(scanned_files),
            "symbols": len(definitions),
            "entryPoints": len(entry_points),
            "skippedLarge": skipped_large,
            "skippedUnsafe": skipped_unsafe,
            "bytesRead": read_bytes,
            "readByteLimit": MAX_CODE_TOTAL_READ_BYTES,
            "scanTimeLimitMs": int(MAX_CODE_SCAN_SECONDS * 1000),
            "budgetStop": budget_stop,
            "outputTruncated": False,
            "genMs": int((time.monotonic() - started) * 1000),
        },
        "modules": modules,
        "entryPoints": entry_points,
        "topSymbols": top_symbols,
        "byExt": dict(by_extension.most_common(30)),
        "fileSymbols": file_symbols,
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
    serialized_map, output_bytes = _bounded_project_map(project_map)
    existed = {path for path in (json_path, md_path, cache_path) if path.exists()}
    _ensure_dir(out_dir, 0o700)
    _atomic_write(json_path, serialized_map)
    _atomic_write(md_path, markdown)
    _atomic_write(
        cache_path,
        json.dumps(
            {
                "schemaVersion": CODE_MAP_CACHE_SCHEMA,
                "policyVersion": CODE_MAP_POLICY_VERSION,
                "generatedAt": generated_at,
                "fingerprintHash": fingerprint,
                "candidateCodeFiles": len(fingerprints),
                "completeListing": complete_listing,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    return {
        "status": "refreshed" if json_path in existed else "generated",
        "path": ".agentlas/code-map/project-map.json",
        "created": [
            path.relative_to(project).as_posix()
            for path in (json_path, md_path, cache_path)
            if path not in existed
        ],
        "stats": project_map["stats"],
        "outputBytes": output_bytes,
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
        "memory-map.json",
        "memory-tickets.jsonl",
        "vault-references.json",
        "activation.json",
        "code-map/project-map.json",
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
    if missing:
        status = "incomplete"
    elif not privacy_block or permission_issues or tracked_sensitive or privacy_warnings:
        status = "privacy_warning"
    else:
        status = "active"
    return {
        "schemaVersion": BOOTSTRAP_SCHEMA,
        "status": status,
        "missing": missing,
        "privacyBlockInstalled": privacy_block,
        "privateModeCompliant": not permission_issues,
        "permissionIssues": permission_issues,
        "trackedSensitivePaths": tracked_sensitive,
        "trackedSensitiveScanComplete": tracked_scan_complete,
        "privacyWarnings": privacy_warnings,
    }


def ensure_project(project: str | Path, *, reason: str = "host-first-contact", force_code_map: bool = False) -> dict[str, Any]:
    root = _project_root(project)
    with _project_lock(root):
        gitignore_changed, gitignore_path = _ensure_gitignore(root)
        seed_created, seed_warnings = _seed_project_files(root)
        graph_created, graph_warnings = _ensure_graph_runtimes(root)
        code_map = generate_code_map(root, force=force_code_map)
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
        "codeMap": {
            "status": code_map.get("status"),
            "stats": code_map.get("stats") or {},
            "refresh": code_map.get("refresh"),
            "budgetStop": code_map.get("budgetStop"),
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
