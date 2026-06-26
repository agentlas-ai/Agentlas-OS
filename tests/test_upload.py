import json
import os
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from agentlas_cloud import upload as upload_module
from agentlas_cloud.upload import package_agent, publish_agent


def make_upload_agent(tmp_path: Path, *, public_profile: bool = True) -> Path:
    agent = tmp_path / "demo-upload-agent"
    (agent / ".agentlas").mkdir(parents=True)
    (agent / "AGENTS.md").write_text("# Demo Upload Agent\n\nBuilds small upload verification packages.\n", encoding="utf-8")
    (agent / ".agentlas" / "agent-card.json").write_text(
        json.dumps(
            {
                "schemaVersion": "1.0",
                "name": "Demo Upload Agent",
                "slug": "demo-upload-agent",
                "summary": "Small package used to verify public upload gates.",
            }
        ),
        encoding="utf-8",
    )
    (agent / "bench.jsonl").write_text(
        "\n".join(json.dumps({"id": f"case-{index}", "query": f"upload package case {index}"}) for index in range(10)) + "\n",
        encoding="utf-8",
    )
    (agent / ".agentlas" / "routing-card.json").write_text(
        json.dumps(
            {
                "schemaVersion": "routing-card/2.0",
                "id": "local/demo-upload-agent",
                "canonical_id": "local/demo-upload-agent",
                "type": "agent",
                "name": "Demo Upload Agent",
                "summary": "Builds and validates small Agentlas upload packages.",
                "description": "Builds and validates small Agentlas upload packages without relying on external private publishing tooling.",
                "capabilities": ["package_agent_uploads", "validate_routing_cards"],
                "trigger_examples": [
                    {"text": "업로드 패키지 검증해줘", "locale": "ko"},
                    {"text": "이 에이전트를 Hub에 올릴 수 있는지 봐줘", "locale": "ko"},
                    {"text": "package this agent for upload", "locale": "en"},
                    {"text": "validate the routing card", "locale": "en"},
                    {"text": "publish this local agent", "locale": "en"},
                ],
                "anti_triggers": [
                    {"text": "draft a lawsuit", "locale": "en"},
                    {"text": "upload social media posts", "locale": "en"},
                    {"text": "주식 자동매매 실행", "locale": "ko"},
                ],
                "required_inputs": [],
                "entrypoints": {"canonical_command": "/demo-upload", "agent": "AGENTS.md"},
                "risk_profile": {"tier": "medium", "capabilities_at_risk": ["file_write", "cloud_call", "publish"]},
                "memory_behavior": {"reads": "project", "writes": "project", "exports_to_cloud": False},
                "cloud_delegation_policy": "ask",
                "benchmark_fixtures": "bench.jsonl",
                "locale_coverage": {"primary": "en", "ready": ["ko", "en"], "partial": []},
                "routing_status": "routing_ready",
                "agent_card_ref": {"path": ".agentlas/agent-card.json", "slug": "demo-upload-agent", "content_hash": None},
                "source": {"kind": "local_path", "ref": None, "package_hash": None, "package_version": "0.0.0"},
            }
        ),
        encoding="utf-8",
    )
    if public_profile:
        (agent / "agentlas.json").write_text(
            json.dumps(
                {
                    "publicProfile": {
                        "titleKo": "데모 업로드 검증 에이전트",
                        "descriptionKo": "Agentlas Hub 업로드 전에 routing-card, 공개 설명, 패키지 해시, 정적 보안 검사를 확인하는 테스트 에이전트입니다.",
                        "guide": {
                            "what-it-does": ["업로드 가능 여부를 정적 검증합니다."],
                            "best-for": ["작은 Agentlas 에이전트 패키지 검증"],
                            "prerequisites": ["완성된 AGENTS.md와 routing-card.json"],
                            "expected-outputs": ["업로드 manifest와 review 결과"],
                            "careful-with": ["실제 인증 정보는 패키지에 넣지 않습니다."],
                        },
                        "members": [{"name": "Demo Upload Agent", "role": "validator"}],
                        "flow": ["package", "review", "register"],
                    }
                }
            ),
            encoding="utf-8",
        )
    return agent


def test_package_agent_marketplace_is_self_contained_and_hashes_routing_card(tmp_path: Path):
    agent = make_upload_agent(tmp_path)
    result = package_agent(agent, visibility="marketplace")
    card = json.loads((agent / ".agentlas" / "routing-card.json").read_text(encoding="utf-8"))
    manifest = json.loads((agent / "agentlas.json").read_text(encoding="utf-8"))

    assert result["status"] == "ready"
    assert re.fullmatch(r"[0-9a-f]{64}", result["manifest"]["packageHash"])
    assert card["agent_card_ref"]["content_hash"]
    assert card["source"]["package_hash"]
    assert card["source"]["ref"] is None
    assert manifest["publicProfile"]["titleKo"] == "데모 업로드 검증 에이전트"


def test_marketplace_upload_blocks_missing_public_profile_but_private_link_allows_it(tmp_path: Path):
    agent = make_upload_agent(tmp_path, public_profile=False)
    public_result = package_agent(agent, visibility="marketplace")
    private_result = package_agent(agent, visibility="private-link")

    assert public_result["status"] == "blocked"
    assert any(finding["id"].startswith("public-profile-required") for finding in public_result["review"]["findings"])
    assert private_result["status"] == "ready"


def test_publish_posts_bundle_to_register_api_without_forge(tmp_path: Path, monkeypatch):
    agent = make_upload_agent(tmp_path)
    received: dict[str, object] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            received["path"] = self.path
            received["authorization"] = self.headers.get("Authorization")
            length = int(self.headers.get("Content-Length", "0"))
            received["payload"] = json.loads(self.rfile.read(length).decode("utf-8"))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"slug":"demo-upload-agent","status":"registered"}')

        def log_message(self, format, *args):  # noqa: A002
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(upload_module, "ensure_access_token", lambda base_url, interactive=True: "signed-token")
    try:
        result = publish_agent(agent, visibility="marketplace", base_url=f"http://127.0.0.1:{server.server_port}", interactive=False)
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert result["status"] == "registered"
    assert received["path"] == "/api/cloud-agents/v1/register"
    assert received["authorization"] == "Bearer signed-token"
    payload = received["payload"]
    assert payload["visibility"] == "marketplace"
    assert payload["manifest"]["packageHash"] == result["manifest"]["packageHash"]


def test_bin_hephaestus_package_does_not_require_forge_checkout(tmp_path: Path):
    agent = make_upload_agent(tmp_path)
    fake_home = tmp_path / "home-without-forge"
    fake_home.mkdir()

    completed = subprocess.run(
        ["./bin/hephaestus", "package", str(agent), "--visibility", "marketplace"],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "HOME": str(fake_home), "PYTHONUTF8": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Hephaestus_agent_forge" not in completed.stdout
    assert json.loads(completed.stdout)["status"] == "ready"


def test_bin_hephaestus_upload_visibility_runs_without_tty_or_forge(tmp_path: Path):
    agent = make_upload_agent(tmp_path)
    fake_home = tmp_path / "home-without-forge"
    fake_home.mkdir()

    completed = subprocess.run(
        ["./bin/hephaestus", "hep-upload", str(agent), "--visibility", "marketplace", "--dry-run", "--no-open"],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "HOME": str(fake_home), "PYTHONUTF8": "1"},
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "No upload performed" not in completed.stderr
    assert "Hephaestus_agent_forge" not in completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["status"] == "dry-run"
    assert payload["manifest"]["visibility"] == "marketplace"


def test_bin_hephaestus_upload_rejects_missing_visibility_value(tmp_path: Path):
    agent = make_upload_agent(tmp_path)
    completed = subprocess.run(
        ["./bin/hephaestus", "hep-upload", str(agent), "--visibility"],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONUTF8": "1"},
        text=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 2
    assert "Missing value for --visibility" in completed.stderr


def test_bin_hephaestus_ignores_shadow_agentlas_cloud_in_cwd(tmp_path: Path):
    shadow = tmp_path / "shadow-project"
    fake_home = tmp_path / "home"
    (shadow / "agentlas_cloud").mkdir(parents=True)
    fake_home.mkdir()
    (shadow / "agentlas_cloud" / "__init__.py").write_text("", encoding="utf-8")
    (shadow / "agentlas_cloud" / "__main__.py").write_text("raise SystemExit(99)\n", encoding="utf-8")

    repo = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [str(repo / "bin" / "hephaestus"), "auth", "status"],
        cwd=shadow,
        env={**os.environ, "HOME": str(fake_home), "PYTHONUTF8": "1"},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "signed_out"
