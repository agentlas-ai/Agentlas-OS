from agentlas_cloud.networking.search_call import call_agents, parse_agent_refs, search_agents


def test_search_agents_returns_cloud_bookmark_and_hub_sections(tmp_path, monkeypatch):
    calls = []

    def fake_search_hub(tokens, home=None, approved=False, scope="network"):
        calls.append((tuple(tokens), scope))
        return {
            "status": "ok",
            "scope": scope,
            "query": " ".join(tokens),
            "results": [
                {
                    "slug": f"{scope}-analyst",
                    "name": f"{scope.title()} Analyst",
                    "tagline": "Builds market report briefs.",
                    "kind": "cloud-callable",
                    "callable": True,
                    "routingReady": True,
                }
            ],
        }

    monkeypatch.setattr("agentlas_cloud.networking.search_call.search_hub", fake_search_hub)
    result = search_agents("시장 리포트 에이전트 찾아줘", home=tmp_path / "networking", limit=10)

    assert result["action"] == "agent_search"
    assert result["sections"]["cloud"]["results"][0]["slug"] == "cloud-analyst"
    assert result["sections"]["bookmarks"]["results"][0]["slug"] == "bookmark-analyst"
    assert result["sections"]["hub"]["results"][0]["slug"] == "network-analyst"
    assert result["sections"]["hub"]["results"][0]["description"] == "Builds market report briefs."
    assert result["receipt_id"]
    assert [scope for _, scope in calls] == ["cloud", "bookmark", "network"]


def test_search_agents_retries_with_expanded_intent_when_hub_clarifies(tmp_path, monkeypatch):
    calls = []

    def fake_search_hub(tokens, home=None, approved=False, scope="network"):
        calls.append((tuple(tokens), scope))
        if "market" not in tokens:
            return {"status": "clarify", "scope": scope, "query": " ".join(tokens), "reason": "low_confidence"}
        return {
            "status": "ok",
            "scope": scope,
            "query": " ".join(tokens),
            "results": [
                {
                    "slug": f"{scope}-researcher",
                    "name": "Researcher",
                    "tagline": "Researches market reports.",
                    "kind": "cloud-callable",
                    "callable": True,
                }
            ],
        }

    monkeypatch.setattr("agentlas_cloud.networking.search_call.search_hub", fake_search_hub)
    result = search_agents("시장 리포트 써야 하는데 쓸만한 에이전트 찾아줘", home=tmp_path / "networking")

    assert result["sections"]["hub"]["results"][0]["slug"] == "network-researcher"
    assert result["sections"]["hub"]["fallbackReason"] == "clarify"
    assert any("market" in tokens and scope == "network" for tokens, scope in calls)


def test_call_agents_prepares_exact_named_slugs(tmp_path, monkeypatch):
    prepared = []

    def fake_invoke(request, **kwargs):
        prepared.append((request, kwargs))
        return {
            "action": "hub_invoke",
            "status": "prepared",
            "slug": kwargs["slug"],
            "execution_id": f"exec-{kwargs['slug']}",
            "output": {"entry_excerpt": "Do the work.", "grounding": {"directive": "Use local memory if relevant."}},
        }

    monkeypatch.setattr("agentlas_cloud.networking.search_call.invoke_hub_agent", fake_invoke)
    result = call_agents(
        "hub:market-researcher, cloud:report-writer",
        "시장 리포트 작성",
        home=tmp_path / "networking",
    )

    assert result["status"] == "prepared"
    assert [item["slug"] for item in result["agents"]] == ["market-researcher", "report-writer"]
    assert [item["requested_scope"] for item in result["agents"]] == ["hub", "cloud"]
    assert result["receipt_id"]
    assert [kwargs["slug"] for _, kwargs in prepared] == ["market-researcher", "report-writer"]


def test_parse_agent_refs_dedupes_comma_and_newline_input():
    assert parse_agent_refs("a, b\na") == ["a", "b"]


def test_call_agents_strips_router_marketplace_tiers(tmp_path, monkeypatch):
    prepared = []

    def fake_invoke(request, **kwargs):
        prepared.append(kwargs)
        return {"status": "prepared", "slug": kwargs["slug"]}

    monkeypatch.setattr("agentlas_cloud.networking.search_call.invoke_hub_agent", fake_invoke)
    result = call_agents(
        "paid/agentlas-prd-maker-studio, free/researcher-017-agent-repo-security-regression-suite",
        "Run the routed stages.",
        home=tmp_path / "networking",
    )

    assert result["status"] == "prepared"
    assert [item["slug"] for item in result["agents"]] == [
        "agentlas-prd-maker-studio",
        "researcher-017-agent-repo-security-regression-suite",
    ]
    assert [item["requested_scope"] for item in result["agents"]] == ["hub", "hub"]


def test_call_agents_preserves_exact_scope_and_entity_kind(tmp_path, monkeypatch):
    prepared = []

    def fake_invoke(request, **kwargs):
        prepared.append(kwargs)
        return {"status": "prepared", "slug": kwargs["slug"], "entityKind": kwargs.get("expected_entity_kind")}

    monkeypatch.setattr("agentlas_cloud.networking.search_call.invoke_hub_agent", fake_invoke)
    result = call_agents(
        "cloud/team/release-control, hub/agent/reviewer",
        "Run exact units.",
        home=tmp_path / "networking",
    )

    assert [item["slug"] for item in result["agents"]] == ["release-control", "reviewer"]
    assert [item["requested_scope"] for item in result["agents"]] == ["cloud", "hub"]
    assert [item["requested_entity_kind"] for item in result["agents"]] == ["team", "agent"]
    assert [item["expected_entity_kind"] for item in prepared] == ["team", "agent"]
