from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any
import webbrowser

from .runtime import DEFAULT_DB_PATH, OntologyRuntime, RuntimeConfig

RUNTIME_CONFIG_FILE = "ontology-runtime.json"
SOURCE_MANIFEST_FILE = "ontology-sources.json"
INBOX_DIR = "ontology-inbox"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ontology", description="Hephaestus local-first ontology runtime")
    parser.add_argument("--db", default=None, help="SQLite runtime database path")
    parser.add_argument(
        "--embedding-adapter",
        default="hash",
        choices=["hash", "model2vec"],
        help="Local-only embedding adapter (default: hash)",
    )
    parser.add_argument(
        "--local-model-path",
        help="Existing local Model2Vec directory; required with --embedding-adapter model2vec",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    auto = sub.add_parser("auto", help="Safely activate and sync a project ontology")
    auto.add_argument("project", nargs="?", default=".")
    auto.add_argument("--scope", default="internal", choices=["public", "internal", "private"], help="Default ingest scope")
    auto.add_argument("--no-ingest", action="store_true", help="Only create activation files")

    sources = sub.add_parser("sources", help="Registered source commands")
    sources_sub = sources.add_subparsers(dest="sources_command", required=True)
    source_add = sources_sub.add_parser("add", help="Register one source path for this project")
    source_add.add_argument("path")
    source_add.add_argument("--project", default=".")
    source_add.add_argument("--scope", default="internal", choices=["public", "internal", "private"])
    source_add.add_argument("--kind", default="project", choices=["project", "company", "personal"])
    source_add.add_argument("--no-ingest", action="store_true")
    source_list = sources_sub.add_parser("list", help="List registered source paths")
    source_list.add_argument("--project", default=".")

    ingest = sub.add_parser("ingest", help="Ingest a file or directory")
    ingest.add_argument("path")
    ingest.add_argument("--scope", default="internal", choices=["public", "internal", "private"], help="Access/privacy scope")
    ingest.add_argument("--parent-source-id")

    query = sub.add_parser("query", help="Run GraphRAG query")
    query.add_argument("question")
    query.add_argument("--agent")
    query.add_argument("--scope", action="append", choices=["public", "internal", "private"], help="Allowed scope; repeatable")
    query.add_argument("--limit", type=int, default=5)
    query.add_argument("--experience-token-budget", type=int, default=800)
    query.add_argument("--experience-top-k", type=int, default=8)
    query.add_argument(
        "--record-memory",
        action="store_true",
        help="Opt in to Memory Curator suggestions and working-memory cache writes; recall is read-only by default",
    )

    experience = sub.add_parser("experience", help="Agent-scoped experience projection commands")
    experience_sub = experience.add_subparsers(dest="experience_command", required=True)
    experience_ingest = experience_sub.add_parser("ingest", help="Upsert one rebuildable local experience projection")
    experience_ingest.add_argument("summary")
    experience_ingest.add_argument("--agent", required=True)
    experience_ingest.add_argument("--tag", action="append", default=[])
    experience_ingest.add_argument("--salience", type=float, default=0.5)
    experience_ingest.add_argument("--scope", default="private", choices=["public", "internal", "private"])
    experience_ingest.add_argument("--status", default="active")
    experience_ingest.add_argument("--kind", default="experience")
    experience_ingest.add_argument("--source-memory-id")
    experience_ingest.add_argument("--source-updated-at")
    experience_ingest.add_argument("--source-refs-json", default="[]", help="JSON array of provenance refs")
    experience_ingest.add_argument("--suggested-scope", default="agent_repo")
    experience_ingest.add_argument("--similar-threshold", type=float, default=0.72)
    experience_query = experience_sub.add_parser("query", help="Read-only lexical+cosine RRF recall")
    experience_query.add_argument("question")
    experience_query.add_argument("--agent", required=True)
    experience_query.add_argument("--scope", action="append", choices=["public", "internal", "private"])
    experience_query.add_argument("--token-budget", type=int, default=800)
    experience_query.add_argument("--top-k", type=int, default=8)

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
    decide.add_argument("--target", help="With supersede/deprecate: the ticket that replaces this one (records a structural supersedes edge)")

    dedup = memory_sub.add_parser("dedup", help="Detect semantically similar candidate tickets using local vector cosine")
    dedup.add_argument("--threshold", type=float, default=0.72, help="Local vector cosine threshold in (0,1], default 0.72")

    mem_graph = memory_sub.add_parser("graph", help="Show a candidate ticket with its relation edges")
    mem_graph.add_argument("ticket_id")

    mem_link = memory_sub.add_parser("link", help="Record a typed relation edge between two tickets")
    mem_link.add_argument("from_ticket")
    mem_link.add_argument("to_ticket")
    mem_link.add_argument("link_type", choices=["similar_to", "supersedes", "contradicts"])
    mem_link.add_argument("--reason", required=True)
    mem_link.add_argument("--score", type=float, default=1.0)

    working = sub.add_parser("working-memory", help="Agent Working Memory commands")
    working_sub = working.add_subparsers(dest="working_command", required=True)
    read = working_sub.add_parser("read", help="Read agent hot cache")
    read.add_argument("--agent", required=True)
    read.add_argument("--include-expired", action="store_true")
    prune = working_sub.add_parser("prune", help="Expire/evict stale cache entries")
    prune.add_argument("--agent", required=True)
    prune.add_argument("--min-importance", type=float, default=0.0)

    gui = sub.add_parser("gui", help="Create and open a project-local ontology GUI")
    gui.add_argument("project", nargs="?", default=".")
    gui.add_argument("--scope", default="internal", choices=["public", "internal", "private"], help="Default ingest scope")
    gui.add_argument("--no-ingest", action="store_true", help="Only create activation and GUI files")
    gui.add_argument("--no-open", action="store_true", help="Create the GUI file without opening a browser")

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

    if args.command == "auto":
        return emit(
            auto_activate_project(
                args.project,
                args.scope,
                no_ingest=args.no_ingest,
                db_override=args.db,
                vector_adapter_name=args.embedding_adapter,
                local_model_path=args.local_model_path,
            )
        )
    if args.command == "sources" and args.sources_command == "add":
        return emit(
            register_source(
                args.project,
                args.path,
                args.scope,
                args.kind,
                no_ingest=args.no_ingest,
                db_override=args.db,
                vector_adapter_name=args.embedding_adapter,
                local_model_path=args.local_model_path,
            )
        )
    if args.command == "sources" and args.sources_command == "list":
        return emit({"sources": read_source_manifest(project_agentlas_dir(args.project)).get("sources", [])})
    if args.command == "gui":
        return emit(
            render_gui(
                args.project,
                args.scope,
                no_ingest=args.no_ingest,
                db_override=args.db,
                open_browser=not args.no_open,
                vector_adapter_name=args.embedding_adapter,
                local_model_path=args.local_model_path,
            )
        )

    runtime = OntologyRuntime(
        RuntimeConfig(
            db_path=Path(args.db or DEFAULT_DB_PATH),
            vector_adapter_name=args.embedding_adapter,
            local_model_path=args.local_model_path,
        )
    )

    if args.command == "ingest":
        return emit(runtime.ingest_path(args.path, access_scope=args.scope, parent_source_id=args.parent_source_id))
    if args.command == "query":
        return emit(
            runtime.query(
                args.question,
                agent_id=args.agent,
                allowed_scopes=args.scope,
                limit=args.limit,
                record_memory=args.record_memory,
                experience_token_budget=args.experience_token_budget,
                experience_top_k=args.experience_top_k,
            )
        )
    if args.command == "experience" and args.experience_command == "ingest":
        source_refs = json.loads(args.source_refs_json)
        if not isinstance(source_refs, list):
            raise SystemExit("--source-refs-json must decode to a JSON array")
        return emit(
            runtime.ingest_experience(
                agent_id=args.agent,
                summary=args.summary,
                tags=args.tag,
                salience=args.salience,
                privacy_scope=args.scope,
                status=args.status,
                memory_kind=args.kind,
                source_memory_id=args.source_memory_id,
                source_updated_at=args.source_updated_at,
                source_refs=source_refs,
                suggested_scope=args.suggested_scope,
                similar_threshold=args.similar_threshold,
            )
        )
    if args.command == "experience" and args.experience_command == "query":
        return emit(
            runtime.query_experience(
                args.question,
                agent_id=args.agent,
                allowed_scopes=args.scope,
                token_budget=args.token_budget,
                top_k=args.top_k,
            )
        )
    if args.command == "graph" and args.graph_command == "entity":
        return emit(runtime.graph_entity(args.name))
    if args.command == "memory" and args.memory_command == "candidates":
        return emit({"candidates": runtime.list_memory_candidates(status=args.status)})
    if args.command == "memory" and args.memory_command == "decide":
        return emit(runtime.decide_memory_candidate(args.ticket_id, args.decision, args.reason, target_ticket=args.target))
    if args.command == "memory" and args.memory_command == "dedup":
        return emit(runtime.relate_memory_candidates(threshold=args.threshold))
    if args.command == "memory" and args.memory_command == "graph":
        return emit(runtime.memory_graph(args.ticket_id))
    if args.command == "memory" and args.memory_command == "link":
        return emit(runtime.link_memory(args.from_ticket, args.to_ticket, args.link_type, args.reason, score=args.score))
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


def project_root(project: str | Path) -> Path:
    return Path(project).expanduser().resolve()


def project_agentlas_dir(project: str | Path) -> Path:
    return project_root(project) / ".agentlas"


def project_db_path(project: str | Path, db_override: str | None = None) -> Path:
    return Path(db_override).expanduser().resolve() if db_override else project_agentlas_dir(project) / "ontology-runtime.sqlite"


def ensure_runtime_files(project: str | Path, default_scope: str = "internal", db_override: str | None = None) -> dict[str, Any]:
    root = project_root(project)
    agentlas_dir = root / ".agentlas"
    inbox = agentlas_dir / INBOX_DIR
    db_path = project_db_path(root, db_override)
    agentlas_dir.mkdir(parents=True, exist_ok=True)
    inbox.mkdir(parents=True, exist_ok=True)

    config_path = agentlas_dir / RUNTIME_CONFIG_FILE
    now_config = {
        "schemaVersion": "1.0",
        "kind": "agentlas-ontology-runtime",
        "state": "active",
        "activation": "automatic",
        "projectRoot": str(root),
        "dbPath": str(db_path),
        "inboxPath": str(inbox),
        "sourceManifest": str(agentlas_dir / SOURCE_MANIFEST_FILE),
        "defaultScope": default_scope,
        "autoIngestPolicy": {
            "mode": "inbox_and_registered_sources_only",
            "neverScanHomeDirectory": True,
            "neverScanSiblingProjects": True,
            "crossProjectSearchDefault": "disabled",
            "privateScopeDefaultSearch": "excluded",
        },
        "memoryPolicy": {
            "durableWrites": "candidate-ticket-only",
            "workingMemory": "runtime-cache-only",
        },
    }
    if not config_path.exists():
        config_path.write_text(json.dumps(now_config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    manifest_path = agentlas_dir / SOURCE_MANIFEST_FILE
    if not manifest_path.exists():
        manifest_path.write_text(
            json.dumps(
                {
                    "schemaVersion": "1.0",
                    "kind": "agentlas-ontology-source-manifest",
                    "projectRoot": str(root),
                    "sources": [],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return {
        "project_root": str(root),
        "agentlas_dir": str(agentlas_dir),
        "config_path": str(config_path),
        "source_manifest_path": str(manifest_path),
        "inbox_path": str(inbox),
        "db_path": str(db_path),
    }


def read_source_manifest(agentlas_dir: Path) -> dict[str, Any]:
    path = agentlas_dir / SOURCE_MANIFEST_FILE
    if not path.exists():
        return {
            "schemaVersion": "1.0",
            "kind": "agentlas-ontology-source-manifest",
            "projectRoot": str(agentlas_dir.parent),
            "sources": [],
        }
    return json.loads(path.read_text(encoding="utf-8"))


def write_source_manifest(agentlas_dir: Path, manifest: dict[str, Any]) -> None:
    (agentlas_dir / SOURCE_MANIFEST_FILE).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def registered_ingest_paths(project: str | Path) -> list[dict[str, str]]:
    root = project_root(project)
    agentlas_dir = root / ".agentlas"
    manifest = read_source_manifest(agentlas_dir)
    paths: list[dict[str, str]] = []
    inbox = agentlas_dir / INBOX_DIR
    if inbox.exists():
        paths.append({"path": str(inbox), "scope": "internal", "kind": "project_inbox"})
    for item in manifest.get("sources", []):
        source_path = Path(str(item.get("path", ""))).expanduser()
        if source_path.exists():
            paths.append(
                {
                    "path": str(source_path.resolve()),
                    "scope": str(item.get("scope") or "internal"),
                    "kind": str(item.get("kind") or "project"),
                }
            )
    return paths


def auto_activate_project(
    project: str | Path,
    scope: str = "internal",
    no_ingest: bool = False,
    db_override: str | None = None,
    vector_adapter_name: str = "hash",
    local_model_path: str | None = None,
) -> dict[str, Any]:
    files = ensure_runtime_files(project, scope, db_override)
    runtime = OntologyRuntime(
        RuntimeConfig(
            db_path=Path(files["db_path"]),
            vector_adapter_name=vector_adapter_name,
            local_model_path=local_model_path,
        )
    )
    sync_results: list[dict[str, Any]] = []
    if not no_ingest:
        for source in registered_ingest_paths(project):
            summary = runtime.ingest_path(source["path"], access_scope=source["scope"])
            sync_results.append(
                {
                    "path": source["path"],
                    "kind": source["kind"],
                    "scope": source["scope"],
                    "chunks_written": summary["chunks_written"],
                    "entities_written": summary["entities_written"],
                    "relations_written": summary["relations_written"],
                    "idempotent_skips": summary["idempotent_skips"],
                    "sources": len(summary["sources"]),
                }
            )
    verify = runtime.verify()
    return {
        "status": "active",
        "project_root": files["project_root"],
        "db_path": files["db_path"],
        "config_path": files["config_path"],
        "inbox_path": files["inbox_path"],
        "source_manifest_path": files["source_manifest_path"],
        "auto_ingest_policy": "inbox_and_registered_sources_only",
        "cross_project_search_default": "disabled",
        "sync_results": sync_results,
        "verify": verify,
    }


def register_source(
    project: str | Path,
    source_path: str | Path,
    scope: str,
    kind: str,
    no_ingest: bool = False,
    db_override: str | None = None,
    vector_adapter_name: str = "hash",
    local_model_path: str | None = None,
) -> dict[str, Any]:
    files = ensure_runtime_files(project, scope, db_override)
    agentlas_dir = Path(files["agentlas_dir"])
    manifest = read_source_manifest(agentlas_dir)
    resolved = Path(source_path).expanduser().resolve()
    if not resolved.exists():
        raise SystemExit(f"source does not exist: {resolved}")
    sources = [item for item in manifest.get("sources", []) if Path(str(item.get("path", ""))).expanduser().resolve() != resolved]
    sources.append({"path": str(resolved), "scope": scope, "kind": kind})
    manifest["sources"] = sources
    write_source_manifest(agentlas_dir, manifest)
    result = {
        "status": "registered",
        "project_root": files["project_root"],
        "source": {"path": str(resolved), "scope": scope, "kind": kind},
        "source_manifest_path": files["source_manifest_path"],
    }
    if not no_ingest:
        runtime = OntologyRuntime(
            RuntimeConfig(
                db_path=Path(files["db_path"]),
                vector_adapter_name=vector_adapter_name,
                local_model_path=local_model_path,
            )
        )
        result["ingest"] = runtime.ingest_path(resolved, access_scope=scope)
    return result


def render_gui(
    project: str | Path,
    scope: str = "internal",
    no_ingest: bool = False,
    db_override: str | None = None,
    open_browser: bool = True,
    vector_adapter_name: str = "hash",
    local_model_path: str | None = None,
) -> dict[str, Any]:
    activation = auto_activate_project(
        project,
        scope,
        no_ingest=no_ingest,
        db_override=db_override,
        vector_adapter_name=vector_adapter_name,
        local_model_path=local_model_path,
    )
    agentlas_dir = Path(activation["config_path"]).parent
    gui_dir = agentlas_dir / "ontology-gui"
    gui_dir.mkdir(parents=True, exist_ok=True)
    gui_path = gui_dir / "index.html"
    sources = read_source_manifest(agentlas_dir).get("sources", [])
    html_text = build_gui_html(activation, sources)
    gui_path.write_text(html_text, encoding="utf-8")
    gui_url = gui_path.resolve().as_uri()
    opened = False
    if open_browser:
        try:
            opened = bool(webbrowser.open(gui_url))
        except Exception:
            opened = False
    return {
        "status": "gui_ready",
        "gui_path": str(gui_path),
        "gui_url": gui_url,
        "opened": opened,
        "project_root": activation["project_root"],
        "db_path": activation["db_path"],
        "inbox_path": activation["inbox_path"],
        "verify": activation["verify"],
        "sync_results": activation["sync_results"],
    }


def build_gui_html(activation: dict[str, Any], sources: list[dict[str, Any]]) -> str:
    verify_counts = activation.get("verify", {}).get("counts", {})
    sync_results = activation.get("sync_results", [])
    status = str(activation.get("verify", {}).get("status", "unknown"))
    project_root = str(activation.get("project_root", ""))
    inbox_path = str(activation.get("inbox_path", ""))
    db_path = str(activation.get("db_path", ""))
    source_count = int(verify_counts.get("sources", len(sources)) or 0)
    last_sync_count = len(sync_results)
    active_count = sum(1 for result in sync_results if int(result.get("sources", 0) or 0) > 0)
    memory_candidate_count = int(verify_counts.get("memory_candidates", 0) or 0)

    cards = [
        ("Sources", verify_counts.get("sources", 0), "Registered and ingested", "teal"),
        ("Chunks", verify_counts.get("chunks", 0), "Searchable evidence", "blue"),
        ("Entities", verify_counts.get("entities", 0), "Graph nodes", "violet"),
        ("Relations", verify_counts.get("relations", 0), "Graph edges", "amber"),
        ("Memory tickets", memory_candidate_count, "Curator queue", "rose"),
    ]
    card_html = "\n".join(
        (
            f"<article class=\"metric-card metric-{accent}\">"
            f"<span>{html.escape(label)}</span>"
            f"<strong>{html.escape(str(value))}</strong>"
            f"<small>{html.escape(caption)}</small>"
            "</article>"
        )
        for label, value, caption, accent in cards
    )
    source_html = source_table_html(sources)
    sync_html = sync_activity_html(sync_results)
    memory_html = memory_queue_html(memory_candidate_count)
    graph_html = graph_workspace_html(verify_counts, sources, project_root)
    source_chips = source_chips_html(sources)
    commands_html = command_list_html()
    project_name = Path(project_root).name or "Current Project"
    payload_json = json.dumps(
        {
            "project_root": project_root,
            "project_name": project_name,
            "inbox_path": inbox_path,
            "db_path": db_path,
            "status": status,
            "counts": verify_counts,
            "sources": sources,
            "sync_results": sync_results,
        },
        ensure_ascii=False,
        sort_keys=True,
    ).replace("</", "<\\/")
    template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Hephaestus Ontology</title>
  <link rel="icon" href="data:,">
  <style>
    :root {
      color-scheme: light;
      --bg: #f4f6f8;
      --surface: #ffffff;
      --surface-2: #eef2f6;
      --ink: #111827;
      --muted: #667085;
      --line: #d7dde5;
      --line-strong: #b8c2cf;
      --teal: #0f766e;
      --teal-soft: #d9f0ec;
      --blue: #2563eb;
      --blue-soft: #dce8ff;
      --violet: #6d28d9;
      --violet-soft: #ece6ff;
      --amber: #a15c07;
      --amber-soft: #fff0cf;
      --rose: #b42318;
      --rose-soft: #ffe4e0;
      --shadow: 0 12px 32px rgba(15, 23, 42, 0.08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    button, input, textarea, select {
      font: inherit;
    }
    button {
      cursor: pointer;
    }
    code {
      background: var(--surface-2);
      border: 1px solid var(--line);
      border-radius: 5px;
      padding: 2px 5px;
      overflow-wrap: anywhere;
    }
    .app-shell {
      display: grid;
      grid-template-columns: 248px minmax(0, 1fr);
      min-height: 100vh;
    }
    .sidebar {
      background: #0f172a;
      color: #eef2f7;
      padding: 18px 14px;
      display: flex;
      flex-direction: column;
      gap: 18px;
      min-width: 0;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 4px 6px 14px;
      border-bottom: 1px solid rgba(255,255,255,0.12);
    }
    .brand-mark {
      width: 34px;
      height: 34px;
      border-radius: 8px;
      background: #f8fafc;
      color: #0f172a;
      display: grid;
      place-items: center;
      font-weight: 800;
    }
    .brand strong,
    .brand span {
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .brand span {
      color: #b7c3d2;
      font-size: 12px;
    }
    .nav-section {
      display: grid;
      gap: 6px;
    }
    .nav-label {
      color: #94a3b8;
      font-size: 11px;
      font-weight: 700;
      text-transform: uppercase;
      padding: 0 8px;
    }
    .nav-item {
      width: 100%;
      border: 0;
      border-radius: 8px;
      background: transparent;
      color: #cbd5e1;
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 9px;
      text-align: left;
      min-height: 40px;
    }
    .nav-item:hover,
    .nav-item.is-active {
      background: rgba(255,255,255,0.1);
      color: #ffffff;
    }
    .nav-icon {
      width: 20px;
      height: 20px;
      border-radius: 6px;
      border: 1px solid rgba(255,255,255,0.22);
      display: grid;
      place-items: center;
      font-size: 11px;
      flex: 0 0 auto;
    }
    .sidebar-footer {
      margin-top: auto;
      display: grid;
      gap: 8px;
    }
    .status-pill {
      border: 1px solid rgba(255,255,255,0.16);
      border-radius: 8px;
      padding: 10px;
      background: rgba(255,255,255,0.06);
    }
    .status-pill span {
      display: block;
      color: #a8b6c8;
      font-size: 12px;
    }
    .status-pill strong {
      display: block;
      color: #ffffff;
      margin-top: 2px;
      overflow-wrap: anywhere;
    }
    .main {
      min-width: 0;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .topbar {
      position: sticky;
      top: 0;
      z-index: 10;
      background: rgba(244, 246, 248, 0.92);
      border-bottom: 1px solid var(--line);
      backdrop-filter: blur(14px);
    }
    .topbar-inner {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      padding: 16px 22px;
      min-width: 0;
    }
    .title-block {
      min-width: 0;
    }
    .title-block h1 {
      margin: 0;
      font-size: 21px;
      letter-spacing: 0;
      line-height: 1.2;
    }
    .title-block p {
      margin: 4px 0 0;
      color: var(--muted);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      justify-content: flex-end;
      gap: 8px;
    }
    .btn {
      min-height: 36px;
      border: 1px solid var(--line-strong);
      border-radius: 8px;
      background: var(--surface);
      color: var(--ink);
      padding: 8px 11px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      text-decoration: none;
      max-width: 100%;
    }
    .btn.primary {
      background: var(--teal);
      border-color: var(--teal);
      color: #ffffff;
    }
    .btn.ghost {
      background: transparent;
    }
    .icon {
      width: 17px;
      height: 17px;
      border-radius: 5px;
      border: 1px solid currentColor;
      display: inline-grid;
      place-items: center;
      font-size: 10px;
      line-height: 1;
      flex: 0 0 auto;
    }
    .content {
      padding: 22px;
      display: grid;
      gap: 18px;
      min-width: 0;
    }
    .view {
      display: none;
      gap: 18px;
    }
    .view.is-active {
      display: grid;
    }
    .dashboard-grid {
      display: grid;
      grid-template-columns: minmax(0, 1.5fr) minmax(280px, 0.8fr);
      gap: 18px;
      align-items: start;
    }
    .metrics-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(126px, 1fr));
      gap: 10px;
    }
    .metric-card,
    .panel,
    .table-shell,
    .graph-shell,
    .queue-item {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
    }
    .metric-card {
      min-height: 104px;
      padding: 13px;
      border-top-width: 4px;
      box-shadow: none;
    }
    .metric-card span,
    .section-label,
    .field-label {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }
    .metric-card strong {
      display: block;
      margin-top: 8px;
      font-size: 28px;
      line-height: 1;
    }
    .metric-card small {
      display: block;
      margin-top: 9px;
      color: var(--muted);
      overflow-wrap: anywhere;
    }
    .metric-teal { border-top-color: var(--teal); }
    .metric-blue { border-top-color: var(--blue); }
    .metric-violet { border-top-color: var(--violet); }
    .metric-amber { border-top-color: var(--amber); }
    .metric-rose { border-top-color: var(--rose); }
    .panel {
      padding: 16px;
      min-width: 0;
    }
    .panel-header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 14px;
      min-width: 0;
    }
    .panel-title h2,
    .panel-title h3 {
      margin: 0;
      font-size: 16px;
      letter-spacing: 0;
    }
    .panel-title p {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
    }
    .split {
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(240px, 0.46fr);
      gap: 14px;
      align-items: stretch;
    }
    .runtime-stack {
      display: grid;
      gap: 10px;
    }
    .runtime-row {
      display: grid;
      gap: 5px;
      min-width: 0;
    }
    .runtime-row code {
      display: block;
      white-space: normal;
    }
    .badge-row {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
    }
    .badge {
      border: 1px solid var(--line);
      background: var(--surface-2);
      border-radius: 999px;
      padding: 5px 8px;
      font-size: 12px;
      color: var(--muted);
      max-width: 100%;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .badge.pass {
      background: var(--teal-soft);
      border-color: #9ad5cc;
      color: #0d5d57;
    }
    .badge.warn {
      background: var(--amber-soft);
      border-color: #f3c76b;
      color: #6d3c02;
    }
    .badge.scope-private {
      background: var(--rose-soft);
      border-color: #ffbbb3;
      color: #8b1a12;
    }
    .badge.scope-internal {
      background: var(--blue-soft);
      border-color: #b8cdf8;
      color: #184aa5;
    }
    .badge.scope-public {
      background: var(--teal-soft);
      border-color: #9ad5cc;
      color: #0d5d57;
    }
    .graph-shell {
      min-height: 440px;
      overflow: hidden;
      display: grid;
      grid-template-rows: auto 1fr auto;
    }
    .graph-toolbar {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      padding: 12px;
      border-bottom: 1px solid var(--line);
    }
    .segmented {
      display: inline-flex;
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      background: var(--surface-2);
      flex: 0 0 auto;
    }
    .segmented button {
      border: 0;
      background: transparent;
      color: var(--muted);
      padding: 7px 10px;
      min-width: 74px;
    }
    .segmented button.is-active {
      background: var(--surface);
      color: var(--ink);
      box-shadow: inset 0 0 0 1px var(--line-strong);
    }
    .graph-canvas {
      position: relative;
      min-height: 330px;
      background:
        linear-gradient(var(--line) 1px, transparent 1px),
        linear-gradient(90deg, var(--line) 1px, transparent 1px),
        #f9fbfd;
      background-size: 28px 28px;
      overflow: hidden;
    }
    .graph-edge-layer {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
    }
    .graph-edge {
      stroke: #9aa7b5;
      stroke-width: 1.4;
      stroke-dasharray: 4 5;
    }
    .graph-node {
      position: absolute;
      width: 112px;
      min-height: 54px;
      border: 1px solid var(--line-strong);
      border-radius: 8px;
      background: var(--surface);
      color: var(--ink);
      padding: 8px;
      box-shadow: 0 8px 18px rgba(15, 23, 42, 0.12);
      text-align: left;
      overflow: hidden;
    }
    .graph-node strong {
      display: block;
      font-size: 13px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .graph-node span {
      display: block;
      margin-top: 3px;
      font-size: 12px;
      color: var(--muted);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .graph-node.root {
      left: 42%;
      top: 40%;
      background: #102033;
      color: #ffffff;
      border-color: #102033;
    }
    .graph-node.sources { left: 7%; top: 15%; }
    .graph-node.chunks { left: 30%; top: 10%; }
    .graph-node.entities { right: 18%; top: 14%; }
    .graph-node.relations { right: 7%; top: 48%; }
    .graph-node.memory { left: 22%; bottom: 14%; }
    .graph-node.is-selected {
      outline: 3px solid var(--blue-soft);
      border-color: var(--blue);
    }
    .graph-footer {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      padding: 12px;
      border-top: 1px solid var(--line);
      background: var(--surface);
    }
    .query-box {
      display: grid;
      gap: 10px;
    }
    .query-box textarea {
      width: 100%;
      min-height: 104px;
      resize: vertical;
      border: 1px solid var(--line-strong);
      border-radius: 8px;
      padding: 11px;
      color: var(--ink);
      background: #fbfcfd;
    }
    .result-list {
      display: grid;
      gap: 9px;
    }
    .result-row {
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 10px;
      background: #fbfcfd;
    }
    .result-row strong {
      display: block;
      font-size: 13px;
    }
    .result-row p {
      margin: 4px 0 0;
      color: var(--muted);
    }
    .table-toolbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      margin-bottom: 10px;
    }
    .search-input {
      width: min(360px, 100%);
      border: 1px solid var(--line-strong);
      border-radius: 8px;
      padding: 9px 10px;
      background: #fbfcfd;
      color: var(--ink);
    }
    .table-shell {
      padding: 14px;
      overflow: auto;
      box-shadow: none;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 680px;
    }
    th, td {
      text-align: left;
      border-bottom: 1px solid var(--line);
      padding: 10px 9px;
      vertical-align: top;
    }
    th {
      color: var(--muted);
      font-weight: 600;
      font-size: 12px;
    }
    tr:last-child td {
      border-bottom: 0;
    }
    td {
      overflow-wrap: anywhere;
    }
    .queue-list {
      display: grid;
      gap: 10px;
    }
    .queue-item {
      padding: 12px;
      box-shadow: none;
    }
    .queue-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 10px;
      margin-bottom: 8px;
    }
    .queue-item h3 {
      margin: 0;
      font-size: 14px;
    }
    .queue-item p {
      margin: 5px 0 0;
      color: var(--muted);
    }
    .queue-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      margin-top: 10px;
    }
    .command-list {
      display: grid;
      gap: 8px;
    }
    .command-row {
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 8px;
      background: #fbfcfd;
    }
    .command-row code {
      border: 0;
      background: transparent;
      padding: 0;
    }
    .empty-state {
      border: 1px dashed var(--line-strong);
      border-radius: 8px;
      background: #fbfcfd;
      padding: 16px;
      color: var(--muted);
    }
    .palette {
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.45);
      display: none;
      align-items: flex-start;
      justify-content: center;
      padding: 10vh 18px 18px;
      z-index: 40;
    }
    .palette.is-open {
      display: flex;
    }
    .palette-panel {
      width: min(720px, 100%);
      background: var(--surface);
      border-radius: 8px;
      border: 1px solid var(--line);
      box-shadow: 0 24px 60px rgba(15,23,42,0.28);
      overflow: hidden;
    }
    .palette-panel input {
      width: 100%;
      border: 0;
      border-bottom: 1px solid var(--line);
      padding: 14px 16px;
      outline: 0;
      color: var(--ink);
    }
    .palette-results {
      padding: 8px;
      display: grid;
      gap: 5px;
    }
    .palette-results button {
      width: 100%;
      border: 0;
      border-radius: 8px;
      background: transparent;
      text-align: left;
      padding: 10px;
      display: grid;
      gap: 3px;
    }
    .palette-results button:hover {
      background: var(--surface-2);
    }
    .toast {
      position: fixed;
      right: 18px;
      bottom: 18px;
      background: #111827;
      color: #ffffff;
      border-radius: 8px;
      padding: 10px 12px;
      display: none;
      z-index: 50;
    }
    .toast.is-visible {
      display: block;
    }
    .muted { color: var(--muted); }
    .strong {
      font-weight: 700;
    }
    [hidden] {
      display: none !important;
    }
    @media (max-width: 1120px) {
      .metrics-grid {
        grid-template-columns: repeat(3, minmax(126px, 1fr));
      }
      .dashboard-grid,
      .split {
        grid-template-columns: 1fr;
      }
    }
    @media (max-width: 820px) {
      .app-shell {
        grid-template-columns: 1fr;
      }
      .sidebar {
        position: static;
      }
      .nav-section {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      .nav-label {
        grid-column: 1 / -1;
      }
      .sidebar-footer {
        grid-template-columns: repeat(2, minmax(0, 1fr));
        margin-top: 0;
      }
      .topbar-inner {
        align-items: stretch;
        flex-direction: column;
      }
      .actions {
        justify-content: flex-start;
      }
      .metrics-grid {
        grid-template-columns: repeat(2, minmax(126px, 1fr));
      }
      .graph-node {
        width: 96px;
      }
      .graph-node.root { left: 36%; top: 41%; }
      .graph-node.entities { right: 6%; top: 12%; }
      .graph-node.relations { right: 4%; top: 53%; }
    }
    @media (max-width: 560px) {
      .content,
      .topbar-inner {
        padding: 14px;
      }
      .metrics-grid {
        grid-template-columns: 1fr;
      }
      .command-row,
      .table-toolbar,
      .panel-header {
        grid-template-columns: 1fr;
        display: grid;
      }
      .segmented {
        width: 100%;
      }
      .segmented button {
        flex: 1;
        min-width: 0;
      }
    }
  </style>
</head>
<body data-app="ontology-dashboard">
  <script id="ontology-data" type="application/json">__PAYLOAD_JSON__</script>
  <div class="app-shell">
    <aside class="sidebar" aria-label="Ontology navigation">
      <div class="brand">
        <div class="brand-mark">H</div>
        <div>
          <strong>Hephaestus Ontology</strong>
          <span>__PROJECT_NAME__</span>
        </div>
      </div>
      <nav class="nav-section">
        <div class="nav-label">Workspace</div>
        <button class="nav-item is-active" data-view-target="overview"><span class="nav-icon">O</span><span>Overview</span></button>
        <button class="nav-item" data-view-target="graph"><span class="nav-icon">G</span><span>Graph</span></button>
        <button class="nav-item" data-view-target="sources"><span class="nav-icon">S</span><span>Sources</span></button>
        <button class="nav-item" data-view-target="ask"><span class="nav-icon">Q</span><span>Ask</span></button>
        <button class="nav-item" data-view-target="memory"><span class="nav-icon">M</span><span>Memory</span></button>
        <button class="nav-item" data-view-target="commands"><span class="nav-icon">/</span><span>Commands</span></button>
      </nav>
      <div class="sidebar-footer">
        <div class="status-pill">
          <span>Runtime</span>
          <strong>__STATUS__</strong>
        </div>
        <div class="status-pill">
          <span>Indexed sources</span>
          <strong>__SOURCE_COUNT__</strong>
        </div>
      </div>
    </aside>
    <main class="main">
      <header class="topbar">
        <div class="topbar-inner">
          <div class="title-block">
            <h1>Ontology Command Center</h1>
            <p>__PROJECT_ROOT__</p>
          </div>
          <div class="actions">
            <button class="btn ghost" id="openPalette"><span class="icon">/</span>Palette</button>
            <button class="btn" data-copy="/hep-build ontology"><span class="icon">C</span>Copy slash</button>
            <button class="btn primary" data-copy="bin/hephaestus ontology --no-open ."><span class="icon">R</span>Resync</button>
          </div>
        </div>
      </header>
      <section class="content">
        <section class="view is-active" data-view="overview">
          <div class="metrics-grid">__CARD_HTML__</div>
          <div class="dashboard-grid">
            <section class="graph-shell" aria-label="Knowledge Graph preview">
              __GRAPH_HTML__
            </section>
            <section class="panel">
              <div class="panel-header">
                <div class="panel-title">
                  <h2>Runtime Scope</h2>
                  <p>Project-local only</p>
                </div>
                <span class="badge __STATUS_BADGE__">__STATUS__</span>
              </div>
              <div class="runtime-stack">
                <div class="runtime-row">
                  <span class="field-label">Inbox</span>
                  <code>__INBOX_PATH__</code>
                </div>
                <div class="runtime-row">
                  <span class="field-label">Database</span>
                  <code>__DB_PATH__</code>
                </div>
                <div class="runtime-row">
                  <span class="field-label">Source chips</span>
                  <div class="badge-row">__SOURCE_CHIPS__</div>
                </div>
              </div>
            </section>
          </div>
          <div class="split">
            <section class="panel">
              <div class="panel-header">
                <div class="panel-title">
                  <h2>Ask Ontology</h2>
                  <p>GraphRAG query surface</p>
                </div>
                <span class="badge scope-private">private opt-in</span>
              </div>
              <div class="query-box">
                <textarea id="overviewQuery">What does this company depend on?</textarea>
                <div class="badge-row">
                  <button class="btn primary" data-query-run="overviewQuery">Preview query</button>
                  <button class="btn" data-copy="bin/ontology query &quot;What does this company depend on?&quot; --scope private">Copy CLI</button>
                </div>
                <div class="result-list" id="overviewResults">
                  <div class="result-row">
                    <strong>Evidence-first answer path</strong>
                    <p>Queries return chunks, entities, relation edges, source spans, and Memory Curator candidate suggestions.</p>
                  </div>
                </div>
              </div>
            </section>
            <section class="panel">
              <div class="panel-header">
                <div class="panel-title">
                  <h2>Sync Activity</h2>
                  <p>__LAST_SYNC_COUNT__ path checks, __ACTIVE_SYNC_COUNT__ active</p>
                </div>
              </div>
              __SYNC_HTML__
            </section>
          </div>
        </section>

        <section class="view" data-view="graph">
          <section class="graph-shell" aria-label="Knowledge Graph">
            __GRAPH_HTML__
          </section>
        </section>

        <section class="view" data-view="sources">
          <section class="panel">
            <div class="panel-header">
              <div class="panel-title">
                <h2>Registered Sources</h2>
                <p>Inbox and explicit registrations only</p>
              </div>
              <button class="btn primary" data-copy="/hep-build ontology add ./company-docs --kind company --scope private"><span class="icon">C</span>Copy add</button>
            </div>
            <div class="table-toolbar">
              <input class="search-input" id="sourceSearch" placeholder="Filter sources" aria-label="Filter sources">
              <div class="segmented" aria-label="Source scope filter">
                <button class="is-active" data-scope-filter="all">All</button>
                <button data-scope-filter="public">Public</button>
                <button data-scope-filter="internal">Internal</button>
                <button data-scope-filter="private">Private</button>
              </div>
            </div>
            __SOURCE_HTML__
          </section>
        </section>

        <section class="view" data-view="ask">
          <section class="panel">
            <div class="panel-header">
              <div class="panel-title">
                <h2>Ask Ontology</h2>
                <p>Local GraphRAG command builder</p>
              </div>
              <div class="segmented" aria-label="Query scope">
                <button class="is-active" data-query-scope="internal">Internal</button>
                <button data-query-scope="private">Private</button>
                <button data-query-scope="public">Public</button>
              </div>
            </div>
            <div class="query-box">
              <textarea id="askQuery">Project Helios Memory Curator</textarea>
              <div class="badge-row">
                <button class="btn primary" data-query-run="askQuery">Preview query</button>
                <button class="btn" id="copyAskCommand"><span class="icon">C</span>Copy command</button>
              </div>
              <div class="result-list" id="askResults">
                <div class="result-row">
                  <strong>Ready</strong>
                  <p>Command builder ready. Scope and query determine the copied command.</p>
                </div>
              </div>
            </div>
          </section>
        </section>

        <section class="view" data-view="memory">
          <section class="panel">
            <div class="panel-header">
              <div class="panel-title">
                <h2>Memory Candidate Queue</h2>
                <p>Ontology suggests, Memory Curator decides</p>
              </div>
              <span class="badge scope-private">direct durable writes blocked</span>
            </div>
            <div class="queue-list">__MEMORY_HTML__</div>
          </section>
        </section>

        <section class="view" data-view="commands">
          <section class="panel">
            <div class="panel-header">
              <div class="panel-title">
                <h2>Command Palette</h2>
                <p>Copy exact commands</p>
              </div>
            </div>
            <div class="command-list">__COMMANDS_HTML__</div>
          </section>
        </section>
      </section>
    </main>
  </div>
  <div class="palette" id="palette" aria-hidden="true">
    <div class="palette-panel" role="dialog" aria-modal="true" aria-label="Ontology command palette">
      <input id="paletteInput" placeholder="Search views and commands">
      <div class="palette-results">
        <button data-palette-view="overview"><strong>Overview</strong><span class="muted">Dashboard and current runtime status</span></button>
        <button data-palette-view="graph"><strong>Knowledge Graph</strong><span class="muted">Obsidian-style graph workspace</span></button>
        <button data-palette-view="sources"><strong>Registered Sources</strong><span class="muted">Search and filter project-approved sources</span></button>
        <button data-palette-view="ask"><strong>Ask Ontology</strong><span class="muted">Build a local GraphRAG query command</span></button>
        <button data-palette-view="memory"><strong>Memory Candidate Queue</strong><span class="muted">Curator-ready suggestions</span></button>
      </div>
    </div>
  </div>
  <div class="toast" id="toast">Copied</div>
  <script>
    (() => {
      const data = JSON.parse(document.getElementById("ontology-data").textContent);
      const navItems = [...document.querySelectorAll("[data-view-target]")];
      const views = [...document.querySelectorAll("[data-view]")];
      const palette = document.getElementById("palette");
      const paletteInput = document.getElementById("paletteInput");
      const toast = document.getElementById("toast");
      let currentScope = "internal";

      function showToast(label) {
        toast.textContent = label || "Copied";
        toast.classList.add("is-visible");
        window.setTimeout(() => toast.classList.remove("is-visible"), 1400);
      }

      function setView(name) {
        navItems.forEach((item) => item.classList.toggle("is-active", item.dataset.viewTarget === name));
        views.forEach((view) => view.classList.toggle("is-active", view.dataset.view === name));
        closePalette();
      }

      function copyText(text) {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(text).then(() => showToast("Copied")).catch(() => fallbackCopy(text));
        } else {
          fallbackCopy(text);
        }
      }

      function fallbackCopy(text) {
        const area = document.createElement("textarea");
        area.value = text;
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        area.remove();
        showToast("Copied");
      }

      function openPalette() {
        palette.classList.add("is-open");
        palette.setAttribute("aria-hidden", "false");
        paletteInput.value = "";
        paletteInput.focus();
      }

      function closePalette() {
        palette.classList.remove("is-open");
        palette.setAttribute("aria-hidden", "true");
      }

      function renderQueryPreview(targetId) {
        const input = document.getElementById(targetId);
        const results = targetId === "askQuery" ? document.getElementById("askResults") : document.getElementById("overviewResults");
        const query = input.value.trim() || "Project ontology query";
        const counts = data.counts || {};
        results.innerHTML = [
          `<div class="result-row"><strong>Command</strong><p><code>bin/ontology query "${escapeHtml(query)}" --scope ${escapeHtml(currentScope)}</code></p></div>`,
          `<div class="result-row"><strong>Search plan</strong><p>${counts.chunks || 0} chunks, ${counts.entities || 0} entities, ${counts.relations || 0} relation edges available locally.</p></div>`,
          `<div class="result-row"><strong>Memory bridge</strong><p>Candidate tickets can be suggested, but durable memory promotion stays with Memory Curator.</p></div>`
        ].join("");
      }

      function escapeHtml(value) {
        return String(value).replace(/[&<>"']/g, (char) => ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#039;"
        }[char]));
      }

      navItems.forEach((item) => item.addEventListener("click", () => setView(item.dataset.viewTarget)));
      document.querySelectorAll("[data-copy]").forEach((button) => {
        button.addEventListener("click", () => copyText(button.dataset.copy));
      });
      document.querySelectorAll("[data-query-run]").forEach((button) => {
        button.addEventListener("click", () => renderQueryPreview(button.dataset.queryRun));
      });
      document.querySelectorAll("[data-query-scope]").forEach((button) => {
        button.addEventListener("click", () => {
          currentScope = button.dataset.queryScope;
          document.querySelectorAll("[data-query-scope]").forEach((item) => item.classList.toggle("is-active", item === button));
        });
      });
      document.getElementById("copyAskCommand").addEventListener("click", () => {
        const query = document.getElementById("askQuery").value.trim() || "Project ontology query";
        copyText(`bin/ontology query "${query.replace(/"/g, '\\"')}" --scope ${currentScope}`);
      });
      document.getElementById("openPalette").addEventListener("click", openPalette);
      palette.addEventListener("click", (event) => {
        if (event.target === palette) closePalette();
      });
      document.querySelectorAll("[data-palette-view]").forEach((button) => {
        button.addEventListener("click", () => setView(button.dataset.paletteView));
      });
      document.addEventListener("keydown", (event) => {
        const tag = document.activeElement && document.activeElement.tagName;
        const typing = tag === "INPUT" || tag === "TEXTAREA";
        if (event.key === "/" && !typing) {
          event.preventDefault();
          openPalette();
        }
        if (event.key === "Escape") closePalette();
      });

      const sourceSearch = document.getElementById("sourceSearch");
      if (sourceSearch) {
        const sourceRows = [...document.querySelectorAll("[data-source-row]")];
        let scopeFilter = "all";
        function applySourceFilter() {
          const term = sourceSearch.value.trim().toLowerCase();
          sourceRows.forEach((row) => {
            const text = row.textContent.toLowerCase();
            const scope = row.dataset.scope || "";
            row.hidden = (term && !text.includes(term)) || (scopeFilter !== "all" && scope !== scopeFilter);
          });
        }
        sourceSearch.addEventListener("input", applySourceFilter);
        document.querySelectorAll("[data-scope-filter]").forEach((button) => {
          button.addEventListener("click", () => {
            scopeFilter = button.dataset.scopeFilter;
            document.querySelectorAll("[data-scope-filter]").forEach((item) => item.classList.toggle("is-active", item === button));
            applySourceFilter();
          });
        });
      }

      document.querySelectorAll("[data-queue-action]").forEach((button) => {
        button.addEventListener("click", () => {
          const item = button.closest(".queue-item");
          const badge = item.querySelector("[data-queue-status]");
          badge.textContent = button.dataset.queueAction;
          badge.className = "badge";
          showToast("Queue status updated");
        });
      });

      document.querySelectorAll(".graph-node").forEach((node) => {
        node.addEventListener("click", () => {
          document.querySelectorAll(".graph-node").forEach((item) => item.classList.remove("is-selected"));
          node.classList.add("is-selected");
          showToast(node.dataset.nodeLabel || "Selected");
        });
      });
    })();
  </script>
</body>
</html>
"""
    replacements = {
        "__PROJECT_NAME__": html.escape(project_name),
        "__PROJECT_ROOT__": html.escape(project_root),
        "__INBOX_PATH__": html.escape(inbox_path),
        "__DB_PATH__": html.escape(db_path),
        "__STATUS__": html.escape(status),
        "__STATUS_BADGE__": "pass" if status == "pass" else "warn",
        "__SOURCE_COUNT__": html.escape(str(source_count)),
        "__LAST_SYNC_COUNT__": html.escape(str(last_sync_count)),
        "__ACTIVE_SYNC_COUNT__": html.escape(str(active_count)),
        "__CARD_HTML__": card_html,
        "__SOURCE_HTML__": source_html,
        "__SYNC_HTML__": sync_html,
        "__GRAPH_HTML__": graph_html,
        "__SOURCE_CHIPS__": source_chips,
        "__MEMORY_HTML__": memory_html,
        "__COMMANDS_HTML__": commands_html,
    }
    for key, value in replacements.items():
        template = template.replace(key, value)
    template = template.replace("__PAYLOAD_JSON__", payload_json)
    return template


def source_table_html(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return (
            "<div class=\"empty-state\">No registered source paths yet. "
            "The project inbox is still active.</div>"
        )
    rows: list[str] = []
    for source in sources:
        scope = str(source.get("scope") or "internal")
        kind = str(source.get("kind") or "project")
        path = str(source.get("path") or "")
        label = Path(path).name or path
        rows.append(
            "<tr data-source-row data-scope=\"{scope}\">"
            "<td><span class=\"badge\">{kind}</span></td>"
            "<td><span class=\"badge scope-{scope}\">{scope}</span></td>"
            "<td class=\"strong\">{label}</td>"
            "<td><code>{path}</code></td>"
            "</tr>".format(
                kind=html.escape(kind),
                scope=html.escape(scope),
                label=html.escape(label),
                path=html.escape(path),
            )
        )
    return (
        "<div class=\"table-shell\"><table>"
        "<thead><tr><th>Kind</th><th>Scope</th><th>Name</th><th>Path</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table></div>"
    )


def sync_activity_html(sync_results: list[dict[str, Any]]) -> str:
    if not sync_results:
        return "<div class=\"empty-state\">No sync activity in this run.</div>"
    rows = []
    for result in sync_results[:6]:
        path = str(result.get("path") or "")
        label = Path(path).name or path
        chunks = str(result.get("chunks_written", 0))
        entities = str(result.get("entities_written", 0))
        relations = str(result.get("relations_written", 0))
        skips = str(result.get("idempotent_skips", 0))
        rows.append(
            "<div class=\"result-row\">"
            f"<strong>{html.escape(label)}</strong>"
            f"<p>{html.escape(chunks)} chunks, {html.escape(entities)} entities, "
            f"{html.escape(relations)} relations, {html.escape(skips)} skips</p>"
            f"<p><code>{html.escape(path)}</code></p>"
            "</div>"
        )
    return "<div class=\"result-list\">" + "".join(rows) + "</div>"


def source_chips_html(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "<span class=\"badge\">inbox only</span>"
    chips = []
    for source in sources[:5]:
        scope = str(source.get("scope") or "internal")
        path = str(source.get("path") or "")
        label = Path(path).name or path
        chips.append(f"<span class=\"badge scope-{html.escape(scope)}\">{html.escape(label)}</span>")
    if len(sources) > 5:
        chips.append(f"<span class=\"badge\">+{len(sources) - 5} more</span>")
    return "".join(chips)


def memory_queue_html(candidate_count: int) -> str:
    if candidate_count <= 0:
        return (
            "<div class=\"empty-state\">No Memory Curator candidates yet. "
            "Query results can create source-backed tickets when useful.</div>"
        )
    rows = []
    for index in range(1, min(candidate_count, 4) + 1):
        rows.append(
            "<article class=\"queue-item\">"
            "<div class=\"queue-top\">"
            f"<div><h3>Candidate ticket {index}</h3>"
            "<p>Source-backed fact awaiting curator review.</p></div>"
            "<span class=\"badge warn\" data-queue-status>pending</span>"
            "</div>"
            "<div class=\"queue-actions\">"
            "<button class=\"btn\" data-queue-action=\"approved\">Approve</button>"
            "<button class=\"btn\" data-queue-action=\"quarantined\">Quarantine</button>"
            "<button class=\"btn\" data-queue-action=\"rejected\">Reject</button>"
            "</div>"
            "</article>"
        )
    return "".join(rows)


def graph_workspace_html(verify_counts: dict[str, Any], sources: list[dict[str, Any]], project_root: str) -> str:
    source_label = Path(project_root).name or "Project"
    source_total = verify_counts.get("sources", 0)
    chunks_total = verify_counts.get("chunks", 0)
    entities_total = verify_counts.get("entities", 0)
    relations_total = verify_counts.get("relations", 0)
    memory_total = verify_counts.get("memory_candidates", 0)
    if sources:
        source_label = Path(str(sources[0].get("path") or source_label)).name or source_label
    return f"""
      <div class="graph-toolbar">
        <div class="panel-title">
          <h2>Knowledge Graph</h2>
          <p>Obsidian-style project map</p>
        </div>
        <div class="segmented" aria-label="Graph mode">
          <button class="is-active">Map</button>
          <button>Edges</button>
          <button>Evidence</button>
        </div>
      </div>
      <div class="graph-canvas">
        <svg class="graph-edge-layer" viewBox="0 0 800 420" preserveAspectRatio="none" aria-hidden="true">
          <line class="graph-edge" x1="400" y1="210" x2="130" y2="95"></line>
          <line class="graph-edge" x1="400" y1="210" x2="290" y2="75"></line>
          <line class="graph-edge" x1="400" y1="210" x2="610" y2="90"></line>
          <line class="graph-edge" x1="400" y1="210" x2="690" y2="250"></line>
          <line class="graph-edge" x1="400" y1="210" x2="255" y2="330"></line>
        </svg>
        <button class="graph-node root" data-node-label="Project root"><strong>Project</strong><span>{html.escape(Path(project_root).name or "root")}</span></button>
        <button class="graph-node sources" data-node-label="Sources"><strong>Sources</strong><span>{html.escape(str(source_total))} indexed</span></button>
        <button class="graph-node chunks" data-node-label="Chunks"><strong>Chunks</strong><span>{html.escape(str(chunks_total))} evidence</span></button>
        <button class="graph-node entities" data-node-label="Entities"><strong>Entities</strong><span>{html.escape(str(entities_total))} nodes</span></button>
        <button class="graph-node relations" data-node-label="Relations"><strong>Relations</strong><span>{html.escape(str(relations_total))} edges</span></button>
        <button class="graph-node memory" data-node-label="Memory candidates"><strong>Memory</strong><span>{html.escape(str(memory_total))} tickets</span></button>
      </div>
      <div class="graph-footer">
        <span class="badge">focus: {html.escape(source_label)}</span>
        <span class="badge scope-internal">local FTS</span>
        <span class="badge scope-public">local vector</span>
        <span class="badge scope-private">curator gated</span>
      </div>
    """


def command_list_html() -> str:
    commands = [
        ("/hep-build ontology", "Open or refresh the ontology dashboard"),
        ("/hep-build ontology add ./company-docs --kind company --scope private", "Register a private source folder"),
        ("bin/hephaestus ontology --no-open .", "Terminal refresh without opening a browser"),
        ("bin/ontology query \"Project Helios Memory Curator\" --scope private", "Run a local GraphRAG query"),
        ("bin/ontology memory candidates", "List curator candidate tickets"),
    ]
    rows = []
    for command, label in commands:
        rows.append(
            "<div class=\"command-row\">"
            f"<div><code>{html.escape(command)}</code><div class=\"muted\">{html.escape(label)}</div></div>"
            f"<button class=\"btn\" data-copy=\"{html.escape(command, quote=True)}\">Copy</button>"
            "</div>"
        )
    return "".join(rows)
