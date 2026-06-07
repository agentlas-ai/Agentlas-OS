# Codex Plugin Install

Install from a new computer with the OS terminal:

```bash
codex plugin marketplace add agentlas-ai/Hephaestus --ref v0.2.1
codex plugin add agentlas-meta-agent@agentlas-core-engine
```

The Codex CLI command is singular: `codex plugin`, not `codex plugins`.

Then open or restart Codex in the project and type:

```text
/Hephaestus ontology
```

That command creates and opens:

```text
.agentlas/ontology-gui/index.html
```

Use the same slash command for builder work:

```text
/Hephaestus create a self-evolving research agent
/Hephaestus package this existing Codex workspace into Agentlas architecture
```

Local validation from this repository:

```bash
python3 -m json.tool codex/plugins/agentlas-core-engine-meta-agent/.codex-plugin/plugin.json >/dev/null
```
