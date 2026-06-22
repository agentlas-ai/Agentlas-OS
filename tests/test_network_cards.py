import json

from agentlas_cloud.networking import add_source, init_networking, load_global_cards, reindex, save_card
from agentlas_cloud.networking.card_lint import effective_status, lint_card
from agentlas_cloud.networking.card_migrate import migrate_package


def make_ready_card(tmp_path, slug, *, triggers_ko, triggers_en, antis, capabilities, domains=None):
    fixture = tmp_path / f"bench-{slug}.jsonl"
    fixture.write_text(
        "\n".join(json.dumps({"id": f"{slug}-{i}", "query": f"case {i}"}) for i in range(10)) + "\n",
        encoding="utf-8",
    )
    card = {
        "schemaVersion": "routing-card/2.0",
        "id": f"local/{slug}",
        "canonical_id": f"local/{slug}",
        "type": "agent",
        "name": slug.replace("-", " "),
        "summary": f"{slug} specialist",
        "capabilities": capabilities,
        "trigger_examples": [{"text": text, "locale": "ko"} for text in triggers_ko]
        + [{"text": text, "locale": "en"} for text in triggers_en],
        "anti_triggers": [{"text": text, "locale": "en"} for text in antis],
        "required_inputs": [],
        "entrypoints": {"canonical_command": f"/{slug}"},
        "risk_profile": {"tier": "low", "capabilities_at_risk": []},
        "memory_behavior": {"reads": "project", "writes": "project", "exports_to_cloud": False},
        "cloud_delegation_policy": "never",
        "benchmark_fixtures": str(fixture),
        "locale_coverage": {"primary": "en", "ready": ["ko", "en"], "partial": []},
        "routing_status": "routing_ready",
    }
    if domains is not None:
        card["domains"] = domains
    return card


def test_lint_gates_ready_status(tmp_path):
    card = make_ready_card(
        tmp_path,
        "insta-team",
        triggers_ko=["인스타그램 콘텐츠 만들어줘", "인스타 릴스 기획"],
        triggers_en=["create instagram content", "plan instagram reels", "instagram campaign"],
        antis=["legal contract review", "ios deploy", "code review"],
        capabilities=["plan_instagram_content", "write_captions"],
    )
    report = lint_card(card)
    assert report["errors"] == []
    assert report["ready_blockers"] == []
    assert report["allowed_status"] == "routing_ready"
    assert report["quality_score"] > 0.5


def test_lint_blocks_draft_and_broad_cards(tmp_path):
    draft = {
        "schemaVersion": "routing-card/2.0",
        "id": "restricted/some-agent",
        "type": "agent",
        "name": "some agent",
        "summary": "auto migrated",
        "capabilities": ["do_anything"],
        "routing_status": "routing_ready",
    }
    report = lint_card(draft)
    assert any("do anything" in blocker for blocker in report["ready_blockers"])
    assert effective_status(draft) == "searchable" or effective_status(draft) == "draft"


def test_malformed_card_is_quarantined_individually(tmp_path):
    home = tmp_path / "networking"
    init_networking(home)
    good = make_ready_card(
        tmp_path,
        "good-agent",
        triggers_ko=["좋은 작업 해줘", "문서 정리"],
        triggers_en=["organize documents", "summarize files", "tidy notes"],
        antis=["payment", "deploy", "delete files"],
        capabilities=["organize_documents"],
    )
    save_card(home, good)
    bad_path = home / "cards" / "agents" / "broken.json"
    bad_path.write_text("{not valid json", encoding="utf-8")
    cards, quarantined = load_global_cards(home)
    assert len(cards) == 1
    assert len(quarantined) == 1
    assert "malformed" in quarantined[0]["reason"]


def test_reindex_imports_and_marks_stale(tmp_path):
    home = tmp_path / "networking"
    init_networking(home)
    # Hermetic: default sources point at real plugin caches (which ship a
    # bundled meta-agent card since v0.4.1) — restrict to the test source only.
    from agentlas_cloud.networking.bootstrap import atomic_write_json

    atomic_write_json(home / "sources.json", {"schemaVersion": "2.0", "sources": []})
    package = tmp_path / "packages" / "demo-agent"
    (package / ".agentlas").mkdir(parents=True)
    card = make_ready_card(
        tmp_path,
        "demo-agent",
        triggers_ko=["데모 작업 해줘", "샘플 생성"],
        triggers_en=["run the demo", "generate a sample", "demo task"],
        antis=["payment", "deployment", "deletion"],
        capabilities=["run_demo_tasks"],
    )
    (package / ".agentlas" / "routing-card.json").write_text(json.dumps(card), encoding="utf-8")
    add_source(tmp_path / "packages", home=home)

    report = reindex(home)
    assert report["imported"] == 1
    assert report["stale"] == 0
    assert (home / "registry.sqlite").is_file()

    # Remove the source package: the card must be excluded as stale, not deleted.
    (package / ".agentlas" / "routing-card.json").unlink()
    (package / ".agentlas").rmdir()
    package.rmdir()
    report2 = reindex(home)
    assert report2["stale"] == 1
    cards, _ = load_global_cards(home)
    assert cards[0]["stale"] is True
    assert effective_status(cards[0]) == "stale"


def test_migrate_package_produces_draft(tmp_path):
    home = tmp_path / "networking"
    init_networking(home)
    package = tmp_path / "restricted" / "researcher-099-sample-packager"
    (package / ".agentlas").mkdir(parents=True)
    (package / "AGENTS.md").write_text("# Sample packager\n", encoding="utf-8")
    (package / ".agentlas" / "agent-card.json").write_text(
        json.dumps(
            {
                "protocolVersion": "a2a-1.0-draft",
                "name": "sample-packager",
                "description": "Package sample agents for the marketplace.",
                "capabilities": {"skills": ["build-an"], "runtimeTargets": ["claude-code"], "safety": {"fileAccess": True}},
            }
        ),
        encoding="utf-8",
    )
    result = migrate_package(package, tier="restricted", home=home)
    assert result["status"] == "migrated"
    cards, _ = load_global_cards(home)
    assert len(cards) == 1
    card = cards[0]
    assert card["routing_status"] == "draft"
    assert card["id"] == "restricted/researcher-099-sample-packager"
    assert card["risk_profile"]["capabilities_at_risk"] == ["file_write"]
    assert effective_status(card) in ("draft", "searchable")

    again = migrate_package(package, tier="restricted", home=home)
    assert again["status"] == "kept_existing"


def test_migrate_package_local_becomes_trusted(tmp_path):
    home = tmp_path / "networking"
    init_networking(home)
    package = tmp_path / "local" / "fast-local-agent"
    (package / ".agentlas").mkdir(parents=True)
    (package / "AGENTS.md").write_text("# Fast local agent\n", encoding="utf-8")
    (package / ".agentlas" / "agent-card.json").write_text(
        json.dumps(
            {
                "protocolVersion": "a2a-1.0-draft",
                "name": "fast-local-agent",
                "description": "Local agent package for quick run tests.",
                "capabilities": {"skills": ["run-local"]},
            }
        ),
        encoding="utf-8",
    )
    result = migrate_package(package, tier="local", home=home)
    assert result["status"] == "migrated"
    cards, _ = load_global_cards(home)
    assert len(cards) == 1
    card = cards[0]
    assert card["routing_status"] == "trusted"
    assert effective_status(card) == "trusted"


def _agent_card_package(tmp_path, slug, **card_fields):
    package = tmp_path / "restricted" / slug
    (package / ".agentlas").mkdir(parents=True)
    (package / "AGENTS.md").write_text("# helper\n", encoding="utf-8")
    payload = {
        "protocolVersion": "a2a-1.0-draft",
        "name": slug,
        "description": "Domain-neutral helper.",
        "capabilities": {"skills": ["help"], "runtimeTargets": ["claude-code"]},
    }
    payload.update(card_fields)
    (package / ".agentlas" / "agent-card.json").write_text(json.dumps(payload), encoding="utf-8")
    return package


def test_migrate_package_maps_category_to_domain(tmp_path):
    # The bug the commit set out to fix: an agent-card `category` was silently
    # dropped. It must map to the routing card's `domains`, including when the
    # category casing/whitespace isn't already canonical.
    home = tmp_path / "networking"
    init_networking(home)
    migrate_package(_agent_card_package(tmp_path, "finhelper-001", category="finance"), tier="restricted", home=home)
    migrate_package(_agent_card_package(tmp_path, "finhelper-002", category="  Finance "), tier="restricted", home=home)
    cards, _ = load_global_cards(home)
    by_id = {c["id"]: c for c in cards}
    assert by_id["restricted/finhelper-001"]["domains"] == ["finance"]
    # normalization (strip + lowercase) recovers a non-canonical category
    assert by_id["restricted/finhelper-002"]["domains"] == ["finance"]


def test_backfill_domains_does_not_leak_internal_keys(tmp_path):
    from agentlas_cloud.networking.card_migrate import backfill_domains

    home = tmp_path / "networking"
    init_networking(home)
    card = make_ready_card(
        tmp_path, "stocks",
        triggers_ko=["증권 종목 포트폴리오 리밸런싱 발굴해줘"],
        triggers_en=["screen stock ideas", "rebalance portfolio", "equity research report"],
        antis=["game art", "sprite sheet", "tileset"],
        capabilities=["screen_stock_ideas"],
    )
    save_card(home, card)
    report = backfill_domains(home, write=True)
    assert report["updated"] >= 1

    # Read the persisted card file RAW (load_global_cards re-adds _card_path on
    # read, so inspect the on-disk JSON directly): no internal key, and no
    # absolute machine path, may have leaked into the stored card.
    files = list((home / "cards").rglob("*.json"))
    assert files
    for path in files:
        raw = json.loads(path.read_text(encoding="utf-8"))
        assert not any(str(key).startswith("_") for key in raw), f"internal key leaked into {path.name}"
        assert "_card_path" not in raw
    cards, _ = load_global_cards(home)
    assert "finance" in (cards[0].get("domains") or [])
