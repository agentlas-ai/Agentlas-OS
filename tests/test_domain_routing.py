"""Domain-coherence + semantic routing guards.

Regression for the polysemy mis-route where a game "에셋"(art asset) request
surfaced a financial "자산/운용"(asset management) team. These tests are written
to be LOAD-BEARING: they toggle the guard on/off (via a policy file) and use a
finance fixture that lexically cross-routes the game query, so a test fails if
the guard is ever removed — not merely if the lexical scores happen to diverge.
"""

import json

from agentlas_cloud.networking import init_networking, route_request, save_card
from agentlas_cloud.networking.bootstrap import default_routing_policy
from agentlas_cloud.networking.domains import classify_domains
from test_network_cards import make_ready_card


def _write_policy(home, **overrides):
    policy = default_routing_policy()
    policy.update(overrides)
    pdir = home / "policies"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "routing-policy.json").write_text(json.dumps(policy), encoding="utf-8")


def _ids(result):
    out = [c.get("id") for c in (result.get("candidates") or [])]
    if result.get("selected"):
        out.append(result["selected"]["id"])
    return out


def _card_score(result, card_id):
    for key in ("candidates", "suggestions"):
        for c in (result.get(key) or []):
            if c.get("id") == card_id:
                return c.get("score")
    sel = result.get("selected")
    if sel and sel.get("id") == card_id:
        return sel.get("score")
    return None


# ── taxonomy: substring-collision regressions ───────────────────────────────


def test_classify_domains_separates_game_and_finance():
    assert classify_domains("2D 게임 스프라이트 타일셋 에셋 제작") == ["game"]
    assert classify_domains("증권 종목 포트폴리오 리밸런싱") == ["finance"]
    # bare polysemous words alone resolve to NO domain (must not bias)
    assert classify_domains("에셋 자산 제작") == []
    # genuinely mixed context surfaces both → ambiguous (caller must not penalize)
    assert set(classify_domains("게임 만들고 증권 투자도")) == {"game", "finance"}


def test_classify_domains_no_substring_false_positives():
    # '주식' must not fire inside '주식회사' (Inc./Co.) — a pure software task.
    assert "finance" not in classify_domains("주식회사 코드리뷰 자동화 도구")
    assert classify_domains("주식 매수 종목 추천 봇") == ["finance"]
    # '영업' must not fire inside 영업비밀(trade secret) / 영업이익(operating profit).
    assert "sales" not in classify_domains("영업비밀 유출 관련 소송 준비서면")
    assert "sales" in classify_domains("신규 영업 전략 수립 도와줘")
    # ASCII markers match only at word boundaries.
    assert "finance" not in classify_domains("직무 평가 evaluation 시스템")
    assert classify_domains("company valuation DCF 모델") == ["finance"]
    assert "design" not in classify_domains("canvas 위에 그림 그리는 앱")
    assert "productivity" not in classify_domains("notional value 계산")
    # coverage the commit claimed but originally missed
    assert classify_domains("자산관리 포트폴리오 상담") == ["finance"]
    assert classify_domains("자산 관리 리포트") == ["finance"]


# ── end-to-end routing guard ────────────────────────────────────────────────


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
    # Finance card deliberately shares the WHOLE words 게임+에셋 with the game
    # request, so without the domain guard it scores > 0 and co-surfaces. Its
    # domain is pinned to finance, so the guard (not the lexical scorer) is what
    # must keep it out of a game route — this is what makes the test load-bearing.
    finance = make_ready_card(
        tmp_path,
        "asset-firm",
        triggers_ko=["증권 종목 발굴해줘", "게임 에셋 투자 가치 산정해줘", "포트폴리오 리밸런싱 리포트"],
        triggers_en=["screen stock ideas", "rebalance my portfolio", "equity research report"],
        antis=["sprite sheet", "tileset", "instagram ad"],
        capabilities=["screen_stock_ideas", "rebalance_portfolio"],
        domains=["finance"],
    )
    save_card(home, game)
    save_card(home, finance)
    return home


def test_polysemy_guard_demotes_cross_domain_finance(tmp_path):
    home = _setup(tmp_path)
    query = "게임 스프라이트 에셋 만들어줘"

    # Guard OFF (penalty+boost forced to 0): the finance card lexically overlaps
    # the game query (게임+에셋), so it scores > 0 and appears.
    _write_policy(home, domain_penalty=0.0, domain_boost=0.0, semantic_weight=0.0)
    off = route_request(query, home=home, use_hub=False)
    score_off = _card_score(off, "local/asset-firm")
    assert score_off is not None and score_off > 0, "fixture must make finance lexically cross-route"

    # Guard ON (defaults): finance is never the SELECTED route for a game request,
    # and the guard DEMOTES it (load-bearing: this fails if the penalty is removed,
    # because then score_on would equal score_off).
    _write_policy(home)
    on = route_request(query, home=home, use_hub=False)
    assert (on.get("selected") or {}).get("id") != "local/asset-firm"
    if on.get("action") == "route":
        assert on["selected"]["id"] == "local/game-studio"
    score_on = _card_score(on, "local/asset-firm")
    assert score_on is not None and score_on < score_off


def test_finance_request_still_routes_to_finance(tmp_path):
    home = _setup(tmp_path)
    query = "증권 종목 발굴해줘"
    # No-regress: a legitimate finance query routes to finance with the guard on,
    # and the guard does not change that decision (compare against guard off).
    _write_policy(home, domain_penalty=0.0, domain_boost=0.0, semantic_weight=0.0)
    off = route_request(query, home=home, use_hub=False)
    _write_policy(home)
    on = route_request(query, home=home, use_hub=False)
    assert on.get("action") == "route"
    assert on["selected"]["id"] == "local/asset-firm"
    assert (off.get("selected") or {}).get("id") == on["selected"]["id"]


# ── _score_card arithmetic + the mis-classification floor ───────────────────


def test_score_card_domain_penalty_and_boost(tmp_path):
    from agentlas_cloud.networking import router

    game = make_ready_card(
        tmp_path, "g", triggers_ko=["게임 에셋"], triggers_en=["game asset"],
        antis=["finance", "legal", "design"], capabilities=["create_game_sprites"], domains=["game"],
    )
    router._INDEX_CACHE.clear()
    q = {"게임", "에셋", "game", "asset"}
    base_game, _ = router._score_card(game, q, {}, False, 4.5, query_domains=None)
    boosted_game, _ = router._score_card(game, q, {}, False, 4.5, query_domains={"game"}, domain_boost=1.5)
    assert base_game > 0
    assert boosted_game == base_game + 1.5  # same-domain boost


def test_cross_domain_penalty_demotes_but_never_eliminates(tmp_path):
    # The #3 regression fix: a single-domain MIS-classification must DEMOTE a
    # lexically-relevant correct card, not silently drop it below the score>0
    # gate. With a penalty larger than the lexical score, the card floors at a
    # tiny positive value (stays eligible) instead of going non-positive.
    from agentlas_cloud.networking import router

    game = make_ready_card(
        tmp_path, "g2", triggers_ko=["게임 에셋"], triggers_en=["game asset"],
        antis=["finance", "legal", "design"], capabilities=["create_game_sprites"], domains=["game"],
    )
    router._INDEX_CACHE.clear()
    q = {"게임", "에셋", "game", "asset"}
    base_game, _ = router._score_card(game, q, {}, False, 4.5, query_domains=None)
    assert 0 < base_game < 100  # lexically relevant
    # Query wrongly classified as finance; the genuinely-correct game card is now
    # "cross-domain". A huge penalty must not eliminate it.
    floored, reasons = router._score_card(
        game, q, {}, False, 4.5, query_domains={"finance"}, domain_penalty=base_game + 50.0
    )
    assert floored > 0, "penalty alone must not drop a lexically-relevant card below the gate"
    assert any("cross-domain penalty" in r for r in reasons)


def test_name_only_match_cannot_cross_confident_route_threshold(tmp_path):
    from agentlas_cloud.networking import router

    card = make_ready_card(
        tmp_path,
        "alpha-beta",
        triggers_ko=["무관한 한국어 요청", "또 다른 무관한 요청"],
        triggers_en=["unrelated request", "separate task", "different work"],
        antis=["finance", "legal", "deployment"],
        capabilities=["handle_unrelated_work"],
        domains=[],
    )
    card["summary"] = "unrelated specialist"
    router._INDEX_CACHE.clear()

    score, reasons = router._score_card(card, {"alpha", "beta"}, {}, False, 4.5)

    assert score == 4.49
    assert "name match x2" in reasons
    assert "name-only cap: weak signal, forcing rerank ceiling" in reasons


def test_name_match_with_substantive_trigger_is_not_capped(tmp_path):
    from agentlas_cloud.networking import router

    card = make_ready_card(
        tmp_path,
        "alpha-beta",
        triggers_ko=["무관한 한국어 요청", "또 다른 무관한 요청"],
        triggers_en=["alpha beta build", "separate task", "different work"],
        antis=["finance", "legal", "deployment"],
        capabilities=["handle_unrelated_work"],
        domains=[],
    )
    card["summary"] = "unrelated specialist"
    router._INDEX_CACHE.clear()

    score, reasons = router._score_card(card, {"alpha", "beta", "build"}, {}, False, 4.5)

    assert score > 4.5
    assert any(reason.startswith("trigger overlap") for reason in reasons)
    assert not any(reason.startswith("name-only cap") for reason in reasons)


# ── card-derived ontology graph_path ────────────────────────────────────────


def test_card_derived_ontology_populates_graph_path(tmp_path):
    home = _setup(tmp_path)
    result = route_request("게임 스프라이트 에셋 만들어줘", home=home, use_hub=False)
    assert result["fallback_scope"] == "card_derived_ontology"
    assert "agent_ontology_graph_cards" in result["allowed_by"]
    if result.get("action") == "route":
        assert result["selected"]["id"] == "local/game-studio"
        assert result["graph_path"], "card-derived route must emit a graph_path"
        edge = result["graph_path"][0]
        # Query and card share the 'game' domain → a concrete in_domain edge,
        # NOT the degenerate routes_to fallback.
        assert edge["relation"] == "in_domain"
        assert edge["from"] == "domain:game"
        assert edge["to"] == "local/game-studio"


def test_card_route_path_does_not_fabricate_domain_edge():
    from agentlas_cloud.agent_graph import card_route_path

    # query shares the card's domain → in_domain edge
    shared = card_route_path("local/x", {"game"}, {"game"})
    assert shared == [{"from": "domain:game", "to": "local/x", "relation": "in_domain", "kind": "card_ontology"}]
    # card has a domain but the query has NONE → must NOT claim in_domain; the
    # domain logic did not drive this route.
    no_query_domain = card_route_path("local/x", {"game"}, set())
    assert no_query_domain == [{"from": "router", "to": "local/x", "relation": "routes_to", "kind": "card_ontology"}]
    # neither side has a domain → plain routes_to
    assert card_route_path("local/x", set(), set())[0]["relation"] == "routes_to"


# ── semantic graceful fallback ──────────────────────────────────────────────


def test_routing_survives_unavailable_semantic_adapter(tmp_path, monkeypatch):
    from agentlas_cloud.networking import router

    home = _setup(tmp_path)
    monkeypatch.setattr(router, "_VECTOR_ADAPTER", None)
    router._EMBED_CACHE.clear()
    # With no embedding adapter the semantic signal degrades to nothing; routing
    # must still work and never raise.
    result = route_request("게임 스프라이트 에셋 만들어줘", home=home, use_hub=False)
    if result.get("action") == "route":
        assert result["selected"]["id"] == "local/game-studio"
    assert (result.get("selected") or {}).get("id") != "local/asset-firm"


# ── AO graph materialization ────────────────────────────────────────────────


def test_ingest_routing_cards_materializes_ao_graph(tmp_path):
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
    assert any(e["relation"] == "has_capability" and e["from"] == "local/game-studio" for e in graph["edges"])

    home = tmp_path / "net"
    home.mkdir()
    summary = ingest_routing_cards(home, cards)
    assert summary["agents"] == 2
    ao_dir = home / "agent-ontology"
    agents = [json.loads(line) for line in (ao_dir / "agents.jsonl").read_text().splitlines() if line.strip()]
    assert {a["id"] for a in agents} == {"local/game-studio", "local/asset-firm"}
    assert all(a["type"] == "ExternalAgent" for a in agents)
    domains = [json.loads(line) for line in (ao_dir / "domains.jsonl").read_text().splitlines() if line.strip()]
    assert {d["name"] for d in domains} == {"game", "finance"}
