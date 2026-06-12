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
    tools = responses[1]["result"]["tools"]
    tool_names = {tool["name"] for tool in tools}
    assert tool_names == {"hephaestus_route", "hephaestus_hub_invoke", "hephaestus_network_status"}
    route_tool = next(tool for tool in tools if tool["name"] == "hephaestus_route")
    assert "hub_only" in route_tool["inputSchema"]["properties"]
    invoke_tool = next(tool for tool in tools if tool["name"] == "hephaestus_hub_invoke")
    assert "memory_root" in invoke_tool["inputSchema"]["properties"]


def test_tools_call_status_and_route(monkeypatch, tmp_path):
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
