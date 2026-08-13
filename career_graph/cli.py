from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .runtime import CareerGraphRuntime, RuntimeConfig


def main(argv: list[str] | None = None) -> int:
    normalized_argv, common = normalize_common_args(argv)
    parser = argparse.ArgumentParser(
        prog="career-graph",
        description="Agentlas Career Graph: rebuildable index over local Markdown/JSONL ledgers",
    )
    parser.add_argument("--project", default=common["project"], help=argparse.SUPPRESS)
    parser.add_argument("--db", default=common["db"], help=argparse.SUPPRESS)
    parser.add_argument("--include-networking-home", action="store_true", default=common["include_networking_home"], help=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show graph files, source counts, and freshness")

    ingest = sub.add_parser("ingest", help="Rebuild the derived Career Graph index from canonical ledgers")
    ingest.add_argument(
        "--incremental",
        action="store_true",
        help="Reparse only new or checksum-changed sources and prune deleted projections",
    )

    query = sub.add_parser("query", help="Search graph nodes and return source refs the agent should inspect")
    query.add_argument("text")
    query.add_argument("--limit", type=int, default=8)

    trace = sub.add_parser("trace", help="Show a node/edge with source provenance")
    trace.add_argument("id")

    public_card = sub.add_parser("public-card", help="Emit a redacted Hub-safe Career Graph summary")
    public_card.add_argument("--write", action="store_true", help="Write .agentlas/public-career-card.json")

    sub.add_parser("verify", help="Fail when the graph is missing, empty, or stale")

    args = parser.parse_args(normalized_argv)
    runtime = CareerGraphRuntime(
        RuntimeConfig(
            project=Path(args.project),
            db_path=Path(args.db) if args.db else None,
            include_networking_home=bool(args.include_networking_home),
        )
    )

    if args.command == "status":
        result = runtime.status()
        emit(result)
        return payload_exit_code(result)
    if args.command == "ingest":
        try:
            result = runtime.ingest(rebuild=not args.incremental)
        except (OSError, ValueError) as exc:
            emit({"status": "error", "error": "career_ingest_failed", "detail": str(exc)})
            return 2
        emit(result)
        return payload_exit_code(result)
    if args.command == "query":
        result = runtime.query(args.text, limit=args.limit)
        emit(result)
        return payload_exit_code(result)
    if args.command == "trace":
        result = runtime.trace(args.id)
        emit(result)
        return payload_exit_code(result)
    if args.command == "public-card":
        return emit(runtime.public_card(write=args.write))
    if args.command == "verify":
        result = runtime.verify()
        emit(result)
        return 0 if result["verify_status"] == "pass" else 1
    parser.error("unhandled command")
    return 2


def normalize_common_args(argv: list[str] | None) -> tuple[list[str], dict[str, Any]]:
    """Accept common options before or after the subcommand.

    Argparse only accepts parser-level options before a subcommand by default,
    but the README-facing examples use `career-graph ingest --project .`.
    Normalize that form instead of forcing users to remember option order.
    """
    raw = list(argv) if argv is not None else None
    if raw is None:
        import sys

        raw = sys.argv[1:]

    common: dict[str, Any] = {"project": ".", "db": None, "include_networking_home": False}
    normalized: list[str] = []
    i = 0
    while i < len(raw):
        arg = raw[i]
        if arg == "--project":
            if i + 1 >= len(raw):
                raise SystemExit("career-graph: --project requires a value")
            common["project"] = raw[i + 1]
            i += 2
            continue
        if arg.startswith("--project="):
            common["project"] = arg.split("=", 1)[1]
            i += 1
            continue
        if arg == "--db":
            if i + 1 >= len(raw):
                raise SystemExit("career-graph: --db requires a value")
            common["db"] = raw[i + 1]
            i += 2
            continue
        if arg.startswith("--db="):
            common["db"] = arg.split("=", 1)[1]
            i += 1
            continue
        if arg == "--include-networking-home":
            common["include_networking_home"] = True
            i += 1
            continue
        normalized.append(arg)
        i += 1
    return normalized, common


def emit(payload: Any) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def payload_exit_code(payload: Any) -> int:
    if not isinstance(payload, dict):
        return 0
    status = str(payload.get("status") or "ok")
    if status in {"ok", "active"}:
        return 0
    if status in {"missing_index", "not_found", "stale", "stale_index"}:
        return 1
    return 2
