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
    assert result["paid_slug_present"] is False
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


def test_hub_invocation_blocks_paid_overlap(tmp_path):
    home = tmp_path / "networking"
    init_networking(home)
    paid = make_ready_card(
        tmp_path,
        "paid-agent",
        triggers_ko=["유료 에이전트"],
        triggers_en=["paid agent task", "premium agent task", "private agent task"],
        antis=["public hub", "free agent", "demo task"],
        capabilities=["review_private_task"],
    )
    paid["id"] = "paid/paid-agent"
    save_card(home, paid)

    result = invoke_hub_agent(
        "Run a Hub task.",
        slug="paid-agent",
        hub_decision={
            "action": "hub_candidates",
            "receipt_id": "route123",
            "hub": {"results": [{"slug": "paid-agent", "kind": "cloud-callable", "callable": True}]},
        },
        home=home,
    )

    assert result["status"] == "blocked_paid_overlap"
    assert result["slug"] == "paid-agent"
