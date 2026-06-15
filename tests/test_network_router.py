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


def test_routes_to_best_card(tmp_path):
    home = setup_home(tmp_path)
    result = route_request("인스타그램 마케팅 콘텐츠 만들어줘", home=home, use_hub=False)
    assert result["action"] == "route"
    assert result["selected"]["id"] == "local/insta-team"
    assert result["receipt_id"]
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
