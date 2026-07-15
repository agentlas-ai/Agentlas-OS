import json
import os
import subprocess
from pathlib import Path

from agentlas_cloud.global_router import BEGIN, END, global_router_status, install_global_router, remove_global_router


ROOT = Path(__file__).resolve().parents[1]


def test_global_router_install_status_remove(tmp_path: Path) -> None:
    codex = tmp_path / ".codex" / "AGENTS.md"
    claude = tmp_path / ".claude" / "CLAUDE.md"
    antigravity = tmp_path / ".gemini" / "GEMINI.md"
    codex.parent.mkdir(parents=True)
    claude.parent.mkdir(parents=True)
    antigravity.parent.mkdir(parents=True)
    codex.write_text("# Existing Codex\n\nKeep this.\n", encoding="utf-8")
    claude.write_text("# Existing Claude\n\nKeep this too.\n", encoding="utf-8")
    antigravity.write_text("# Existing Gemini\n\nKeep this also.\n", encoding="utf-8")

    result = install_global_router(home=tmp_path, backup=False)
    assert {item["target"] for item in result["results"]} == {"codex", "claude", "antigravity"}
    assert all(item["status"] == "updated" for item in result["results"])
    assert BEGIN in codex.read_text(encoding="utf-8")
    assert "Keep this." in codex.read_text(encoding="utf-8")
    assert "insufficient_credits" in claude.read_text(encoding="utf-8")
    assert "Agentlas Browser first" in codex.read_text(encoding="utf-8")
    assert "/prompts:hep-browser" in codex.read_text(encoding="utf-8")
    assert "Local host skills last" in codex.read_text(encoding="utf-8")
    assert "Agents used: <agent names>" in codex.read_text(encoding="utf-8")
    assert "사용 에이전트: <agent names>" in codex.read_text(encoding="utf-8")
    antigravity_text = antigravity.read_text(encoding="utf-8")
    assert "Antigravity/Gemini" in antigravity_text
    assert "/hep-browser" in antigravity_text
    assert "<url-or-query>" in antigravity_text
    assert "/hep-network <request>" in antigravity_text

    status = global_router_status(home=tmp_path)
    assert all(item["installed"] for item in status["results"])

    second = install_global_router(home=tmp_path, backup=False)
    assert all(item["status"] == "unchanged" for item in second["results"])

    removed = remove_global_router(home=tmp_path, backup=False, targets=["codex"])
    assert removed["results"][0]["status"] == "removed"
    assert BEGIN not in codex.read_text(encoding="utf-8")
    assert END in claude.read_text(encoding="utf-8")


def test_global_router_cli_wrapper(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["HEPHAESTUS_UPDATE_CHECK"] = "0"
    completed = subprocess.run(
        [str(ROOT / "bin" / "hep-global"), "install", "--home", str(tmp_path), "--target", "codex", "--no-backup"],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(completed.stdout)
    assert payload["action"] == "global_router_install"
    assert payload["results"][0]["target"] == "codex"

    prompt = tmp_path / ".codex" / "AGENTS.md"
    text = prompt.read_text(encoding="utf-8")
    assert BEGIN in text
    assert "global-router.v3" in text
    assert "workforce.search_candidates" in text
    assert "Hephaestus Network" in text
    assert "Never announce `hep-network`" in text
