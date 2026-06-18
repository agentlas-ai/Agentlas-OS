---
description: Build, repair, or package Agentlas agents and teams with Hephaestus.
---

# /hephaestus-build

Run Hephaestus, the Agentlas Core Engine builder, inside this Antigravity
workspace. The request is the text the user typed after `/hephaestus-build`.
It may be empty, `ontology`, or a build/package instruction such as
`create a research agent for SEC filings`.

This is the clearer build-focused name for the older `/hephaestus` command.
Keep `/hephaestus` working for compatibility, but prefer `/hephaestus-build`
in new docs.

## Step 0 — Resolve the engine root

Hephaestus may live in this workspace OR in a global runtime cache. Resolve the
engine root before routing:

```bash
ENGINE=""
CODEX_HOME_DIR="${CODEX_HOME:-$HOME/.codex}"
if [ -f "./AGENTS.md" ] && [ -f "./.agentlas/mode-map.json" ]; then
  ENGINE="."
else
  for dir in \
    "$HOME/.claude/plugins/cache/agentlas-core-engine/hephaestus/"*/ \
    "$CODEX_HOME_DIR/plugins/cache/agentlas-core-engine/hephaestus/"*/
  do
    [ -f "$dir/SKILL.md" ] && ENGINE="$dir"
  done
fi
echo "ENGINE=$ENGINE"
```

If `ENGINE` is empty, go to the final section ("not installed").

## Route

### If the request is `ontology`

Open the project-local Knowledge/Memory panel:

```bash
RUNNER=""
for candidate in \
  "./bin/hephaestus" \
  "./claude/plugins/agentlas-core-engine-meta-agent/bin/hephaestus" \
  "./codex/plugins/agentlas-core-engine-meta-agent/bin/hephaestus"
do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then RUNNER="$candidate"; fi
done
if [ -z "$RUNNER" ]; then
  for cache in "$HOME/.claude/plugins/cache/agentlas-core-engine/hephaestus" \
               "${CODEX_HOME:-$HOME/.codex}/plugins/cache/agentlas-core-engine/hephaestus"; do
    newest="$(ls -d "$cache"/*/bin/hephaestus 2>/dev/null | sort -V | tail -1)"
    if [ -n "$newest" ] && [ -x "$newest" ]; then RUNNER="$newest"; break; fi
  done
fi
[ -n "$RUNNER" ] || { echo "Hephaestus runtime not found. Run the installer first." >&2; exit 1; }
"$RUNNER" ontology --gui .
```

Report the returned `gui_url`, `db_path`, `inbox_path`, and verification status.

### Otherwise

Read `$ENGINE/AGENTS.md` if it exists, otherwise `$ENGINE/SKILL.md`, then:

1. Read `$ENGINE/.agentlas/mode-map.json` and
   `$ENGINE/.agentlas/global-commands.json` when present.
2. Classify the request with the mode-classification skill as single-agent
   builder, multi-agent team builder, or agentlas-packager.
3. If missing details would change files, adapters, or the public/private
   boundary, run the clarify-question-loop skill first.
4. Generate or repair the smallest useful Agentlas package in the current
   workspace, then verify it.
5. Return `status`, `evidence`, `output`, `global_commands`, and `blockers`.

## If no engine root was found

Tell the user to run the one-touch installer from an OS terminal, then reopen
the workspace in Antigravity:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh | bash
```
