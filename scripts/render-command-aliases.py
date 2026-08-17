#!/usr/bin/env python3
"""Generate /agentlas-<verb> redirect aliases from the canonical /hep-<verb> files.

Single source of truth: this script, plus the manifest at
schemas/command-alias-manifest.json for the handful of runtime targets whose
alias body is hand-authored content rather than a mechanical redirect (the
Codex "Agent Skills" family — see NON_REDIRECT_FAMILIES below).

Every other target's alias is derived, not duplicated: its frontmatter is read
live from the sibling canonical hep-<verb> file at render time (never copied
into a manifest), and its body is one of the fixed redirect templates below.
This is deliberately narrow in scope: the canonical hep-<verb> FILES
THEMSELVES (the real instructions) are never touched by this script — runtimes
have already hand-tuned that body content differently on purpose, and
unifying it would be a content decision, not a packaging one.

Usage:
    scripts/render-command-aliases.py           # write aliases to disk
    scripts/render-command-aliases.py --check   # fail (exit 1) on any drift
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "schemas" / "command-alias-manifest.json"

FRONTMATTER_RE = re.compile(r"\A---\n(.*?\n)---\n", re.DOTALL)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _frontmatter_block(text: str) -> str:
    """Return the source file's own '---\\n...\\n---\\n' block, or '' if absent."""
    m = FRONTMATTER_RE.match(text)
    return m.group(0) if m else ""


def _md_redirect_body(verb: str) -> str:
    return (
        f"# /agentlas-{verb}\n\n"
        f"Identical to `/hep-{verb}` and `/agentlas {verb} <request>`. Locate the file "
        f"named `hep-{verb}.md` in the exact same directory this file was loaded from, "
        f"read it, and follow its instructions exactly — treating everything typed "
        f"after `/agentlas-{verb}` as that command's request.\n\n"
        f"Do not improvise a separate workflow and do not summarize `hep-{verb}.md` "
        f"from memory; that file is the sole authority for this command's behavior.\n"
    )


def _toml_description(hep_toml_text: str) -> str:
    m = re.search(r'^description = (".*")\s*$', hep_toml_text, re.MULTILINE)
    return m.group(1) if m else '""'


def _toml_alias(verb: str, hep_toml_text: str) -> str:
    description = _toml_description(hep_toml_text)
    body = (
        f'description = {description}\n'
        f'prompt = """\n'
        f"# /agentlas-{verb}\n\n"
        f"Argument: {{{{args}}}}\n\n"
        f"Identical to `/hep-{verb}` and `/agentlas {verb} <request>`. Locate the file "
        f"named `hep-{verb}.toml` in the exact same directory this file was loaded from, "
        f"read its `prompt` value, and follow those instructions exactly — treating the "
        f"argument above as that command's request.\n\n"
        f"Do not improvise a separate workflow and do not summarize `hep-{verb}.toml` "
        f"from memory; that file is the sole authority for this command's behavior.\n"
        f'"""\n'
    )
    return body


def _kimi_description(hep_skill_text: str) -> str:
    m = re.search(r"^description:\s*(.*)$", hep_skill_text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def _kimi_skill_alias(verb: str, hep_skill_text: str) -> str:
    description = _kimi_description(hep_skill_text)
    return (
        "---\n"
        f"name: agentlas-{verb}\n"
        f"description: {description}\n"
        "---\n"
        f"# agentlas-{verb}\n\n"
        f"Identical to `/skill:hep-{verb}` and `/agentlas {verb} <request>`. Locate the\n"
        f"sibling skill directory `hep-{verb}` (i.e. `../hep-{verb}/SKILL.md` relative to\n"
        "this file, under the same `kimi/skills/` root this skill was loaded from), read\n"
        "its `SKILL.md`, and follow its instructions exactly — treating everything typed\n"
        f"after `/skill:agentlas-{verb}` as that command's request.\n\n"
        f"Do not improvise a separate workflow and do not summarize `hep-{verb}/SKILL.md`\n"
        "from memory; that file is the sole authority for this command's behavior.\n"
    )


# Runtime targets whose alias is a mechanical redirect derived from the
# sibling hep-<verb> file. `glob` finds which verbs exist for that runtime
# (coverage differs — e.g. several runtimes have no hep-connect).
MD_TARGETS = [
    (".claude/commands", "hep-{verb}.md", "agentlas-{verb}.md"),
    ("claude/plugins/agentlas-core-engine-meta-agent/commands", "hep-{verb}.md", "agentlas-{verb}.md"),
    ("codex/prompts", "hep-{verb}.md", "agentlas-{verb}.md"),
    ("cursor/plugin/commands", "hep-{verb}.md", "agentlas-{verb}.md"),
    ("antigravity/workflows", "hep-{verb}.md", "agentlas-{verb}.md"),
    (".agents/workflows", "hep-{verb}.md", "agentlas-{verb}.md"),
    ("opencode/commands", "hep-{verb}.md", "agentlas-{verb}.md"),
    (".zcode/commands", "hep-{verb}.md", "agentlas-{verb}.md"),
]

TOML_TARGETS = [
    (".gemini/commands", "hep-{verb}.toml", "agentlas-{verb}.toml"),
    ("gemini/extension/commands", "hep-{verb}.toml", "agentlas-{verb}.toml"),
]

KIMI_TARGETS = [
    ("kimi/skills", "hep-{verb}/SKILL.md", "agentlas-{verb}/SKILL.md"),
]

# The Codex "Agent Skills" family (codex/plugins/.../skills/agentlas-<verb>)
# is hand-authored, richer content (a mini workflow doc), not a one-line
# redirect — see the module docstring. Its content lives in the manifest as
# an explicit, checked snapshot rather than being derived, so --check still
# catches drift without this script inventing new prose on a rewrite.


def load_manifest() -> dict:
    return json.loads(_read(MANIFEST_PATH))


def planned_files() -> dict[Path, str]:
    """Return {absolute_path: desired_content} for every generated alias."""
    plan: dict[Path, str] = {}

    for root_rel, hep_pat, alias_pat in MD_TARGETS:
        root = ROOT / root_rel
        if not root.is_dir():
            continue
        for hep_file in sorted(root.glob("hep-*.md")):
            verb = hep_file.stem[len("hep-"):]
            hep_text = _read(hep_file)
            fm = _frontmatter_block(hep_text)
            alias_path = root / alias_pat.format(verb=verb)
            plan[alias_path] = fm + _md_redirect_body(verb)

    for root_rel, hep_pat, alias_pat in TOML_TARGETS:
        root = ROOT / root_rel
        if not root.is_dir():
            continue
        for hep_file in sorted(root.glob("hep-*.toml")):
            verb = hep_file.stem[len("hep-"):]
            hep_text = _read(hep_file)
            alias_path = root / alias_pat.format(verb=verb)
            plan[alias_path] = _toml_alias(verb, hep_text)

    for root_rel, hep_pat, alias_pat in KIMI_TARGETS:
        root = ROOT / root_rel
        if not root.is_dir():
            continue
        for hep_dir in sorted(root.glob("hep-*")):
            skill_file = hep_dir / "SKILL.md"
            if not skill_file.is_file():
                continue
            verb = hep_dir.name[len("hep-"):]
            hep_text = _read(skill_file)
            alias_path = root / alias_pat.format(verb=verb)
            plan[alias_path] = _kimi_skill_alias(verb, hep_text)

    manifest = load_manifest()
    for entry in manifest.get("verbatimSkills", []):
        alias_path = ROOT / entry["path"]
        plan[alias_path] = entry["content"]

    return plan


def main(argv: list[str]) -> int:
    check = "--check" in argv
    plan = planned_files()
    drift: list[str] = []

    for path, desired in plan.items():
        current = path.read_text(encoding="utf-8") if path.is_file() else None
        if current == desired:
            continue
        if check:
            rel = path.relative_to(ROOT)
            reason = "missing" if current is None else "content differs"
            drift.append(f"{rel} ({reason})")
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(desired, encoding="utf-8")

    if check:
        if drift:
            print(f"render-command-aliases --check: {len(drift)} file(s) out of date:", file=sys.stderr)
            for line in drift:
                print(f"  {line}", file=sys.stderr)
            return 1
        print(f"render-command-aliases --check: {len(plan)} alias file(s) all up to date.")
        return 0

    print(f"render-command-aliases: wrote/verified {len(plan)} alias file(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
