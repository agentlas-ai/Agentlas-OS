---
description: Run Hephaestus meta-agent or open the project ontology GUI
argument-hint: '[ontology|meta-agent|team|single-agent|package] [details...]'
allowed-tools: Bash, Read, Glob, Grep
---

# /Hephaestus

Raw arguments:
`$ARGUMENTS`

## Route

If the first argument is `ontology`, open the project-local ontology GUI:

1. Find the first executable path from the shell snippet below.
2. Run:

```bash
RUNNER=""
for candidate in \
  "${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/bin/hephaestus}" \
  "${CODEX_PLUGIN_ROOT:+$CODEX_PLUGIN_ROOT/bin/hephaestus}" \
  "${PLUGIN_ROOT:+$PLUGIN_ROOT/bin/hephaestus}" \
  "./bin/hephaestus" \
  "./claude/plugins/agentlas-core-engine-meta-agent/bin/hephaestus" \
  "./codex/plugins/agentlas-core-engine-meta-agent/bin/hephaestus"
do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then
    RUNNER="$candidate"
    break
  fi
done
if [ -z "$RUNNER" ]; then
  echo "Hephaestus runtime not found. Install the plugin or run the standalone installer first." >&2
  exit 1
fi
"$RUNNER" ontology --gui .
```

3. Report the returned `gui_url`, `db_path`, `inbox_path`, and verification status.

If the first argument is not `ontology`, route to the Agentlas Core Engine
Meta-Agent team:

1. Read `AGENTS.md`.
2. Read `.agentlas/mode-map.json`.
3. Classify the request as single-agent builder, multi-agent team builder, or
   packager.
4. Load only the matching public skills.
5. Return `status`, `evidence`, `output`, and `blockers`.

## Examples

```text
/Hephaestus ontology
/Hephaestus create a self-evolving research agent
/Hephaestus package this existing Claude agent into Agentlas architecture
```
