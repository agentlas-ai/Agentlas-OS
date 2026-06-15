import io
import json

from agentlas_cloud.mcp_stdio import serve


def run_session(lines, monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLAS_NETWORKING_HOME", str(tmp_path / "networking"))
    stdin = io.StringIO("".join(json.dumps(line) + "\n" for line in lines))
    stdout = io.StringIO()
    assert serve(stdin=stdin, stdout=stdout) == 0
    return [json.loads(line) for line in stdout.getvalue().splitlines()]


def test_initialize_and_tools_list(monkeypatch, tmp_path):
    responses = run_session(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ],
        monkeypatch,
        tmp_path,
    )
    assert len(responses) == 2  # the notification gets no response
    init = responses[0]["result"]
    assert init["protocolVersion"] == "2025-06-18"
    assert init["serverInfo"]["name"] == "hephaestus-network"
    assert init["serverInfo"]["version"] == "0.5.0"
    tools = responses[1]["result"]["tools"]
    tool_names = {tool["name"] for tool in tools}
    assert tool_names == {
        "agentlas_authenticate",
        "agentlas_auth_status",
        "hephaestus_route",
        "hephaestus_hub_invoke",
        "hephaestus_network_status",
    }
    route_tool = next(tool for tool in tools if tool["name"] == "hephaestus_route")
    assert "hub_only" in route_tool["inputSchema"]["properties"]
    invoke_tool = next(tool for tool in tools if tool["name"] == "hephaestus_hub_invoke")
    assert "memory_root" in invoke_tool["inputSchema"]["properties"]
    auth_tool = next(tool for tool in tools if tool["name"] == "agentlas_authenticate")
    assert "open_browser" in auth_tool["inputSchema"]["properties"]


def test_tools_call_status_and_route(monkeypatch, tmp_path):
    def fake_search_hub(query_tokens, home=None, approved=False):
        return {"status": "offline", "query": " ".join(query_tokens), "detail": "test fixture"}

    monkeypatch.setattr("agentlas_cloud.networking.router.search_hub", fake_search_hub)
    responses = run_session(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "hephaestus_network_status", "arguments": {}}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "hephaestus_route", "arguments": {"request": "weekly report from meeting notes"}},
            },
        ],
        monkeypatch,
        tmp_path,
    )
    status = json.loads(responses[0]["result"]["content"][0]["text"])
    assert "card_counts" in status
    decision = json.loads(responses[1]["result"]["content"][0]["text"])
    assert decision["action"] in {"route", "clarify", "pipeline", "hub_fallback", "hub_candidates", "propose_new", "refuse"}
    assert decision["receipt_id"]


def test_unknown_tool_and_method(monkeypatch, tmp_path):
    responses = run_session(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "nope", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 2, "method": "resources/list"},
        ],
        monkeypatch,
        tmp_path,
    )
    assert responses[0]["error"]["code"] == -32602
    assert responses[1]["error"]["code"] == -32601


def test_agentlas_authenticate_tool_opens_browser_flow(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLAS_NETWORKING_HOME", str(tmp_path / "networking"))
    monkeypatch.setenv("AGENTLAS_AUTH_HOME", str(tmp_path / "auth"))
    calls = {}

    def fake_ensure_access_token(base_url=None, interactive=False, open_browser=True, timeout_seconds=180):
        calls["args"] = {
            "base_url": base_url,
            "interactive": interactive,
            "open_browser": open_browser,
            "timeout_seconds": timeout_seconds,
        }
        return "secret-token-not-surfaced"

    monkeypatch.setattr("agentlas_cloud.auth.ensure_access_token", fake_ensure_access_token)
    responses = run_session(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "agentlas_authenticate",
                    "arguments": {"base_url": "https://agentlas.cloud", "timeout_seconds": 9},
                },
            }
        ],
        monkeypatch,
        tmp_path,
    )
    result = json.loads(responses[0]["result"]["content"][0]["text"])
    assert result["status"] == "authenticated"
    assert "secret-token-not-surfaced" not in responses[0]["result"]["content"][0]["text"]
    assert calls["args"] == {
        "base_url": "https://agentlas.cloud",
        "interactive": True,
        "open_browser": True,
        "timeout_seconds": 9,
    }


def test_hub_invoke_with_explicit_slug_does_not_require_hub_candidates(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTLAS_NETWORKING_HOME", str(tmp_path / "networking"))
    calls = {}

    def fake_route_request(*args, **kwargs):
        return {"action": "propose_new", "receipt_id": "route123", "selected": None}

    def fake_invoke_hub_agent(request, **kwargs):
        calls["kwargs"] = kwargs
        return {"action": "hub_invoke", "status": "prepared", "slug": kwargs["slug"]}

    monkeypatch.setattr("agentlas_cloud.networking.route_request", fake_route_request)
    monkeypatch.setattr("agentlas_cloud.networking.hub_invocation.invoke_hub_agent", fake_invoke_hub_agent)
    responses = run_session(
        [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "hephaestus_hub_invoke",
                    "arguments": {"request": "특허청 제출 양식 템플릿", "slug": "researcher-098-agent-repo-readiness-reviewer", "approve_hub": True},
                },
            }
        ],
        monkeypatch,
        tmp_path,
    )
    result = json.loads(responses[0]["result"]["content"][0]["text"])
    assert result["status"] == "prepared"
    assert calls["kwargs"]["hub_decision"]["action"] == "propose_new"
