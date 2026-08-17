# Kimi Code CLI Adapter

Moonshot AI's Kimi Code CLI (github.com/MoonshotAI/kimi-cli) reads
project-level skills from `.kimi/skills/<name>/SKILL.md` (and merges in
`.claude/skills/`, `.codex/skills/`, `.agents/skills/` by default). Skills are
invoked as `/skill:<name>`, not as a bare `/<name>` command — this is a
different invocation surface from Claude Code's `.claude/commands/*.md`.

This `kimi/skills/` directory is the *source* for that surface: each
`hep-<verb>` skill carries real Hephaestus engine-resolution content (adapted
from `codex/prompts/hep-<verb>.md`), and each `agentlas-<verb>` skill is a
thin redirect to its sibling `hep-<verb>` skill, matching the alias pattern
used for every other runtime in this repo.

**Not yet wired into `scripts/install-all-runtimes.sh`** — that script's
runtime list does not include `kimi` yet, so these files do not get copied
into a user's real `~/.kimi/skills/` (or project `.kimi/skills/`) by the
installer. Add `kimi` to that list and its `write_*` install step before this
becomes live, and add the matching entries to
`scripts/verify-global-command-contract.sh` so drift is caught automatically.
