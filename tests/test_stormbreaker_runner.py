import json
import os
import shlex
import subprocess
import sys
import time
from argparse import Namespace
from pathlib import Path

from agentlas_cloud.cli import (
    _stormbreaker_background_environment,
    _stormbreaker_background_process_options,
    _stormbreaker_child_argv,
    main,
)
from agentlas_cloud.networking import route_request, run_stormbreaker_decision, run_stormbreaker_query
from agentlas_cloud.networking.stormbreaker_runner import _stormbreaker_worker_process_options
from agentlas_cloud.research.contracts import ResearchRequest
from agentlas_cloud.research.loadouts import apply_loadout
from test_network_pipeline import pipeline_home


ROOT = Path(__file__).resolve().parents[1]


def native_hephaestus_command(*args: str, shortcut: bool = False) -> list[str]:
    if os.name == "nt":
        wrapper = ROOT / "bin" / "hephaestus.cmd"
        wrapper_args = ["hep-storm", *args] if shortcut else list(args)
        # Keep each token separate so Python applies Windows quoting once. Passing
        # a pre-joined command as the /c argument makes cmd.exe preserve literal
        # quotes around Korean goals and paths containing spaces.
        return [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/c",
            "call",
            str(wrapper),
            *wrapper_args,
        ]
    wrapper = ROOT / "bin" / ("hep-storm" if shortcut else "hephaestus")
    return [str(wrapper), *args]


def native_hephaestus_process_options() -> dict[str, int]:
    if os.name != "nt":
        return {}
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return {"creationflags": no_window}


def executor_script(tmp_path, body: str) -> str:
    script = tmp_path / "executor.py"
    script.write_text(body, encoding="utf-8")
    parts = [sys.executable, str(script)]
    if os.name == "nt":
        return subprocess.list2cmdline(parts)
    return shlex.join(parts)


def test_stormbreaker_runner_completes_pipeline_packets(tmp_path):
    home = pipeline_home(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    executor = executor_script(
        tmp_path,
        """
import os
from pathlib import Path

scope = Path(os.environ["STORMBREAKER_WRITE_SCOPE"])
scope.mkdir(parents=True, exist_ok=True)
(scope / "executor-artifact.txt").write_text(
    os.environ["STORMBREAKER_PACKET_ID"] + "\\n" + os.environ["STORMBREAKER_STAGE"],
    encoding="utf-8",
)
""",
    )

    result = run_stormbreaker_query(
        "웹앱 기획부터 구현, 테스트 검증까지 끝까지 해줘",
        home=home,
        project_dir=project,
        use_hub=False,
        session_inventory=[
            {"session_id": "claude:planner", "provider": "claude", "capabilities": ["planning"]},
            {"session_id": "codex:builder", "provider": "codex", "capabilities": ["coding"]},
            {"session_id": "deepseek:verifier", "provider": "deepseek", "capabilities": ["verification"]},
        ],
        executor_command=executor,
    )

    assert result["status"] == "completed"
    assert result["execution_mode"] == "executor_command"
    assert result["final_gate"]["can_report_success"] is True
    assert all(status == "passing" for status in result["packet_statuses"].values())
    assert len(result["packets"]) == 3
    assert (project / result["journal"]).is_file()
    assert all((project / packet["write_scope"] / "executor-artifact.txt").is_file() for packet in result["packets"])
    ledger = (home / "ledgers" / "executions.jsonl").read_text(encoding="utf-8")
    assert '"parent_receipt_id"' in ledger
    assert '"session_id": "codex:builder"' in ledger


def test_stormbreaker_runner_blocks_dependents_after_failed_packet(tmp_path):
    home = pipeline_home(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    executor = executor_script(
        tmp_path,
        """
import os
import sys

if os.environ["STORMBREAKER_STAGE"] == "build":
    sys.exit(7)
""",
    )

    result = run_stormbreaker_query(
        "웹앱 기획부터 구현, 테스트 검증까지 끝까지 해줘",
        home=home,
        project_dir=project,
        use_hub=False,
        executor_command=executor,
    )

    assert result["status"] == "blocked"
    assert result["final_gate"]["can_report_success"] is False
    build_packet = next(packet for packet in result["packets"] if packet["stage"] == "build")
    verify_packet = next(packet for packet in result["packets"] if packet["stage"] == "verify")
    assert build_packet["status"] == "blocked"
    assert build_packet["detail"] == "executor_failed:7"
    assert verify_packet["status"] == "blocked"
    assert verify_packet["detail"].startswith("dependency_not_passing:")


def test_stormbreaker_runner_attaches_research_evidence(tmp_path, monkeypatch):
    home = pipeline_home(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    seen_requests = []

    def fake_research(request, *, home=None):
        seen_requests.append(request)
        return {
            "schema": "agentlas.research.v0",
            "status": "ok",
            "request": {**request, "request_hash": "research_hash"},
            "capability_summary": {
                "status": "ready",
                "loadout": "safe",
                "max_weight": "light",
                "depth": "quick",
                "mounted_modules": ["search.news_rss"],
                "heavy_modules_mounted": [],
                "browser": {
                    "requested": False,
                    "attempted": False,
                    "used": False,
                    "status": "not_requested",
                    "modules": [],
                    "evidence": False,
                },
                "social": {
                    "requested": False,
                    "official_evidence": False,
                    "public_fallback_evidence": False,
                    "public_fallback_platforms": [],
                    "official_missing_modules": [],
                    "missing_proofs": [],
                },
                "web": {
                    "search_evidence": True,
                    "direct_read_evidence": False,
                    "search_only": True,
                },
                "trust": {
                    "usable_result_count": 1,
                    "warnings": ["search_snippets_need_followup"],
                    "missing_proofs": [],
                    "can_use_for_build_context": True,
                },
            },
            "results": [
                {
                    "title": "Evidence",
                    "url": "https://example.com",
                    "platform": "web_search",
                    "confidence": "usable",
                    "limits": [],
                }
            ],
            "receipt": {
                "receipt_id": "research_123",
                "module_chain": ["search.news_rss"],
                "attempts": [],
                "policy": {
                    "evidence_quality": {
                        "status": "thin",
                        "score": 25,
                        "direct_read_count": 0,
                        "search_result_count": 1,
                        "source_class_counts": {"search_snippet": 1},
                    },
                    "evidence_coverage": {
                        "status": "search_only",
                        "search_only": True,
                        "official_social_evidence": False,
                        "public_social_fallback_evidence": False,
                        "browser_evidence": False,
                        "completion_blockers": [],
                        "warnings": ["search_snippets_need_followup"],
                    },
                },
            },
        }

    monkeypatch.setattr("agentlas_cloud.research.run_research", fake_research)
    executor = executor_script(
        tmp_path,
        """
import os
from pathlib import Path

scope = Path(os.environ["STORMBREAKER_WRITE_SCOPE"])
scope.mkdir(parents=True, exist_ok=True)
(scope / "research-env.txt").write_text(
    os.environ.get("STORMBREAKER_RESEARCH_RECEIPT_ID", ""),
    encoding="utf-8",
)
(scope / "research-preflight-env.txt").write_text(
    os.environ.get("STORMBREAKER_RESEARCH_PREFLIGHT_FILE", ""),
    encoding="utf-8",
)
(scope / "research-status-env.txt").write_text(
    os.environ.get("STORMBREAKER_RESEARCH_STATUS_FILE", ""),
    encoding="utf-8",
)
""",
    )

    result = run_stormbreaker_query(
        "웹앱 기획부터 구현, 테스트 검증까지 끝까지 해줘",
        home=home,
        project_dir=project,
        use_hub=False,
        executor_command=executor,
        research_evidence=True,
    )

    assert result["status"] == "completed"
    assert len(seen_requests) == 1
    assert seen_requests[0]["loadout"] == "safe"
    assert seen_requests[0]["depth"] == "quick"
    assert seen_requests[0]["follow_results"] == 1
    assert seen_requests[0]["query_variants"] == []
    assert seen_requests[0]["allowed_modules"] == ["search.ddg_html", "search.news_rss", "read.http"]
    assert seen_requests[0]["source_hints"][0].startswith("search:auto:")
    assert not any(hint.startswith("reddit:search:") for hint in seen_requests[0]["source_hints"])
    assert not any(hint.startswith("threads:keyword:") for hint in seen_requests[0]["source_hints"])
    assert result["research_options"] == {
        "loadout": "safe",
        "depth": "quick",
        "follow_results": 1,
        "query_variants": [],
    }
    plan_packet = next(packet for packet in result["packets"] if packet["stage"] == "plan")
    assert plan_packet["research_evidence"]["receipt_id"] == "research_123"
    assert plan_packet["research_evidence"]["request_hash"] == "research_hash"
    assert plan_packet["research_evidence"]["request"]["loadout"] == "safe"
    assert plan_packet["research_evidence"]["request"]["depth"] == "quick"
    assert plan_packet["research_evidence"]["request"]["follow_results"] == 1
    assert plan_packet["research_evidence"]["request"]["allowed_modules"] == [
        "search.ddg_html",
        "search.news_rss",
        "read.http",
    ]
    assert plan_packet["research_evidence"]["request"]["source_hints"][0].startswith("search:auto:")
    assert plan_packet["research_evidence"]["result_count"] == 1
    assert plan_packet["research_evidence"]["evidence_quality"]["status"] == "thin"
    assert plan_packet["research_evidence"]["evidence_quality"]["score"] == 25
    assert plan_packet["research_evidence"]["evidence_coverage"]["status"] == "search_only"
    assert plan_packet["research_evidence"]["evidence_coverage"]["search_only"] is True
    assert plan_packet["research_evidence"]["evidence_coverage"]["warnings"] == ["search_snippets_need_followup"]
    capability = plan_packet["research_evidence"]["capability_summary"]
    assert capability["status"] == "ready"
    assert capability["loadout"] == "safe"
    assert capability["browser"]["status"] == "not_requested"
    assert capability["web"]["search_only"] is True
    assert capability["trust"]["can_use_for_build_context"] is True
    readiness = plan_packet["research_evidence"]["readiness"]
    assert readiness["status"] == "partial"
    assert readiness["goal_ready"] is False
    assert readiness["commands_will_run"] is False
    assert readiness["network_will_run"] is False
    assert readiness["summary"]["core_engine_ok"] is True
    assert readiness["summary"]["credentialed_social_ok"] is False
    assert "reddit_oauth_live_check" in readiness["summary"]["missing_or_unready_proofs"]
    assert "threads_live_graph_check" in readiness["summary"]["missing_or_unready_proofs"]
    preflight = plan_packet["research_evidence"]["preflight"]
    assert preflight["status"] == "ok"
    assert preflight["resolved_loadout"] == "safe"
    assert preflight["commands_will_run"] is False
    assert preflight["network_will_run"] is False
    assert preflight["browser_will_run"] is False
    assert preflight["browser_modules_mounted"] is False
    assert preflight["slot_summary"]["browser"]["mounted_count"] == 0
    assert preflight["boundaries"]["heavy_modules_are_detachable"] is True

    plan_scope = project / plan_packet["write_scope"]
    evidence_file = project / plan_packet["research_evidence"]["file"]
    preflight_file = project / plan_packet["research_evidence"]["preflight"]["file"]
    status_file = project / plan_packet["research_evidence"]["readiness"]["file"]
    packet_file = json.loads((plan_scope / "packet.json").read_text(encoding="utf-8"))
    packet_result = json.loads((plan_scope / "packet-result.json").read_text(encoding="utf-8"))
    assert evidence_file.is_file()
    assert preflight_file.is_file()
    assert status_file.is_file()
    assert json.loads(evidence_file.read_text(encoding="utf-8"))["receipt"]["receipt_id"] == "research_123"
    assert json.loads(preflight_file.read_text(encoding="utf-8"))["schema"] == "agentlas.research.preflight.v0"
    assert json.loads(status_file.read_text(encoding="utf-8"))["schema"] == "agentlas.research.status.v0"
    assert packet_file["research_evidence"]["receipt_id"] == "research_123"
    assert packet_file["research_evidence"]["preflight"]["file"] == str(Path(plan_packet["research_evidence"]["preflight"]["file"]))
    assert packet_file["research_evidence"]["readiness"]["file"] == str(Path(plan_packet["research_evidence"]["readiness"]["file"]))
    assert packet_result["research_evidence"]["receipt_id"] == "research_123"
    assert packet_result["research_evidence"]["preflight"]["resolved_loadout"] == "safe"
    assert packet_result["research_evidence"]["readiness"]["summary"]["core_engine_ok"] is True
    assert (plan_scope / "research-env.txt").read_text(encoding="utf-8") == "research_123"
    assert (plan_scope / "research-preflight-env.txt").read_text(encoding="utf-8") == plan_packet["research_evidence"]["preflight"]["file"]
    assert (plan_scope / "research-status-env.txt").read_text(encoding="utf-8") == plan_packet["research_evidence"]["readiness"]["file"]


def test_stormbreaker_runner_applies_research_options(tmp_path, monkeypatch):
    home = pipeline_home(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    seen_requests = []
    seen_expanded_requests = []

    def fake_research(request, *, home=None):
        seen_requests.append(request)
        seen_expanded_requests.append(apply_loadout(ResearchRequest.from_value(request)).to_dict())
        return {
            "schema": "agentlas.research.v0",
            "status": "ok",
            "request": {**seen_expanded_requests[-1], "request_hash": "research_hash"},
            "results": [],
            "receipt": {
                "receipt_id": "research_456",
                "module_chain": [],
                "attempts": [],
                "policy": {
                    "evidence_quality": {
                        "status": "missing",
                        "score": 0,
                        "direct_read_count": 0,
                        "search_result_count": 0,
                        "source_class_counts": {},
                    },
                    "evidence_coverage": {
                        "status": "missing",
                        "search_only": False,
                        "official_social_evidence": False,
                        "public_social_fallback_evidence": False,
                        "public_social_fallback_platforms": [],
                        "official_social_modules_missing": ["platform.reddit.oauth", "platform.threads"],
                        "missing_credentials": [
                            "AGENTLAS_REDDIT_BEARER_TOKEN",
                            "REDDIT_BEARER_TOKEN",
                            "AGENTLAS_THREADS_ACCESS_TOKEN",
                            "THREADS_ACCESS_TOKEN",
                        ],
                        "browser_evidence": False,
                        "completion_blockers": ["reddit_oauth_live_check", "threads_live_graph_check"],
                        "warnings": ["official_reddit_missing", "official_threads_missing"],
                    },
                },
            },
        }

    monkeypatch.setattr("agentlas_cloud.research.run_research", fake_research)
    executor = executor_script(tmp_path, "print('ok')\n")

    result = run_stormbreaker_query(
        "웹앱 기획부터 구현, 테스트 검증까지 끝까지 해줘",
        home=home,
        project_dir=project,
        use_hub=False,
        executor_command=executor,
        research_evidence=True,
        research_loadout="social",
        research_depth="deep",
        research_follow_results=4,
        research_variants=["reddit", "github", "reddit"],
    )

    assert result["status"] == "completed"
    assert result["research_options"] == {
        "loadout": "social",
        "depth": "deep",
        "follow_results": 4,
        "query_variants": ["reddit", "github"],
    }
    assert len(seen_requests) == 1
    assert seen_requests[0]["loadout"] == "social"
    assert seen_requests[0]["depth"] == "deep"
    assert seen_requests[0]["follow_results"] == 4
    assert seen_requests[0]["query_variants"] == ["reddit", "github", "threads"]
    assert "allowed_modules" not in seen_requests[0]
    assert any(hint.startswith("reddit:search:") for hint in seen_requests[0]["source_hints"])
    assert any(hint.startswith("threads:keyword:") for hint in seen_requests[0]["source_hints"])
    assert "platform.reddit.oauth" in seen_expanded_requests[0]["allowed_modules"]
    assert "platform.reddit" in seen_expanded_requests[0]["allowed_modules"]
    assert "platform.threads" in seen_expanded_requests[0]["allowed_modules"]
    assert "platform.threads.public" in seen_expanded_requests[0]["allowed_modules"]
    plan_packet = next(packet for packet in result["packets"] if packet["stage"] == "plan")
    assert plan_packet["research_evidence"]["options"]["loadout"] == "social"
    assert plan_packet["research_evidence"]["options"]["query_variants"] == ["reddit", "github"]
    request_summary = plan_packet["research_evidence"]["request"]
    assert request_summary["loadout"] == "social"
    assert request_summary["query_variants"] == ["reddit", "github", "threads"]
    assert "platform.reddit.oauth" in request_summary["allowed_modules"]
    assert "platform.reddit" in request_summary["allowed_modules"]
    assert "platform.threads" in request_summary["allowed_modules"]
    assert "platform.threads.public" in request_summary["allowed_modules"]
    assert any(hint.startswith("reddit:search:") for hint in request_summary["source_hints"])
    assert any(hint.startswith("threads:keyword:") for hint in request_summary["source_hints"])
    coverage = plan_packet["research_evidence"]["evidence_coverage"]
    assert coverage["official_social_modules_missing"] == ["platform.reddit.oauth", "platform.threads"]
    assert coverage["missing_credentials"] == [
        "AGENTLAS_REDDIT_BEARER_TOKEN",
        "REDDIT_BEARER_TOKEN",
        "AGENTLAS_THREADS_ACCESS_TOKEN",
        "THREADS_ACCESS_TOKEN",
    ]
    assert coverage["completion_blockers"] == ["reddit_oauth_live_check", "threads_live_graph_check"]


def test_stormbreaker_runner_resolves_recommended_research_loadout(tmp_path, monkeypatch):
    home = pipeline_home(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    seen_requests = []

    def fake_research(request, *, home=None):
        seen_requests.append(request)
        expanded = apply_loadout(ResearchRequest.from_value(request)).to_dict()
        return {
            "schema": "agentlas.research.v0",
            "status": "ok",
            "request": {**expanded, "request_hash": "recommended_hash"},
            "results": [],
            "receipt": {
                "receipt_id": "research_recommended",
                "module_chain": [],
                "attempts": [],
                "policy": {
                    "evidence_quality": {
                        "status": "missing",
                        "score": 0,
                        "direct_read_count": 0,
                        "search_result_count": 0,
                        "source_class_counts": {},
                    }
                },
            },
        }

    monkeypatch.setattr("agentlas_cloud.research.run_research", fake_research)
    decision = route_request("웹앱 기획부터 구현, 테스트 검증까지 끝까지 해줘", home=home, use_hub=False)
    packet = decision["execution_fabric"]["packets"][0]
    packet["research_request"] = {
        "query": "Threads와 Reddit 반응까지 조사",
        "intent": "search",
        "source_hints": ["search:auto:Threads와 Reddit 반응까지 조사"],
        "loadout": "recommended",
    }

    result = run_stormbreaker_decision(
        decision,
        home=home,
        project_dir=project,
        executor_command=executor_script(tmp_path, "print('ok')\n"),
        research_evidence=True,
    )

    assert result["status"] == "completed"
    assert len(seen_requests) == 1
    request = seen_requests[0]
    assert request["loadout"] == "public-web"
    assert request["depth"] == "quick"
    assert request["follow_results"] == 3
    assert request["max_cost"]["requests"] == 7
    assert request["query_variants"] == ["reddit", "threads"]
    assert not any(hint.startswith("reddit:search:") for hint in request["source_hints"])
    assert not any(hint.startswith("threads:keyword:") for hint in request["source_hints"])
    assert not any(key.startswith("_stormbreaker_") for key in request)

    plan_packet = next(packet for packet in result["packets"] if packet["stage"] == "plan")
    evidence = plan_packet["research_evidence"]
    assert evidence["options"]["loadout"] == "safe"
    assert evidence["request"]["loadout"] == "public-web"
    assert evidence["recommendation"]["loadout"] == "public-web"
    assert evidence["recommendation"]["follow_results"] == 3
    assert "public_social_research_requested" in evidence["recommendation"]["reasons"]
    assert "official_social_apis_not_mounted_by_default" in evidence["recommendation"]["reasons"]
    assert evidence["recommendation"]["mount_decision"]["credentialed_social"] == "detached"
    assert evidence["recommendation"]["mount_decision"]["browser_hardpoints"] == "detached"
    assert evidence["preflight"]["resolved_loadout"] == "public-web"
    assert evidence["preflight"]["mount_decision"]["credentialed_social"] == "detached"
    assert evidence["preflight"]["mount_decision"]["browser_hardpoints"] == "detached"
    assert evidence["preflight"]["slot_summary"]["browser"]["mounted_count"] == 0
    assert evidence["preflight"]["slot_summary"]["platform"]["mounted_count"] == 2


def test_stormbreaker_recommended_research_uses_original_user_query(tmp_path, monkeypatch):
    home = pipeline_home(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    seen_requests = []
    user_query = "웹앱 기획부터 구현, 테스트 검증까지 끝까지 해줘. Threads와 Reddit 반응도 조사해줘"

    def fake_research(request, *, home=None):
        seen_requests.append(request)
        expanded = apply_loadout(ResearchRequest.from_value(request)).to_dict()
        return {
            "schema": "agentlas.research.v0",
            "status": "ok",
            "request": {**expanded, "request_hash": "recommended_user_query_hash"},
            "results": [],
            "receipt": {
                "receipt_id": "research_recommended_user_query",
                "module_chain": [],
                "attempts": [],
                "policy": {
                    "evidence_quality": {
                        "status": "missing",
                        "score": 0,
                        "direct_read_count": 0,
                        "search_result_count": 0,
                        "source_class_counts": {},
                    }
                },
            },
        }

    monkeypatch.setattr("agentlas_cloud.research.run_research", fake_research)

    result = run_stormbreaker_query(
        user_query,
        home=home,
        project_dir=project,
        use_hub=False,
        executor_command=executor_script(tmp_path, "print('ok')\n"),
        research_evidence=True,
        research_loadout="recommended",
    )

    assert result["status"] == "completed"
    assert len(seen_requests) == 1
    request = seen_requests[0]
    assert "Threads와 Reddit 반응도 조사해줘" in request["query"]
    assert request["loadout"] == "public-web"
    assert request["query_variants"] == ["reddit", "threads"]
    assert not any(hint.startswith("reddit:search:") for hint in request["source_hints"])
    assert not any(hint.startswith("threads:keyword:") for hint in request["source_hints"])
    assert request["source_hints"][0] == f"search:auto:{user_query}"
    assert not any("paid/" in hint or "/prd" in hint for hint in request["source_hints"])
    plan_packet = next(packet for packet in result["packets"] if packet["stage"] == "plan")
    evidence = plan_packet["research_evidence"]
    assert evidence["recommendation"]["loadout"] == "public-web"
    assert evidence["recommendation"]["mount_decision"]["credentialed_social"] == "detached"
    assert evidence["recommendation"]["mount_decision"]["browser_hardpoints"] == "detached"
    assert evidence["preflight"]["resolved_loadout"] == "public-web"
    assert evidence["preflight"]["mount_decision"]["credentialed_social"] == "detached"
    assert evidence["preflight"]["mount_decision"]["browser_hardpoints"] == "detached"
    assert evidence["preflight"]["slot_summary"]["platform"]["mounted_count"] == 2


def test_stormbreaker_cli_runs_pipeline(tmp_path, monkeypatch, capsys):
    home = pipeline_home(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("AGENTLAS_NETWORKING_HOME", str(home))
    executor = executor_script(tmp_path, "import os\nprint(os.environ['STORMBREAKER_PACKET_ID'])\n")

    code = main(
        [
            "stormbreaker",
            "run",
            "웹앱 기획부터 구현, 테스트 검증까지 끝까지 해줘",
            "--project",
            str(project),
            "--no-hub",
            "--executor-command",
            executor,
            "--session-inventory",
            json.dumps([{"session_id": "codex:local", "capabilities": ["planning", "coding", "verification"], "local": True}]),
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["final_gate"]["can_report_success"] is True
    assert payload["route_decision"]["action"] == "pipeline"
    assert payload["claim_level"] == "external_executor_completed"


def test_stormbreaker_cli_background_run_writes_result(tmp_path, monkeypatch, capsys):
    home = pipeline_home(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("AGENTLAS_NETWORKING_HOME", str(home))
    executor = executor_script(tmp_path, "import os\nprint(os.environ['STORMBREAKER_PACKET_ID'])\n")
    args = [
        "stormbreaker",
        "run",
        "웹앱 기획부터 구현, 테스트 검증까지 끝까지 해줘",
        "--project",
        str(project),
        "--no-hub",
        "--executor-command",
        executor,
        "--background",
    ]

    if os.name == "nt":
        # Exercise the real Windows host boundary. Running a background child
        # from inside pytest's own console can deliver a delayed control event
        # to pytest instead of the CLI process that owns the child.
        env = os.environ.copy()
        env.update(
            AGENTLAS_NETWORKING_HOME=str(home),
            HEPHAESTUS_PYTHON=sys.executable,
        )
        completed = subprocess.run(
            native_hephaestus_command(*args),
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
            **native_hephaestus_process_options(),
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        payload = json.loads(completed.stdout)
    else:
        code = main(args)
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "background_started"
    result_file = Path(payload["result_file"])
    for _ in range(50):
        if result_file.is_file():
            break
        time.sleep(0.1)
    assert result_file.is_file()
    result = json.loads(result_file.read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    assert result["final_gate"]["can_report_success"] is True


def test_stormbreaker_background_detaches_from_windows_console_signals():
    options = _stormbreaker_background_process_options("nt")

    assert "start_new_session" not in options
    assert options["creationflags"] & 0x08000000
    assert not options["creationflags"] & 0x00000008
    assert not options["creationflags"] & 0x00000010
    assert not options["creationflags"] & 0x00000200
    assert _stormbreaker_background_process_options("posix") == {"start_new_session": True}


def test_stormbreaker_packet_workers_do_not_share_windows_console_signals():
    options = _stormbreaker_worker_process_options("nt")

    assert options["creationflags"] & 0x08000000
    assert not options["creationflags"] & 0x00000200
    assert _stormbreaker_worker_process_options("posix") == {}


def test_stormbreaker_background_is_not_claimed_by_ci_process_cleanup():
    env = _stormbreaker_background_environment(
        {
            "RUNNER_TRACKING_ID": "github-actions-child",
            "PATH": "test-path",
        }
    )

    assert "RUNNER_TRACKING_ID" not in env
    assert env["PATH"] == "test-path"
    assert env["PYTHONUTF8"] == "1"
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_stormbreaker_background_child_keeps_research_options(tmp_path):
    args = Namespace(
        query="조사하고 계획해줘",
        decision_file=None,
        project=str(tmp_path / "project"),
        runtime="terminal",
        scope="network",
        timeout=900,
        no_hub=False,
        approve_hub=False,
        hub_only=False,
        caller=None,
        session_inventory=None,
        executor_command=None,
        execute_card_commands=False,
        max_workers=None,
        research_evidence=True,
        research_loadout="browser",
        research_depth="deep",
        research_follow_results=5,
        research_variant=["docs", "reddit"],
    )

    argv = _stormbreaker_child_argv(args, tmp_path / "result.json")

    assert "--research-evidence" in argv
    assert argv[argv.index("--research-loadout") + 1] == "browser"
    assert argv[argv.index("--research-depth") + 1] == "deep"
    assert argv[argv.index("--research-follow-results") + 1] == "5"
    assert argv.count("--research-variant") == 2
    assert "docs" in argv
    assert "reddit" in argv


def test_hephaestus_storm_terminal_command_runs_pipeline(tmp_path):
    home = pipeline_home(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    executor = executor_script(tmp_path, "import os\nprint(os.environ['STORMBREAKER_PACKET_ID'])\n")
    env = dict(
        **os.environ,
        AGENTLAS_NETWORKING_HOME=str(home),
        HEPHAESTUS_PYTHON=sys.executable,
    )

    completed = subprocess.run(
        native_hephaestus_command(
            "웹앱 기획부터 구현, 테스트 검증까지 끝까지 해줘",
            "--project",
            str(project),
            "--no-hub",
            "--executor-command",
            executor,
            shortcut=True,
        ),
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        **native_hephaestus_process_options(),
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["status"] == "completed"
    assert payload["route_decision"]["action"] == "pipeline"
    assert payload["project_bootstrap"]["status"] == "privacy_warning"
    assert (project / ".agentlas" / "project-soul-memory.md").is_file()
    assert ".agentlas/" in (project / ".gitignore").read_text(encoding="utf-8")


def test_python_cli_hep_storm_alias_runs_pipeline(tmp_path, monkeypatch, capsys):
    home = pipeline_home(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    executor = executor_script(tmp_path, "import os\nprint(os.environ['STORMBREAKER_PACKET_ID'])\n")
    monkeypatch.setenv("AGENTLAS_NETWORKING_HOME", str(home))

    args = [
        "hep-storm",
        "웹앱 기획부터 구현, 테스트 검증까지 끝까지 해줘",
        "--project",
        str(project),
        "--no-hub",
        "--executor-command",
        executor,
    ]

    if os.name == "nt":
        # Verify the Python CLI alias at the real Windows process boundary.
        # Calling main() inside pytest would make the host and its concurrent
        # packet executors share pytest's console, which is not how the CLI is
        # invoked by Codex, Claude Code, Desktop, or Terminal adapters.
        env = os.environ.copy()
        env.update(
            AGENTLAS_NETWORKING_HOME=str(home),
            HEPHAESTUS_PYTHON=sys.executable,
        )
        completed = subprocess.run(
            [sys.executable, "-m", "agentlas_cloud.cli", *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
            **native_hephaestus_process_options(),
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        payload = json.loads(completed.stdout)
    else:
        code = main(args)
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed"
    assert payload["route_decision"]["action"] == "pipeline"


def test_hephaestus_stormbreaker_subcommand_runs_pipeline_with_research_preflight(tmp_path):
    home = pipeline_home(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    env = dict(
        **os.environ,
        AGENTLAS_NETWORKING_HOME=str(home),
        HEPHAESTUS_PYTHON=sys.executable,
    )

    completed = subprocess.run(
        native_hephaestus_command(
            "stormbreaker",
            "run",
            "웹앱 기획부터 구현, 테스트 검증까지 끝까지 해줘",
            "--project",
            str(project),
            "--no-hub",
            "--research-evidence",
            "--research-loadout",
            "recommended",
        ),
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
        **native_hephaestus_process_options(),
    )

    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["status"] == "materialized"
    assert payload["final_gate"]["can_report_success"] is False
    assert payload["claim_level"] == "handoff_artifacts_materialized"
    assert payload["route_decision"]["action"] == "pipeline"
    plan_packet = next(packet for packet in payload["packets"] if packet["stage"] == "plan")
    assert plan_packet["research_evidence"]["preflight"]["status"] == "ok"
    assert plan_packet["research_evidence"]["preflight"]["browser_will_run"] is False
    preflight_file = project / plan_packet["research_evidence"]["preflight"]["file"]
    evidence_file = project / plan_packet["research_evidence"]["file"]
    assert preflight_file.is_file()
    assert evidence_file.is_file()


def test_route_auto_run_background_starts_for_pipeline(tmp_path, monkeypatch, capsys):
    home = pipeline_home(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("AGENTLAS_NETWORKING_HOME", str(home))
    executor = executor_script(tmp_path, "import os\nprint(os.environ['STORMBREAKER_PACKET_ID'])\n")

    args = [
        "route",
        "웹앱 기획부터 구현, 테스트 검증까지 끝까지 해줘",
        "--project",
        str(project),
        "--no-hub",
        "--auto-run",
        "--background",
        "--executor-command",
        executor,
    ]

    if os.name == "nt":
        # Background routing is a process-boundary contract on Windows. Keep
        # its launcher and detached grandchild outside pytest's console while
        # still waiting for and validating the durable result below.
        env = os.environ.copy()
        env.update(
            AGENTLAS_NETWORKING_HOME=str(home),
            HEPHAESTUS_PYTHON=sys.executable,
        )
        completed = subprocess.run(
            [sys.executable, "-m", "agentlas_cloud.cli", *args],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            check=False,
            **native_hephaestus_process_options(),
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        payload = json.loads(completed.stdout)
    else:
        code = main(args)
        assert code == 0
        payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "background_started"
    assert payload["route_receipt_id"]
    assert payload["decision_file"]
    result_file = Path(payload["result_file"])
    for _ in range(50):
        if result_file.is_file():
            break
        time.sleep(0.1)
    assert result_file.is_file()
    result = json.loads(result_file.read_text(encoding="utf-8"))
    assert result["status"] == "completed"


def test_route_auto_run_skips_non_pipeline_decision(tmp_path, monkeypatch, capsys):
    home = pipeline_home(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("AGENTLAS_NETWORKING_HOME", str(home))

    code = main(
        [
            "route",
            "웹앱 구현해줘",
            "--project",
            str(project),
            "--no-hub",
            "--auto-run",
            "--background",
        ]
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] != "pipeline"
    assert payload["auto_run"]["status"] == "skipped"
