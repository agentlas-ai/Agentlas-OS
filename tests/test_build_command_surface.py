import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPDATE_FALLBACK = "Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다."


def _run(*args: str) -> str:
    env = os.environ.copy()
    env["HEPHAESTUS_UPDATE_CHECK"] = "0"
    completed = subprocess.run(
        [str(ROOT / "bin" / "hephaestus"), *args],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return completed.stdout


def test_build_subcommands_point_to_hephaestus_build() -> None:
    for command in ("hep-build", "build", "meta-agent"):
        output = _run(command, "create a customer support agent")
        assert "/hep-build create a customer support agent" in output
        assert "Legacy alias:" not in output


def test_standalone_build_wrapper_points_to_hephaestus_build() -> None:
    env = os.environ.copy()
    env["HEPHAESTUS_UPDATE_CHECK"] = "0"
    completed = subprocess.run(
        [str(ROOT / "bin" / "hep-build"), "create a finance agent"],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert "/hep-build create a finance agent" in completed.stdout


def _first_command_body_line(path: Path) -> str:
    lines = path.read_text(encoding="utf-8").splitlines()
    if path.suffix == ".toml":
        start = lines.index('prompt = """') + 1
    elif lines and lines[0] == "---":
        start = lines.index("---", 1) + 1
    else:
        start = 0
    for line in lines[start:]:
        if line.strip():
            return line
    return ""


def test_all_hep_command_surfaces_start_body_with_update_fallback_line() -> None:
    command_dirs = [
        ROOT / "claude" / "plugins" / "agentlas-core-engine-meta-agent" / "commands",
        ROOT / ".claude" / "commands",
        ROOT / "codex" / "prompts",
        ROOT / "gemini" / "extension" / "commands",
        ROOT / ".gemini" / "commands",
        ROOT / "antigravity" / "workflows",
        ROOT / ".agents" / "workflows",
        ROOT / "cursor" / "plugin" / "commands",
        ROOT / "opencode" / "commands",
    ]
    files = []
    for directory in command_dirs:
        files.extend(sorted(directory.glob("hep-*.md")))
        files.extend(sorted(directory.glob("hep-*.toml")))

    assert files
    misplaced = [str(path.relative_to(ROOT)) for path in files if _first_command_body_line(path) != UPDATE_FALLBACK]
    assert misplaced == []
