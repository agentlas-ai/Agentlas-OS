---
description: Run Hephaestus to create/package Agentlas agents or open the project ontology GUI.
---

# /hephaestus

Run Hephaestus, the Agentlas Core Engine Meta-Agent, inside this Antigravity
workspace. `AGENTS.md` is the canonical source of truth.

The text the user typed after `/hephaestus` is the request. It may be empty,
`ontology`, or a build/package instruction such as
`create a research agent for SEC filings`.

## Route

### If the request is `ontology`

Open the project-local ontology GUI by running the first executable runner:

```bash
RUNNER=""
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
for candidate in \
  "./bin/hephaestus" \
  "$CODEX_HOME_DIR/plugins/cache/agentlas-core-engine/hephaestus/"*/bin/hephaestus \
  "./claude/plugins/agentlas-core-engine-meta-agent/bin/hephaestus" \
  "./codex/plugins/agentlas-core-engine-meta-agent/bin/hephaestus"
do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then
    RUNNER="$candidate"
    break
  fi
done
if [ -z "$RUNNER" ]; then
  echo "Hephaestus runtime not found. Run the installer first." >&2
  exit 1
fi
"$RUNNER" ontology --gui .
```

Report the returned `gui_url`, `db_path`, `inbox_path`, and verification status.

### Otherwise (create, package, or repair an agent/team)

1. Read `AGENTS.md` (canonical) and `.agents/agentlas-core-engine-meta-agent/agent.md`.
2. Read `.agentlas/mode-map.json` and `.agentlas/global-commands.json`.
3. Classify the request with `.agents/skills/mode-classification/SKILL.md` as
   single-agent builder, multi-agent team builder, or agentlas-packager.
4. If missing details would change files, adapters, or the public/private
   boundary, run `.agents/skills/clarify-question-loop/SKILL.md` first.
5. Generate or repair the smallest useful Agentlas package, then verify with
   `scripts/verify-package.sh`.
6. Return `status`, `evidence`, `output`, `global_commands`, and `blockers`.
   The `global_commands` section must list the exact Claude Code, Codex, Gemini
   CLI, Antigravity, generic `AGENTS.md`, and terminal commands from
   `.agentlas/global-commands.json`.

## If the Hephaestus package is not present in this workspace

Tell the user to run the one-touch installer from an OS terminal, then reopen
the workspace in Antigravity:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/v0.2.8/scripts/install-all-runtimes.sh | bash
```

The installer registers `/hephaestus` as an Antigravity global workflow at
`~/.gemini/antigravity/global_workflows/hephaestus.md`, so it is available in
every Antigravity workspace.
