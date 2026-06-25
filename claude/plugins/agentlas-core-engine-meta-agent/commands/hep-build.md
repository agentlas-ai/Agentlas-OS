---
description: Build, repair, or package Agentlas agents and teams with Hephaestus.
argument-hint: '[ontology|single-agent|team|package] [details...]'
allowed-tools: Bash, Read, Glob, Grep
---

# /hep-build

Raw arguments:
`$ARGUMENTS`

Use Hephaestus as the Agentlas builder surface:

- create a new single agent
- create a multi-agent team
- package an existing Claude/Codex/Gemini workspace into Agentlas architecture
- repair generated Agentlas command files
- open `ontology` as the Knowledge/Memory panel

Expose this as the only public build command, next to `/hep-network`
and `/hep-cloud`. Do not advertise internal support skills as commands.

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
4. Run the Builder Interview and Research Gate in
   `docs/builder-interview-research-gate.md` before writing substantial package
   files. Ask an 8-12 question first batch when the request is vague; continue
   follow-ups until target user, tasks, inputs, outputs, examples,
   tools/plugins, memory, failure modes, and evals are clear. Research official
   or primary docs, similar agent repositories or comparables, GitHub examples,
   academic/professional theory, and tool/plugin docs. Record selected and
   rejected tools/plugins with permission, secret, fallback, and smoke-test
   notes, then synthesize domain-expert behavior before writing prompts.
5. Generate `docs/builder-interview.md`, `docs/research-sources.md`,
   `docs/tool-selection.md`, `docs/domain-expert-synthesis.md`,
   `docs/prompt-performance-contract.md`, and
   `.agentlas/capability-eval-plan.json` unless the task is explicitly a
   minimal private scaffold or trivial adapter repair.
6. Load only the matching public skills.
7. Generate or repair `.agentlas/global-commands.json` and matching runtime
   command files or aliases.
8. Market Page Copy Gate — make the public detail page readable before
   reporting. For any agent/team package created or repaired, write or repair
   `agentlas.json.publicProfile` (`titleKo`, `descriptionKo`, a `guide` with
   `whatItDoesKo` / `bestForKo` / `prerequisitesKo` / `expectedOutputsKo` /
   `carefulWithKo`, and for teams a `detail` with `members` and `flow` in human
   labels). Mine only sanitized, already-public source fields: routing-card
   `summary_ko` / `capabilities` / `required_inputs` / `produces`,
   `README_FOR_HUMANS.md`, and team `company-blueprint.json`. Do NOT trust
   `.claude/skills/*` descriptions or `CLAUDE.md` titles — generated packages
   often carry a wrong template there. Never copy secrets, local paths, raw
   stage ids (P0/G0), or snake_case capability ids into public copy. The page
   must answer: who it's for, what the user gives it, what it does in plain
   words, what it returns (name ≥ 2 deliverables), what it can access, and where
   a human approves. This is BYOK work — the builder's own model writes the copy.
   Verify with the bundled runtime gate:
   `bin/hephaestus package <pkg> --visibility marketplace`. Recompute the
   package hash after writing `agentlas.json`.
9. If a package was created or repaired in the current workspace, register it to
   local discovery before reporting:
   ```bash
   RUNNER="./bin/hephaestus"
   if [ ! -x "$RUNNER" ] && [ -x "./claude/plugins/agentlas-core-engine-meta-agent/bin/hephaestus" ]; then
     RUNNER="./claude/plugins/agentlas-core-engine-meta-agent/bin/hephaestus"
   fi
   if [ -x "$RUNNER" ]; then
     "$RUNNER" cards migrate . --tier local --overwrite
   else
     echo "Hephaestus runner not found for routing-card migration."
   fi
   ```
10. Return `status`, `evidence`, `output`, `global_commands`, `market_page_copy`,
   `interview_research`, and `blockers`.
   The `global_commands` section must tell the user the exact Claude Code,
   Codex, Gemini CLI, generic AGENTS.md, and terminal commands for the generated
   agent.

## Examples

```text
/hep-build ontology
/hep-build create a self-evolving research agent
/hep-build create a customer support operations team
/hep-build package this existing Claude agent into Agentlas architecture
```
