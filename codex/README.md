# Codex Plugin Install

Install from a new computer with the OS terminal:

On a fresh Mac, install Apple Command Line Tools first if `git` is unavailable:

```bash
xcode-select --install
git --version
```

One-command install or update for Claude, Codex, and Gemini:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/v0.2.8/scripts/install-all-runtimes.sh | bash
```

```bash
codex plugin marketplace add agentlas-ai/Hephaestus --ref v0.2.8
codex plugin add hephaestus@agentlas-core-engine
```

The OS-terminal Codex CLI command is singular: `codex plugin`, not
`codex plugins`. Inside the Codex app, use `/plugins` to browse installed
plugins; do not run `/plugin marketplace add` inside the app.

Then open or restart Codex in the project and type:

```text
/plugins
/hephaestus ontology
```

If an older install still shows `agentlas-meta-agent`:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/v0.2.8/scripts/install-all-runtimes.sh | bash
```

That command creates and opens:

```text
.agentlas/ontology-gui/index.html
```

Use the same slash command for builder work:

```text
/hephaestus create a self-evolving research agent
/hephaestus package this existing Codex workspace into Agentlas architecture
```

After generation, the final handoff must include `global_commands` for the
created agent or team. For teams, that command routes to the orchestrator/HQ.

Local validation from this repository:

```bash
python3 -m json.tool codex/plugins/agentlas-core-engine-meta-agent/.codex-plugin/plugin.json >/dev/null
```
