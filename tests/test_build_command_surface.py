import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPDATE_FALLBACK = "Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다."
PLAIN_SHAPE_QUESTION = "이 일을 한 명의 전문가가 처음부터 끝까지 맡으면 되나요"
# Every app host's permission classifier blocks piping a remote installer into
# bash, so an inline `curl <remote> | bash` auto-update preflight embedded in an
# adapter is dead weight that can never run — and it surfaces a blocked-command
# prompt on every machine. The runtime self-heals instead
# (agentlas_cloud.update.reconcile_adapters). Adapters must carry NONE of these.
BLOCKED_PREFLIGHT_MARKERS = (
    "HEPHAESTUS_APP_AUTO_UPDATE",
    "NEEDS_HEP_UPDATE",
    "HEPHAESTUS_FORCE=1 bash",
    "hephaestus-app-auto-update",
)


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


def test_hep_build_surfaces_use_plain_language_shape_question() -> None:
    files = [
        ROOT / "claude" / "plugins" / "agentlas-core-engine-meta-agent" / "commands" / "hep-build.md",
        ROOT / ".claude" / "commands" / "hep-build.md",
        ROOT / "codex" / "prompts" / "hep-build.md",
        ROOT / "gemini" / "extension" / "commands" / "hep-build.toml",
        ROOT / ".gemini" / "commands" / "hep-build.toml",
        ROOT / "antigravity" / "workflows" / "hep-build.md",
        ROOT / ".agents" / "workflows" / "hep-build.md",
        ROOT / "cursor" / "plugin" / "commands" / "hep-build.md",
        ROOT / "opencode" / "commands" / "hep-build.md",
    ]

    for path in files:
        text = path.read_text(encoding="utf-8")
        normalized = re.sub(r"\s+", " ", text)
        assert PLAIN_SHAPE_QUESTION in normalized, str(path.relative_to(ROOT))
        assert "자기 메모리/컨텍스트" not in text, str(path.relative_to(ROOT))


def test_claude_commands_prefer_runtime_current_before_plugin_cache() -> None:
    files = [
        ROOT / "claude" / "plugins" / "agentlas-core-engine-meta-agent" / "commands" / "hep-build.md",
        ROOT / "claude" / "plugins" / "agentlas-core-engine-meta-agent" / "commands" / "hep-network.md",
        ROOT / "claude" / "plugins" / "agentlas-core-engine-meta-agent" / "commands" / "hep-cloud.md",
        ROOT / "claude" / "plugins" / "agentlas-core-engine-meta-agent" / "commands" / "hep-search.md",
        ROOT / "claude" / "plugins" / "agentlas-core-engine-meta-agent" / "commands" / "hep-call.md",
        ROOT / ".claude" / "commands" / "hep-build.md",
        ROOT / ".claude" / "commands" / "hep-network.md",
        ROOT / ".claude" / "commands" / "hep-cloud.md",
        ROOT / ".claude" / "commands" / "hep-search.md",
        ROOT / ".claude" / "commands" / "hep-call.md",
    ]

    runtime = '"$HOME/.agentlas/runtime/current/bin/hephaestus"'
    plugin_root = '"${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/bin/hephaestus}"'
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert runtime in text, str(path.relative_to(ROOT))
        assert plugin_root in text, str(path.relative_to(ROOT))
        assert text.index(runtime) < text.index(plugin_root), str(path.relative_to(ROOT))


def test_app_host_surfaces_carry_no_blocked_curl_bash_preflight() -> None:
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

    skill_files = [
        ROOT / "skills" / "hephaestus-network" / "SKILL.md",
        ROOT / "skills" / "hephaestus-cloud" / "SKILL.md",
        ROOT / ".agents" / "skills" / "hephaestus-network" / "SKILL.md",
        ROOT / ".agents" / "skills" / "hephaestus-cloud" / "SKILL.md",
        ROOT / "codex" / "plugins" / "agentlas-core-engine-meta-agent" / "skills" / "hephaestus-network" / "SKILL.md",
        ROOT / "codex" / "plugins" / "agentlas-core-engine-meta-agent" / "skills" / "hephaestus-cloud" / "SKILL.md",
        ROOT / "gemini" / "extension" / "skills" / "hephaestus-network" / "SKILL.md",
        ROOT / "gemini" / "extension" / "skills" / "hephaestus-cloud" / "SKILL.md",
        ROOT / "cursor" / "plugin" / "skills" / "hephaestus-network" / "SKILL.md",
        ROOT / "cursor" / "plugin" / "skills" / "hephaestus-cloud" / "SKILL.md",
        ROOT / "hermes" / "skills" / "hephaestus-network" / "SKILL.md",
        ROOT / "hermes" / "skills" / "hephaestus-cloud" / "SKILL.md",
        ROOT / "openclaw" / "skills" / "hephaestus-network" / "SKILL.md",
        ROOT / "openclaw" / "skills" / "hephaestus-cloud" / "SKILL.md",
    ]
    files.extend(skill_files)

    assert files
    offenders = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if any(marker in text for marker in BLOCKED_PREFLIGHT_MARKERS):
            offenders.append(str(path.relative_to(ROOT)))
    assert offenders == [], f"adapters must not embed the classifier-blocked curl|bash preflight: {offenders}"


def test_universal_skills_carry_no_blocked_installer_preflight() -> None:
    for path in [
        ROOT / "skills" / "hephaestus-network" / "SKILL.md",
        ROOT / "skills" / "hephaestus-cloud" / "SKILL.md",
        ROOT / "openclaw" / "skills" / "hephaestus-network" / "SKILL.md",
        ROOT / "openclaw" / "skills" / "hephaestus-cloud" / "SKILL.md",
    ]:
        text = path.read_text(encoding="utf-8")
        assert "/tmp/hephaestus-app-auto-update.log" not in text, str(path.relative_to(ROOT))
        assert "HEPHAESTUS_FORCE=1 bash" not in text, str(path.relative_to(ROOT))
