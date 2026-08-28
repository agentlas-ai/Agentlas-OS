#!/usr/bin/env python3
"""Keep every runtime's copy of a shared SKILL.md body identical to the canonical one.

WHY
    `scripts/sync-adapters.sh` deliberately skipped SKILL.md, on the belief that
    "SKILL.md adapters are intentionally condensed per runtime". Measured
    2026-08-17, that belief was wrong in a way that cost real behaviour:

        hephaestus-network   284 lines everywhere, 53 in openclaw
        hephaestus-upload    144 lines everywhere,  64 in openclaw
        hephaestus-cloud     111 lines everywhere,  91 in openclaw

    The openclaw copy of `hephaestus-upload` had lost the paragraph explaining
    that a Hub upload is public and irreversible and that the destination
    question therefore comes before any packaging. That is not a condensation,
    it is a missing safety rule on one runtime.

WHAT IS GENUINELY PER-HOST
    The frontmatter, and only the frontmatter, for the `hephaestus-*` skills.
    OpenClaw needs its own `metadata: {"openclaw": {...}}` block and describes
    its trigger in its own words because it has no `/hep-*` slash commands. So
    those mirrors keep their own frontmatter verbatim and take the canonical
    body underneath it. `agentlas-one` is a universal skill, so its complete
    file is canonical, including frontmatter; it must never inherit an owner's
    personal name from a stale mirror.

NOT OWNED HERE
    `agentlas-<verb>` redirect aliases (kimi/skills, codex Agent Skills) belong
    to scripts/render-command-aliases.py. Two generators writing one file is the
    disease, not the cure.

Usage:
    scripts/render-host-skills.py           # write bodies
    scripts/render-host-skills.py --check   # fail (exit 1) on any drift
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANONICAL_ROOT = ROOT / "skills"
FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)

# Roots that carry a mirror of a canonical skill.
MIRROR_ROOTS = [
    "claude/plugins/agentlas-core-engine-meta-agent/skills",
    "codex/plugins/agentlas-core-engine-meta-agent/skills",
    "cursor/plugin/skills",
    "gemini/extension/skills",
    "openclaw/skills",
    "hermes/skills",
    ".agents/skills",
    "kimi/skills",
]

# Generated elsewhere — see the module docstring. `agentlas-one` is the one
# exception: it is a real universal skill with a canonical body, not a generated
# `agentlas-<verb>` redirect alias. Treating it as an alias let the stale
# `.agents/skills/agentlas-one` copy keep a maintainer's personal name and omit
# the runner's actual command contract.
def _is_alias(name: str) -> bool:
    return name.startswith("agentlas-") and name != "agentlas-one"


def _split(text: str) -> tuple[str, str]:
    m = FRONTMATTER_RE.match(text)
    return (m.group(0), text[m.end():]) if m else ("", text)


def planned_files() -> dict[Path, str]:
    plan: dict[Path, str] = {}
    if not CANONICAL_ROOT.is_dir():
        return plan
    for canonical_dir in sorted(CANONICAL_ROOT.iterdir()):
        skill = canonical_dir / "SKILL.md"
        if not skill.is_file() or _is_alias(canonical_dir.name):
            continue
        canonical_text = skill.read_text(encoding="utf-8")
        _, canonical_body = _split(canonical_text)
        for mirror_root in MIRROR_ROOTS:
            target = ROOT / mirror_root / canonical_dir.name / "SKILL.md"
            if not target.is_file():
                continue  # this runtime does not ship the skill; that is a product choice
            if canonical_dir.name == "agentlas-one":
                plan[target] = canonical_text
                continue
            head, _ = _split(target.read_text(encoding="utf-8"))
            plan[target] = head + canonical_body
    return plan


def main(argv: list[str]) -> int:
    check = "--check" in argv
    plan = planned_files()
    drift: list[str] = []
    for path, desired in plan.items():
        if path.read_text(encoding="utf-8") == desired:
            continue
        if check:
            drift.append(str(path.relative_to(ROOT)))
        else:
            path.write_text(desired, encoding="utf-8")
    if check:
        for line in drift:
            print(f"  {line} (body differs from skills/<name>/SKILL.md)", file=sys.stderr)
        if drift:
            print(f"render-host-skills --check: {len(drift)} skill body/bodies out of date", file=sys.stderr)
            return 1
        print(f"render-host-skills --check: {len(plan)} mirrored skill body/bodies all match canonical.")
        return 0
    print(f"render-host-skills: wrote/verified {len(plan)} mirrored skill body/bodies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
