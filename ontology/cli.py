from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .runtime import DEFAULT_DB_PATH, OntologyRuntime, RuntimeConfig


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ontology", description="Hephaestus local-first ontology runtime")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite runtime database path")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="Ingest a file or directory")
    ingest.add_argument("path")
    ingest.add_argument("--scope", default="internal", choices=["public", "internal", "private"], help="Access/privacy scope")
    ingest.add_argument("--parent-source-id")

    query = sub.add_parser("query", help="Run GraphRAG query")
    query.add_argument("question")
    query.add_argument("--agent")
    query.add_argument("--scope", action="append", choices=["public", "internal", "private"], help="Allowed scope; repeatable")
    query.add_argument("--limit", type=int, default=5)

    graph = sub.add_parser("graph", help="Graph commands")
    graph_sub = graph.add_subparsers(dest="graph_command", required=True)
    entity = graph_sub.add_parser("entity", help="Show entity graph slice")
    entity.add_argument("name")

    memory = sub.add_parser("memory", help="Memory Curator bridge commands")
    memory_sub = memory.add_subparsers(dest="memory_command", required=True)
    candidates = memory_sub.add_parser("candidates", help="List Memory Curator candidate tickets")
    candidates.add_argument("--status")
    decide = memory_sub.add_parser("decide", help="Record candidate review state")
    decide.add_argument("ticket_id")
    decide.add_argument("decision", choices=["approve", "reject", "quarantine", "supersede", "deprecate"])
    decide.add_argument("--reason", required=True)

    working = sub.add_parser("working-memory", help="Agent Working Memory commands")
    working_sub = working.add_subparsers(dest="working_command", required=True)
    read = working_sub.add_parser("read", help="Read agent hot cache")
    read.add_argument("--agent", required=True)
    read.add_argument("--include-expired", action="store_true")
    prune = working_sub.add_parser("prune", help="Expire/evict stale cache entries")
    prune.add_argument("--agent", required=True)
    prune.add_argument("--min-importance", type=float, default=0.0)

    sub.add_parser("verify", help="Run runtime integrity verification")

    storage = sub.add_parser("storage", help="Storage backup/export/import")
    storage_sub = storage.add_subparsers(dest="storage_command", required=True)
    backup = storage_sub.add_parser("backup")
    backup.add_argument("destination")
    export = storage_sub.add_parser("export")
    export.add_argument("destination")
    import_cmd = storage_sub.add_parser("import")
    import_cmd.add_argument("source")

    args = parser.parse_args(argv)
    runtime = OntologyRuntime(RuntimeConfig(db_path=Path(args.db)))

    if args.command == "ingest":
        return emit(runtime.ingest_path(args.path, access_scope=args.scope, parent_source_id=args.parent_source_id))
    if args.command == "query":
        return emit(runtime.query(args.question, agent_id=args.agent, allowed_scopes=args.scope, limit=args.limit))
    if args.command == "graph" and args.graph_command == "entity":
        return emit(runtime.graph_entity(args.name))
    if args.command == "memory" and args.memory_command == "candidates":
        return emit({"candidates": runtime.list_memory_candidates(status=args.status)})
    if args.command == "memory" and args.memory_command == "decide":
        return emit(runtime.decide_memory_candidate(args.ticket_id, args.decision, args.reason))
    if args.command == "working-memory" and args.working_command == "read":
        return emit({"items": runtime.read_working_memory(args.agent, include_expired=args.include_expired)})
    if args.command == "working-memory" and args.working_command == "prune":
        return emit(runtime.prune_working_memory(args.agent, min_importance=args.min_importance))
    if args.command == "verify":
        result = runtime.verify()
        emit(result)
        return 0 if result["status"] == "pass" else 1
    if args.command == "storage" and args.storage_command == "backup":
        return emit(runtime.backup(args.destination))
    if args.command == "storage" and args.storage_command == "export":
        return emit(runtime.export_json(args.destination))
    if args.command == "storage" and args.storage_command == "import":
        return emit(runtime.import_json(args.source))
    parser.error("unhandled command")
    return 2


def emit(payload: Any) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0
