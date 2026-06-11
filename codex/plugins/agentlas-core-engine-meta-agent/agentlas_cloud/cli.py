from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from .runtime import AgentlasMockStore, compile_runtime_bundle, read_agent_file, run_setup_wizard, scan_agent_folder


def main(argv: list[str] | None = None) -> int:
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

    plugins = sub.add_parser("plugins", help="Plugin discovery (local installs + Agentlas Hub)")
    plugins_sub = plugins.add_subparsers(dest="plugins_command", required=True)
    plugins_list = plugins_sub.add_parser("list", help="Scan locally installed plugins")
    plugins_list.add_argument("--project", default=".")
    plugins_resolve = plugins_sub.add_parser("resolve", help="Resolve a capability need from local + hub plugins")
    plugins_resolve.add_argument("query")
    plugins_resolve.add_argument("--project", default=".")
    plugins_resolve.add_argument("--no-hub", action="store_true", help="Skip the Agentlas Hub query (local scan only)")

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
    if args.command == "plugins":
        from .plugin_discovery import resolve_plugins, scan_local_plugins

        if args.plugins_command == "list":
            return emit(scan_local_plugins(args.project))
        if args.plugins_command == "resolve":
            return emit(resolve_plugins(args.query, args.project, use_hub=not args.no_hub))
    parser.error("unhandled command")
    return 2


def emit(payload: Any) -> int:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


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
