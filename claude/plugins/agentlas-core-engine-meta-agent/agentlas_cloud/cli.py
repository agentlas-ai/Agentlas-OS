from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .runtime import AgentlasMockStore, compile_runtime_bundle, read_agent_file, run_setup_wizard, scan_agent_folder
from .update import maybe_print_update_notice, run_update, write_python_shims


def main(argv: list[str] | None = None) -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(prog="agentlas-cloud", description="Agentlas Cloud v1 local package tools")
    sub = parser.add_subparsers(dest="command", required=True)

    wizard = sub.add_parser("wizard", help="Generate or repair agentlas.json")
    wizard.add_argument("folder")
    wizard.add_argument("--name")
    wizard.add_argument("--no-write", action="store_true")

    security = sub.add_parser("security", help="Security commands")
    security_sub = security.add_subparsers(dest="security_command", required=True)
    scan = security_sub.add_parser("scan", help="Scan an agent folder (static rules + optional BYOK LLM judgment merge)")
    scan.add_argument("folder")
    scan.add_argument("--strict", action="store_true")
    scan.add_argument("--llm-judgment", help="Path to a security-llm-judgment.json file (default: <folder>/.agentlas/security-llm-judgment.json)")
    scan.add_argument("--acknowledge-warn", action="store_true", help="With --strict, treat an explicitly approved WARN verdict as pass")

    bundle = sub.add_parser("bundle", help="Compile runtime bundle")
    bundle.add_argument("folder")

    read = sub.add_parser("read-agent-file", help="Lazy file read with manifest gates")
    read.add_argument("folder")
    read.add_argument("path")

    sub.add_parser("field-test", help="Run local fixture field test")
    sub.add_parser("doctor", help="Diagnose and self-heal local Hephaestus runtime issues")
    update = sub.add_parser("update", help="Check for or install the latest Hephaestus runtime")
    update.add_argument("--check", action="store_true", help="Only report whether a newer release is available")

    auth = sub.add_parser("auth", help="Agentlas account sign-in for local runtimes")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    for auth_name in ("status", "login", "ensure", "logout"):
        auth_cmd = auth_sub.add_parser(auth_name)
        auth_cmd.add_argument("--base-url", default=None)
        if auth_name in {"login", "ensure"}:
            auth_cmd.add_argument("--no-open", action="store_true", help="Print the authorization URL instead of opening a browser")
            auth_cmd.add_argument("--timeout", type=int, default=180)

    plugins = sub.add_parser("plugins", help="Plugin discovery (local installs + Agentlas Hub)")
    plugins_sub = plugins.add_subparsers(dest="plugins_command", required=True)
    plugins_list = plugins_sub.add_parser("list", help="Scan locally installed plugins")
    plugins_list.add_argument("--project", default=".")
    plugins_resolve = plugins_sub.add_parser("resolve", help="Resolve a capability need from local + hub plugins")
    plugins_resolve.add_argument("query")
    plugins_resolve.add_argument("--project", default=".")
    plugins_resolve.add_argument("--no-hub", action="store_true", help="Skip the Agentlas Hub query (local scan only)")

    network = sub.add_parser("network", help="Hephaestus Network 2.0 (~/.agentlas/networking)")
    network_sub = network.add_subparsers(dest="network_command", required=True)
    network_sub.add_parser("init", help="Create or migrate the global networking structure (idempotent)")
    network_sub.add_parser("status", help="Card counts, benchmark state, auto-routing gate")
    network_add = network_sub.add_parser("add-source", help="Register a folder to index (never the home folder)")
    network_add.add_argument("path")
    network_remove = network_sub.add_parser("remove-source", help="Unregister an indexed folder")
    network_remove.add_argument("path")
    network_sub.add_parser("reindex", help="Re-import cards from registered sources and rebuild registry.sqlite")
    network_bench = network_sub.add_parser("bench", help="Run the routing benchmark suites")
    network_bench.add_argument("--suite", action="append", default=[], help="Path to a .jsonl suite (repeatable)")
    network_grant = network_sub.add_parser("grant", help="Record a legacy capability grant")
    network_grant.add_argument("capability")
    network_grant.add_argument("--target", required=True)
    network_grant.add_argument("--scope", default="per_call")
    network_grant.add_argument("--ttl", type=int, default=None)
    network_feedback = network_sub.add_parser("feedback", help="Record a routing correction (boost/suppress, never card promotion)")
    network_feedback.add_argument("query")
    network_feedback.add_argument("--chosen", default=None)
    network_feedback.add_argument("--correct", default=None)

    cards = sub.add_parser("cards", help="Routing card tools")
    cards_sub = cards.add_subparsers(dest="cards_command", required=True)
    cards_lint = cards_sub.add_parser("lint", help="Validate routing cards and report quality gates")
    cards_lint.add_argument("path", nargs="?", default=None, help="Folder to scan for routing-card.json (default: global cards)")
    cards_migrate = cards_sub.add_parser("migrate", help="Generate draft routing cards from existing packages")
    cards_migrate.add_argument("root")
    cards_migrate.add_argument("--tier", required=True, choices=["free", "paid", "plugin", "local"])
    cards_migrate.add_argument("--overwrite", action="store_true")
    cards_migrate.add_argument("--no-global", action="store_true", help="Write package-local cards only")

    ao = sub.add_parser("ao", help="Agent Ontology commands")
    ao_sub = ao.add_subparsers(dest="ao_command", required=True)
    ao_lint = ao_sub.add_parser("lint", help="Validate AO graph and grammar")
    ao_lint.add_argument("project", nargs="?", default=".")
    ao_migrate = ao_sub.add_parser("migrate", help="Build/rebuild canonical AO JSONL graph")
    ao_migrate.add_argument("project", nargs="?", default=".")
    ao_migrate.add_argument("--no-write", action="store_true", help="Dry-run only (do not write JSONL)")
    ao_migrate.add_argument("--overwrite", action="store_true", help="Overwrite existing AO directory")
    ao_graph = ao_sub.add_parser("graph", help="Print AO graph summary")
    ao_graph.add_argument("project", nargs="?", default=".")
    ao_graph.add_argument("--agent", default=None, help="Optional agent id filter")
    ao_query = ao_sub.add_parser("query", help="Run AO queries over the graph")
    ao_query.add_argument("query")
    ao_query.add_argument("project", nargs="?", default=".")
    ao_query.add_argument("--max", type=int, default=100, help="Unused placeholder for future pagination")
    ao_plan = ao_sub.add_parser("plan", help="Find AO path between two agents")
    ao_plan.add_argument("start", help="Source agent id")
    ao_plan.add_argument("target", help="Target agent id")
    ao_plan.add_argument("project", nargs="?", default=".")
    ao_plan.add_argument("--max-depth", type=int, default=5, help="Search depth")
    ao_plan.add_argument("--relation", default=None, help="Optional relation filter")
    ao_plan.add_argument("--allow-blocked", action="store_true", help="Allow paths through blocked edges")
    ao_diff = ao_sub.add_parser("diff", help="Diff AO graph against migration output")
    ao_diff.add_argument("project", nargs="?", default=".")
    ao_reach = ao_sub.add_parser("reachable", help="Alias for plan path lookup")
    ao_reach.add_argument("start")
    ao_reach.add_argument("target")
    ao_reach.add_argument("project", nargs="?", default=".")
    ao_reach.add_argument("--max-depth", type=int, default=6)
    ao_reach.add_argument("--relation", default=None)
    ao_reach.add_argument("--allow-blocked", action="store_true")
    ao_a2a = ao_sub.add_parser("a2a", help="A2A Agent Card import/export boundary")
    ao_a2a_sub = ao_a2a.add_subparsers(dest="a2a_command", required=True)
    ao_a2a_import = ao_a2a_sub.add_parser("import", help="Import an external A2A AgentCard (proposes aligned_with; never can_invoke)")
    ao_a2a_import.add_argument("card", help="Path to an A2A AgentCard JSON file")
    ao_a2a_import.add_argument("project", nargs="?", default=".")
    ao_a2a_export = ao_a2a_sub.add_parser("export", help="Export an internal agent as an A2A AgentCard")
    ao_a2a_export.add_argument("project", nargs="?", default=".")
    ao_a2a_export.add_argument("--agent", default=None, help="Agent id to export (default: local meta-agent)")
    ao_a2a_registry = ao_a2a_sub.add_parser("registry", help="Queryable A2A registry of internal agents (with identity blocks)")
    ao_a2a_registry.add_argument("project", nargs="?", default=".")
    ao_okf = ao_sub.add_parser("okf", help="OKF (Open Knowledge Format) bundle import/export")
    ao_okf_sub = ao_okf.add_subparsers(dest="okf_command", required=True)
    ao_okf_export = ao_okf_sub.add_parser("export", help="Serialize the AO graph to an OKF Markdown bundle (redaction-safe)")
    ao_okf_export.add_argument("project", nargs="?", default=".")
    ao_okf_export.add_argument("--out", default=None, help="Output bundle directory (default: .agentlas/okf-export)")
    ao_okf_import = ao_okf_sub.add_parser("import", help="Parse an external OKF bundle into nodes/edges (proposal only)")
    ao_okf_import.add_argument("bundle", help="Path to an OKF bundle directory")
    ao_okf_import.add_argument("project", nargs="?", default=".")
    ao_kernel = ao_sub.add_parser("kernel", help="Super-ontology kernel status (runtime-enforced seed contracts)")
    ao_kernel.add_argument("project", nargs="?", default=".")
    ao_pack = ao_sub.add_parser("pack", help="Build an installable Ontology Pack manifest")
    ao_pack.add_argument("project", nargs="?", default=".")
    ao_os = ao_sub.add_parser("os", help="Agent OS kernel-module surface (live status)")
    ao_os.add_argument("project", nargs="?", default=".")
    ao_catalog = ao_sub.add_parser("catalog", help="Knowledge Catalog descriptor over an OKF export (cross-runtime)")
    ao_catalog.add_argument("project", nargs="?", default=".")
    ao_catalog.add_argument("--out", default=None, help="OKF bundle output dir")
    ao_catalog.add_argument("--no-export", action="store_true", help="Describe without re-exporting the bundle")
    ao_pipeline = ao_sub.add_parser("pipeline", help="Plan a multi-stage pipeline via produces/consumes edges")
    ao_pipeline.add_argument("artifact", help="Target artifact the pipeline must produce")
    ao_pipeline.add_argument("project", nargs="?", default=".")

    route = sub.add_parser("route", help="Route a natural-language request to a local agent/team/plugin")
    route.add_argument("query")
    route.add_argument("--project", default=".")
    route.add_argument("--runtime", default="terminal")
    route.add_argument("--no-hub", action="store_true")
    route.add_argument("--approve-hub", action="store_true", help="Legacy no-op; Hub lookup already uses redacted keywords only")
    route.add_argument("--hub-only", action="store_true", help="Skip local cards and search Agentlas Hub marketplace only (/hep-network)")
    route.add_argument(
        "--scope",
        choices=["network", "cloud"],
        default="network",
        help="network = public Hub marketplace; cloud = the signed-in owner's OWN cloud packages (보관함). cloud implies --hub-only (/hep-cloud).",
    )
    route.add_argument(
        "--caller",
        default=None,
        help="Caller agent id for AO deny/require gating (agent-to-agent calls supply this; omit for top-level user routing).",
    )
    route.add_argument(
        "--session-inventory",
        default=None,
        help="JSON array of active host sessions for Stormbreaker pipeline scheduling (for example Codex, Claude, GLM, DeepSeek).",
    )
    route.add_argument("--auto-run", action="store_true", help="When routing returns a pipeline execution_fabric, run it with Stormbreaker.")
    route.add_argument("--plan-only", action="store_true", help="Return the route/plan only, even when --auto-run is present.")
    route.add_argument("--background", action="store_true", help="With --auto-run, detach the Stormbreaker packet runner.")
    route.add_argument(
        "--executor-command",
        default=None,
        help="With --auto-run, shell command launched once per packet. Packet data is exposed through STORMBREAKER_* env vars.",
    )
    route.add_argument(
        "--execute-card-commands",
        action="store_true",
        help="With --auto-run, execute non-slash card canonical_command values as shell commands.",
    )
    route.add_argument("--max-workers", type=int, default=None, help="With --auto-run, maximum concurrent packet workers.")
    route.add_argument("--timeout", type=int, default=900, help="With --auto-run, per-packet executor timeout in seconds.")

    stormbreaker = sub.add_parser("stormbreaker", help="Stormbreaker packet runner")
    stormbreaker_sub = stormbreaker.add_subparsers(dest="stormbreaker_command", required=True)
    stormbreaker_run = stormbreaker_sub.add_parser("run", help="Route and execute a pipeline execution_fabric")
    stormbreaker_run.add_argument("query", nargs="?", help="Natural-language pipeline request")
    stormbreaker_run.add_argument("--decision-file", default=None, help="Run an existing route decision JSON instead of routing a query")
    stormbreaker_run.add_argument("--project", default=".")
    stormbreaker_run.add_argument("--runtime", default="terminal")
    stormbreaker_run.add_argument("--no-hub", action="store_true")
    stormbreaker_run.add_argument("--approve-hub", action="store_true", help="Legacy no-op; Hub lookup already uses redacted keywords only")
    stormbreaker_run.add_argument("--hub-only", action="store_true", help="Skip local cards and search Agentlas Hub marketplace only")
    stormbreaker_run.add_argument("--scope", choices=["network", "cloud"], default="network")
    stormbreaker_run.add_argument("--caller", default=None)
    stormbreaker_run.add_argument(
        "--session-inventory",
        default=None,
        help="JSON array of active host sessions; packets in the same parallel group can run concurrently.",
    )
    stormbreaker_run.add_argument(
        "--executor-command",
        default=None,
        help="Shell command launched once per packet. Packet data is exposed through STORMBREAKER_* env vars.",
    )
    stormbreaker_run.add_argument(
        "--execute-card-commands",
        action="store_true",
        help="Execute card canonical_command values as shell commands when they are not slash commands.",
    )
    stormbreaker_run.add_argument("--background", action="store_true", help="Detach the runner and write logs/results under .agentlas/stormbreaker/background/")
    stormbreaker_run.add_argument("--output-file", default=None, help=argparse.SUPPRESS)
    stormbreaker_run.add_argument("--max-workers", type=int, default=None)
    stormbreaker_run.add_argument("--timeout", type=int, default=900, help="Per-packet executor timeout in seconds")

    local_gui = sub.add_parser("local-gui", help=argparse.SUPPRESS)
    local_gui.add_argument("query")
    local_gui.add_argument("--no-open", action="store_true")
    local_gui.add_argument("--detach", action="store_true")
    local_gui.add_argument("--quiet-not-found", action="store_true")
    local_gui.add_argument("--allow-local", action="store_true", help=argparse.SUPPRESS)
    local_gui.add_argument("--local-first", action="store_true", help=argparse.SUPPRESS)

    search = sub.add_parser("search", help="Show top owner-cloud and public Hub agent candidates without invoking")
    search.add_argument("query")
    search.add_argument("--project", default=".")
    search.add_argument("--runtime", default="terminal")
    search.add_argument("--limit", type=int, default=10, help="Candidates per section (default 10, max 25)")

    call = sub.add_parser("call", help="Prepare explicitly named Hub/cloud agents")
    call.add_argument("agents", help="Comma-separated slugs, for example: hub:agent-a, cloud:agent-b")
    call.add_argument("context", nargs="*", help="Task context passed to the named agents")
    call.add_argument("--context", dest="context_text", default=None, help="Context string (alternative to positional context)")
    call.add_argument("--project", default=".")
    call.add_argument("--runtime", default="terminal")
    call.add_argument("--version", default="latest")
    call.add_argument("--local-inventory", default=None, help="JSON array or comma list of installed plugin names for Hub plugin resolution")

    mcp = sub.add_parser("mcp", help="MCP integration")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    mcp_sub.add_parser("serve", help="Serve the network router as a local stdio MCP server")

    args = parser.parse_args(argv)
    if args.command == "wizard":
        return emit(run_setup_wizard(args.folder, args.name, write=not args.no_write))
    if args.command == "security" and args.security_command == "scan":
        report = scan_agent_folder(args.folder, llm_judgment_path=args.llm_judgment)
        emit(report)
        if args.strict:
            if report["verdict"] == "BLOCK":
                return 1
            if report["verdict"] == "WARN" and not args.acknowledge_warn:
                return 2
        return 0
    if args.command == "bundle":
        return emit(compile_runtime_bundle(args.folder))
    if args.command == "read-agent-file":
        return emit(read_agent_file(args.folder, args.path))
    if args.command == "field-test":
        return emit(run_field_test())
    if args.command == "doctor":
        return emit(run_doctor())
    if args.command == "update":
        return emit(run_update(check_only=args.check))
    if args.command == "auth":
        from .auth import AgentlasAuthError, auth_status, ensure_access_token, login, logout, normalize_base_url, token_path

        if args.auth_command == "status":
            return emit(auth_status(args.base_url))
        if args.auth_command == "logout":
            return emit(logout(args.base_url))
        try:
            if args.auth_command == "login":
                result = login(args.base_url, open_browser=not args.no_open, timeout_seconds=args.timeout)
            elif args.auth_command == "ensure":
                token = ensure_access_token(
                    args.base_url,
                    interactive=True,
                    open_browser=not args.no_open,
                    timeout_seconds=args.timeout,
                )
                result = {
                    "status": "authenticated" if token else "signed_out",
                    "base_url": normalize_base_url(args.base_url),
                    "token_path": str(token_path(args.base_url)),
                }
            else:
                parser.error("unhandled auth command")
        except AgentlasAuthError as exc:
            return emit({"status": "error", "error": str(exc), "token_path": str(token_path(args.base_url))}) or 1
        # Never print token values from the CLI.
        result.pop("access_token", None)
        return emit(result)
    if args.command == "plugins":
        from .plugin_discovery import resolve_plugins, scan_local_plugins

        if args.plugins_command == "list":
            return emit(scan_local_plugins(args.project))
        if args.plugins_command == "resolve":
            return emit(resolve_plugins(args.query, args.project, use_hub=not args.no_hub))
    if args.command == "network":
        from . import networking

        if args.network_command == "init":
            return emit(networking.init_networking())
        if args.network_command == "status":
            return emit(networking.network_status())
        if args.network_command == "add-source":
            return emit(networking.add_source(args.path))
        if args.network_command == "remove-source":
            return emit(networking.remove_source(args.path))
        if args.network_command == "reindex":
            return emit(networking.reindex())
        if args.network_command == "bench":
            from .networking.bench import run_bench

            suites = args.suite or [
                str(Path(__file__).resolve().parent.parent / "benchmarks" / "routing" / name)
                for name in ("seed.jsonl", "privacy.jsonl", "edges.jsonl")
            ]
            report = run_bench(suites)
            emit(report)
            return 0 if report["passed"] else 1
        if args.network_command == "grant":
            from .networking.approvals import record_grant

            return emit(record_grant(args.capability, args.target, scope=args.scope, ttl_seconds=args.ttl))
        if args.network_command == "feedback":
            from .networking.memory import record_feedback
            from .networking.tokenize import tokenize

            return emit(record_feedback(tokenize(args.query), args.chosen, args.correct))
    if args.command == "cards":
        if args.cards_command == "lint":
            from .networking.bootstrap import networking_home, read_json
            from .networking.card_lint import lint_card

            reports = []
            if args.path:
                for card_file in sorted(Path(args.path).rglob(".agentlas/routing-card.json")):
                    payload = read_json(card_file)
                    if isinstance(payload, dict):
                        report = lint_card(payload)
                        report["path"] = str(card_file)
                        reports.append(report)
                    else:
                        reports.append({"path": str(card_file), "errors": ["malformed JSON"], "allowed_status": "quarantined"})
            else:
                from .networking.card_store import load_global_cards

                cards_loaded, quarantined = load_global_cards(networking_home())
                for card in cards_loaded:
                    report = lint_card(card)
                    report["path"] = card.get("_card_path")
                    reports.append(report)
                for item in quarantined:
                    reports.append({"path": item["path"], "errors": [item["reason"]], "allowed_status": "quarantined"})
            errors = sum(1 for report in reports if report.get("errors"))
            emit({"cards": len(reports), "with_errors": errors, "reports": reports})
            return 1 if errors else 0
        if args.cards_command == "migrate":
            from .networking.bootstrap import networking_home
            from .networking.card_migrate import migrate_tree

            home = None if args.no_global else networking_home()
            if home is not None:
                from .networking import init_networking

                init_networking(home)
            return emit(migrate_tree(args.root, tier=args.tier, home=home, overwrite=args.overwrite))
    if args.command == "mcp" and args.mcp_command == "serve":
        from .mcp_stdio import serve

        return serve()
    if args.command == "search":
        from .networking import init_networking, search_agents
        from .networking.bootstrap import networking_home

        maybe_print_update_notice()
        init_networking(networking_home())
        return emit(
            search_agents(
                args.query,
                project_dir=args.project,
                runtime=args.runtime,
                limit=args.limit,
            )
        )
    if args.command == "call":
        from .networking import call_agents, init_networking
        from .networking.bootstrap import networking_home
        from .networking.search_call import parse_local_inventory

        maybe_print_update_notice()
        init_networking(networking_home())
        context = args.context_text or " ".join(args.context).strip()
        if not context:
            return emit({"action": "agent_call", "status": "error", "error": "context is required"}) or 2
        return emit(
            call_agents(
                args.agents,
                context,
                project_dir=args.project,
                runtime=args.runtime,
                version=args.version,
                local_inventory=parse_local_inventory(args.local_inventory),
            )
        )
    if args.command == "route":
        from .networking import init_networking, route_request
        from .networking.bootstrap import networking_home
        from .networking.stormbreaker_runner import run_stormbreaker_decision

        maybe_print_update_notice()
        home = networking_home()
        init_networking(home)
        session_inventory = None
        if args.session_inventory:
            try:
                session_inventory = json.loads(args.session_inventory)
                if not isinstance(session_inventory, list):
                    raise ValueError("session inventory must be a JSON array")
            except (json.JSONDecodeError, ValueError) as exc:
                emit({"action": "route", "status": "error", "error": f"invalid --session-inventory: {exc}"})
                return 2
        decision = route_request(
            args.query,
            project_dir=args.project,
            runtime=args.runtime,
            use_hub=not args.no_hub,
            hub_approved=args.approve_hub,
            hub_only=args.hub_only,
            scope=args.scope,
            caller_id=getattr(args, "caller", None),
            session_inventory=session_inventory,
        )
        if args.auto_run and not args.plan_only:
            if decision.get("action") == "pipeline" and isinstance(decision.get("execution_fabric"), dict):
                if args.background:
                    return emit(_start_stormbreaker_background(args, decision=decision))
                result = run_stormbreaker_decision(
                    decision,
                    home=home,
                    project_dir=args.project,
                    executor_command=args.executor_command,
                    execute_card_commands=args.execute_card_commands,
                    max_workers=args.max_workers,
                    timeout_seconds=args.timeout,
                )
                result["route_decision"] = {
                    "action": decision.get("action"),
                    "receipt_id": decision.get("receipt_id"),
                    "match_reason": decision.get("match_reason"),
                }
                emit(result)
                return 0 if result.get("status") == "completed" else 1
            decision["auto_run"] = {
                "status": "skipped",
                "reason": "route decision did not include a runnable pipeline execution_fabric",
                "runner": "hep-storm",
            }
        return emit(decision)
    if args.command == "stormbreaker" and args.stormbreaker_command == "run":
        from .networking import init_networking
        from .networking.bootstrap import networking_home
        from .networking.stormbreaker_runner import run_stormbreaker_decision, run_stormbreaker_query

        maybe_print_update_notice()
        home = networking_home()
        init_networking(home)
        session_inventory = None
        if args.session_inventory:
            try:
                session_inventory = json.loads(args.session_inventory)
                if not isinstance(session_inventory, list):
                    raise ValueError("session inventory must be a JSON array")
            except (json.JSONDecodeError, ValueError) as exc:
                emit({"action": "stormbreaker_run", "status": "error", "error": f"invalid --session-inventory: {exc}"})
                return 2

        if args.background:
            if not args.query and not args.decision_file:
                emit({"action": "stormbreaker_run", "status": "error", "error": "query or --decision-file is required"})
                return 2
            return emit(_start_stormbreaker_background(args))

        if args.decision_file:
            try:
                decision = json.loads(Path(args.decision_file).read_text(encoding="utf-8"))
            except OSError as exc:
                emit({"action": "stormbreaker_run", "status": "error", "error": f"cannot read --decision-file: {exc}"})
                return 2
            except json.JSONDecodeError as exc:
                emit({"action": "stormbreaker_run", "status": "error", "error": f"invalid --decision-file JSON: {exc}"})
                return 2
            result = run_stormbreaker_decision(
                decision,
                home=home,
                project_dir=args.project,
                executor_command=args.executor_command,
                execute_card_commands=args.execute_card_commands,
                max_workers=args.max_workers,
                timeout_seconds=args.timeout,
            )
        else:
            if not args.query:
                emit({"action": "stormbreaker_run", "status": "error", "error": "query or --decision-file is required"})
                return 2
            result = run_stormbreaker_query(
                args.query,
                home=home,
                project_dir=args.project,
                runtime=args.runtime,
                use_hub=not args.no_hub,
                hub_approved=args.approve_hub,
                hub_only=args.hub_only,
                scope=args.scope,
                caller_id=args.caller,
                session_inventory=session_inventory,
                executor_command=args.executor_command,
                execute_card_commands=args.execute_card_commands,
                max_workers=args.max_workers,
                timeout_seconds=args.timeout,
            )
        emit(result)
        if args.output_file:
            from .networking.bootstrap import atomic_write_json

            atomic_write_json(Path(args.output_file), result)
        if result.get("status") == "completed":
            return 0
        if result.get("status") in {"blocked", "not_executed"}:
            return 1
        return 2
    if args.command == "local-gui":
        from .networking import init_networking
        from .networking.bootstrap import networking_home
        from .networking.gui_shortcut import open_local_gui_shortcut

        init_networking(networking_home())
        result = open_local_gui_shortcut(
            args.query,
            no_open=args.no_open,
            detach=args.detach,
            allow_local=args.allow_local,
            local_first=args.local_first,
        )
        if not (args.quiet_not_found and result.get("action") == "no_local_gui_shortcut"):
            emit(result)
        if result.get("action") == "no_local_gui_shortcut":
            return 4
        return 0 if result.get("status") in {"opened", "opening"} else 1
    if args.command == "ao":
        from .agent_graph import (
            describe_graph,
            diff_ontology,
            load_graph,
            execute_query,
            migrate_ontology,
            plan_path,
            validate_graph,
        )
        if args.ao_command == "lint":
            result = validate_graph(args.project)
            emit(result)
            # Non-zero exit on invalid graph so CI / commit gates actually block.
            return 0 if result.get("valid") else 1
        if args.ao_command == "migrate":
            return emit(
                migrate_ontology(
                    project_root=args.project,
                    write=not args.no_write,
                    overwrite=args.overwrite,
                )
            )
        if args.ao_command == "graph":
            graph = describe_graph(args.project)
            if args.agent:
                on_disk = load_graph(args.project)
                agents = [agent for agent in on_disk.get("graph", {}).get("agents", []) if str(agent.get("id")) == args.agent]
                graph = {
                    "path": graph["path"],
                    "agent": agents[0] if agents else None,
                    "counts": {"agents": len(agents), "edges": 0, "artifacts": 0, "capabilities": 0},
                    "found": bool(agents),
                }
            return emit(graph)
        if args.ao_command == "query":
            return emit(execute_query(args.query, project_root=args.project))
        if args.ao_command in {"plan", "reachable"}:
            return emit(
                plan_path(
                    project_root=args.project,
                    start=args.start,
                    target=args.target,
                    max_depth=args.max_depth,
                    relation=args.relation,
                    allow_blocked=args.allow_blocked,
                )
            )
        if args.ao_command == "diff":
            result = diff_ontology(args.project)
            emit(result)
            # Non-zero exit on drift so `ao diff` can gate CI (plan §12).
            return 0 if result.get("status") == "clean" else 1
        if args.ao_command == "a2a":
            from .agent_graph import export_agent_card, import_agent_card

            if args.a2a_command == "import":
                try:
                    card = json.loads(Path(args.card).read_text(encoding="utf-8"))
                except OSError as exc:
                    return emit({"status": "error", "error": f"cannot read card file: {exc}"}) or 2
                except json.JSONDecodeError as exc:
                    return emit({"status": "error", "error": f"invalid JSON in card file: {exc}"}) or 2
                if not isinstance(card, dict):
                    return emit({"status": "error", "error": "agent card must be a JSON object"}) or 2
                return emit(import_agent_card(card, project_root=args.project))
            if args.a2a_command == "export":
                return emit(export_agent_card(project_root=args.project, agent_id=args.agent))
            if args.a2a_command == "registry":
                from .agent_graph import build_a2a_registry

                return emit(build_a2a_registry(args.project))
            return emit({"status": "error", "message": f"unknown a2a command: {args.a2a_command}"}) or 2
        if args.ao_command == "okf":
            from .agent_graph import from_okf_bundle, to_okf_bundle

            if args.okf_command == "export":
                try:
                    return emit(to_okf_bundle(project_root=args.project, out_dir=args.out))
                except OSError as exc:
                    return emit({"status": "error", "error": f"cannot write OKF bundle: {exc}"}) or 2
            if args.okf_command == "import":
                return emit(from_okf_bundle(args.bundle))
            return emit({"status": "error", "message": f"unknown okf command: {args.okf_command}"}) or 2
        if args.ao_command == "kernel":
            from .agent_graph import load_kernel, verify_enforcement

            kernel = load_kernel(args.project)
            verification = verify_enforcement(args.project)
            emit({"kernel": kernel, "verification": verification})
            return 0 if verification.get("all_enforced") else 1
        if args.ao_command == "pack":
            from .agent_graph import build_pack

            return emit(build_pack(args.project))
        if args.ao_command == "os":
            from .agent_graph import os_surface

            surface = os_surface(args.project)
            emit(surface)
            return 0 if surface.get("all_live") else 1
        if args.ao_command == "catalog":
            from .agent_graph import knowledge_catalog_descriptor

            try:
                return emit(
                    knowledge_catalog_descriptor(args.project, okf_dir=args.out, export=not args.no_export)
                )
            except OSError as exc:
                return emit({"status": "error", "error": f"cannot write catalog bundle: {exc}"}) or 2
        if args.ao_command == "pipeline":
            from .agent_graph import plan_pipeline_ao

            return emit(plan_pipeline_ao(args.project, args.artifact))
        return emit({"status": "error", "message": f"unknown ao command: {args.ao_command}"}) or 2
    parser.error("unhandled command")
    return 2


def emit(payload: Any) -> int:
    configure_utf8_stdio()
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def configure_utf8_stdio() -> None:
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass


def _start_stormbreaker_background(args: argparse.Namespace, decision: dict[str, Any] | None = None) -> dict[str, Any]:
    import uuid
    from .networking.bootstrap import atomic_write_json

    project = Path(args.project).expanduser().resolve()
    run_id = uuid.uuid4().hex[:12]
    run_dir = project / ".agentlas" / "stormbreaker" / "background" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    result_file = run_dir / "result.json"
    stdout_file = run_dir / "stdout.log"
    stderr_file = run_dir / "stderr.log"
    decision_file = None
    if decision is not None:
        decision_file = run_dir / "decision.json"
        atomic_write_json(decision_file, decision)
    child_argv = _stormbreaker_child_argv(args, result_file, decision_file=decision_file)
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    with stdout_file.open("w", encoding="utf-8") as out, stderr_file.open("w", encoding="utf-8") as err:
        process = subprocess.Popen(
            child_argv,
            cwd=os.getcwd(),
            env=env,
            stdout=out,
            stderr=err,
            text=True,
            start_new_session=True,
        )
    return {
        "action": "stormbreaker_run",
        "status": "background_started",
        "run_id": run_id,
        "pid": process.pid,
        "result_file": str(result_file),
        "stdout_file": str(stdout_file),
        "stderr_file": str(stderr_file),
        "decision_file": str(decision_file) if decision_file else None,
        "route_receipt_id": decision.get("receipt_id") if decision else None,
    }


def _stormbreaker_child_argv(args: argparse.Namespace, result_file: Path, decision_file: Path | None = None) -> list[str]:
    child = [sys.executable, "-m", "agentlas_cloud", "stormbreaker", "run"]
    if decision_file is not None:
        child.extend(["--decision-file", str(decision_file)])
    elif args.query:
        child.append(args.query)
    if decision_file is None and getattr(args, "decision_file", None):
        child.extend(["--decision-file", args.decision_file])
    child.extend(["--project", args.project])
    child.extend(["--runtime", args.runtime])
    child.extend(["--scope", args.scope])
    child.extend(["--timeout", str(args.timeout)])
    child.extend(["--output-file", str(result_file)])
    if args.no_hub:
        child.append("--no-hub")
    if args.approve_hub:
        child.append("--approve-hub")
    if args.hub_only:
        child.append("--hub-only")
    if args.caller:
        child.extend(["--caller", args.caller])
    if args.session_inventory:
        child.extend(["--session-inventory", args.session_inventory])
    if args.executor_command:
        child.extend(["--executor-command", args.executor_command])
    if args.execute_card_commands:
        child.append("--execute-card-commands")
    if args.max_workers is not None:
        child.extend(["--max-workers", str(args.max_workers)])
    return child


def run_doctor() -> dict[str, Any]:
    root = Path(__file__).resolve().parent.parent
    bin_dir = root / "bin"
    release = (root / "RELEASE").read_text(encoding="utf-8").strip() if (root / "RELEASE").exists() else None
    checks: dict[str, Any] = {
        "platform": platform.platform(),
        "runtime_root": str(root),
        "release": release,
        "current_python": {
            "executable": sys.executable,
            "version": platform.python_version(),
            "stdout_encoding": getattr(sys.stdout, "encoding", None),
            "PYTHONUTF8": os.environ.get("PYTHONUTF8"),
            "PYTHONIOENCODING": os.environ.get("PYTHONIOENCODING"),
        },
        "external_python3": _probe_python_command("python3"),
        "python3_shim": str(bin_dir / "python3"),
        "actions": [],
    }
    external = checks["external_python3"]
    needs_shim = not external.get("ok") or "WindowsApps" in str(external.get("path") or "")
    if needs_shim:
        try:
            _write_python_shims(bin_dir, sys.executable)
            checks["actions"].append("wrote bin/python3 and bin/python3.cmd shim to current Python")
            checks["external_python3_after_shim"] = _probe_python_command(str(bin_dir / "python3"))
        except OSError as exc:
            checks["actions"].append(f"python3 shim failed: {exc}")
    if release is None:
        checks["actions"].append("missing RELEASE marker; reinstall with scripts/install-all-runtimes.sh")
    checks["status"] = "warn" if checks["actions"] else "ok"
    return checks


def _probe_python_command(command: str) -> dict[str, Any]:
    path = shutil.which(command) if os.sep not in command else command
    result: dict[str, Any] = {"command": command, "path": path, "ok": False}
    if not path:
        result["error"] = "not found"
        return result
    try:
        completed = subprocess.run(
            [path, "-c", "import sys,json; print(json.dumps({'version': sys.version.split()[0], 'executable': sys.executable}))"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except OSError as exc:
        result["error"] = str(exc)
        return result
    result["returncode"] = completed.returncode
    result["stdout"] = completed.stdout.strip()[:200]
    result["stderr"] = completed.stderr.strip()[:200]
    if completed.returncode == 0:
        try:
            result.update(json.loads(completed.stdout))
        except ValueError:
            pass
        result["ok"] = True
    elif completed.stdout.strip() == "Python" or "WindowsApps" in str(path):
        result["store_stub"] = True
    return result


def _write_python_shims(bin_dir: Path, executable: str) -> None:
    write_python_shims(bin_dir, executable)


def run_field_test() -> dict[str, Any]:
    base = Path(".agentlas/field-test/hephaestus").resolve()
    if base.exists():
        shutil.rmtree(base)
    agent = base / "mac_a" / "instagram-operator"
    (agent / "skills" / "social-media-strategist").mkdir(parents=True, exist_ok=True)
    (agent / ".agentlas").mkdir(parents=True, exist_ok=True)
    (agent / "AGENTS.md").write_text("# Instagram Operator\n\nBuild weekly Instagram posts.\n", encoding="utf-8")
    (agent / "skills" / "social-media-strategist" / "SKILL.md").write_text(
        "---\nname: social-media-strategist\ndescription: Use for social content.\n---\n\nCreate social plans.\n",
        encoding="utf-8",
    )
    (agent / ".agentlas" / "memory-map.json").write_text('{"project":"instagram-operator"}\n', encoding="utf-8")
    wizard = run_setup_wizard(agent, "instagram-operator")
    bundle = compile_runtime_bundle(agent)
    allowed = read_agent_file(agent, "AGENTS.md")
    denied = read_agent_file(agent, ".env")
    store = AgentlasMockStore()
    record = store.upload_private(
        {
            "agentId": "agent_private_instagram",
            "ownerId": "owner",
            "creatorId": "creator",
            "version": "1.0.0",
            "manifest": wizard["manifest"],
            "files": [{"path": "AGENTS.md", "content": (agent / "AGENTS.md").read_text(encoding="utf-8")}],
            "memory": {"scope": "private", "summary": "private campaign memory", "deltas": ["weekly cadence"]},
        }
    )
    public = store.publish_clean_copy("owner", record["agentId"], "agent_public_instagram")
    denied_download = store.download("other_user", public["agentId"])
    public_call = store.call_agent("other_user", public["agentId"])
    scenarios = [
        ("E1", wizard["status"] == "Ready for MCP call", [str(agent / "agentlas.json"), str(agent / ".agentlas" / "security-scan.json")]),
        ("E2", bundle["entry"]["path"] == "AGENTS.md" and allowed["status"] == "allowed" and denied["status"] == "denied", [str(agent / "agentlas.json")]),
        ("E3", denied_download["status"] == "denied" and public_call["status"] == "PASS", ["in-memory-store", "invocation-ledger"]),
    ]
    report = {
        "suite": "hephaestus-agentlas-cloud-field-test",
        "status": "PASS" if all(item[1] for item in scenarios) else "FAIL",
        "scenarios": [
            {"id": item[0], "status": "PASS" if item[1] else "FAIL", "evidence": item[2], "blockers": [] if item[1] else ["scenario failed"]}
            for item in scenarios
        ],
        "ledger": store.invocation_ledger,
    }
    Path(".agentlas/field-test-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    raise SystemExit(main())
