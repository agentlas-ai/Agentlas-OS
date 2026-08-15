"""Runtime registry — the declarative seed behind `agentlas-one status --runtimes`.

One data file (`contracts/runtime-registry.json`) answers, per runtime, the
questions the six onboarding mechanisms used to answer by hand: which
instruction file, which hook file and JSON shape, whether ACP exists and how to
spawn it, and which access path (subscription CLI / API / local) applies. This
module loads it, validates it without jsonschema (Core is stdlib-only), and
renders the live support matrix by looking at THIS machine: is the binary or
config dir present, is our directive block installed, is our hook entry there.

It reads; it never writes. Installers/uninstallers keep their own hardcoded
paths for now (backlog: make them read this file too).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping, Optional

SCHEMA_VERSION = "agentlas.runtime-registry.v1"
ROLES = {"tier1", "tier0", "model-server"}
GRADES = {"A", "B", "C", "D", "E"}
INSTALL_LEVELS = {"L0", "L1", "L2", "L3"}
ACCESS_PATHS = {"subscription-cli", "api", "local", "unknown"}
HOOK_SHAPES = {"claude-settings", "codex-hooks", "cursor-flat", "agy-namemap", "hookpack-dir", "none"}
ACP_SOURCES = {"native", "adapter", "opt-in", "client", "none"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
DIRECTIVE_MARK = "<!-- AGENTLAS-ONE:BEGIN -->"


def _candidate_paths() -> list[Path]:
    here = Path(__file__).resolve()
    roots = [
        here.parents[1],                                    # source checkout / plugin mirror root
        Path(os.path.expanduser("~/.agentlas/runtime/current")),
    ]
    env_root = os.environ.get("AGENTLAS_RUNTIME_ROOT")
    if env_root:
        roots.insert(0, Path(env_root))
    return [root / "contracts" / "runtime-registry.json" for root in roots]


def registry_path() -> Optional[Path]:
    for candidate in _candidate_paths():
        if candidate.is_file():
            return candidate
    return None


def load_registry(path: Optional[Path] = None) -> dict[str, Any]:
    target = path or registry_path()
    if target is None:
        raise FileNotFoundError("contracts/runtime-registry.json not found in any runtime root")
    with open(target, encoding="utf-8") as fh:
        data = json.load(fh)
    problems = validate_registry(data)
    if problems:
        raise ValueError("runtime registry invalid: " + "; ".join(problems))
    return data


def validate_registry(data: Any) -> list[str]:
    """Hand-rolled check mirroring schemas/runtime-registry.schema.json."""

    problems: list[str] = []
    if not isinstance(data, Mapping):
        return ["registry must be an object"]
    if data.get("schemaVersion") != SCHEMA_VERSION:
        problems.append("schemaVersion must be %s" % SCHEMA_VERSION)
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(data.get("updatedAt") or "")):
        problems.append("updatedAt must be YYYY-MM-DD")
    runtimes = data.get("runtimes")
    if not isinstance(runtimes, list) or not runtimes:
        return problems + ["runtimes must be a non-empty array"]
    seen: set[str] = set()
    for idx, row in enumerate(runtimes):
        where = "runtimes[%d]" % idx
        if not isinstance(row, Mapping):
            problems.append(where + " must be an object")
            continue
        rid = str(row.get("id") or "")
        if not ID_RE.fullmatch(rid):
            problems.append(where + ".id invalid")
        elif rid in seen:
            problems.append(where + ".id duplicate: " + rid)
        seen.add(rid)
        if not isinstance(row.get("label"), str) or not row.get("label"):
            problems.append(where + ".label missing")
        if row.get("role") not in ROLES:
            problems.append(where + ".role invalid")
        if row.get("grade") not in GRADES:
            problems.append(where + ".grade invalid")
        if row.get("installLevel") not in INSTALL_LEVELS:
            problems.append(where + ".installLevel invalid")
        if not isinstance(row.get("vendors"), list):
            problems.append(where + ".vendors must be an array")
        if row.get("accessPath") not in ACCESS_PATHS:
            problems.append(where + ".accessPath invalid")
        hooks = row.get("hooks")
        if not isinstance(hooks, Mapping) or hooks.get("shape") not in HOOK_SHAPES:
            problems.append(where + ".hooks.shape invalid")
        elif hooks.get("shape") != "none" and not hooks.get("file"):
            problems.append(where + ".hooks.file required for shape " + str(hooks.get("shape")))
        acp = row.get("acp")
        if not isinstance(acp, Mapping) or acp.get("source") not in ACP_SOURCES:
            problems.append(where + ".acp.source invalid")
        elif acp.get("source") in {"native", "adapter", "opt-in"} and not acp.get("command"):
            problems.append(where + ".acp.command required for source " + str(acp.get("source")))
        if not isinstance(row.get("pin"), Mapping):
            problems.append(where + ".pin must be an object")
        for key in row.keys():
            if key not in {"id", "label", "role", "grade", "installLevel", "vendors", "accessPath", "binary",
                           "configDir", "entrypoint", "hooks", "acp", "pin", "notes"}:
                problems.append(where + " has unknown key " + str(key))
    return problems


def _expand(path: Optional[str], home: Path) -> Optional[Path]:
    if not path:
        return None
    if path.startswith("~/"):
        return home / path[2:]
    return Path(os.path.expanduser(path))


def _hook_installed(hooks: Mapping[str, Any], home: Path) -> Optional[bool]:
    shape = hooks.get("shape")
    if shape == "none":
        return None
    target = _expand(hooks.get("file"), home)
    if target is None:
        return None
    if shape == "hookpack-dir":
        return target.is_dir()
    if not target.is_file():
        return False
    try:
        return "agentlas-one" in target.read_text(encoding="utf-8")
    except OSError:
        return False


def status_matrix(registry: Mapping[str, Any], *, home: Optional[Path] = None, path_lookup=shutil.which) -> list[dict[str, Any]]:
    """Per-runtime live rows for this machine. Never raises for a missing file."""

    home = home or Path(os.path.expanduser("~"))
    rows: list[dict[str, Any]] = []
    for row in registry.get("runtimes", []):
        binary = row.get("binary")
        config_dir = _expand(row.get("configDir"), home)
        present = bool(binary and path_lookup(binary)) or bool(config_dir and config_dir.is_dir())
        entry = _expand(row.get("entrypoint"), home)
        directive: Optional[bool]
        if entry is None:
            directive = None
        else:
            try:
                directive = entry.is_file() and DIRECTIVE_MARK in entry.read_text(encoding="utf-8")
            except OSError:
                directive = False
        acp = row.get("acp") or {}
        rows.append(
            {
                "id": row["id"],
                "label": row["label"],
                "role": row["role"],
                "grade": row["grade"],
                "installLevel": row["installLevel"],
                "accessPath": row["accessPath"],
                "present": present,
                "directive": directive,
                "hook": _hook_installed(row.get("hooks") or {}, home),
                "acp": acp.get("source"),
                "acpCommand": " ".join([acp.get("command", "")] + list(acp.get("args") or [])).strip() or None,
                "pin": dict(row.get("pin") or {}),
            }
        )
    return rows


def _cell(value: Optional[bool]) -> str:
    if value is None:
        return "-"
    return "yes" if value else "no"


def render_matrix(rows: list[dict[str, Any]]) -> str:
    header = ("runtime", "role", "grade", "level", "present", "directive", "hook", "acp", "access")
    table = [header]
    for row in rows:
        table.append(
            (
                row["id"],
                row["role"],
                row["grade"],
                row["installLevel"],
                _cell(row["present"]),
                _cell(row["directive"]),
                _cell(row["hook"]),
                str(row["acp"] or "none"),
                row["accessPath"],
            )
        )
    widths = [max(len(str(r[i])) for r in table) for i in range(len(header))]
    lines = []
    for n, r in enumerate(table):
        lines.append("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)).rstrip())
        if n == 0:
            lines.append("  ".join("-" * w for w in widths))
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "status"
    fmt = "json" if "--json" in args else "table"
    home_arg = None
    if "--home" in args:
        home_arg = Path(args[args.index("--home") + 1])
    try:
        registry = load_registry()
    except (FileNotFoundError, ValueError) as exc:
        sys.stderr.write("runtime-registry: %s\n" % exc)
        return 2
    if cmd == "validate":
        print("runtime-registry: ok (%d runtimes)" % len(registry["runtimes"]))
        return 0
    if cmd == "status":
        rows = status_matrix(registry, home=home_arg)
        if fmt == "json":
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            print(render_matrix(rows))
        return 0
    sys.stderr.write("usage: runtime_registry.py {status [--json] [--home DIR]|validate}\n")
    return 2


__all__ = ["SCHEMA_VERSION", "load_registry", "registry_path", "render_matrix", "status_matrix", "validate_registry"]

if __name__ == "__main__":
    raise SystemExit(main())
