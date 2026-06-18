---
description: Build, repair, or package Agentlas agents and teams with Hephaestus.
argument-hint: '[ontology|single-agent|team|package] [details...]'
allowed-tools: Bash, Read, Glob, Grep
---

# /hephaestus-build

Raw arguments:
`$ARGUMENTS`

Use Hephaestus as the Agentlas builder surface:

- create a new single agent
- create a multi-agent team
- package an existing Claude/Codex/Gemini workspace into Agentlas architecture
- repair generated Agentlas command files
- open `ontology` as the Knowledge/Memory panel

This command is the clearer build-focused name for the older `/hephaestus`
command. Keep `/hephaestus` working for compatibility, but prefer
`/hephaestus-build` in new user-facing docs.

## Route

If the first argument is `ontology`, open the project-local ontology GUI:

1. Find the first executable path from the shell snippet below.
2. Run:

```bash
RUNNER=""
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
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
  for cache in "$HOME/.claude/plugins/cache/agentlas-core-engine/hephaestus" \
               "${CODEX_HOME:-$HOME/.codex}/plugins/cache/agentlas-core-engine/hephaestus"; do
    newest="$(ls -d "$cache"/*/bin/hephaestus 2>/dev/null | sort -V | tail -1)"
    if [ -n "$newest" ] && [ -x "$newest" ]; then RUNNER="$newest"; break; fi
  done
fi
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
5. Generate or repair `.agentlas/global-commands.json` and matching runtime
   command files or aliases.
6. Return `status`, `evidence`, `output`, `global_commands`, and `blockers`.
   The `global_commands` section must tell the user the exact Claude Code,
   Codex, Gemini CLI, generic AGENTS.md, and terminal commands for the generated
   agent.

## Examples

```text
/hephaestus-build ontology
/hephaestus-build create a self-evolving research agent
/hephaestus-build create a customer support operations team
/hephaestus-build package this existing Claude agent into Agentlas architecture
```
