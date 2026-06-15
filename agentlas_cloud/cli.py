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

    route = sub.add_parser("route", help="Route a natural-language request to a local agent/team/plugin")
    route.add_argument("query")
    route.add_argument("--project", default=".")
    route.add_argument("--runtime", default="terminal")
    route.add_argument("--no-hub", action="store_true")
    route.add_argument("--approve-hub", action="store_true", help="Legacy no-op; Hub lookup already uses redacted keywords only")
    route.add_argument("--hub-only", action="store_true", help="Skip local cards and search Agentlas Hub only")

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
    if args.command == "route":
        from .networking import init_networking, route_request
        from .networking.bootstrap import networking_home

        init_networking(networking_home())
        return emit(
            route_request(
                args.query,
                project_dir=args.project,
                runtime=args.runtime,
                use_hub=not args.no_hub,
                hub_approved=args.approve_hub,
                hub_only=args.hub_only,
            )
        )
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
    bin_dir.mkdir(parents=True, exist_ok=True)
    shell_shim = bin_dir / "python3"
    cmd_shim = bin_dir / "python3.cmd"
    shell_shim.write_text(f'#!/usr/bin/env bash\nexec "{executable}" "$@"\n', encoding="utf-8")
    shell_shim.chmod(0o755)
    cmd_shim.write_text(f'@"{executable}" %*\r\n', encoding="utf-8")


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
