from agentlas_cloud.networking import init_networking, save_card
from agentlas_cloud.networking.hub_invocation import invoke_hub_agent
from test_network_cards import make_ready_card


def test_hub_invocation_fetches_bundle_and_updates_memory(tmp_path, monkeypatch):
    home = tmp_path / "networking"
    init_networking(home)
    memory_root = tmp_path / "agentlas-memory"
    calls = []

    def fake_call(name, arguments=None, home=None, timeout=15):
        calls.append((name, arguments or {}))
        if name == "agentlas.get_runtime_bundle":
            return {
                "bundle": {
                    "agent": arguments["slug"],
                    "packageHash": "sha256:test",
                    "entry": {"path": "AGENTS.md", "content": "Use GitHub and Slack to review an agent repo."},
                    "toolPermissions": {"network": "ask", "fileRead": "manifest-allowlist"},
                }
            }
        if name == "agentlas.resolve_plugins":
            return {"resolved": arguments["needs"], "hub": {"installable": []}}
        if name == "agentlas.memory.status":
            return {"expected_layout": {"soul": ".agentlas/project-soul-memory.md"}}
        if name == "agentlas.wizard.start":
            return {"ok": True, "scope": "global", "root": arguments["memoryRoot"]}
        if name == "agentlas.soul.update":
            return {"write_to": ".agentlas/project-soul-memory.md", "append": "\n### note\n- hub invocation\n"}
        raise AssertionError(name)

    monkeypatch.setattr("agentlas_cloud.networking.hub_invocation.call_hub_tool", fake_call)

    result = invoke_hub_agent(
        "Review this generated agent repository for release readiness.",
        slug="hub-only-reviewer",
        hub_decision={
            "action": "hub_candidates",
            "receipt_id": "route123",
            "hub": {"results": [{"slug": "hub-only-reviewer", "kind": "cloud-callable", "callable": True}]},
        },
        memory_root=memory_root,
        home=home,
    )

    assert result["status"] == "prepared"
    assert result["slug"] == "hub-only-reviewer"
    assert result["local_route_used"] is False
    assert result["restricted_slug_present"] is False
    assert result["memory"]["status"] == "updated"
    assert (memory_root / "memory-map.json").is_file()
    assert (memory_root / "project-soul-memory.md").read_text(encoding="utf-8").count("hub invocation") == 1
    assert (memory_root / "invocation-ledger.jsonl").is_file()
    assert [name for name, _ in calls] == [
        "agentlas.get_runtime_bundle",
        "agentlas.resolve_plugins",
        "agentlas.memory.status",
        "agentlas.wizard.start",
        "agentlas.soul.update",
    ]


def test_hub_invocation_does_not_prepare_invalid_bundle(tmp_path, monkeypatch):
    home = tmp_path / "networking"
    init_networking(home)
    calls = []

    def fake_call(name, arguments=None, home=None, timeout=15):
        calls.append((name, arguments or {}))
        if name == "agentlas.get_runtime_bundle":
            return {
                "error": "manifest_invalid",
                "status": "Needs setup",
                "message": "agentlas.json is missing required fields.",
                "missingFields": ["packageHash"],
            }
        raise AssertionError(name)

    monkeypatch.setattr("agentlas_cloud.networking.hub_invocation.call_hub_tool", fake_call)

    result = invoke_hub_agent(
        "Run a Hub task.",
        slug="broken-hub-agent",
        hub_decision={
            "action": "hub_candidates",
            "receipt_id": "route123",
            "hub": {"results": [{"slug": "broken-hub-agent", "kind": "cloud-callable", "callable": True}]},
        },
        memory_root=tmp_path / "agentlas-memory",
        home=home,
    )

    assert result["status"] == "bundle_unavailable"
    assert result["slug"] == "broken-hub-agent"
    assert result["hub_response"]["error"] == "manifest_invalid"
    assert "packageHash" in result["detail"]
    assert [name for name, _ in calls] == ["agentlas.get_runtime_bundle"]
    assert not (tmp_path / "agentlas-memory").exists()


def test_hub_invocation_does_not_prepare_incomplete_bundle(tmp_path, monkeypatch):
    home = tmp_path / "networking"
    init_networking(home)

    def fake_call(name, arguments=None, home=None, timeout=15):
        if name == "agentlas.get_runtime_bundle":
            return {"bundle": {"agent": arguments["slug"], "entry": {"path": "AGENTS.md", "content": ""}}}
        raise AssertionError(name)

    monkeypatch.setattr("agentlas_cloud.networking.hub_invocation.call_hub_tool", fake_call)

    result = invoke_hub_agent(
        "Run a Hub task.",
        slug="incomplete-hub-agent",
        hub_decision={
            "action": "hub_candidates",
            "receipt_id": "route123",
            "hub": {"results": [{"slug": "incomplete-hub-agent", "kind": "cloud-callable", "callable": True}]},
        },
        home=home,
    )

    assert result["status"] == "bundle_unavailable"
    assert result["missing_fields"] == ["packageHash", "entry.content", "toolPermissions"]


def test_hub_invocation_restricted_slug_is_not_blocked_locally(tmp_path, monkeypatch):
    # A restricted-scope slug that overlaps a local private/restricted card is NOT
    # short-circuited locally. Every caller goes through the SAME server policy
    # (auth + credit gate); the old blocked-overlap guard is gone. The slug is still
    # recorded as restricted in the audit — it just no longer forks behavior.
    home = tmp_path / "networking"
    init_networking(home)
    restricted = make_ready_card(
        tmp_path,
        "restricted-agent",
        triggers_ko=["사설 에이전트"],
        triggers_en=["restricted-agent task", "premium agent task", "private agent task"],
        antis=["public hub", "private-agent task", "demo task"],
        capabilities=["review_private_task"],
    )
    restricted["id"] = "restricted/restricted-agent"
    save_card(home, restricted)

    def fake_call(name, arguments=None, home=None, timeout=15):
        if name == "agentlas.get_runtime_bundle":
            return {
                "bundle": {
                    "agent": arguments["slug"],
                    "packageHash": "sha256:test",
                    "entry": {"path": "AGENTS.md", "content": "Review a private agent repo."},
                    "toolPermissions": {"network": "ask", "fileRead": "manifest-allowlist"},
                }
            }
        if name == "agentlas.resolve_plugins":
            return {"resolved": arguments["needs"], "hub": {"installable": []}}
        if name == "agentlas.memory.status":
            return {"expected_layout": {"soul": ".agentlas/project-soul-memory.md"}}
        if name == "agentlas.wizard.start":
            return {"ok": True, "scope": "global", "root": arguments["memoryRoot"]}
        if name == "agentlas.soul.update":
            return {"write_to": ".agentlas/project-soul-memory.md", "append": "\n### note\n- restricted call\n"}
        raise AssertionError(name)

    monkeypatch.setattr("agentlas_cloud.networking.hub_invocation.call_hub_tool", fake_call)

    result = invoke_hub_agent(
        "Run a Hub task.",
        slug="restricted-agent",
        hub_decision={
            "action": "hub_candidates",
            "receipt_id": "route123",
            "hub": {"results": [{"slug": "restricted-agent", "kind": "cloud-callable", "callable": True}]},
        },
        memory_root=tmp_path / "agentlas-memory",
        home=home,
    )

    assert result["status"] == "prepared"
    assert result["slug"] == "restricted-agent"
    assert result["restricted_slug_present"] is True


def test_hub_invocation_surfaces_insufficient_credits(tmp_path, monkeypatch):
    # A server credit refusal is surfaced as a clean status (not the generic
    # bundle_unavailable), and no memory store is created since no work ran.
    home = tmp_path / "networking"
    init_networking(home)

    def fake_call(name, arguments=None, home=None, timeout=15):
        if name == "agentlas.get_runtime_bundle":
            return {
                "error": "insufficient_credits",
                "needed": 5,
                "have": 1,
                "upgrade": "/pricing",
                "message": "Not enough credits.",
            }
        raise AssertionError(name)

    monkeypatch.setattr("agentlas_cloud.networking.hub_invocation.call_hub_tool", fake_call)

    result = invoke_hub_agent(
        "Run a Hub task.",
        slug="pricey-agent",
        hub_decision={
            "action": "hub_candidates",
            "receipt_id": "route123",
            "hub": {"results": [{"slug": "pricey-agent", "kind": "cloud-callable", "callable": True}]},
        },
        memory_root=tmp_path / "agentlas-memory",
        home=home,
    )

    assert result["status"] == "insufficient_credits"
    assert result["needed"] == 5
    assert result["have"] == 1
    assert result["upgrade"] == "/pricing"
    assert not (tmp_path / "agentlas-memory").exists()
