from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from .runtime import AgentlasMockStore, compile_runtime_bundle, read_agent_file, run_setup_wizard, scan_agent_folder
from .update import maybe_auto_update, reconcile_adapters, run_update, write_python_shims


RESEARCH_SEARCH_PROVIDERS = ("ddg-html", "news-rss", "github", "jina")
RESEARCH_SEARCH_PROVIDER_MODULES = {
    "ddg-html": "search.ddg_html",
    "news-rss": "search.news_rss",
    "github": "search.github_repos",
    "jina": "search.jina",
}
RESEARCH_SEARCH_PROVIDER_HINTS = {
    "ddg-html": "ddg_html",
    "news-rss": "news_rss",
    "github": "github",
    "jina": "jina",
}
AGENTLAS_BROWSER_MODULE = "browser.agent_cli"


def _project_bootstrap_receipt(
    project: str | Path,
    reason: str,
    *,
    requested: bool = False,
    trusted_contact: bool = False,
) -> dict[str, Any]:
    from .project_bootstrap import auto_bootstrap_enabled, ensure_project, maybe_ensure_project

    if requested or trusted_contact:
        try:
            return ensure_project(project, reason=reason)
        except (OSError, TimeoutError, ValueError):
            return {
                "action": "project_bootstrap",
                "status": "error",
                "reason": reason,
                "detail": "project_bootstrap_failed",
                "writeAttempted": True,
            }

    return maybe_ensure_project(
        project,
        reason=reason,
        enabled=auto_bootstrap_enabled(),
    )


def _plugin_contact_runtime(runtime: str | None) -> bool:
    normalized = str(runtime or "").strip().lower()
    return normalized not in {"", "terminal", "cli", "shell"}


def _project_bootstrap_blocks_execution(receipt: Mapping[str, Any]) -> bool:
    if receipt.get("status") == "active":
        return False
    if receipt.get("status") != "privacy_warning":
        return True
    return not (
        receipt.get("privacyBlockInstalled") is True
        and receipt.get("privateModeCompliant") is True
        and not (receipt.get("missing") or [])
        and not (receipt.get("permissionIssues") or [])
    )


def _emit_blocked_project_bootstrap(receipt: Mapping[str, Any]) -> int:
    detail = receipt.get("detail") or "project_bootstrap_incomplete"
    emit(
        {
            "action": "project_bootstrap",
            "status": "blocked",
            "detail": detail,
            "project_bootstrap": dict(receipt),
        }
    )
    return 2


def _configure_stormbreaker_run_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("query", nargs="?", help="Natural-language pipeline request")
    parser.add_argument("--decision-file", default=None, help="Run an existing route decision JSON instead of routing a query")
    parser.add_argument("--project", default=".")
    parser.add_argument(
        "--ensure-project",
        action="store_true",
        help="Explicitly install/refresh private .agentlas project state before this run.",
    )
    parser.add_argument("--runtime", default="terminal")
    parser.add_argument("--no-hub", action="store_true")
    parser.add_argument("--approve-hub", action="store_true", help="Legacy no-op; Hub lookup already uses redacted keywords only")
    parser.add_argument("--hub-only", action="store_true", help="Skip local cards and search Agentlas Hub marketplace only")
    parser.add_argument("--scope", choices=["network", "cloud"], default="network")
    parser.add_argument("--caller", default=None)
    parser.add_argument(
        "--brief",
        default=None,
        help="Path to a Work Brief JSON or a project dir containing .agentlas/work-brief.json. The compact brief is attached to every execution packet.",
    )
    parser.add_argument(
        "--session-inventory",
        default=None,
        help="JSON array of active host sessions; packets in the same parallel group can run concurrently.",
    )
    parser.add_argument(
        "--executor-command",
        default=None,
        help="Shell command launched once per packet. Packet data is exposed through STORMBREAKER_* env vars.",
    )
    parser.add_argument(
        "--execute-card-commands",
        action="store_true",
        help="Execute card canonical_command values as shell commands when they are not slash commands.",
    )
    parser.add_argument("--background", action="store_true", help="Detach the runner and write logs/results under .agentlas/stormbreaker/background/")
    parser.add_argument("--output-file", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--max-workers", type=int, default=None)
    parser.add_argument(
        "--max-replans",
        type=int,
        default=2,
        help="Maximum bounded repair/replan passes after the initial pipeline execution.",
    )
    parser.add_argument("--timeout", type=int, default=900, help="Per-packet executor timeout in seconds")
    parser.add_argument("--research-evidence", action="store_true", help="Attach Research Engine receipts to research/planning packets.")
    parser.add_argument("--research-loadout", default="safe", choices=["auto", "safe", "public-web", "social", "browser", "full", "recommended"], help="With --research-evidence, choose the detachable research module loadout or let Stormbreaker recommend one.")
    parser.add_argument("--research-depth", default="quick", choices=["quick", "deep"], help="With --research-evidence, choose quick or deep follow-up reads.")
    parser.add_argument("--research-follow-results", type=int, default=1, help="With --research-evidence, read the top N search results, bounded to 10.")
    parser.add_argument("--research-variant", action="append", default=[], help="With --research-evidence, add a bounded query variant such as docs, github, reddit, threads, or news.")


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

    package_cmd = sub.add_parser("package", help="Package and statically review an agent folder for Cloud/Hub upload")
    package_cmd.add_argument("folder")
    package_cmd.add_argument("--slug")
    package_cmd.add_argument("--visibility", choices=["marketplace", "private-link"], default="marketplace")
    package_cmd.add_argument("--no-write", action="store_true", help="Do not refresh agentlas.json before review")

    publish_cmd = sub.add_parser("publish", help="Register a reviewed package with Agentlas Cloud or Hub")
    publish_cmd.add_argument("folder")
    publish_cmd.add_argument("--slug")
    publish_cmd.add_argument("--visibility", choices=["marketplace", "private-link"], default="marketplace")
    publish_cmd.add_argument("--base-url", default=None)
    publish_cmd.add_argument("--dry-run", action="store_true", help="Package and review without registering")
    publish_cmd.add_argument("--no-open", action="store_true", help="Do not open a browser for sign-in")

    read = sub.add_parser("read-agent-file", help="Lazy file read with manifest gates")
    read.add_argument("folder")
    read.add_argument("path")

    sub.add_parser("field-test", help="Run local fixture field test")
    sub.add_parser("doctor", help="Diagnose and self-heal local Hephaestus runtime issues")
    update = sub.add_parser("update", help="Check for or install the latest Hephaestus runtime")
    update.add_argument("--check", action="store_true", help="Only report whether a newer release is available")

    global_router = sub.add_parser("global", help="Install or remove Hephaestus global router prompt blocks")
    global_sub = global_router.add_subparsers(dest="global_command", required=True)
    for global_name in ("install", "remove", "status"):
        global_cmd = global_sub.add_parser(global_name)
        global_cmd.add_argument("--home", default=None, help="Home directory to modify (default: current user's home)")
        global_cmd.add_argument(
            "--target",
            action="append",
            choices=["codex", "claude", "antigravity"],
            default=[],
            help="Target host prompt file. Repeatable; defaults to codex, claude, and antigravity.",
        )
        if global_name in {"install", "remove"}:
            global_cmd.add_argument("--no-backup", action="store_true", help="Do not write a timestamped backup before editing")
            global_cmd.add_argument("--dry-run", action="store_true", help="Report what would change without writing files")

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

    project_cmd = sub.add_parser("project", help="Canonical local project bootstrap shared by every Agentlas host")
    project_sub = project_cmd.add_subparsers(dest="project_command", required=True)
    project_ensure = project_sub.add_parser("ensure", help="Create or repair missing local Agentlas project state")
    project_ensure.add_argument("--project", default=".")
    project_ensure.add_argument("--reason", default="explicit-project-ensure")
    project_ensure.add_argument("--refresh-code-map", action="store_true")
    project_status = project_sub.add_parser("status", help="Inspect bootstrap and privacy state without writing")
    project_status.add_argument("--project", default=".")

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
    cards_migrate.add_argument("--tier", required=True, choices=["restricted", "private", "plugin", "local"])
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

    route = sub.add_parser("route", help="Route a natural-language request through Agentlas Hub by default")
    route.add_argument("query")
    route.add_argument("--project", default=".")
    route.add_argument(
        "--ensure-project",
        action="store_true",
        help="Explicitly install/refresh private .agentlas project state before routing.",
    )
    route.add_argument("--runtime", default="terminal")
    route.add_argument("--no-hub", action="store_true")
    route.add_argument("--approve-hub", action="store_true", help="Legacy no-op; Hub lookup already uses redacted keywords only")
    route.add_argument("--hub-only", action="store_true", help="Skip local cards and search Agentlas Hub marketplace only (default unless --allow-local-routing is set)")
    route.add_argument("--allow-local-routing", action="store_true", help=argparse.SUPPRESS)
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
    route.add_argument(
        "--brief",
        default=None,
        help="Path to a Work Brief JSON (briefing interview output) or a project dir containing .agentlas/work-brief.json. Extends stage detection and rides along into pipeline packets.",
    )
    route.add_argument("--auto-run", action="store_true", help="When routing returns a pipeline execution_fabric, run it with Stormbreaker.")
    route.add_argument("--plan-only", action="store_true", help="Return the route/plan only, even when --auto-run is present.")
    route.add_argument("--background", action="store_true", help="With --auto-run, detach the Stormbreaker packet runner.")
    route.add_argument("--research-evidence", action="store_true", help="With --auto-run, attach Research Engine receipts to research/planning packets.")
    route.add_argument("--research-loadout", default="safe", choices=["auto", "safe", "public-web", "social", "browser", "full", "recommended"], help="With --research-evidence, choose the detachable research module loadout or let Stormbreaker recommend one.")
    route.add_argument("--research-depth", default="quick", choices=["quick", "deep"], help="With --research-evidence, choose quick or deep follow-up reads.")
    route.add_argument("--research-follow-results", type=int, default=1, help="With --research-evidence, read the top N search results, bounded to 10.")
    route.add_argument("--research-variant", action="append", default=[], help="With --research-evidence, add a bounded query variant such as docs, github, reddit, threads, or news.")
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
    stormbreaker_sub.add_parser(
        "harness",
        help="Print the canonical Goal + UltraCode harness contract for host runtimes",
    )
    stormbreaker_run = stormbreaker_sub.add_parser("run", help="Route and execute a pipeline execution_fabric")
    _configure_stormbreaker_run_parser(stormbreaker_run)
    stormbreaker_shortcut = sub.add_parser(
        "hep-storm",
        help="Cross-platform shortcut for 'stormbreaker run'",
    )
    _configure_stormbreaker_run_parser(stormbreaker_shortcut)

    stormbreaker_journal = stormbreaker_sub.add_parser(
        "journal", help="Inspect or repair a run journal so an interrupted run can resume"
    )
    journal_sub = stormbreaker_journal.add_subparsers(dest="journal_command", required=True)
    for journal_name in ("status", "verify", "repair", "gate"):
        journal_cmd = journal_sub.add_parser(journal_name)
        journal_cmd.add_argument("--run-id", default=None, help="Run id under .agentlas/stormbreaker/journal/")
        journal_cmd.add_argument("--journal", default=None, help="Explicit journal path (overrides --run-id/--project)")
        journal_cmd.add_argument("--project", default=".")
        if journal_name == "status":
            journal_cmd.add_argument("--loop-threshold", type=int, default=3, help="Restarts of one step before a hard stop")
        if journal_name == "repair":
            journal_cmd.add_argument("--reason", default="interrupted")
        if journal_name == "gate":
            journal_cmd.add_argument("--allow-unverified", action="store_true", help="Do not block on completed-but-unverified steps")

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
    search.add_argument("--ensure-project", action="store_true", help="Explicitly bootstrap private project state before search.")
    search.add_argument("--runtime", default="terminal")
    search.add_argument("--limit", type=int, default=10, help="Candidates per section (default 10, max 25)")

    call = sub.add_parser("call", help="Prepare explicitly named Hub/cloud agents")
    call.add_argument("agents", help="Comma-separated slugs, for example: hub:agent-a, cloud:agent-b")
    call.add_argument("context", nargs="*", help="Task context passed to the named agents")
    call.add_argument("--context", dest="context_text", default=None, help="Context string (alternative to positional context)")
    call.add_argument("--project", default=".")
    call.add_argument("--ensure-project", action="store_true", help="Explicitly bootstrap private project state before the call.")
    call.add_argument("--runtime", default="terminal")
    call.add_argument("--version", default="latest")
    call.add_argument("--local-inventory", default=None, help="JSON array or comma list of installed plugin names for Hub plugin resolution")

    hep_browser = sub.add_parser("hep-browser", help="Short Agentlas browser hardpoint command")
    hep_browser.add_argument("target", nargs="*", help="URL(s) to open or task/search text")
    hep_browser.add_argument("--url", action="append", default=[], help="Explicit http/https URL to read through Agentlas browser")
    hep_browser.add_argument("--query", default=None, help="Task/search text when URLs are supplied")
    hep_browser.add_argument("--provider", action="append", choices=RESEARCH_SEARCH_PROVIDERS, default=[], help="Search provider for query mode, repeatable")
    hep_browser.add_argument("--variant", action="append", default=[], help="Search query variant, repeatable: official, docs, github, reddit, threads, news, or a short literal suffix")
    hep_browser.add_argument("--depth", default="deep", choices=["quick", "deep"], help="Use deep browser follow-up reads by default")
    hep_browser.add_argument("--follow-results", type=int, default=2, help="Read top N result URLs in query mode, bounded by request budget")
    hep_browser.add_argument("--max-requests", type=int, default=None, help="Optional request budget for search and follow-up reads")
    hep_browser.add_argument("--home", default=None, help="Networking home for hardpoint config and receipts")
    hep_browser.add_argument("--raw-url", action="store_true", help="Do not normalize known app-shell URLs to human-facing entry URLs")
    hep_browser.add_argument("--act", action="append", default=[], help="Browser automation instruction. If omitted, non-URL words after a URL become the instruction.")
    hep_browser.add_argument("--read", action="store_true", help="Force read-only browser snapshot even when URL text includes extra words")
    hep_browser.add_argument("--cdp", default=None, help="Pass a Chrome DevTools Protocol port or URL to agent-browser")
    hep_browser.add_argument("--profile", default=None, help="Pass an agent-browser Chrome profile name/path")
    hep_browser.add_argument("--auto-connect", action="store_true", help="Ask agent-browser to auto-connect to a running browser")
    hep_browser.add_argument("--headed", action="store_true", help="Run agent-browser headed when it launches a browser")
    hep_browser.add_argument("--keep-open", action="store_true", help="Keep the agent-browser session open after automation")
    hep_browser.add_argument("--wait-ms", type=int, default=0, help="Wait after primitive actions before the final snapshot")
    hep_browser.add_argument("--click", action="append", default=[], help="Click an explicit agent-browser selector/ref, for example @e1")
    hep_browser.add_argument("--click-text", action="append", default=[], help="Find visible text and click it without requiring an LLM")
    hep_browser_mode = hep_browser.add_mutually_exclusive_group()
    hep_browser_mode.add_argument("--setup", action="store_true", help="Arm the approved npx agent-browser hardpoint recipe")
    hep_browser_mode.add_argument("--check", action="store_true", help="Run one configured Agentlas browser hardpoint check")

    research = sub.add_parser("research", help="Agentlas Research Engine phase-0 tools")
    research_sub = research.add_subparsers(dest="research_command", required=True)
    research_doctor = research_sub.add_parser("doctor", help="Diagnose research engine readiness without running modules")
    research_doctor.add_argument("--home", default=None, help="Networking home to scan for research proof receipts")
    research_status = research_sub.add_parser("status", help="Summarize research engine goal readiness without running modules")
    research_status.add_argument("--home", default=None, help="Networking home to scan for research proof receipts")
    research_credentials = research_sub.add_parser("credentials", help="Show secret-safe Reddit/Threads credential setup state")
    research_credentials.add_argument("--home", default=None, help="Networking home to scan for research proof receipts")
    research_social_fallbacks = research_sub.add_parser("social-fallbacks", help="Explain no-token Reddit/Threads/public-page fallback coverage")
    research_social_fallbacks.add_argument("--home", default=None, help="Networking home to include local hardpoint config in readiness")
    research_proofs = research_sub.add_parser("proofs", help="List research live proof receipts without running modules")
    research_proofs.add_argument("--home", default=None, help="Networking home to scan for research proof receipts")
    research_proofs.add_argument("--limit", type=int, default=50, help="Recent receipt summaries to include, max 200")
    research_verify = research_sub.add_parser("verify", help="Run live public/browser checks and ready credentialed checks")
    research_verify.add_argument("--home", default=None, help="Networking home for research receipts")
    research_verify.add_argument("--skip-public", action="store_true", help="Skip public Reddit/Threads fallback checks")
    research_verify.add_argument("--skip-browser", action="store_true", help="Skip browser hardpoint check")
    research_verify.add_argument("--skip-credentialed", action="store_true", help="Skip credentialed Reddit/Threads checks even when configured")
    research_verify.add_argument("--browser-url", default="https://example.com", help="Public URL to use for the browser hardpoint check")
    research_hardpoints = research_sub.add_parser("hardpoints", help="List or configure approved local browser hardpoints")
    research_hardpoints.add_argument("--home", default=None, help="Networking home for local hardpoint config")
    hardpoint_action = research_hardpoints.add_mutually_exclusive_group()
    hardpoint_action.add_argument("--arm", choices=["browser.agent_cli"], default="", help="Enable an approved hardpoint recipe")
    hardpoint_action.add_argument("--disarm", choices=["browser.agent_cli"], default="", help="Disable a configured hardpoint")
    research_hardpoints.add_argument("--recipe", choices=["npx-agent-browser"], default="npx-agent-browser", help="Approved recipe to arm")
    research_sub.add_parser("modules", help="List detachable research modules and weights")
    research_armory = research_sub.add_parser("armory", help="List research modules with local readiness checks")
    research_armory.add_argument("--loadout", default="auto", choices=["auto", "safe", "public-web", "social", "browser", "full"])
    research_armory.add_argument("--slot", default="", choices=["", "search", "reader", "platform", "browser"], help="Filter by module slot")
    research_armory.add_argument("--home", default=None, help="Networking home to include local hardpoint config in readiness")
    research_profile = research_sub.add_parser("profile", help="Compare loadout footprint, weight, and readiness without running modules")
    research_profile.add_argument("--loadout", default="", choices=["", "auto", "safe", "public-web", "social", "browser", "full"])
    research_profile.add_argument("--source", action="append", default=[], help="Optional source hint to consider for source-aware auto loadout, repeatable")
    research_profile.add_argument("--home", default=None, help="Networking home to include local hardpoint config in readiness")
    research_recommend = research_sub.add_parser("recommend", help="Recommend a detachable research loadout without running modules")
    research_recommend.add_argument("query", nargs="+")
    research_recommend.add_argument("--source", action="append", default=[], help="Optional source hint or URL to consider, repeatable")
    research_recommend.add_argument("--home", default=None, help="Networking home to include local hardpoint config in readiness")
    research_preflight = research_sub.add_parser("preflight", help="Preview recommended module mounts before running build research")
    research_preflight.add_argument("query", nargs="+")
    research_preflight.add_argument("--source", action="append", default=[], help="Optional source hint or URL to consider, repeatable")
    research_preflight.add_argument("--loadout", default="recommended", choices=["auto", "safe", "public-web", "social", "browser", "full", "recommended"])
    research_preflight.add_argument("--depth", default="quick", choices=["quick", "deep"])
    research_preflight.add_argument("--follow-results", type=int, default=None, help="Override recommended follow-up read count")
    research_preflight.add_argument("--variant", action="append", default=[], help="Override recommended query variants")
    research_preflight.add_argument("--max-requests", type=int, default=None, help="Override recommended request budget")
    research_preflight.add_argument("--max-weight", default="", choices=["", "light", "external_light", "adaptive_medium", "credentialed_medium", "browser_heavy"])
    research_preflight.add_argument("--allow-module", action="append", default=[], help="Additional allowed module id, repeatable")
    research_preflight.add_argument("--forbid-module", action="append", default=[], help="Forbidden module id, repeatable")
    research_preflight.add_argument("--home", default=None, help="Networking home to include local hardpoint config in readiness")
    research_bridge = research_sub.add_parser("bridge-contract", help="Describe browser hardpoint command contracts without running them")
    research_bridge.add_argument("--module", default="", help="Browser module id to describe, for example browser.stagehand")
    research_browser_candidates = research_sub.add_parser("browser-candidates", help="List source-backed browser hardpoint candidates without running them")
    research_browser_candidates.add_argument("--module", default="", help="Browser module id to inspect, for example browser.agent_cli")
    research_browser_candidates.add_argument("--query", default="", help="Optional task text for a read-only browser hardpoint recommendation")
    research_browser_candidates.add_argument("--home", default=None, help="Networking home to include local hardpoint config in readiness")
    research_bridge_check = research_sub.add_parser("bridge-check", help="Run one configured browser hardpoint against a URL")
    research_bridge_check.add_argument("--module", required=True, help="Browser module id to check, for example browser.stagehand")
    research_bridge_check.add_argument("--url", required=True, help="Public http/https URL to read through the hardpoint")
    research_bridge_check.add_argument("--home", default=None, help="Networking home for research receipts")
    research_platform = research_sub.add_parser("platform-contract", help="Describe Reddit/Threads platform cartridge contracts")
    research_platform.add_argument("--module", default="", help="Platform module id to describe, for example platform.threads")
    research_platform_check = research_sub.add_parser("platform-check", help="Run one selected Reddit/Threads platform cartridge")
    research_platform_check.add_argument("--module", required=True, help="Platform module id to check, for example platform.threads")
    research_platform_check.add_argument("--source", required=True, help="Platform source hint, for example threads:keyword:agent browser")
    research_platform_check.add_argument("--home", default=None, help="Networking home for research receipts")
    research_sub.add_parser("loadouts", help="List named research module loadouts")
    research_plan = research_sub.add_parser("plan", help="Preview module routing without running network or browser work")
    research_plan.add_argument("source_hints", nargs="*")
    research_plan.add_argument("--query", default=None)
    research_plan.add_argument("--search", action="store_true", help="Preview search:auto expansion for the query")
    research_plan.add_argument("--provider", action="append", choices=RESEARCH_SEARCH_PROVIDERS, default=[], help="Search provider to preview, repeatable")
    research_plan.add_argument("--variant", action="append", default=[], help="Search query variant, repeatable: official, docs, github, reddit, threads, news, or a short literal suffix")
    research_plan.add_argument("--loadout", default="auto", choices=["auto", "safe", "public-web", "social", "browser", "full", "recommended"])
    research_plan.add_argument("--depth", default="quick", choices=["quick", "deep"])
    research_plan.add_argument("--max-weight", default=None, choices=["light", "external_light", "adaptive_medium", "credentialed_medium", "browser_heavy"])
    research_plan.add_argument("--max-requests", type=int, default=None, help="Optional request budget for source expansion and follow-up reads")
    research_plan.add_argument("--follow-results", type=int, default=0)
    research_plan.add_argument("--home", default=None, help="Accepted for symmetry; plan does not write receipts")
    research_plan.add_argument("--allow-module", action="append", default=[], help="Allowed module id, repeatable")
    research_plan.add_argument("--forbid-module", action="append", default=[], help="Forbidden module id, repeatable")
    research_read = research_sub.add_parser("read", help="Read explicit URLs through the lightweight research core")
    research_read.add_argument("urls", nargs="+")
    research_read.add_argument("--query", default=None)
    research_read.add_argument("--loadout", default="auto", choices=["auto", "safe", "public-web", "social", "browser", "full", "recommended"])
    research_read.add_argument("--depth", default="quick", choices=["quick", "deep"], help="quick stops at first usable reader; deep also mounts one configured browser snapshot when allowed.")
    research_read.add_argument("--max-weight", default=None, choices=["light", "external_light", "adaptive_medium", "credentialed_medium", "browser_heavy"], help="Override the mounted loadout's module weight ceiling.")
    research_read.add_argument("--max-requests", type=int, default=None, help="Optional request budget for source expansion and follow-up reads")
    research_read.add_argument("--follow-results", type=int, default=0, help="Read the top N discovered result URLs after platform/search fallback, bounded to 10.")
    research_read.add_argument("--home", default=None, help="Networking home for research receipts")
    research_read.add_argument("--allow-module", action="append", default=[], help="Allowed module id, repeatable")
    research_read.add_argument("--forbid-module", action="append", default=[], help="Forbidden module id, repeatable")
    research_search = research_sub.add_parser("search", help="Search the web through an explicitly selected research module")
    research_search.add_argument("query", nargs="+")
    research_search.add_argument("--provider", choices=RESEARCH_SEARCH_PROVIDERS, default="ddg-html")
    research_search.add_argument("--variant", action="append", default=[], help="Search query variant, repeatable: official, docs, github, reddit, threads, news, or a short literal suffix")
    research_search.add_argument("--loadout", default="auto", choices=["auto", "safe", "public-web", "social", "browser", "full", "recommended"])
    research_search.add_argument("--depth", default="quick", choices=["quick", "deep"], help="Use deep follow-up reads when browser modules are mounted.")
    research_search.add_argument("--max-weight", default=None, choices=["light", "external_light", "adaptive_medium", "credentialed_medium", "browser_heavy"], help="Override the mounted loadout's module weight ceiling.")
    research_search.add_argument("--max-requests", type=int, default=None, help="Optional request budget for source expansion and follow-up reads")
    research_search.add_argument("--follow-results", type=int, default=0, help="Read the top N result URLs after search, bounded to 10.")
    research_search.add_argument("--home", default=None, help="Networking home for research receipts")
    research_search.add_argument("--allow-module", action="append", default=[], help="Additional allowed module id, repeatable")
    research_search.add_argument("--forbid-module", action="append", default=[], help="Forbidden module id, repeatable")
    research_gather = research_sub.add_parser("gather", help="Fan out search modules, then read top result URLs")
    research_gather.add_argument("query", nargs="+")
    research_gather.add_argument("--provider", action="append", choices=RESEARCH_SEARCH_PROVIDERS, default=[], help="Search provider to mount, repeatable. Defaults to the selected loadout.")
    research_gather.add_argument("--variant", action="append", default=[], help="Search query variant, repeatable: official, docs, github, reddit, threads, news, or a short literal suffix")
    research_gather.add_argument("--loadout", default="public-web", choices=["auto", "safe", "public-web", "social", "browser", "full", "recommended"])
    research_gather.add_argument("--depth", default="quick", choices=["quick", "deep"], help="Use deep follow-up reads when browser modules are mounted.")
    research_gather.add_argument("--max-weight", default=None, choices=["light", "external_light", "adaptive_medium", "credentialed_medium", "browser_heavy"], help="Override the mounted loadout's module weight ceiling.")
    research_gather.add_argument("--max-requests", type=int, default=None, help="Optional request budget for source expansion and follow-up reads")
    research_gather.add_argument("--follow-results", type=int, default=3, help="Read the top N result URLs after search, bounded to 10.")
    research_gather.add_argument("--home", default=None, help="Networking home for research receipts")
    research_gather.add_argument("--allow-module", action="append", default=[], help="Additional allowed module id, repeatable")
    research_gather.add_argument("--forbid-module", action="append", default=[], help="Forbidden module id, repeatable")

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
    if args.command == "package":
        from .upload import UploadError, package_agent

        try:
            result = package_agent(args.folder, slug=args.slug, visibility=args.visibility, write_manifest=not args.no_write)
        except UploadError as exc:
            return emit({"status": "error", "error": str(exc)}) or 1
        emit(result)
        return 1 if result.get("status") == "blocked" else 0
    if args.command == "publish":
        from .upload import UploadError, publish_agent

        try:
            result = publish_agent(
                args.folder,
                slug=args.slug,
                visibility=args.visibility,
                base_url=args.base_url,
                dry_run=args.dry_run,
                interactive=not args.no_open,
            )
        except UploadError as exc:
            return emit({"status": "error", "error": str(exc)}) or 1
        emit(result)
        return 1 if result.get("status") == "blocked" else 0
    if args.command == "read-agent-file":
        return emit(read_agent_file(args.folder, args.path))
    if args.command == "field-test":
        return emit(run_field_test())
    if args.command == "doctor":
        return emit(run_doctor())
    if args.command == "update":
        return emit(run_update(check_only=args.check))
    if args.command == "global":
        from .global_router import global_router_status, install_global_router, remove_global_router

        home = Path(args.home).expanduser() if args.home else None
        targets = args.target or None
        try:
            if args.global_command == "install":
                return emit(
                    install_global_router(
                        home=home,
                        targets=targets,
                        backup=not args.no_backup,
                        dry_run=args.dry_run,
                    )
                )
            if args.global_command == "remove":
                return emit(
                    remove_global_router(
                        home=home,
                        targets=targets,
                        backup=not args.no_backup,
                        dry_run=args.dry_run,
                    )
                )
            if args.global_command == "status":
                return emit(global_router_status(home=home, targets=targets))
        except ValueError as exc:
            return emit({"action": "global_router", "status": "error", "error": str(exc)}) or 2
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
    if args.command == "project":
        from .project_bootstrap import ensure_project, project_status

        try:
            if args.project_command == "ensure":
                return emit(
                    ensure_project(
                        args.project,
                        reason=args.reason,
                        force_code_map=args.refresh_code_map,
                    )
                )
            return emit(project_status(args.project))
        except (OSError, TimeoutError, ValueError):
            return emit(
                {
                    "action": "project_bootstrap",
                    "status": "error",
                    "detail": "project_bootstrap_failed",
                }
            ) or 2
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
    if args.command == "research" and args.research_command == "read":
        from .research import run_research

        request = _resolve_recommended_research_request(
            {
                "query": args.query or "Read explicit web sources",
                "source_hints": args.urls,
                "loadout": args.loadout,
                "depth": args.depth,
                "max_weight": args.max_weight,
                "follow_results": args.follow_results,
                "max_cost": _max_cost_from_args(args),
                "allowed_modules": args.allow_module,
                "forbidden_modules": args.forbid_module,
            },
            home=args.home,
        )
        return emit(
            run_research(
                request,
                home=args.home,
            )
        )
    if args.command == "research" and args.research_command == "plan":
        from .research import run_research_plan

        query = args.query or " ".join(args.source_hints).strip()
        provider_modules = [_research_search_provider_module(provider) for provider in args.provider]
        source_hints = list(args.source_hints)
        if args.search:
            if args.provider:
                source_hints = [f"search:{_research_search_provider_hint(provider)}:{query}" for provider in args.provider]
            else:
                source_hints = [f"search:auto:{query}"] if query else []
        request = _resolve_recommended_research_request(
            {
                "query": query or "Preview research plan",
                "intent": "plan",
                "source_hints": source_hints,
                "loadout": args.loadout,
                "depth": args.depth,
                "max_weight": args.max_weight,
                "follow_results": args.follow_results,
                "query_variants": args.variant,
                "max_cost": _max_cost_from_args(args),
                "allowed_modules": _dedupe(args.allow_module + provider_modules),
                "forbidden_modules": args.forbid_module,
            },
            home=args.home,
            allow_override_fields={"query_variants", "max_cost"},
        )
        return emit(run_research_plan(request))
    if args.command == "research" and args.research_command == "search":
        from .research import run_research

        query = " ".join(args.query).strip()
        provider_id = _research_search_provider_hint(args.provider)
        provider_module = _research_search_provider_module(args.provider)
        request = _resolve_recommended_research_request(
            {
                "query": query,
                "intent": "search",
                "source_hints": [f"search:{provider_id}:{query}"],
                "loadout": args.loadout,
                "depth": args.depth,
                "max_weight": args.max_weight,
                "follow_results": args.follow_results,
                "query_variants": args.variant,
                "max_cost": _max_cost_from_args(args),
                "allowed_modules": _dedupe(args.allow_module + [provider_module]),
                "forbidden_modules": args.forbid_module,
            },
            home=args.home,
            allow_override_fields={"query_variants", "max_cost"},
        )
        return emit(run_research(request, home=args.home))
    if args.command == "research" and args.research_command == "gather":
        from .research import run_research

        query = " ".join(args.query).strip()
        provider_modules = [_research_search_provider_module(provider) for provider in args.provider]
        source_hints = (
            [f"search:{_research_search_provider_hint(provider)}:{query}" for provider in args.provider]
            if args.provider
            else [f"search:auto:{query}"]
        )
        request = _resolve_recommended_research_request(
            {
                "query": query,
                "intent": "gather",
                "source_hints": source_hints,
                "loadout": args.loadout,
                "depth": args.depth,
                "max_weight": args.max_weight,
                "follow_results": args.follow_results,
                "query_variants": args.variant,
                "max_cost": _max_cost_from_args(args),
                "allowed_modules": _dedupe(args.allow_module + provider_modules),
                "forbidden_modules": args.forbid_module,
            },
            home=args.home,
            allow_override_fields={"query_variants", "max_cost"},
        )
        return emit(run_research(request, home=args.home))
    if args.command == "research" and args.research_command == "modules":
        from .research.engine import default_registry

        return emit(
            {
                "schema": "agentlas.research.modules.v0",
                "modules": default_registry().module_manifests(),
            }
        )
    if args.command == "research" and args.research_command == "doctor":
        from .research import run_research_doctor

        return emit(run_research_doctor(home=args.home))
    if args.command == "research" and args.research_command == "status":
        from .research import run_research_status

        return emit(run_research_status(home=args.home))
    if args.command == "research" and args.research_command == "credentials":
        from .research import run_research_credentials

        return emit(run_research_credentials(home=args.home))
    if args.command == "research" and args.research_command == "social-fallbacks":
        from .research import run_research_social_fallbacks

        return emit(run_research_social_fallbacks(home=args.home))
    if args.command == "research" and args.research_command == "proofs":
        from .research import run_research_proofs

        return emit(run_research_proofs(home=args.home, limit=args.limit))
    if args.command == "research" and args.research_command == "verify":
        from .research import run_research_verify

        return emit(
            run_research_verify(
                home=args.home,
                include_public=not args.skip_public,
                include_browser=not args.skip_browser,
                include_credentialed=not args.skip_credentialed,
                browser_url=args.browser_url,
            )
        )
    if args.command == "research" and args.research_command == "hardpoints":
        from .research import run_research_hardpoints

        action = "arm" if args.arm else ("disarm" if args.disarm else "list")
        return emit(run_research_hardpoints(action=action, module_id=args.arm or args.disarm, recipe=args.recipe, home=args.home))
    if args.command == "research" and args.research_command == "armory":
        from .research import run_research_armory

        return emit(run_research_armory(loadout=args.loadout, slot=args.slot, home=args.home))
    if args.command == "research" and args.research_command == "profile":
        from .research import run_research_profile

        return emit(run_research_profile(loadout=args.loadout, source_hints=args.source, home=args.home))
    if args.command == "research" and args.research_command == "recommend":
        from .research import run_research_recommendation

        return emit(run_research_recommendation(query=" ".join(args.query), source_hints=args.source, home=args.home))
    if args.command == "research" and args.research_command == "preflight":
        from .research import run_research_preflight

        return emit(
            run_research_preflight(
                query=" ".join(args.query),
                source_hints=args.source,
                loadout=args.loadout,
                depth=args.depth,
                follow_results=args.follow_results,
                query_variants=args.variant,
                max_requests=args.max_requests,
                max_weight=args.max_weight,
                allowed_modules=args.allow_module,
                forbidden_modules=args.forbid_module,
                home=args.home,
            )
        )
    if args.command == "research" and args.research_command == "bridge-contract":
        from .research import run_research_bridge_contracts

        return emit(run_research_bridge_contracts(module_id=args.module))
    if args.command == "research" and args.research_command == "browser-candidates":
        from .research import run_research_browser_candidates

        return emit(run_research_browser_candidates(module_id=args.module, query=args.query, home=args.home))
    if args.command == "research" and args.research_command == "bridge-check":
        from .research import run_research_bridge_check

        return emit(run_research_bridge_check(module_id=args.module, url=args.url, home=args.home))
    if args.command == "research" and args.research_command == "platform-contract":
        from .research import run_research_platform_contracts

        return emit(run_research_platform_contracts(module_id=args.module))
    if args.command == "research" and args.research_command == "platform-check":
        from .research import run_research_platform_check

        return emit(run_research_platform_check(module_id=args.module, source_hint=args.source, home=args.home))
    if args.command == "research" and args.research_command == "loadouts":
        from .research import loadout_catalog

        return emit(
            {
                "schema": "agentlas.research.loadouts.v0",
                "loadouts": loadout_catalog(),
            }
        )
    if args.command == "search":
        from .networking import init_networking, search_agents
        from .networking.bootstrap import networking_home

        maybe_auto_update()
        init_networking(networking_home())
        bootstrap = _project_bootstrap_receipt(
            args.project,
            "hephaestus-search",
            requested=args.ensure_project,
        )
        if args.ensure_project and _project_bootstrap_blocks_execution(bootstrap):
            return _emit_blocked_project_bootstrap(bootstrap)
        result = search_agents(
            args.query,
            project_dir=args.project,
            runtime=args.runtime,
            limit=args.limit,
        )
        result["project_bootstrap"] = bootstrap
        return emit(result)
    if args.command == "call":
        from .networking import call_agents, init_networking
        from .networking.bootstrap import networking_home
        from .networking.search_call import parse_local_inventory

        maybe_auto_update()
        init_networking(networking_home())
        context = args.context_text or " ".join(args.context).strip()
        if not context:
            return emit({"action": "agent_call", "status": "error", "error": "context is required"}) or 2
        bootstrap = _project_bootstrap_receipt(
            args.project,
            "hephaestus-call",
            requested=args.ensure_project,
        )
        if args.ensure_project and _project_bootstrap_blocks_execution(bootstrap):
            return _emit_blocked_project_bootstrap(bootstrap)
        result = call_agents(
            args.agents,
            context,
            project_dir=args.project,
            runtime=args.runtime,
            version=args.version,
            local_inventory=parse_local_inventory(args.local_inventory),
        )
        result["project_bootstrap"] = bootstrap
        return emit(result)
    if args.command == "hep-browser":
        return _run_hep_browser(args)
    if args.command == "route":
        from .networking import init_networking, route_request
        from .networking.bootstrap import networking_home
        from .networking.stormbreaker_runner import run_stormbreaker_decision

        maybe_auto_update()
        trusted_project_contact = (
            _plugin_contact_runtime(args.runtime)
            or args.scope == "cloud"
            or args.auto_run
        )
        bootstrap = _project_bootstrap_receipt(
            args.project,
            "hephaestus-route",
            requested=args.ensure_project,
            trusted_contact=trusted_project_contact,
        )
        if (trusted_project_contact or args.ensure_project) and _project_bootstrap_blocks_execution(bootstrap):
            return _emit_blocked_project_bootstrap(bootstrap)
        home = networking_home()
        init_networking(home)
        session_inventory = None
        session_inventory_raw = args.session_inventory or os.environ.get("AGENTLAS_SESSION_INVENTORY")
        if session_inventory_raw:
            try:
                session_inventory = json.loads(session_inventory_raw)
                if not isinstance(session_inventory, list):
                    raise ValueError("session inventory must be a JSON array")
            except (json.JSONDecodeError, ValueError) as exc:
                emit({"action": "route", "status": "error", "error": f"invalid --session-inventory: {exc}"})
                return 2
        hub_only = False if args.no_hub else (True if not args.allow_local_routing else args.hub_only)
        work_brief = None
        brief_source = getattr(args, "brief", None) or args.project
        if brief_source:
            from .interview import load_work_brief

            work_brief = load_work_brief(brief_source)
        decision = route_request(
            args.query,
            project_dir=args.project,
            runtime=args.runtime,
            use_hub=not args.no_hub,
            hub_approved=args.approve_hub,
            hub_only=hub_only,
            scope=args.scope,
            caller_id=getattr(args, "caller", None),
            session_inventory=session_inventory,
            work_brief=work_brief,
        )
        decision["project_bootstrap"] = bootstrap
        if args.auto_run and not args.plan_only:
            if decision.get("action") == "pipeline" and isinstance(decision.get("execution_fabric"), dict):
                if args.background:
                    background_result = _start_stormbreaker_background(args, decision=decision)
                    background_result["project_bootstrap"] = bootstrap
                    return emit(background_result)
                result = run_stormbreaker_decision(
                    decision,
                    home=home,
                    project_dir=args.project,
                    executor_command=args.executor_command,
                    execute_card_commands=args.execute_card_commands,
                    max_workers=args.max_workers,
                    timeout_seconds=args.timeout,
                    research_evidence=args.research_evidence,
                    research_loadout=args.research_loadout,
                    research_depth=args.research_depth,
                    research_follow_results=args.research_follow_results,
                    research_variants=args.research_variant,
                )
                result["route_decision"] = {
                    "action": decision.get("action"),
                    "receipt_id": decision.get("receipt_id"),
                    "match_reason": decision.get("match_reason"),
                }
                result["project_bootstrap"] = bootstrap
                emit(result)
                return 0 if result.get("status") in {"completed", "materialized"} else 1
            decision["auto_run"] = {
                "status": "skipped",
                "reason": "route decision did not include a runnable pipeline execution_fabric",
                "runner": "hep-storm",
            }
        return emit(decision)
    if args.command == "stormbreaker" and args.stormbreaker_command == "harness":
        from .networking.stormbreaker_harness import goal_ultracode_harness

        return emit(goal_ultracode_harness())
    if args.command == "stormbreaker" and args.stormbreaker_command == "journal":
        from .networking.run_journal import RunJournal, default_journal_path

        if args.journal:
            journal_path = Path(args.journal)
        elif args.run_id:
            journal_path = default_journal_path(args.project, args.run_id)
        else:
            emit({"action": "stormbreaker_journal", "status": "error", "error": "--run-id or --journal is required"})
            return 2
        journal = RunJournal(journal_path)
        if args.journal_command == "status":
            return emit(journal.resume_plan(loop_threshold=args.loop_threshold))
        if args.journal_command == "verify":
            result = journal.verify()
            emit(result)
            return 0 if result["status"] == "pass" else 1
        if args.journal_command == "gate":
            result = journal.final_gate(require_verification=not args.allow_unverified)
            emit(result)
            return 0 if result["ok"] else 1
        if args.journal_command == "repair":
            return emit(
                {
                    "action": "stormbreaker_journal",
                    "status": "ok",
                    "journal": str(journal_path),
                    "repaired": journal.repair_dangling(reason=args.reason),
                }
            )
        parser.error("unhandled stormbreaker journal command")
        return 2
    if args.command == "hep-storm" or (
        args.command == "stormbreaker" and args.stormbreaker_command == "run"
    ):
        from .networking import init_networking
        from .networking.bootstrap import networking_home
        from .networking.stormbreaker_runner import run_stormbreaker_decision, run_stormbreaker_query

        maybe_auto_update()
        bootstrap = _project_bootstrap_receipt(
            args.project,
            "hephaestus-storm",
            requested=args.ensure_project,
            trusted_contact=True,
        )
        if _project_bootstrap_blocks_execution(bootstrap):
            return _emit_blocked_project_bootstrap(bootstrap)
        home = networking_home()
        init_networking(home)
        session_inventory = None
        session_inventory_raw = args.session_inventory or os.environ.get("AGENTLAS_SESSION_INVENTORY")
        if session_inventory_raw:
            try:
                session_inventory = json.loads(session_inventory_raw)
                if not isinstance(session_inventory, list):
                    raise ValueError("session inventory must be a JSON array")
            except (json.JSONDecodeError, ValueError) as exc:
                emit({"action": "stormbreaker_run", "status": "error", "error": f"invalid --session-inventory: {exc}"})
                return 2

        if args.background:
            if not args.query and not args.decision_file:
                emit({"action": "stormbreaker_run", "status": "error", "error": "query or --decision-file is required"})
                return 2
            background_result = _start_stormbreaker_background(args)
            background_result["project_bootstrap"] = bootstrap
            return emit(background_result)

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
                research_evidence=args.research_evidence,
                research_loadout=args.research_loadout,
                research_depth=args.research_depth,
                research_follow_results=args.research_follow_results,
                research_variants=args.research_variant,
                max_replans=max(0, args.max_replans),
            )
        else:
            if not args.query:
                emit({"action": "stormbreaker_run", "status": "error", "error": "query or --decision-file is required"})
                return 2
            from .interview import load_work_brief

            work_brief = load_work_brief(args.brief or args.project)
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
                research_evidence=args.research_evidence,
                research_loadout=args.research_loadout,
                research_depth=args.research_depth,
                research_follow_results=args.research_follow_results,
                research_variants=args.research_variant,
                work_brief=work_brief,
                max_replans=max(0, args.max_replans),
            )
        result["project_bootstrap"] = bootstrap
        emit(result)
        if args.output_file:
            from .networking.bootstrap import atomic_write_json

            atomic_write_json(Path(args.output_file), result)
        if result.get("status") in {"completed", "materialized"}:
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


def _hep_browser_engine(args: argparse.Namespace):
    """Resolve the hep-browser engine. Default = the user's own agentlas-browser launcher
    (dedicated logged-in profile + approval + learn-and-replay skills, no third-party binary).
    Set AGENTLAS_BROWSER_ENGINE=agent-browser to fall back to the external agent-browser CLI."""
    engine = str(os.environ.get("AGENTLAS_BROWSER_ENGINE", "agentlas")).strip().lower()
    if engine in {"agent-browser", "agent_cli", "vercel", "cli"}:
        from .research.adapters.agent_browser_cli import AgentBrowserCliAdapter

        return AgentBrowserCliAdapter(home=args.home)
    from .research.adapters.agentlas_browser import AgentlasBrowserAdapter

    return AgentlasBrowserAdapter(home=args.home)


def _run_hep_browser(args: argparse.Namespace) -> int:
    from .research import run_research, run_research_bridge_check, run_research_hardpoints

    raw_urls, query_parts = _split_hep_browser_targets(args.target, args.url)
    urls, url_rewrites = _humanize_hep_browser_urls(raw_urls, raw=bool(getattr(args, "raw_url", False)))
    if args.setup:
        return emit(
            run_research_hardpoints(
                action="arm",
                module_id=AGENTLAS_BROWSER_MODULE,
                recipe="npx-agent-browser",
                home=args.home,
            )
        )
    if args.check:
        return emit(
            run_research_bridge_check(
                module_id=AGENTLAS_BROWSER_MODULE,
                url=(urls[0] if urls else "https://example.com"),
                home=args.home,
            )
        )

    query = (args.query or " ".join(query_parts)).strip()
    if not urls and not query:
        return emit(
            {
                "schema": "agentlas.research.hep_browser.v0",
                "status": "needs_target",
                "usage": "hep-browser <url-or-query> [--setup|--check]",
                "default_browser_module": AGENTLAS_BROWSER_MODULE,
            }
        ) or 2

    primitive_actions = _agent_browser_primitive_actions_from_hep_browser(args)
    if urls and primitive_actions:
        adapter = _hep_browser_engine(args)
        runs = [
            adapter.run_actions(
                url,
                primitive_actions,
                browser_args=_agent_browser_args_from_hep_browser(args),
                keep_open=bool(args.keep_open),
                wait_ms=max(0, int(getattr(args, "wait_ms", 0) or 0)),
            )
            for url in urls
        ]
        status = "ok" if all(item.get("status") == "ok" for item in runs) else "error"
        return emit(
            {
                "schema": "agentlas.research.hep_browser.v0",
                "status": status,
                "mode": "primitive",
                "surface": {
                    "command": "hep-browser",
                    "default_browser_module": AGENTLAS_BROWSER_MODULE,
                    "agentlas_browser_first": True,
                    "automation": True,
                    "llm_required": False,
                },
                "request": {
                    "original_urls": raw_urls,
                    "urls": urls,
                    "url_rewrites": url_rewrites,
                    "actions": primitive_actions,
                    "browser_args": _agent_browser_args_from_hep_browser(args),
                    "keep_open": bool(args.keep_open),
                    "wait_ms": max(0, int(getattr(args, "wait_ms", 0) or 0)),
                },
                "runs": runs,
            }
        ) or (0 if status == "ok" else 1)

    action = " ".join([str(item).strip() for item in getattr(args, "act", []) if str(item).strip()]).strip()
    if urls and not action and query and not args.read:
        action = query
    if urls and action and not args.read:
        adapter = _hep_browser_engine(args)
        runs = [
            adapter.automate(
                url,
                action,
                browser_args=_agent_browser_args_from_hep_browser(args),
                keep_open=bool(args.keep_open),
            )
            for url in urls
        ]
        status = "ok" if all(item.get("status") == "ok" for item in runs) else "error"
        return emit(
            {
                "schema": "agentlas.research.hep_browser.v0",
                "status": status,
                "mode": "automation",
                "surface": {
                    "command": "hep-browser",
                    "default_browser_module": AGENTLAS_BROWSER_MODULE,
                    "agentlas_browser_first": True,
                    "automation": True,
                },
                "request": {
                    "original_urls": raw_urls,
                    "urls": urls,
                    "url_rewrites": url_rewrites,
                    "instruction": action,
                    "browser_args": _agent_browser_args_from_hep_browser(args),
                    "keep_open": bool(args.keep_open),
                },
                "runs": runs,
            }
        ) or (0 if status == "ok" else 1)

    if urls:
        request = {
            "query": query or "Agentlas browser read",
            "intent": "hep-browser:read",
            "source_hints": urls,
            "loadout": "auto",
            "depth": args.depth,
            "follow_results": args.follow_results,
            "query_variants": args.variant,
            "max_weight": "browser_heavy",
            "max_cost": _max_cost_from_args(args),
            "allowed_modules": [AGENTLAS_BROWSER_MODULE],
            "browser_args": _agent_browser_args_from_hep_browser(args),
            "browser_keep_open": bool(args.keep_open),
        }
    else:
        provider_modules = [_research_search_provider_module(provider) for provider in args.provider]
        source_hints = (
            [f"search:{_research_search_provider_hint(provider)}:{query}" for provider in args.provider]
            if args.provider
            else [f"search:auto:{query}"]
        )
        request = {
            "query": query,
            "intent": "hep-browser:gather",
            "source_hints": source_hints,
            "loadout": "browser",
            "depth": args.depth,
            "follow_results": args.follow_results,
            "query_variants": args.variant,
            "max_weight": "browser_heavy",
            "max_cost": _max_cost_from_args(args),
            "allowed_modules": provider_modules,
        }
    result = run_research(request, home=args.home)
    result["surface"] = {
        "command": "hep-browser",
        "default_browser_module": AGENTLAS_BROWSER_MODULE,
        "agentlas_browser_first": True,
        "original_urls": raw_urls,
        "url_rewrites": url_rewrites,
    }
    return emit(result)


def _agent_browser_args_from_hep_browser(args: argparse.Namespace) -> list[str]:
    browser_args: list[str] = []
    if getattr(args, "cdp", None):
        browser_args.extend(["--cdp", str(args.cdp)])
    if getattr(args, "profile", None):
        browser_args.extend(["--profile", str(args.profile)])
    if getattr(args, "auto_connect", False):
        browser_args.append("--auto-connect")
    if not any(item in browser_args for item in ("--cdp", "--profile", "--auto-connect")):
        browser_args.extend(_auto_agent_browser_attach_args())
    if getattr(args, "headed", False):
        browser_args.append("--headed")
    return browser_args


def _auto_agent_browser_attach_args() -> list[str]:
    if str(os.environ.get("HEPHAESTUS_BROWSER_AUTO_CDP", "1")).lower() in {"0", "false", "no", "off"}:
        return []
    port = str(os.environ.get("AGENTLAS_CDP_PORT") or "9222")
    return ["--cdp", port] if _local_tcp_port_ready("127.0.0.1", port) else []


def _local_tcp_port_ready(host: str, port: str) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=0.25):
            return True
    except (OSError, ValueError):
        return False


def _agent_browser_primitive_actions_from_hep_browser(args: argparse.Namespace) -> list[dict[str, str]]:
    actions: list[dict[str, str]] = []
    for target in getattr(args, "click", []) or []:
        value = str(target or "").strip()
        if value:
            actions.append({"type": "click", "target": value})
    for target in getattr(args, "click_text", []) or []:
        value = str(target or "").strip()
        if value:
            actions.append({"type": "find_text_click", "target": value})
    return actions


def _split_hep_browser_targets(targets: list[str], explicit_urls: list[str]) -> tuple[list[str], list[str]]:
    urls: list[str] = []
    query_parts: list[str] = []
    for value in [*explicit_urls, *targets]:
        item = str(value or "").strip()
        if not item:
            continue
        if _is_http_url(item):
            urls.append(item)
        else:
            query_parts.append(item)
    return _dedupe(urls), query_parts


def _humanize_hep_browser_urls(urls: list[str], *, raw: bool = False) -> tuple[list[str], list[dict[str, str]]]:
    if raw:
        return urls, []
    rewritten: list[str] = []
    changes: list[dict[str, str]] = []
    for url in urls:
        human_url = _human_browser_url(url)
        rewritten.append(human_url)
        if human_url != url:
            changes.append({"from": url, "to": human_url, "reason": "human_entry_url"})
    return _dedupe(rewritten), changes


def _human_browser_url(value: str) -> str:
    parsed = urlsplit(value)
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    fragment = parsed.fragment.lower().strip("/")
    if host == "mail.google.com" and path in {"", "/mail", "/mail/u/0", "/mail/u/1", "/mail/u/2"}:
        if fragment in {"", "inbox"}:
            return "https://mail.google.com/"
    return value


def _is_http_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


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


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _research_search_provider_module(provider: str) -> str:
    return RESEARCH_SEARCH_PROVIDER_MODULES.get(provider, f"search.{provider.replace('-', '_')}")


def _research_search_provider_hint(provider: str) -> str:
    return RESEARCH_SEARCH_PROVIDER_HINTS.get(provider, provider.replace("-", "_"))


def _max_cost_from_args(args: argparse.Namespace) -> dict[str, int] | None:
    value = getattr(args, "max_requests", None)
    if value is None:
        return None
    return {"requests": max(0, int(value))}


def _resolve_recommended_research_request(
    request: dict[str, Any],
    *,
    home: str | None,
    allow_override_fields: set[str] | None = None,
) -> dict[str, Any]:
    if request.get("loadout") != "recommended":
        return request
    from .research import run_research_recommendation

    protected = allow_override_fields or set()
    recommendation = run_research_recommendation(
        query=str(request.get("query") or ""),
        source_hints=[str(item) for item in request.get("source_hints") or []],
        home=home,
    )
    rec = recommendation.get("recommendation") if isinstance(recommendation, dict) else {}
    if not isinstance(rec, dict):
        rec = {}
    resolved = dict(request)
    resolved["loadout"] = str(rec.get("loadout") or "safe")
    if "depth" not in protected:
        resolved["depth"] = str(rec.get("depth") or resolved.get("depth") or "quick")
    if "follow_results" not in protected:
        resolved["follow_results"] = rec.get("follow_results", resolved.get("follow_results", 0))
    if "query_variants" in protected:
        resolved["query_variants"] = _dedupe([str(item) for item in resolved.get("query_variants") or []] + [str(item) for item in rec.get("query_variants") or []])
    else:
        resolved["query_variants"] = [str(item) for item in rec.get("query_variants") or resolved.get("query_variants") or []]
    if "max_cost" in protected:
        max_requests = rec.get("max_requests")
        if isinstance(max_requests, int) and max_requests > 0:
            max_cost = dict(resolved.get("max_cost") or {})
            max_cost.setdefault("requests", max_requests)
            resolved["max_cost"] = max_cost
    return resolved


def _start_stormbreaker_background(args: argparse.Namespace, decision: dict[str, Any] | None = None) -> dict[str, Any]:
    import uuid
    from .networking.bootstrap import atomic_write_json
    from .networking.stormbreaker_harness import goal_ultracode_harness

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
    env = _stormbreaker_background_environment()
    process_options = _stormbreaker_background_process_options()
    with stdout_file.open("w", encoding="utf-8") as out, stderr_file.open("w", encoding="utf-8") as err:
        process = subprocess.Popen(
            child_argv,
            cwd=os.getcwd(),
            env=env,
            stdout=out,
            stderr=err,
            text=True,
            **process_options,
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
        "execution_harness": goal_ultracode_harness(),
    }


def _stormbreaker_background_process_options(platform_name: str | None = None) -> dict[str, Any]:
    """Detach background runs without sharing the Windows console signal group."""

    target = os.name if platform_name is None else platform_name
    if target == "nt":
        # Run without a console. Do not also request a new process group: the
        # combination can leak Windows control events back to the host process.
        return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)}
    return {"start_new_session": True}


def _stormbreaker_background_environment(base: Mapping[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    # GitHub Actions tracks descendants through this marker and can deliver a
    # cleanup interrupt to a process intentionally launched in the background.
    # A detached Stormbreaker run must outlive the invoking shell/process.
    env.pop("RUNNER_TRACKING_ID", None)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


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
    if getattr(args, "brief", None):
        child.extend(["--brief", args.brief])
    if args.session_inventory:
        child.extend(["--session-inventory", args.session_inventory])
    if args.executor_command:
        child.extend(["--executor-command", args.executor_command])
    if args.execute_card_commands:
        child.append("--execute-card-commands")
    if args.max_workers is not None:
        child.extend(["--max-workers", str(args.max_workers)])
    child.extend(["--max-replans", str(max(0, getattr(args, "max_replans", 2)))])
    if getattr(args, "research_evidence", False):
        child.append("--research-evidence")
    if getattr(args, "research_loadout", None):
        child.extend(["--research-loadout", args.research_loadout])
    if getattr(args, "research_depth", None):
        child.extend(["--research-depth", args.research_depth])
    if getattr(args, "research_follow_results", None) is not None:
        child.extend(["--research-follow-results", str(args.research_follow_results)])
    for variant in getattr(args, "research_variant", []) or []:
        child.extend(["--research-variant", variant])
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
    try:
        sanitized = reconcile_adapters()
        if sanitized["count"]:
            checks["actions"].append(
                f"stripped blocked curl|bash auto-update preflight from {sanitized['count']} installed adapter(s)"
            )
            checks["adapters_sanitized"] = sanitized["sanitized"]
    except Exception as exc:
        checks["actions"].append(f"adapter reconcile failed: {exc}")
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
            "version": "1.1.37",
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
