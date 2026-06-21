# Claude Code Plugin Install

Install from a new computer with the OS terminal:

On a fresh Mac, install Apple Command Line Tools first if `git` is unavailable:

```bash
xcode-select --install
git --version
```

One-command install or update for Claude, Codex, and Gemini:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/v0.7.14/scripts/install-all-runtimes.sh | bash
```

```bash
claude plugin marketplace add https://github.com/agentlas-ai/Hephaestus --sparse .claude-plugin claude/plugins
claude plugin install hephaestus@agentlas-core-engine
```

Then open or restart Claude Code in the project and type:

```text
/reload-plugins
/hep-build ontology
```

If an older install still points at `agentlas-meta-agent`:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/v0.7.14/scripts/install-all-runtimes.sh | bash
```

That command creates and opens:

```text
.agentlas/ontology-gui/index.html
```

Use the same slash command for builder work:

```text
/hep-build create a research agent for SEC filing analysis
/hep-build package this existing Claude agent into Agentlas architecture
/hep-network split this launch into research, copy, QA, and release agents
/hep-cloud use my saved analyst agent
/hep-search find agents for market report research
/hep-call market-researcher, report-writer {draft a market report brief}
```

After generation, the final handoff must include `global_commands` for the
created agent or team. For teams, that command routes to the orchestrator/HQ.

Local validation from this repository:

```bash
claude plugin validate claude/plugins/agentlas-core-engine-meta-agent
claude plugin validate claude
```

Local checkout install:

```bash
claude plugin marketplace add ./claude
claude plugin install hephaestus@agentlas-core-engine
```

Use directly for one Claude session without installing:

```bash
claude --plugin-dir claude/plugins/agentlas-core-engine-meta-agent
```
