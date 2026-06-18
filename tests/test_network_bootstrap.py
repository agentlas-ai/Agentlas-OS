import os
from pathlib import Path

from agentlas_cloud.networking import add_source, init_networking, network_status
from agentlas_cloud.networking.bootstrap import SCHEMA_VERSION


def test_init_is_idempotent(tmp_path):
    home = tmp_path / "networking"
    first = init_networking(home)
    assert first["schema_version"] == SCHEMA_VERSION
    assert "VERSION" in first["created"]
    assert (home / "cards" / "agents").is_dir()
    assert (home / "policies" / "routing-policy.json").is_file()
    assert (home / "memory" / "playbook-registry.json").is_file()
    assert (home / "memory" / "playbook-candidates.jsonl").is_file()
    assert (home / "ledgers" / "routing-decisions.jsonl").is_file()

    second = init_networking(home)
    assert second["created"] == []
    assert second["migrated_from"] is None


def test_init_migrates_old_version(tmp_path):
    home = tmp_path / "networking"
    init_networking(home)
    (home / "VERSION").write_text("1.0\n", encoding="utf-8")
    report = init_networking(home)
    assert report["migrated_from"] == "1.0"
    assert (home / "VERSION").read_text(encoding="utf-8").strip() == SCHEMA_VERSION


def test_add_source_rejects_home_directory(tmp_path):
    home = tmp_path / "networking"
    init_networking(home)
    user_home = Path(os.path.expanduser("~"))
    rejected = add_source(user_home, home=home)
    assert rejected["status"] == "rejected"
    assert "home directory" in rejected["reason"]


def test_add_source_accepts_explicit_folder(tmp_path):
    home = tmp_path / "networking"
    init_networking(home)
    package_root = tmp_path / "packages"
    package_root.mkdir()
    added = add_source(package_root, home=home)
    assert added["status"] == "added"
    again = add_source(package_root, home=home)
    assert again["status"] == "exists"


def test_status_reports_auto_routing_gate(tmp_path):
    home = tmp_path / "networking"
    init_networking(home)
    status = network_status(home)
    assert status["initialized"] is True
    assert status["auto_routing_enabled"] is False
    assert "routing_ready" not in status["card_counts"]
