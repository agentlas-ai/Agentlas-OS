"""File-level import resolution for the code map, one resolver per language family.

The map's dependency edges say "file A imports file B". They are what ``impact`` follows, so a
language whose imports are not read is a language where "what breaks if I change this" answers
with the file itself. Only relative Python and JavaScript/TypeScript imports used to be read, so
alias imports (``@/...``, ``package:``) and every other language produced no edges at all.

Only an edge that points at exactly one real file is recorded. A name that could be an external
package, a namespace or a symbol creates nothing: a missing edge is visible, a wrong one is not.
No parser and no native dependency; every rule works on the paths already in the map.
"""

from __future__ import annotations

import json
import posixpath
import re
import sys
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Iterable, Mapping

CONFIG_BASENAME = re.compile(
    r"^(?:(?:tsconfig|jsconfig)(?:\.[\w.-]+)?\.json|pubspec\.yaml|go\.mod|Cargo\.toml)$"
)
MAX_CONFIG_FILES = 256
MAX_CONFIG_BYTES = 256 * 1024
MAX_PACKAGE_TARGETS = 512
MAX_SUFFIX_INDEX_FILES = 300_000
_MAX_EXTENDS_DEPTH = 5

# Languages whose imports the map can read. Anything else (Swift, C#, Elixir, SQL, CSS) has no
# file-level import to follow, so "no dependents found" there means "not looked at", not "none".
RESOLVER_LANGUAGES = frozenset({
    "python", "javascript", "typescript", "vue", "dart", "go", "rust", "java", "kotlin",
    "c", "cpp", "objective-c", "objective-cpp", "ruby", "php", "shell",
})
JS_SUFFIXES = frozenset({".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts", ".vue"})
# What a TypeScript project resolves a bare path to, in this order.
_JS_PRIORITY = (".ts", ".tsx", ".d.ts", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs", ".vue")
# ESM TypeScript writes ``./x.js`` for a file that is x.ts.
_JS_SWAP = {".js": (".ts", ".tsx"), ".jsx": (".tsx",), ".mjs": (".mts",), ".cjs": (".cts",)}
_C_SUFFIXES = frozenset({".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".m", ".mm"})
_SHELL_SUFFIXES = frozenset({".sh", ".bash", ".zsh"})

# A line starts with spaces and tabs, never with newlines: `^\s*` let a file of blank (or
# comment-stripped) lines cost quadratic time (20,000 blank lines took 7 seconds).
JS_IMPORT_SPECIFIER_PATTERNS = (
    re.compile(r"(?m)^[ \t]*import[ \t]*['\"]([^'\"]+)['\"]"),
    re.compile(r"(?ms)^[ \t]*(?:import|export)\s+[^;]{0,2000}?\s+from\s*['\"]([^'\"]+)['\"]"),
    re.compile(r"\brequire\(\s*['\"]([^'\"]+)['\"]\s*\)"),
    re.compile(r"\bimport\(\s*['\"]([^'\"]+)['\"]\s*\)"),
)
PYTHON_IMPORT_SPECIFIER_PATTERNS = (
    re.compile(r"(?m)^[ \t]*from[ \t]+([.]*[A-Za-z_][\w.]*)[ \t]+import[ \t]"),
    re.compile(r"(?m)^[ \t]*import[ \t]+([A-Za-z_][\w.]*)"),
)
# `import os, mymod as m` names several modules on one line.
_PYTHON_IMPORT_LINE = re.compile(r"(?m)^[ \t]*import[ \t]+([^\n;#]{1,400})")
# `from . import content_guard` / `from .pkg import mod` name a SIBLING MODULE, not a symbol,
# and the patterns above never saw the bare-dots form at all. Each imported name is also offered
# as a submodule specifier; the resolver keeps it only when exactly one project file matches.
_PYTHON_FROM_IMPORT_NAMES = re.compile(
    r"(?m)^[ \t]*from[ \t]+([.]*(?:[A-Za-z_][\w.]*)?)[ \t]+import[ \t]+(\([^)]{0,2000}\)|[^\n]*)"
)
_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")
# A Dart directive can carry several URIs: `import 'a.dart' if (dart.library.io) 'a_io.dart';`
_DART_STATEMENT = re.compile(r"(?m)^[ \t]*(?:import|export|part)[ \t]+([^;]{1,600});")
_QUOTED = re.compile(r"""['"]([^'"]+)['"]""")
_GO_SINGLE = re.compile(r'(?m)^[ \t]*import[ \t]+(?:[\w.]+[ \t]+)?"([^"]+)"')
_GO_BLOCK = re.compile(r"(?m)^[ \t]*import[ \t]*\(([^)]{0,20000})\)")
_GO_BLOCK_LINE = re.compile(r'(?m)^[ \t]*(?:[\w.]+[ \t]+)?"([^"]+)"')
_RUST_MOD = re.compile(r"(?m)^[ \t]*(?:pub(?:\([^)]*\))?[ \t]+)?mod[ \t]+(\w+)[ \t]*;")
_RUST_USE = re.compile(r"(?m)^[ \t]*(?:pub(?:\([^)]*\))?[ \t]+)?use[ \t]+(crate(?:::\w+)*)(?:::\{([^{}]{0,600})\})?")
_JVM = re.compile(r"(?m)^[ \t]*import[ \t]+(static[ \t]+)?([\w.]+?)(\.\*)?(?:[ \t]+as[ \t]+\w+)?[ \t]*;?[ \t]*$")
_C_INCLUDE = re.compile(r'(?m)^[ \t]*#[ \t]*(?:include|import)[ \t]+"([^"]+)"')
_RUBY_REQUIRE_RELATIVE = re.compile(r"""(?m)^[ \t]*require_relative[ \t]*\(?[ \t]*['"]([^'"]+)['"]""")
_RUBY_REQUIRE = re.compile(r"""(?m)^[ \t]*require[ \t]*\(?[ \t]*['"]([^'"]+)['"]""")
_PHP_INCLUDE = re.compile(
    r"""(?:require|include)(?:_once)?\s*\(?\s*(?:__DIR__\s*\.\s*)?['"]([^'"]+)['"]"""
)
_SHELL_SOURCE = re.compile(r"""(?m)^[ \t]*(?:source|\.)[ \t]+["']?([^\s"';|&]+)""")

_STDLIB_FALLBACK = frozenset(
    "abc argparse ast asyncio base64 collections concurrent contextlib copy csv dataclasses datetime "
    "decimal difflib email enum errno fnmatch functools glob gzip hashlib heapq hmac html http importlib "
    "inspect io itertools json logging math mimetypes multiprocessing os pathlib pickle platform queue "
    "random re secrets select shlex shutil signal socket sqlite3 ssl stat string struct subprocess sys "
    "tempfile textwrap threading time tomllib traceback types typing unittest urllib uuid warnings "
    "weakref xml zipfile zlib".split()
)


def is_config_path(relative: str) -> bool:
    return bool(CONFIG_BASENAME.match(posixpath.basename(relative)))


def _strip_block_comments(text: str) -> str:
    """Remove ``/* ... */`` in one pass. An unclosed ``/*`` (a glob inside a string, ``"src/*"``)
    leaves the rest of the file as it is; a regex retried the scan to the end of the file from
    every such ``/*`` and grew quadratically."""

    if "/*" not in text:
        return text
    parts: list[str] = []
    position = 0
    while True:
        start = text.find("/*", position)
        if start < 0:
            break
        end = text.find("*/", start + 2)
        if end < 0:
            break  # no later "*/" exists either: nothing further can close
        parts.append(text[position:start])
        position = end + 2
    parts.append(text[position:])
    return "".join(parts)


def _strip_c_comments(text: str) -> str:
    return _strip_block_comments(re.sub(r"(?m)(?<![:\"'])//.*$", "", text))


def extract_specifiers(importer: str, text: str) -> list[str]:
    """Every project-looking import a file declares, as language-specific specifier strings."""

    suffix = PurePosixPath(importer).suffix.lower()
    found: set[str] = set()
    text = text.lstrip("\ufeff")  # a byte-order mark hid the first line's import (Windows-saved files)
    if suffix == ".py":
        searchable = re.sub(r"(?m)#.*$", "", text)
        for pattern in PYTHON_IMPORT_SPECIFIER_PATTERNS:
            found.update(m.group(1).strip() for m in pattern.finditer(searchable) if m.group(1).strip())
        for match in _PYTHON_IMPORT_LINE.finditer(searchable):
            for part in match.group(1).split(","):
                tokens = part.split()
                if tokens and re.fullmatch(r"[A-Za-z_][\w.]*", tokens[0]):
                    found.add(tokens[0])
        for match in _PYTHON_FROM_IMPORT_NAMES.finditer(searchable):
            module = match.group(1)
            if not module:
                continue
            for part in re.split(r"[,\n]", match.group(2).strip().strip("()")):
                tokens = part.split()
                name = tokens[0] if tokens else ""
                if _IDENTIFIER.match(name):
                    found.add(module + name if module.endswith(".") else f"{module}.{name}")
    elif suffix in JS_SUFFIXES:
        searchable = _strip_block_comments(text)
        searchable = re.sub(r"(?m)//.*$", "", searchable)
        for pattern in JS_IMPORT_SPECIFIER_PATTERNS:
            found.update(m.group(1).strip() for m in pattern.finditer(searchable) if m.group(1).strip())
    elif suffix == ".dart":
        for match in _DART_STATEMENT.finditer(re.sub(r"(?m)//.*$", "", text)):
            for uri in _QUOTED.findall(match.group(1)):
                if uri.startswith(("package:", "dart:")) or ".dart" in uri:
                    found.add(uri.strip())
    elif suffix == ".go":
        searchable = _strip_c_comments(text)
        found.update(m.group(1) for m in _GO_SINGLE.finditer(searchable))
        for block in _GO_BLOCK.finditer(searchable):
            found.update(m.group(1) for m in _GO_BLOCK_LINE.finditer(block.group(1)))
    elif suffix == ".rs":
        searchable = _strip_c_comments(text)
        found.update("mod:" + m.group(1) for m in _RUST_MOD.finditer(searchable))
        for match in _RUST_USE.finditer(searchable):
            found.add("use:" + match.group(1))
            for item in (match.group(2) or "").split(","):  # use crate::{a, b::c};
                name = item.strip().split(" as ")[0].strip()
                if name and name != "self" and re.fullmatch(r"\w+(?:::\w+)*", name):
                    found.add(f"use:{match.group(1)}::{name}")
    elif suffix in {".java", ".kt", ".kts"}:
        for match in _JVM.finditer(_strip_c_comments(text)):
            if match.group(3):  # wildcard: a package, not a file
                continue
            found.add(("static:" if match.group(1) else "") + match.group(2))
    elif suffix in _C_SUFFIXES:
        found.update(m.group(1) for m in _C_INCLUDE.finditer(_strip_c_comments(text)))
    elif suffix == ".rb":
        searchable = re.sub(r"(?m)#.*$", "", text)
        found.update("rel:" + m.group(1) for m in _RUBY_REQUIRE_RELATIVE.finditer(searchable))
        found.update("lib:" + m.group(1) for m in _RUBY_REQUIRE.finditer(searchable))
    elif suffix == ".php":
        found.update(m.group(1) for m in _PHP_INCLUDE.finditer(_strip_c_comments(text)))
    elif suffix in _SHELL_SUFFIXES:
        for match in _SHELL_SOURCE.finditer(re.sub(r"(?m)^[ \t]*#.*$", "", text)):
            value = match.group(1)
            if "$" not in value and "*" not in value and "`" not in value:
                found.add(value)
    return sorted(found)


def _loads_jsonc(text: str) -> dict:
    """tsconfig allows comments and trailing commas."""

    text = text.lstrip("\ufeff")
    cleaned = re.sub(
        r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[^*]*\*+(?:[^/*][^*]*\*+)*/',
        lambda m: m.group(0) if m.group(0).startswith('"') else "",
        text,
    )
    cleaned = re.sub(r",(\s*[}\]])", r"\1", cleaned)
    try:
        data = json.loads(cleaned)
    except (ValueError, RecursionError):
        return {}
    return data if isinstance(data, dict) else {}


def _normalize(path: str) -> str | None:
    normalized = posixpath.normpath(path)
    if normalized in {".", ""} or normalized.startswith("../") or normalized == ".." or normalized.startswith("/"):
        return None
    return normalized


def _join(base: str, rest: str) -> str | None:
    return _normalize(posixpath.join(base, rest) if base else rest)


def _ancestors(directory: str) -> list[str]:
    """``a/b/c`` -> ['a/b/c', 'a/b', 'a', ''] (nearest first)."""

    parts = [part for part in directory.split("/") if part and part != "."]
    return ["/".join(parts[:i]) for i in range(len(parts), -1, -1)]


class ImportResolver:
    """Resolves one specifier of one importer to the project files it names."""

    def __init__(
        self,
        source_files: Iterable[str],
        configs: Mapping[str, str] | None = None,
        known_files: Iterable[str] | None = None,
    ) -> None:
        self.sources = set(source_files)
        self.known = set(known_files) if known_files is not None else self.sources
        self._configs = dict(configs or {})
        self._ts: list[dict] | None = None
        self._pubspecs: dict[str, str] | None = None
        self._go_modules: list[tuple[str, str]] | None = None
        self._tails: dict[str, list[str]] | None = None
        self._by_dir: dict[str, list[str]] | None = None
        self._stdlib = getattr(sys, "stdlib_module_names", _STDLIB_FALLBACK)

    # ---- public ---------------------------------------------------------------------
    def resolve(self, importer: str, spec: str) -> list[str]:
        spec = spec.strip()
        if not spec:
            return []
        suffix = PurePosixPath(importer).suffix.lower()
        if suffix == ".py":
            found = self._python(importer, spec)
        elif suffix in JS_SUFFIXES:
            found = self._js(importer, spec)
        elif suffix == ".dart":
            found = self._dart(importer, spec)
        elif suffix == ".go":
            found = self._go(spec)
        elif suffix == ".rs":
            found = self._rust(importer, spec)
        elif suffix in {".java", ".kt", ".kts"}:
            found = self._jvm(spec)
        elif suffix in _C_SUFFIXES:
            found = self._c(importer, spec)
        elif suffix == ".rb":
            found = self._ruby(importer, spec)
        elif suffix == ".php":
            found = self._relative_file(importer, spec.lstrip("/") if spec.startswith("/") else spec)
        elif suffix in _SHELL_SUFFIXES:
            found = self._relative_file(importer, spec)
        else:
            found = []
        return [target for target in dict.fromkeys(found) if target != importer]

    def resolve_one(self, importer: str, spec: str) -> str | None:
        found = self.resolve(importer, spec)
        return found[0] if len(found) == 1 else None

    # ---- shared helpers -------------------------------------------------------------
    def _relative_file(self, importer: str, spec: str) -> list[str]:
        target = _join(posixpath.dirname(importer), spec.replace("\\", "/"))
        return [target] if target and target in self.sources else []

    def _dir_index(self) -> dict[str, list[str]]:
        if self._by_dir is None:
            index: dict[str, list[str]] = defaultdict(list)
            for path in sorted(self.sources):
                index[posixpath.dirname(path)].append(path)
            self._by_dir = index
        return self._by_dir

    def _tail_lookup(self, tail: str, suffixes: Iterable[str]) -> list[str]:
        """Files whose extension-less path ends with ``tail`` on a folder boundary."""

        if self._tails is None:
            self._tails = defaultdict(list)
            if len(self.sources) <= MAX_SUFFIX_INDEX_FILES:
                for path in sorted(self.sources):
                    stem = path.rsplit(".", 1)[0] if "." in posixpath.basename(path) else path
                    parts = stem.split("/")
                    for i in range(len(parts)):
                        self._tails["/".join(parts[i:])].append(path)
        wanted = tuple(suffixes)
        return [path for path in self._tails.get(tail, []) if path.lower().endswith(wanted)]

    def _config_dir(self, config_path: str) -> str:
        return posixpath.dirname(config_path)

    # ---- python ---------------------------------------------------------------------
    def _python(self, importer: str, spec: str) -> list[str]:
        parent = posixpath.dirname(importer)
        dots = len(spec) - len(spec.lstrip("."))
        module = spec[dots:].replace(".", "/")
        if dots:
            base = parent
            for _ in range(max(0, dots - 1)):
                base = posixpath.dirname(base)
            roots = [_join(base, module) if module else (base or None)]
        else:
            roots = [_normalize(module), _normalize("src/" + module)]
        exact = self._exact_python([r for r in roots if r])
        if exact is not None:
            return [exact]
        if dots or not module or module.split("/")[0] in self._stdlib:
            return []
        sibling = _join(parent, module)
        if sibling:
            found = self._exact_python([sibling])
            if found is not None:
                return [found]
        # A project whose package root is not the repository root (a nested app, a src layout):
        # accept a module only when exactly one file ends with that path.
        matches = sorted(
            set(self._tail_lookup(module, (".py",)))
            | set(self._tail_lookup(module + "/__init__", (".py",)))
        )
        return matches if len(matches) == 1 else []

    def _exact_python(self, roots: list[str]) -> str | None:
        candidates: list[str] = []
        for raw in roots:
            candidates.append(raw)
            if not PurePosixPath(raw).suffix:
                candidates.append(raw + ".py")
                candidates.append(raw + "/__init__.py")
        present = sorted({c for c in candidates if c in self.sources and c.endswith(".py")})
        return present[0] if len(present) == 1 else None

    # ---- javascript / typescript -----------------------------------------------------
    def _js_match(self, base: str | None) -> str | None:
        if not base:
            return None
        if base in self.sources:  # any project file the specifier names exactly (./x.ts, ./styles.css)
            return base
        suffix = PurePosixPath(base).suffix.lower()
        stem = base[: -len(suffix)] if suffix in _JS_SWAP else None
        if stem is not None:
            for swapped in _JS_SWAP[suffix]:
                if stem + swapped in self.sources:
                    return stem + swapped
        for ext in _JS_PRIORITY:
            if base + ext in self.sources:
                return base + ext
        for ext in _JS_PRIORITY:
            if f"{base}/index{ext}" in self.sources:
                return f"{base}/index{ext}"
        return None

    def _ts_configs(self) -> list[dict]:
        if self._ts is None:
            self._ts = []
            for path in sorted(self._configs):
                name = posixpath.basename(path)
                if not re.match(r"^(?:tsconfig|jsconfig)", name):
                    continue
                effective = self._effective_ts(path, ())
                if effective and (effective["paths"] or effective["baseUrl"] is not None):
                    self._ts.append(effective)
        return self._ts

    def _effective_ts(self, path: str, seen: tuple[str, ...]) -> dict | None:
        text = self._configs.get(path)
        if text is None or path in seen or len(seen) >= _MAX_EXTENDS_DEPTH:
            return None
        data = _loads_jsonc(text)
        directory = self._config_dir(path)
        merged: dict = {"dir": directory, "baseUrl": None, "paths": [], "pathsRoot": directory}
        extends = data.get("extends")
        for parent in ([extends] if isinstance(extends, str) else extends if isinstance(extends, list) else []):
            if not isinstance(parent, str) or not parent.startswith("."):
                continue  # a package's shared config: not in this project
            target = _join(directory, parent if parent.endswith(".json") else parent + ".json")
            inherited = self._effective_ts(target, (*seen, path)) if target else None
            if inherited:
                merged["baseUrl"] = inherited["baseUrl"]
                merged["paths"] = inherited["paths"]
                merged["pathsRoot"] = inherited["pathsRoot"]
        options = data.get("compilerOptions")
        options = options if isinstance(options, dict) else {}
        if isinstance(options.get("baseUrl"), str):
            resolved_base = posixpath.normpath(posixpath.join(directory, options["baseUrl"]))
            if resolved_base == ".":
                resolved_base = ""  # the repository root
            if not resolved_base.startswith("..") and not resolved_base.startswith("/"):
                merged["baseUrl"] = resolved_base
        paths = options.get("paths")
        if isinstance(paths, dict):
            merged["paths"] = [
                (pattern, [t for t in targets if isinstance(t, str)])
                for pattern, targets in paths.items()
                if isinstance(pattern, str) and isinstance(targets, list)
            ]
            merged["pathsRoot"] = merged["baseUrl"] if merged["baseUrl"] is not None else directory
        return merged

    @staticmethod
    def _pattern_capture(pattern: str, spec: str) -> str | None:
        if "*" not in pattern:
            return "" if pattern == spec else None
        prefix, suffix = pattern.split("*", 1)
        if spec.startswith(prefix) and spec.endswith(suffix) and len(spec) >= len(prefix) + len(suffix):
            return spec[len(prefix): len(spec) - len(suffix)]
        return None

    def _js(self, importer: str, spec: str) -> list[str]:
        parent = posixpath.dirname(importer)
        if spec.startswith("."):
            joined = posixpath.normpath(posixpath.join(parent, spec)) if parent else posixpath.normpath(spec)
            if joined == ".":  # the project root: its index file
                for ext in _JS_PRIORITY:
                    if f"index{ext}" in self.sources:
                        return [f"index{ext}"]
                return []
            found = self._js_match(_normalize(joined))
            return [found] if found else []
        applicable = [
            config
            for config in self._ts_configs()
            if config["dir"] == "" or importer == config["dir"] or importer.startswith(config["dir"] + "/")
        ]
        applicable.sort(key=lambda config: -len(config["dir"]))
        for config in applicable:
            for pattern, targets in config["paths"]:
                captured = self._pattern_capture(pattern, spec)
                if captured is None:
                    continue
                for target in targets:
                    found = self._js_match(_join(config["pathsRoot"], target.replace("*", captured)))
                    if found:
                        return [found]
            if config["baseUrl"] is not None:
                found = self._js_match(_join(config["baseUrl"], spec))
                if found:
                    return [found]
        if spec.startswith(("@/", "~/")):
            rest = spec[2:]
            for directory in _ancestors(parent):
                package = f"{directory}/package.json" if directory else "package.json"
                if package in self.known:
                    for base in (f"src/{rest}", rest):
                        found = self._js_match(_join(directory, base))
                        if found:
                            return [found]
            for base in (rest, f"src/{rest}"):
                found = self._js_match(_normalize(base))
                if found:
                    return [found]
        return []

    # ---- dart -----------------------------------------------------------------------
    def _dart(self, importer: str, spec: str) -> list[str]:
        if spec.startswith("dart:"):
            return []
        if spec.startswith("package:"):
            if self._pubspecs is None:
                self._pubspecs = {}
                for path, text in self._configs.items():
                    if posixpath.basename(path) == "pubspec.yaml":
                        match = re.search(r"(?m)^name:\s*['\"]?([\w.-]+)", text)
                        if match:
                            self._pubspecs.setdefault(match.group(1), self._config_dir(path))
            package, _, rest = spec[len("package:"):].partition("/")
            directory = self._pubspecs.get(package)
            if directory is None or not rest:
                return []
            target = _join(directory, "lib/" + rest)
            return [target] if target and target in self.sources else []
        return self._relative_file(importer, spec)

    # ---- go -------------------------------------------------------------------------
    def _go(self, spec: str) -> list[str]:
        if self._go_modules is None:
            self._go_modules = []
            for path, text in self._configs.items():
                if posixpath.basename(path) == "go.mod":
                    match = re.search(r"(?m)^module\s+(\S+)", text)
                    if match:
                        self._go_modules.append((match.group(1), self._config_dir(path)))
            self._go_modules.sort(key=lambda row: -len(row[0]))
        for module, directory in self._go_modules:
            if spec == module or spec.startswith(module + "/"):
                package_dir = _join(directory, spec[len(module):].lstrip("/")) if spec != module else (directory or None)
                key = package_dir if package_dir is not None else ""
                files = [
                    path
                    for path in self._dir_index().get(key, [])
                    if path.endswith(".go") and not path.endswith("_test.go")
                ]
                return files[:MAX_PACKAGE_TARGETS]
        return []

    # ---- rust -----------------------------------------------------------------------
    def _rust(self, importer: str, spec: str) -> list[str]:
        kind, _, value = spec.partition(":")
        parent = posixpath.dirname(importer)
        stem = PurePosixPath(importer).stem
        if kind == "mod":
            base = parent if stem in {"mod", "lib", "main"} else _join(parent, stem) or parent
            for candidate in (_join(base, value + ".rs"), _join(base, value + "/mod.rs")):
                if candidate and candidate in self.sources:
                    return [candidate]
            return []
        if kind == "use":
            segments = value.split("::")[1:]
            if not segments:
                return []
            # `crate` is the folder of the crate's root file (main.rs / lib.rs), which a Cargo.toml
            # [[bin]] path can put anywhere; src/ next to Cargo.toml is only the default.
            roots: list[str] = []
            for directory in _ancestors(parent):
                for root_file in ("main.rs", "lib.rs"):
                    if (f"{directory}/{root_file}" if directory else root_file) in self.sources:
                        roots.append(directory or ".")
            for directory in _ancestors(parent):
                manifest = f"{directory}/Cargo.toml" if directory else "Cargo.toml"
                if manifest in self.known:
                    roots += [_join(directory, "src") or "src", directory or "."]
            for count in range(len(segments), 0, -1):
                base = "/".join(segments[:count])
                for root in dict.fromkeys(roots):
                    for candidate in (_join(root, base + ".rs"), _join(root, base + "/mod.rs")):
                        if candidate and candidate in self.sources:
                            return [candidate]
            return []
        return []

    # ---- java / kotlin --------------------------------------------------------------
    def _jvm(self, spec: str) -> list[str]:
        static = spec.startswith("static:")
        dotted = spec[len("static:"):] if static else spec
        names = [dotted]
        parts = dotted.split(".")
        for drop in (1, 2):  # a nested class or a static member: the file is the enclosing class
            if len(parts) - drop >= 2:
                names.append(".".join(parts[:-drop]))
        for name in names:
            matches = sorted(set(self._tail_lookup(name.replace(".", "/"), (".java", ".kt", ".kts"))))
            if len(matches) == 1:
                return matches
        return []

    # ---- c family -------------------------------------------------------------------
    def _c(self, importer: str, spec: str) -> list[str]:
        near = self._relative_file(importer, spec)
        if near:
            return near
        stem = spec.rsplit(".", 1)[0] if "." in posixpath.basename(spec) else spec
        matches = sorted(set(self._tail_lookup(stem, tuple(_C_SUFFIXES))))
        matches = [m for m in matches if m.endswith("/" + spec) or m == spec]
        return matches if len(matches) == 1 else []

    # ---- ruby -----------------------------------------------------------------------
    def _ruby(self, importer: str, spec: str) -> list[str]:
        kind, _, value = spec.partition(":")
        name = value if value.endswith(".rb") else value + ".rb"
        if kind == "rel":
            return self._relative_file(importer, name)
        matches = [
            path
            for path in sorted(set(self._tail_lookup(name[:-3], (".rb",))))
            if path == "lib/" + name or "/lib/" + name in path
        ]
        return matches if len(matches) == 1 else []
