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
        "id": "free/some-agent",
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
    package = tmp_path / "Free" / "researcher-099-sample-packager"
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
    result = migrate_package(package, tier="free", home=home)
    assert result["status"] == "migrated"
    cards, _ = load_global_cards(home)
    assert len(cards) == 1
    card = cards[0]
    assert card["routing_status"] == "draft"
    assert card["id"] == "free/researcher-099-sample-packager"
    assert card["risk_profile"]["capabilities_at_risk"] == ["file_write"]
    assert effective_status(card) in ("draft", "searchable")

    again = migrate_package(package, tier="free", home=home)
    assert again["status"] == "kept_existing"
