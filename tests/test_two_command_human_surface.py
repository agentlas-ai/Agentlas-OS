import json
import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class _HubHandler(BaseHTTPRequestHandler):
    requests_seen: list[str] = []

    def do_POST(self):  # noqa: N802 - stdlib hook
        length = int(self.headers.get("Content-Length") or 0)
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        args = ((payload.get("params") or {}).get("arguments") or {})
        query = str(args.get("q") or "")
        self.__class__.requests_seen.append(query)
        slug = "hub-general-agent"
        if "prd" in query or "plan" in query:
            slug = "hub-planner-agent"
        elif "codebase_change" in query or "build" in query:
            slug = "hub-builder-agent"
        elif "qa_report" in query or "verify" in query:
            slug = "hub-verifier-agent"
        body = {
            "jsonrpc": "2.0",
            "id": payload.get("id"),
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps(
                            {
                                "results": [
                                    {
                                        "slug": slug,
                                        "name": slug.replace("-", " ").title(),
                                        "kind": "cloud-callable",
                                        "callable": True,
                                        "routingReady": True,
                                    }
                                ]
                            }
                        ),
                    }
                ]
            },
        }
        data = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *_args):
        return None


def _start_fake_hub() -> tuple[HTTPServer, str]:
    _HubHandler.requests_seen = []
    server = HTTPServer(("127.0.0.1", 0), _HubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    return server, f"http://{host}:{port}"


def _write_ready_card(package: Path, slug: str, triggers: list[str], capabilities: list[str]) -> None:
    fixture = package / f"{slug}-bench.jsonl"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(
        "\n".join(json.dumps({"id": f"{slug}-{idx}", "query": f"case {idx}"}) for idx in range(10)) + "\n",
        encoding="utf-8",
    )
    card = {
        "schemaVersion": "routing-card/2.0",
        "id": f"local/{slug}",
        "canonical_id": f"local/{slug}",
        "type": "agent",
        "name": slug.replace("-", " "),
        "summary": f"{slug} specialist",
        "capabilities": capabilities,
        "trigger_examples": [{"text": text, "locale": "en"} for text in triggers[:3]]
        + [{"text": text, "locale": "ko"} for text in triggers[3:]],
        "anti_triggers": [
            {"text": "payment processing", "locale": "en"},
            {"text": "delete production data", "locale": "en"},
            {"text": "legal contract review", "locale": "en"},
        ],
        "required_inputs": [],
        "entrypoints": {"canonical_command": f"/{slug}"},
        "risk_profile": {"tier": "low", "capabilities_at_risk": []},
        "memory_behavior": {"reads": "project", "writes": "project", "exports_to_cloud": False},
        "cloud_delegation_policy": "never",
        "benchmark_fixtures": str(fixture),
        "locale_coverage": {"primary": "en", "ready": ["ko", "en"], "partial": []},
        "routing_status": "routing_ready",
        "produces": [{"kind": "qa_report"}],
    }
    target = package / ".agentlas" / "routing-card.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(card, ensure_ascii=False), encoding="utf-8")


def _command_aliases(tmp_path: Path) -> Path:
    aliases = tmp_path / "cmd"
    aliases.mkdir()
    for name, target in {
        "Hephaestus": ROOT / "bin" / "hephaestus",
        "hephaests-network": ROOT / "bin" / "hephaests-network",
    }.items():
        alias = aliases / name
        alias.write_text(f"#!/usr/bin/env bash\nexec {target} \"$@\"\n", encoding="utf-8")
        alias.chmod(0o755)
    return aliases


def test_three_command_surface_keeps_network_120_human_style_invocations(tmp_path: Path) -> None:
    fake_hub, hub_url = _start_fake_hub()
    try:
        aliases = _command_aliases(tmp_path)
        home = tmp_path / "networking"
        packages = tmp_path / "packages"
        report_pkg = packages / "weekly-report-agent"
        _write_ready_card(
            report_pkg,
            "weekly-report-agent",
            [
                "weekly report from meeting notes",
                "turn meeting notes into a weekly report",
                "summarize meeting notes as weekly report",
                "회의록 주간 보고서 정리",
                "회의 메모 주간 리포트",
            ],
            ["write_weekly_reports", "summarize_meeting_notes"],
        )

        env = os.environ.copy()
        env.update(
            {
                "AGENTLAS_NETWORKING_HOME": str(home),
                "HEPHAESTUS_UPDATE_CHECK": "0",
                "PATH": f"{aliases}:{env.get('PATH', '')}",
            }
        )

        def run(command: list[str]) -> dict:
            completed = subprocess.run(
                command,
                cwd=str(ROOT),
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            assert completed.returncode == 0, completed.stderr or completed.stdout
            return json.loads(completed.stdout)

        run(["Hephaestus", "network", "init"])
        (home / "sources.json").write_text(
            json.dumps({"schemaVersion": "2.0", "sources": []}, ensure_ascii=False),
            encoding="utf-8",
        )
        (home / "config.json").write_text(
            json.dumps({"schemaVersion": "2.0", "hub_url": hub_url, "telemetry": False}, ensure_ascii=False),
            encoding="utf-8",
        )
        (home / "policies" / "routing-policy.json").write_text(
            json.dumps(
                {
                    "schemaVersion": "2.0",
                    "t_high": 4.5,
                    "t_low": 3.0,
                    "margin": 0.8,
                    "min_ready_cards": 1,
                    "max_hops": 2,
                    "clarify_max_candidates": 3,
                    "multi_route": False,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        run(["Hephaestus", "network", "add-source", str(packages)])
        reindex = run(["Hephaestus", "network", "reindex"])
        assert reindex["imported"] == 1

        commands: list[list[str]] = []
        commands.extend([["Hephaestus", "weekly report from meeting notes"]] * 40)
        commands.extend([["Hephaestus", "기획부터 구현하고 테스트까지 릴리즈 끝까지"]] * 20)
        commands.extend([["Hephaestus", "내 private memory 참고해서 weekly report from meeting notes"]] * 20)
        commands.extend([["hephaests-network", f"상품 설명 써주는 에이전트 case {idx}"] for idx in range(20)])
        commands.extend([["hephaests-network", f"기획부터 구현하고 테스트까지 끝까지 case {idx}"] for idx in range(20)])

        seen_command_names: list[str] = []
        action_counts: dict[str, int] = {}
        for command in commands:
            seen_command_names.append(command[0])
            result = run(command)
            action_counts[result["action"]] = action_counts.get(result["action"], 0) + 1
            assert result["receipt_id"]
            assert result["agent_os_router"]["command_model"] == "three_command"
            assert result["agent_os_router"]["commands"]["network"] == "hephaests-network"
            assert result["task_force"]["mode"] == "agent_os_router"
            assert result["policy_decision"]["mode"] == "local_operator"
            assert result["memory_playbook"]["mode"] == "memory_playbook_control_plane"
            if command[0] == "hephaests-network":
                assert result["action"] == "hub_candidates"
                assert result["task_force"]["formation"] in {
                    "single_stage_hub_candidates",
                    "hub_stage_candidates",
                }
            if "릴리즈" in command[1]:
                assert result["task_force"]["temporary_tf"] is True
                assert result["graph_path"]
                assert result["memory_playbook"]["candidates"]

        assert len(commands) == 120
        assert set(seen_command_names) == {"Hephaestus", "hephaests-network"}
        assert action_counts["route"] >= 40
        assert action_counts["pipeline"] >= 20
        assert action_counts["hub_candidates"] >= 40
        receipts = (home / "ledgers" / "routing-decisions.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(receipts) >= 120
        assert len(_HubHandler.requests_seen) >= 40
    finally:
        fake_hub.shutdown()
