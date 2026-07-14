#!/usr/bin/env python3
"""Static cross-host contract gate for the post-build private Cloud choice."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SOURCES = [
    ROOT / "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-build.md",
    ROOT / "codex/prompts/hep-build.md",
    ROOT / "antigravity/workflows/hep-build.md",
    ROOT / "gemini/extension/commands/hep-build.toml",
    ROOT / "codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-build/SKILL.md",
]

MIRRORS = [
    (
        ROOT / "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-build.md",
        ROOT / ".claude/commands/hep-build.md",
    ),
    (
        ROOT / "antigravity/workflows/hep-build.md",
        ROOT / ".agents/workflows/hep-build.md",
    ),
    (
        ROOT / "gemini/extension/commands/hep-build.toml",
        ROOT / ".gemini/commands/hep-build.toml",
    ),
]


def check_source(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    flat = " ".join(text.split())
    required = (
        "Cloud에 올리기",
        "로컬에만 저장",
        "private-link",
        "local-only",
        "paired Desktop",
    )
    for marker in required:
        assert marker in flat, f"{path}: missing {marker!r}"
    assert (
        "hosted LLM" in flat
        or "hosted model" in flat
        or "does not run the LLM" in flat
        or "not a hosted LLM" in flat
    ), (
        f"{path}: Cloud storage must not be described as hosted execution"
    )
    assert "Public Hub" in flat or "public Hub" in flat, (
        f"{path}: public publishing must remain a separate action"
    )


def main() -> None:
    for source in SOURCES:
        check_source(source)
    for source, mirror in MIRRORS:
        assert source.read_bytes() == mirror.read_bytes(), (
            f"adapter mirror drift: {mirror.relative_to(ROOT)}"
        )
    print(f"post-build Cloud choice contract: PASS ({len(SOURCES)} hosts, {len(MIRRORS)} mirrors)")


if __name__ == "__main__":
    main()
