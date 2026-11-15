"""Legacy markdown -> per-slug drawer import: stopped.

An agent's memory lives only in the agent's own folder, so the per-slug drawer under
``networking/hub-agents/<slug>`` is no longer written and nothing is classified or planned here (no model is called).
The command stays so older scripts that call it get a clear answer instead of a crash.

Usage:
  python -m agentlas_cloud.memory_import <folder-or-file> --slug <slug> [--apply]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .memory_contract import normalize_slug


def run_import(path: str, slug: str, *, apply: bool, out=print) -> int:
    if not normalize_slug(slug):
        out("error: --slug is required and must normalize to a non-empty slug")
        return 2
    if not Path(path).expanduser().exists():
        out(f"error: path not found: {Path(path).expanduser()}")
        return 2
    out("memory import is stopped: an agent's memory is kept only in the agent's own folder, and the per-slug drawer is no longer written.")
    out("Nothing was read, classified or written.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agentlas_cloud.memory_import",
        description="Stopped: agent memory is kept only in the agent's own folder.",
    )
    parser.add_argument("path")
    parser.add_argument("--slug", required=True)
    parser.add_argument("--apply", action="store_true", help="accepted and ignored")
    args = parser.parse_args(argv)
    return run_import(args.path, args.slug, apply=args.apply)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
