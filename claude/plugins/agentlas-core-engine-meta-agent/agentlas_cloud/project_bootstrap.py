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
import re
import subprocess
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

PRIVACY_PATTERNS = (
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


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _project_root(project: str | Path) -> Path:
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"project directory does not exist: {root}")
    unsafe = {Path.home().resolve(), Path(root.anchor).resolve()}
    if root in unsafe:
        raise ValueError(f"refusing to initialize unsafe project root: {root}")
    return root


def _template_root() -> Path | None:
    candidates = (
        Path(__file__).resolve().parent.parent / "templates",
        Path(os.environ.get("HEPHAESTUS_RUNTIME_ROOT", "")) / "templates",
    )
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


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, path)


def _write_missing(path: Path, content: str, created: list[str], root: Path) -> None:
    if path.exists():
        return
    _atomic_write(path, content)
    created.append(path.relative_to(root).as_posix())


@contextmanager
def _project_lock(root: Path, timeout_seconds: float = 15.0) -> Iterable[None]:
    agentlas = root / ".agentlas"
    agentlas.mkdir(parents=True, exist_ok=True)
    lock = agentlas / ".project-bootstrap.lock"
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.write(descriptor, f"{os.getpid()}\n".encode("ascii"))
            os.close(descriptor)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > 120:
                    lock.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for project bootstrap lock: {lock}")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def _managed_gitignore_block() -> str:
    return "\n".join((MANAGED_GITIGNORE_START, *PRIVACY_PATTERNS, MANAGED_GITIGNORE_END))


def _ensure_gitignore(root: Path) -> tuple[bool, str]:
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    block = _managed_gitignore_block()
    if MANAGED_GITIGNORE_START in existing and MANAGED_GITIGNORE_END in existing:
        start = existing.index(MANAGED_GITIGNORE_START)
        end = existing.index(MANAGED_GITIGNORE_END, start) + len(MANAGED_GITIGNORE_END)
        updated = existing[:start] + block + existing[end:]
    else:
        prefix = existing.rstrip("\n")
        updated = f"{prefix}\n\n{block}\n" if prefix else f"{block}\n"
    if updated == existing:
        return False, path.as_posix()
    _atomic_write(path, updated)
    return True, path.as_posix()


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
        with closing(runtime.connect()):
            pass
    except Exception as exc:
        warnings.append(f"career_graph_setup_failed:{type(exc).__name__}")
    after = {path for path in (root / ".agentlas").rglob("*") if path.is_file()}
    created.extend(sorted(path.relative_to(root).as_posix() for path in after - before))
    return created, warnings


def _git_file_list(root: Path) -> list[Path] | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
            check=False,
            capture_output=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    files: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        relative = Path(os.fsdecode(raw))
        if any(part in SKIP_DIRS for part in relative.parts):
            continue
        path = root / relative
        if path.is_file():
            files.append(path)
    return files


def _walk_file_list(root: Path) -> list[Path]:
    files: list[Path] = []
    for current, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        current_path = Path(current)
        for name in filenames:
            files.append(current_path / name)
            if len(files) >= MAX_CODE_FILES * 3:
                return files
    return files


def _extract_symbols(text: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in SYMBOL_PATTERNS:
            match = pattern.search(line)
            if match:
                symbols.append({"n": match.group(1), "k": kind, "l": line_number})
                break
    return symbols[:500]


def generate_code_map(root: str | Path, *, force: bool = False) -> dict[str, Any]:
    project = _project_root(root)
    out_dir = project / ".agentlas" / "code-map"
    json_path = out_dir / "project-map.json"
    md_path = out_dir / "project-map.md"
    cache_path = out_dir / ".cache.json"
    if json_path.exists() and md_path.exists() and not force:
        return {"status": "existing", "path": str(json_path), "created": []}

    started = time.monotonic()
    all_files = _git_file_list(project)
    source = "git" if all_files is not None else "filesystem"
    all_files = all_files if all_files is not None else _walk_file_list(project)
    relative_files = sorted(
        path.relative_to(project).as_posix()
        for path in all_files
        if path.is_file() and not any(part in SKIP_DIRS for part in path.relative_to(project).parts)
    )
    code_files = [relative for relative in relative_files if Path(relative).suffix.lower() in CODE_EXTENSIONS][
        :MAX_CODE_FILES
    ]
    file_symbols: dict[str, list[dict[str, Any]]] = {}
    definitions: dict[str, list[dict[str, Any]]] = defaultdict(list)
    token_counts: Counter[str] = Counter()
    by_extension: Counter[str] = Counter()
    skipped_large = 0
    cache_files: dict[str, dict[str, Any]] = {}
    for relative in code_files:
        path = project / relative
        try:
            stat = path.stat()
            if stat.st_size > MAX_CODE_FILE_BYTES:
                skipped_large += 1
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        symbols = _extract_symbols(text)
        if symbols:
            file_symbols[relative] = symbols
            for symbol in symbols:
                definitions[symbol["n"].lower()].append({"f": relative, "l": symbol["l"]})
        token_counts.update(token.lower() for token in re.findall(r"[A-Za-z_$][\w$]{2,}", text))
        by_extension[Path(relative).suffix.lower()] += 1
        cache_files[relative] = {"mtimeNs": stat.st_mtime_ns, "size": stat.st_size}

    modules: list[dict[str, Any]] = []
    module_counts: Counter[str] = Counter()
    for relative in code_files:
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
            "codeFiles": len(code_files) - skipped_large,
            "symbols": len(definitions),
            "entryPoints": len(entry_points),
            "skippedLarge": skipped_large,
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
    out_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write(json_path, json.dumps(project_map, ensure_ascii=False, indent=2) + "\n")
    _atomic_write(md_path, markdown)
    _atomic_write(
        cache_path,
        json.dumps(
            {"schemaVersion": "agentlas.code-map-cache.v1", "generatedAt": generated_at, "files": cache_files},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )
    return {
        "status": "generated",
        "path": str(json_path),
        "created": [
            json_path.relative_to(project).as_posix(),
            md_path.relative_to(project).as_posix(),
            cache_path.relative_to(project).as_posix(),
        ],
        "stats": project_map["stats"],
    }


def _tracked_sensitive_paths(root: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", ".agentlas", ".env", ".env.local", "signing", "credentials"],
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    tracked = [os.fsdecode(item) for item in result.stdout.split(b"\0") if item]
    private_prefixes = (
        ".agentlas/project-soul-memory.md",
        ".agentlas/memory-",
        ".agentlas/vault-",
        ".agentlas/code-map/",
        ".agentlas/ontology-",
        ".agentlas/career-graph",
        ".agentlas/stormbreaker/",
        ".env",
        "signing/",
        "credentials/",
    )
    return sorted(path for path in tracked if path.startswith(private_prefixes))


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
    gitignore = root / ".gitignore"
    gitignore_text = gitignore.read_text(encoding="utf-8", errors="replace") if gitignore.exists() else ""
    return {
        "schemaVersion": BOOTSTRAP_SCHEMA,
        "status": "active" if not missing else "incomplete",
        "projectRoot": str(root),
        "missing": missing,
        "privacyBlockInstalled": MANAGED_GITIGNORE_START in gitignore_text and MANAGED_GITIGNORE_END in gitignore_text,
        "trackedSensitivePaths": _tracked_sensitive_paths(root),
    }


def ensure_project(project: str | Path, *, reason: str = "host-first-contact", force_code_map: bool = False) -> dict[str, Any]:
    root = _project_root(project)
    with _project_lock(root):
        gitignore_changed, gitignore_path = _ensure_gitignore(root)
        seed_created, seed_warnings = _seed_project_files(root)
        graph_created, graph_warnings = _ensure_graph_runtimes(root)
        code_map = generate_code_map(root, force=force_code_map)
        status = project_status(root)
    created = list(dict.fromkeys(seed_created + graph_created + list(code_map.get("created") or [])))
    return {
        **status,
        "action": "project_bootstrap",
        "reason": reason,
        "created": created,
        "gitignore": {"path": gitignore_path, "changed": gitignore_changed},
        "codeMap": code_map,
        "warnings": list(dict.fromkeys(seed_warnings + graph_warnings)),
        "mergeOnly": True,
        "overwritten": [],
    }
