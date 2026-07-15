#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any


BEGIN_MARKER = "<!-- AGENTLAS:MEMORY-HOOK:BEGIN -->"
END_MARKER = "<!-- AGENTLAS:MEMORY-HOOK:END -->"
SUPPORTED_HOSTS = ("antigravity", "grok", "opencode")


class InstallError(RuntimeError):
    pass


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode if path.exists() else None
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(content, encoding="utf-8")
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, path)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InstallError(f"refusing to overwrite invalid JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise InstallError(f"refusing to overwrite non-object JSON: {path}")
    return payload


def _copy_owned(source: Path, target: Path) -> None:
    if not source.is_file():
        raise InstallError(f"missing hook asset: {source}")
    _atomic_write(target, source.read_text(encoding="utf-8"))


def install_antigravity(source_dir: Path, home: Path) -> list[str]:
    source = source_dir / "antigravity" / "hooks" / "agentlas-memory.json"
    incoming = _read_json(source)
    if set(incoming) != {"agentlas-memory"}:
        raise InstallError(f"invalid Agentlas Antigravity hook asset: {source}")
    target = home / ".gemini" / "config" / "hooks.json"
    merged = _read_json(target)
    merged["agentlas-memory"] = incoming["agentlas-memory"]
    _atomic_write(target, json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return [str(target)]


def _managed_block(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    start = text.find(BEGIN_MARKER)
    end = text.find(END_MARKER)
    if start < 0 or end < start:
        raise InstallError(f"invalid managed memory rule asset: {source}")
    return text[start : end + len(END_MARKER)].strip()


def _merge_markdown_block(target: Path, block: str) -> None:
    existing = target.read_text(encoding="utf-8") if target.exists() else ""
    begin_count = existing.count(BEGIN_MARKER)
    end_count = existing.count(END_MARKER)
    if begin_count != end_count or begin_count > 1:
        raise InstallError(f"refusing to repair ambiguous managed markers: {target}")
    if begin_count == 1:
        existing = re.sub(
            re.escape(BEGIN_MARKER) + r".*?" + re.escape(END_MARKER),
            "",
            existing,
            count=1,
            flags=re.DOTALL,
        )
    prefix = existing.rstrip()
    content = f"{prefix}\n\n{block}\n" if prefix else f"{block}\n"
    _atomic_write(target, content)


def install_grok(source_dir: Path, home: Path) -> list[str]:
    hook_source = source_dir / "grok" / "hooks" / "agentlas-memory.json"
    hook_target = home / ".grok" / "hooks" / "agentlas-memory.json"
    _copy_owned(hook_source, hook_target)
    rule_source = source_dir / "grok" / "agentlas-memory-rule.md"
    rule_target = home / ".grok" / "AGENTS.md"
    _merge_markdown_block(rule_target, _managed_block(rule_source))
    return [str(hook_target), str(rule_target)]


def install_opencode(source_dir: Path, home: Path) -> list[str]:
    source = source_dir / "opencode" / "plugins" / "agentlas-memory.js"
    target = home / ".config" / "opencode" / "plugins" / "agentlas-memory.js"
    _copy_owned(source, target)
    return [str(target)]


def _detected_hosts(home: Path) -> list[str]:
    hosts: list[str] = []
    if (
        os.environ.get("HEPHAESTUS_FORCE_ANTIGRAVITY")
        or (home / ".gemini" / "antigravity").is_dir()
        or (home / ".gemini" / "antigravity-ide").is_dir()
    ):
        hosts.append("antigravity")
    if shutil.which("grok") or (home / ".grok").is_dir():
        hosts.append("grok")
    if shutil.which("opencode") or (home / ".config" / "opencode").is_dir():
        hosts.append("opencode")
    return hosts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install merge-safe Agentlas host memory hooks")
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--home", type=Path, default=Path.home())
    parser.add_argument(
        "--hosts",
        default="auto",
        help="auto, all, or a comma-separated subset of antigravity,grok,opencode",
    )
    args = parser.parse_args(argv)
    source_dir = args.source_dir.expanduser().resolve()
    home = args.home.expanduser().resolve()
    if args.hosts == "auto":
        hosts = _detected_hosts(home)
    elif args.hosts == "all":
        hosts = list(SUPPORTED_HOSTS)
    else:
        hosts = [item.strip() for item in args.hosts.split(",") if item.strip()]
        unknown = sorted(set(hosts) - set(SUPPORTED_HOSTS))
        if unknown:
            parser.error(f"unsupported hosts: {', '.join(unknown)}")
    installers = {
        "antigravity": install_antigravity,
        "grok": install_grok,
        "opencode": install_opencode,
    }
    installed: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    for host in hosts:
        try:
            installed[host] = installers[host](source_dir, home)
        except (InstallError, OSError) as exc:
            errors[host] = str(exc)
    print(
        json.dumps(
            {
                "status": "pass" if not errors else "fail",
                "installed": installed,
                "errors": errors,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
