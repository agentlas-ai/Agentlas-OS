import json

from agentlas_cloud.networking import init_networking, load_global_cards, route_request, save_card
from agentlas_cloud.networking.bench import run_bench
from agentlas_cloud.networking.tokenize import tokenize
from test_network_cards import make_ready_card


def setup_home(tmp_path):
    home = tmp_path / "networking"
    init_networking(home)
    insta = make_ready_card(
        tmp_path,
        "insta-team",
        triggers_ko=["인스타그램 마케팅 콘텐츠 만들어줘", "인스타 릴스 캠페인 기획해줘"],
        triggers_en=["create instagram marketing content", "plan an instagram reels campaign", "instagram growth plan"],
        antis=["legal contract review", "ios testflight deploy", "database schema design"],
        capabilities=["plan_instagram_content", "write_marketing_captions", "schedule_social_posts"],
    )
    legal = make_ready_card(
        tmp_path,
        "legal-review",
        triggers_ko=["계약서 검토해줘", "법률 계약 리스크 확인"],
        triggers_en=["review this contract", "check legal risks in the agreement", "contract clause analysis"],
        antis=["instagram content", "social media campaign", "image generation"],
        capabilities=["review_legal_contracts", "flag_contract_risks"],
    )
    save_card(home, insta)
    save_card(home, legal)
    return home


def _assert_routing_evidence_fields(result: dict) -> None:
    assert isinstance(result.get("match_reason"), str)
    assert isinstance(result.get("graph_path"), list)
    assert isinstance(result.get("allowed_by"), list)
    assert isinstance(result.get("blocked_by_axiom"), list)
    assert result["agent_os_router"]["command_model"] == "three_command"
    assert result["agent_os_router"]["commands"]["build"] == "hep-build"
    assert result["policy_decision"]["mode"] == "local_operator"
    assert result["memory_playbook"]["mode"] == "memory_playbook_control_plane"
    assert result["task_force"]["mode"] == "agent_os_router"
    assert "fallback_scope" in result
    assert result.get("receipt_id")


def _write_minimal_ao_graph(project, agents):
    ontology = project / ".agentlas" / "agent-ontology"
    ontology.mkdir(parents=True)
    (ontology / "agents.jsonl").write_text(
        "\n".join(json.dumps(agent, ensure_ascii=False) for agent in agents) + "\n",
        encoding="utf-8",
    )
    (ontology / "artifacts.jsonl").write_text("", encoding="utf-8")
    (ontology / "edges.jsonl").write_text("", encoding="utf-8")
    (ontology / "capabilities.json").write_text(
        json.dumps({"capabilities": ["run_regression_tests"]}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def test_routes_to_best_card(tmp_path):
    home = setup_home(tmp_path)
    result = route_request("인스타그램 마케팅 콘텐츠 만들어줘", home=home, use_hub=False)
    assert result["action"] == "route"
    assert result["selected"]["id"] == "local/insta-team"
    assert result["receipt_id"]
    _assert_routing_evidence_fields(result)
    ledger = (home / "ledgers" / "routing-decisions.jsonl").read_text(encoding="utf-8")
    assert "insta-team" in ledger
    assert "만들어줘" not in ledger  # raw prompt is never persisted verbatim


def test_korean_attached_fillers_are_stripped():
    tokens = tokenize("agentlas 새기능 추천좀")
    assert "추천" in tokens
    assert "기능" in tokens
    assert "새기" not in tokens
    assert "추천좀" not in tokens
    assert "천좀" not in tokens


def test_english_query_routes_too(tmp_path):
    home = setup_home(tmp_path)
    result = route_request("review this contract for legal risks", home=home, use_hub=False)
    assert result["action"] == "route"
    assert result["selected"]["id"] == "local/legal-review"


def test_draft_cards_never_auto_route(tmp_path):
    home = setup_home(tmp_path)
    draft = make_ready_card(
        tmp_path,
        "draft-agent",
        triggers_ko=["초안 작업"],
        triggers_en=["draft work"],
        antis=[],
        capabilities=["draft_things"],
    )
    draft["routing_status"] = "draft"
    draft["trigger_examples"] = [{"text": "wedding photo retouching plan", "locale": "en"}]
    save_card(home, draft)
    result = route_request("wedding photo retouching plan", home=home, use_hub=False)
    assert result["action"] != "route"
    suggestion_ids = {item["id"] for item in result.get("suggestions") or []}
    assert "local/draft-agent" in suggestion_ids


def test_plugins_never_route_as_agents(tmp_path):
    home = setup_home(tmp_path)
    shopify = make_ready_card(
        tmp_path,
        "shopify-dev",
        triggers_ko=["AI처럼 보이지 않게 해줘", "카피를 자연스럽게 다듬어줘"],
        triggers_en=["make this not look AI written", "polish ecommerce copy", "shopify product copy"],
        antis=[],
        capabilities=["shopify_content_tooling", "copy_polish_tool"],
    )
    shopify["id"] = "plugin/shopify-dev"
    shopify["canonical_id"] = "plugin/shopify-dev"
    shopify["type"] = "plugin"
    shopify["name"] = "Shopify Dev Plugin"
    save_card(home, shopify)

    result = route_request("이거 AI처럼 보이지 않게 해줘", home=home, use_hub=False)
    serialized = json.dumps(result, ensure_ascii=False)
    assert result["action"] != "route" or result["selected"]["id"] != "plugin/shopify-dev"
    assert "plugin/shopify-dev" not in serialized
    assert "Shopify Dev Plugin" not in serialized


def test_similar_cards_force_clarify(tmp_path):
    home = setup_home(tmp_path)
    twin = make_ready_card(
        tmp_path,
        "insta-twin",
        triggers_ko=["인스타그램 마케팅 콘텐츠 만들어줘", "인스타 릴스 캠페인 기획해줘"],
        triggers_en=["create instagram marketing content", "plan an instagram reels campaign", "instagram growth plan"],
        antis=["legal contract review", "ios deploy", "database design"],
        capabilities=["plan_instagram_content", "write_marketing_captions"],
    )
    save_card(home, twin)
    result = route_request("인스타그램 마케팅 콘텐츠 만들어줘", home=home, use_hub=False)
    assert result["action"] == "clarify"
    candidate_ids = {item["id"] for item in result["candidates"]}
    assert {"local/insta-team", "local/insta-twin"} <= candidate_ids


def test_korean_query_against_english_only_card_clarifies(tmp_path):
    home = tmp_path / "networking"
    init_networking(home)
    card = make_ready_card(
        tmp_path,
        "en-only",
        triggers_ko=["임시", "임시2"],
        triggers_en=["summarize research papers", "academic literature scan", "paper summary"],
        antis=["payment", "deployment", "deletion"],
        capabilities=["summarize_research_papers"],
    )
    card["locale_coverage"] = {"primary": "en", "ready": ["en"], "partial": ["ko"]}
    card["trigger_examples"] = [entry for entry in card["trigger_examples"] if entry["locale"] == "en"] + [
        {"text": "research summary please", "locale": "en"},
        {"text": "summarize papers fast", "locale": "en"},
    ]
    # keep >=2 ko examples requirement off: force searchable→ not ready... so mark ko examples present but locale not ready
    card["trigger_examples"] += [
        {"text": "논문 요약", "locale": "ko"},
        {"text": "연구 자료 정리", "locale": "ko"},
    ]
    save_card(home, card)
    result = route_request("논문 요약 정리해줘", home=home, use_hub=False)
    assert result["action"] in ("clarify", "propose_new")
    assert result["action"] != "route"


def test_privacy_keywords_do_not_block_hub_lookup(tmp_path, monkeypatch):
    home = setup_home(tmp_path)

    def fake_search_hub(query_tokens, home=None, approved=False):
        assert approved is True
        return {
            "status": "ok",
            "query": " ".join(query_tokens),
            "results": [{"slug": "memory-safe-agent", "name": "Memory Safe Agent", "kind": "cloud-callable"}],
        }

    monkeypatch.setattr("agentlas_cloud.networking.router.search_hub", fake_search_hub)
    result = route_request("내 프로젝트 메모리 전부 클라우드로 업로드해줘", home=home, use_hub=True)
    assert result["action"] == "hub_candidates"
    assert result.get("approval_request") is None


def test_payment_keywords_do_not_add_router_approval(tmp_path):
    home = setup_home(tmp_path)
    result = route_request("인스타그램 마케팅 콘텐츠 만들어서 바로 결제 처리까지 해줘", home=home, use_hub=False)
    assert result["action"] in ("clarify", "route")
    if result["action"] == "route":
        assert result.get("approval_request") is None


def test_card_approval_requirements_do_not_gate_routing(tmp_path):
    home = setup_home(tmp_path)
    cards, _ = load_global_cards(home)
    insta = next(card for card in cards if card["id"] == "local/insta-team")
    insta["approval_requirements"] = ["file_write"]
    insta["risk_profile"] = {"tier": "medium", "capabilities_at_risk": ["file_write"]}
    save_card(home, insta)

    result = route_request("인스타그램 마케팅 콘텐츠 만들어줘", home=home, use_hub=False)
    assert result["action"] == "route"
    assert result["selected"]["id"] == "local/insta-team"
    assert result.get("approval_request") is None


def test_explicit_command_routes_directly(tmp_path):
    home = setup_home(tmp_path)
    result = route_request("/legal-review check this NDA", home=home, use_hub=False)
    assert result["action"] == "route"
    assert result["selected"]["id"] == "local/legal-review"


def test_loop_guard_refuses(tmp_path):
    home = setup_home(tmp_path)
    result = route_request("인스타그램 콘텐츠", home=home, use_hub=False, hop_count=3)
    assert result["action"] == "refuse"
    assert "loop" in result["reasons"][0]
    _assert_routing_evidence_fields(result)
    assert result["match_reason"] == "loop_guard"
    assert result["allowed_by"] == ["loop_guard"]
    assert result["graph_path"] == []
    assert result["blocked_by_axiom"] == []


def test_ao_caller_gate_removes_all_blocked_candidates(tmp_path):
    home = tmp_path / "networking"
    init_networking(home)
    target = make_ready_card(
        tmp_path,
        "target-agent",
        triggers_ko=["회귀 테스트 실행", "품질 검증"],
        triggers_en=["run regression tests", "verify the build", "qa pass"],
        antis=["instagram content", "legal contract", "payment"],
        capabilities=["run_regression_tests"],
    )
    save_card(home, target)

    project = tmp_path / "project"
    _write_minimal_ao_graph(
        project,
        [
            {"id": "local/caller-agent", "type": "Specialist", "name": "Caller"},
            {"id": "local/target-agent", "type": "Specialist", "name": "Target"},
        ],
    )

    result = route_request(
        "run regression tests",
        home=home,
        project_dir=project,
        use_hub=False,
        caller_id="local/caller-agent",
    )

    assert result["action"] == "propose_new"
    assert result["selected"] is None
    assert not result.get("candidates")
    assert result["fallback_scope"] == "local_graph_and_caller_gate"
    assert result["blocked_by_axiom"] == [
        "deny rule matched: local/caller-agent -> routes_to -> local/target-agent"
    ]


def test_hub_fallback_searches_without_approval_gate(tmp_path, monkeypatch):
    home = setup_home(tmp_path)

    def fake_search_hub(query_tokens, home=None, approved=False):
        assert approved is True
        return {
            "status": "ok",
            "query": " ".join(query_tokens),
            "results": [{"slug": "chemistry-simulator", "name": "Chemistry Simulator", "kind": "cloud-callable"}],
        }

    monkeypatch.setattr("agentlas_cloud.networking.router.search_hub", fake_search_hub)
    result = route_request("quantum chemistry simulation pipeline", home=home, use_hub=True)
    assert result["action"] == "hub_candidates"
    assert result.get("approval_request") is None


def test_hub_only_skips_strong_local_match(tmp_path, monkeypatch):
    home = setup_home(tmp_path)

    def fake_search_hub(query_tokens, home=None, approved=False):
        assert approved is True
        return {
            "status": "ok",
            "query": " ".join(query_tokens),
            "results": [{"slug": "hub-instagram-agent", "name": "Hub Instagram Agent", "kind": "cloud-callable"}],
        }

    monkeypatch.setattr("agentlas_cloud.networking.router.search_hub", fake_search_hub)
    result = route_request("인스타그램 마케팅 콘텐츠 만들어줘", home=home, use_hub=True, hub_approved=True, hub_only=True)
    assert result["action"] == "hub_candidates"
    assert result["selected"] is None
    assert result["candidates"] == []
    assert result["suggestions"] == []
    assert result.get("approval_request") is None
    assert result["hub"]["results"][0]["slug"] == "hub-instagram-agent"
    assert result["reasons"] == ["hub_only_results_found"]
    _assert_routing_evidence_fields(result)
    assert result["match_reason"] == "hub_only_hub_results"
    assert result["graph_path"] == []
    assert result["task_force"]["formation"] == "single_stage_hub_candidates"


def test_network_hub_only_prefers_cloud_then_bookmarks_before_public_hub(tmp_path, monkeypatch):
    home = setup_home(tmp_path)
    calls = []

    def fake_search_hub(query_tokens, home=None, approved=False, scope="network"):
        calls.append(scope)
        if scope == "cloud":
            return {"status": "ok", "scope": "cloud", "query": " ".join(query_tokens), "results": []}
        if scope == "bookmark":
            return {
                "status": "ok",
                "scope": "bookmark",
                "query": " ".join(query_tokens),
                "results": [{"slug": "saved-report-agent", "name": "Saved Report Agent", "kind": "cloud-callable"}],
            }
        return {
            "status": "ok",
            "scope": "network",
            "query": " ".join(query_tokens),
            "results": [{"slug": "public-report-agent", "name": "Public Report Agent", "kind": "cloud-callable"}],
        }

    monkeypatch.setattr("agentlas_cloud.networking.router.search_hub", fake_search_hub)
    result = route_request("시장 보고서 작성해줘", home=home, use_hub=True, hub_only=True)

    assert result["action"] == "hub_candidates"
    assert result["hub"]["scope"] == "bookmark"
    assert result["hub"]["results"][0]["slug"] == "saved-report-agent"
    assert calls == ["cloud", "bookmark"]
    assert result["reasons"] == ["hub_only_bookmark_results_found"]
    assert "route_order:cloud_bookmark_hub" in result["allowed_by"]


def test_hub_only_composite_request_forms_stagewise_task_force(tmp_path, monkeypatch):
    home = setup_home(tmp_path)
    seen = []

    def fake_search_hub(query_tokens, home=None, approved=False):
        seen.append(list(query_tokens))
        stage = "generic"
        if "prd" in query_tokens or "plan" in query_tokens:
            stage = "planner"
        elif "codebase_change" in query_tokens or "build" in query_tokens:
            stage = "builder"
        elif "qa_report" in query_tokens or "verify" in query_tokens:
            stage = "verifier"
        return {
            "status": "ok",
            "query": " ".join(query_tokens),
            "results": [{"slug": f"hub-{stage}", "name": f"Hub {stage}", "kind": "cloud-callable"}],
        }

    monkeypatch.setattr("agentlas_cloud.networking.router.search_hub", fake_search_hub)
    result = route_request(
        "기획부터 구현하고 테스트까지 끝까지 처리해줘",
        home=home,
        use_hub=True,
        hub_only=True,
    )

    assert result["action"] == "hub_candidates"
    assert result["match_reason"] == "hub_only_task_force_results"
    assert result["task_force"]["formation"] == "hub_stage_candidates"
    assert result["task_force"]["temporary_tf"] is True
    assert [stage["stage"] for stage in result["task_force"]["stages"]] == ["plan", "build", "verify"]
    assert len(seen) == 3
    assert result["policy_decision"]["decision"] == "allow_with_label"
    assert result["memory_playbook"]["candidates"]


def test_hub_only_uses_whole_word_query_tokens(tmp_path, monkeypatch):
    home = setup_home(tmp_path)
    seen = {}

    def fake_search_hub(query_tokens, home=None, approved=False):
        seen["tokens"] = query_tokens
        return {
            "status": "ok",
            "query": " ".join(query_tokens),
            "results": [{"slug": "shop-product-writer", "name": "Product Copywriter", "kind": "install-only"}],
        }

    monkeypatch.setattr("agentlas_cloud.networking.router.search_hub", fake_search_hub)
    result = route_request("상품 설명 써주는 에이전트", home=home, use_hub=True, hub_approved=True, hub_only=True)

    assert result["action"] == "hub_candidates"
    assert seen["tokens"] == ["상품", "설명", "써주", "에이전트"]


def test_hub_only_surfaces_hub_clarify(tmp_path, monkeypatch):
    home = setup_home(tmp_path)

    def fake_search_hub(query_tokens, home=None, approved=False):
        assert approved is True
        return {
            "status": "clarify",
            "questionKo": "어떤 작업을 맡길까요?",
            "suggestions": [{"slug": "generic-agent"}],
        }

    monkeypatch.setattr("agentlas_cloud.networking.router.search_hub", fake_search_hub)
    result = route_request("agent routing tokenizer trust", home=home, use_hub=True, hub_approved=True, hub_only=True)
    assert result["action"] == "clarify"
    assert result["clarify_question"] == "어떤 작업을 맡길까요?"
    assert result["local_routing"] == "skipped"
    assert result["reasons"] == ["hub_only_low_confidence"]


def test_secretary_does_not_trigger_secret_privacy_gate(tmp_path, monkeypatch):
    home = setup_home(tmp_path)

    def fake_search_hub(query_tokens, home=None, approved=False):
        return {
            "status": "ok",
            "query": " ".join(query_tokens),
            "results": [{"slug": "marketer-schedule-secretary", "name": "Schedule Secretary", "kind": "install-only"}],
        }

    monkeypatch.setattr("agentlas_cloud.networking.router.search_hub", fake_search_hub)
    result = route_request("marketer-schedule-secretary content calendar", home=home, use_hub=True, hub_approved=True, hub_only=True)
    assert result["action"] == "hub_candidates"
    assert result["hub"]["results"][0]["slug"] == "marketer-schedule-secretary"
    assert result["policy_decision"]["decision"] == "allow_with_label"


def test_private_memory_hub_request_auto_redacts_without_human_approval(tmp_path, monkeypatch):
    home = setup_home(tmp_path)

    def fake_search_hub(query_tokens, home=None, approved=False):
        return {
            "status": "ok",
            "query": " ".join(query_tokens),
            "results": [{"slug": "safe-memory-agent", "name": "Safe Memory Agent", "kind": "cloud-callable"}],
        }

    monkeypatch.setattr("agentlas_cloud.networking.router.search_hub", fake_search_hub)
    result = route_request("내 private memory를 참고해서 hub agent 후보 찾아줘", home=home, use_hub=True, hub_only=True)

    assert result["action"] == "hub_candidates"
    assert result.get("approval_request") is None
    assert result["policy_decision"]["decision"] == "auto_redact"
    assert "privacy_confidentiality_boundary" in result["policy_decision"]["labels"]


def test_patent_claim_template_does_not_trigger_payment_or_submit_gate(tmp_path, monkeypatch):
    home = setup_home(tmp_path)

    def fake_search_hub(query_tokens, home=None, approved=False):
        assert approved is True
        return {
            "status": "ok",
            "query": " ".join(query_tokens),
            "results": [{"slug": "korean-patent-document-writer", "name": "Patent Writer", "kind": "cloud-callable"}],
        }

    monkeypatch.setattr("agentlas_cloud.networking.router.search_hub", fake_search_hub)
    result = route_request(
        "특허 명세서 청구항 작성 화면과 특허청 제출 양식 템플릿을 만들어줘",
        home=home,
        use_hub=True,
        hub_approved=True,
        hub_only=True,
    )
    assert result["action"] == "hub_candidates"
    assert result["reasons"] == ["hub_only_results_found"]


def test_reply_or_form_templates_do_not_trigger_action_gates(tmp_path, monkeypatch):
    home = setup_home(tmp_path)

    def fake_search_hub(query_tokens, home=None, approved=False):
        return {
            "status": "ok",
            "query": " ".join(query_tokens),
            "results": [{"slug": "template-writer", "name": "Template Writer", "kind": "cloud-callable"}],
        }

    monkeypatch.setattr("agentlas_cloud.networking.router.search_hub", fake_search_hub)
    for query in (
        "환불 답변 템플릿을 작성해줘",
        "파일 전송 화면 UI를 구현해줘",
        "공개특허 문서 편집 화면을 만들어줘",
    ):
        result = route_request(query, home=home, use_hub=True, hub_approved=True, hub_only=True)
        assert result["action"] == "hub_candidates", query


def test_submit_or_payment_words_do_not_block_hub_bundle_lookup(tmp_path, monkeypatch):
    home = setup_home(tmp_path)
    def fake_search_hub(query_tokens, home=None, approved=False):
        return {
            "status": "ok",
            "query": " ".join(query_tokens),
            "results": [{"slug": "action-word-agent", "name": "Action Word Agent", "kind": "cloud-callable"}],
        }

    monkeypatch.setattr("agentlas_cloud.networking.router.search_hub", fake_search_hub)

    submit = route_request("특허 명세서 파일을 특허청에 바로 제출해줘", home=home, use_hub=True, hub_approved=True, hub_only=True)
    assert submit["action"] == "hub_candidates"

    payment = route_request("고객 환불 결제를 바로 처리해줘", home=home, use_hub=True, hub_approved=True, hub_only=True)
    assert payment["action"] == "hub_candidates"


def test_project_override_wins(tmp_path):
    home = setup_home(tmp_path)
    project = tmp_path / "project"
    (project / ".agentlas").mkdir(parents=True)
    (project / ".agentlas" / "routing-overrides.json").write_text(
        json.dumps({"overrides": [{"contains": "주간 보고", "card_id": "local/legal-review"}]}),
        encoding="utf-8",
    )
    result = route_request("주간 보고 만들어줘", home=home, project_dir=project, use_hub=False)
    assert result["action"] == "route"
    assert result["selected"]["id"] == "local/legal-review"


def test_bench_runner_reports_metrics(tmp_path):
    home = setup_home(tmp_path)
    suite = tmp_path / "suite.jsonl"
    cases = [
        {
            "id": "s1",
            "query": "인스타그램 마케팅 콘텐츠 만들어줘",
            "locale": "ko",
            "expected": {"action": "route", "top1": "local/insta-team", "top3_any": ["local/insta-team"]},
        },
        {
            "id": "s2",
            "query": "review this contract for legal risks",
            "locale": "en",
            "expected": {"action": "route", "top1": "local/legal-review", "top3_any": ["local/legal-review"]},
        },
        {
            "id": "p1",
            "query": "내 메모리 전부 클라우드로 업로드해줘",
            "locale": "ko",
            "tags": ["privacy"],
            "expected": {"action": "propose_new"},
        },
        {
            "id": "h1",
            "query": "quantum chemistry simulation pipeline",
            "locale": "en",
            "tags": ["hub"],
            "expected": {"action": "hub_fallback"},
        },
    ]
    suite.write_text("\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n", encoding="utf-8")
    report = run_bench([suite], home=home)
    assert report["metrics"]["cases"] == 4
    assert report["metrics"]["unsafe_routes"] == 0
    assert report["metrics"]["top3_recall"] == 1.0
    assert report["passed"] is True
    assert (home / "cache" / "bench-status.json").is_file()
