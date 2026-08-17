# ZCode Adapter

[ZCode](https://zcode.z.ai) is Z.ai's (formerly Zhipu AI) official agentic
dev environment for GLM-5.2/5.3 — confirmed real, actively maintained
(public launch July 2026), with a documented custom-command system
(https://zcode.z.ai/en/docs/commands). Its command frontmatter
(`description`, `argument-hint`, `$ARGUMENTS`) is byte-identical to Claude
Code's, so the files in `.zcode/commands/` are verbatim copies of
`.claude/commands/`.

Two ways `/hep-<verb>` and `/agentlas-<verb>` can reach a ZCode user:

1. **Project commands**: ZCode reads workspace-level commands from the
   project directory. This repo ships them at `.zcode/commands/*.md`
   (24 files: 12 `hep-<verb>` canonical + 12 `agentlas-<verb>` redirects,
   plus `agentlas.md`).
2. **Claude Code plugin marketplace reuse**: ZCode docs state it "ships
   with access to the Claude Code plugin marketplace, so you can install
   community plugins you're already familiar with" — meaning
   `claude/plugins/agentlas-core-engine-meta-agent/commands/` may already
   be reachable the same way Grok reuses it (see `grok/README.md`). Not
   independently verified here; needs a live ZCode install to confirm
   which path actually wins.

Not added to `scripts/install-all-runtimes.sh` yet — these files are not
copied to a real user's `~/.zcode/` by the installer until that's wired up.
