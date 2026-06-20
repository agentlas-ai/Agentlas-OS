"""Domain-coherence + semantic routing guards.

Regression for the polysemy mis-route where a game "에셋"(art asset) request
surfaced a financial "자산/운용"(asset management) team.
"""

from agentlas_cloud.networking import init_networking, route_request, save_card
from agentlas_cloud.networking.domains import classify_domains
from test_network_cards import make_ready_card


def test_classify_domains_separates_game_and_finance():
    assert classify_domains("2D 게임 스프라이트 타일셋 에셋 제작") == ["game"]
    assert classify_domains("증권 종목 포트폴리오 리밸런싱") == ["finance"]
    # bare polysemous words alone resolve to NO domain (must not bias)
    assert classify_domains("에셋 자산 제작") == []
    # genuinely mixed context surfaces both → ambiguous (caller must not penalize)
    assert set(classify_domains("게임 만들고 증권 투자도")) == {"game", "finance"}


def _setup(tmp_path):
    home = tmp_path / "networking"
    init_networking(home)
    game = make_ready_card(
        tmp_path,
        "game-studio",
        triggers_ko=["게임 스프라이트 에셋 만들어줘", "2D 타일셋 배경 에셋 제작해줘"],
        triggers_en=["create game sprite assets", "design 2d tileset backgrounds", "game art asset pack"],
        antis=["financial portfolio", "legal contract", "instagram campaign"],
        capabilities=["create_game_sprites", "design_tilesets"],
        domains=["game"],
    )
    # Finance card deliberately shares the lexical token "제작"(produce) with a
    # game request, so without the domain guard it would co-surface.
    finance = make_ready_card(
        tmp_path,
        "asset-firm",
        triggers_ko=["증권 종목 발굴해줘", "포트폴리오 리밸런싱 제작 리포트"],
        triggers_en=["screen stock ideas", "rebalance my portfolio", "equity research report"],
        antis=["game art", "sprite sheet", "tileset"],
        capabilities=["screen_stock_ideas", "rebalance_portfolio"],
        domains=["finance"],
    )
    save_card(home, game)
    save_card(home, finance)
    return home


def test_game_request_does_not_route_to_finance(tmp_path):
    home = _setup(tmp_path)
    result = route_request("게임 스프라이트 에셋 만들어줘", home=home, use_hub=False)
    # Must never select the finance team for a game-asset request.
    if result.get("action") == "route":
        assert result["selected"]["id"] == "local/game-studio"
    selected_or_candidates = [c.get("id") for c in (result.get("candidates") or [])]
    if result.get("selected"):
        selected_or_candidates.append(result["selected"]["id"])
    assert "local/asset-firm" not in selected_or_candidates


def test_finance_request_still_routes_to_finance(tmp_path):
    home = _setup(tmp_path)
    result = route_request("증권 종목 발굴해줘", home=home, use_hub=False)
    assert result.get("action") == "route"
    assert result["selected"]["id"] == "local/asset-firm"


def test_score_card_domain_penalty_and_boost(tmp_path):
    from agentlas_cloud.networking import router

    game = make_ready_card(
        tmp_path, "g", triggers_ko=["게임 에셋"], triggers_en=["game asset"],
        antis=["finance", "legal", "design"], capabilities=["create_game_sprites"], domains=["game"],
    )
    finance = make_ready_card(
        tmp_path, "f", triggers_ko=["증권 투자"], triggers_en=["stock invest"],
        antis=["game", "legal", "design"], capabilities=["screen_stock_ideas"], domains=["finance"],
    )
    router._INDEX_CACHE.clear()
    q = {"게임", "에셋", "game", "asset"}
    base_game, _ = router._score_card(game, q, {}, False, 4.5, query_domains=None)
    boosted_game, _ = router._score_card(game, q, {}, False, 4.5, query_domains={"game"}, domain_boost=1.5)
    base_fin, _ = router._score_card(finance, q, {}, False, 4.5, query_domains=None)
    penal_fin, _ = router._score_card(finance, q, {}, False, 4.5, query_domains={"game"}, domain_penalty=6.0)
    assert boosted_game == base_game + 1.5  # same-domain boost
    assert penal_fin == base_fin - 6.0       # cross-domain penalty


def test_card_derived_ontology_populates_graph_path(tmp_path):
    home = _setup(tmp_path)
    result = route_request("게임 스프라이트 에셋 만들어줘", home=home, use_hub=False)
    # The global cards now form a card-derived AO graph (not blind lexical).
    assert result["fallback_scope"] == "card_derived_ontology"
    assert "agent_ontology_graph_cards" in result["allowed_by"]
    if result.get("action") == "route":
        assert result["selected"]["id"] == "local/game-studio"
        # Routed card carries a concrete ontology edge (domain -> agent).
        assert result["graph_path"], "card-derived route must emit a graph_path"
        edge = result["graph_path"][0]
        assert edge["to"] == "local/game-studio"
        assert edge["relation"] in ("in_domain", "routes_to")


def test_ingest_routing_cards_materializes_ao_graph(tmp_path):
    import json as _json

    from agentlas_cloud.agent_graph import build_card_ontology, ingest_routing_cards

    cards = [
        {
            "id": "local/game-studio",
            "name": "game studio",
            "capabilities": ["create_game_sprites", "design_tilesets"],
            "domains": ["game"],
        },
        {
            "id": "local/asset-firm",
            "name": "asset firm",
            "capabilities": ["screen_stock_ideas"],
            "domains": ["finance"],
        },
    ]
    graph = build_card_ontology(cards)
    assert "local/game-studio" in graph["node_index"]
    assert "game" in graph["domains"] and "finance" in graph["domains"]
    assert any(e["relation"] == "in_domain" and e["to"] == "local/game-studio" for e in graph["edges"])

    home = tmp_path / "net"
    home.mkdir()
    summary = ingest_routing_cards(home, cards)
    assert summary["agents"] == 2
    ao_dir = home / "agent-ontology"
    agents = [_json.loads(line) for line in (ao_dir / "agents.jsonl").read_text().splitlines() if line.strip()]
    assert {a["id"] for a in agents} == {"local/game-studio", "local/asset-firm"}
    assert all(a["type"] == "ExternalAgent" for a in agents)
    domains = [_json.loads(line) for line in (ao_dir / "domains.jsonl").read_text().splitlines() if line.strip()]
    assert {d["name"] for d in domains} == {"game", "finance"}
