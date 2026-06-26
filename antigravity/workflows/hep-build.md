---
description: Build, repair, or package Agentlas agents and teams with Hephaestus.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# /hep-build


Run Hephaestus, the Agentlas Core Engine builder, inside this Antigravity
workspace. The request is the text the user typed after `/hep-build`.
It may be empty, `ontology`, or a build/package instruction such as
`create a research agent for SEC filings`.

Expose this as the public build workflow next to `hephaestus-network` and
`hephaestus-cloud`.

## Step 0 — Resolve the engine root

First run the app-host auto-update preflight inside Antigravity when a local
shell command is available (`HEPHAESTUS_APP_AUTO_UPDATE=1`, installer URL
`https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh`).
Do not ask the user to open a separate terminal. If the preflight cannot install
or update Hephaestus, continue with the installed engine or report
`/tmp/hephaestus-app-auto-update.log`.

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
  "$HOME/.agentlas/runtime/current/bin/hephaestus" \
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
[ -n "$RUNNER" ] || { echo "Hephaestus runtime not found after app auto-update preflight. See /tmp/hephaestus-app-auto-update.log if it exists." >&2; exit 1; }
"$RUNNER" ontology --gui .
```

Report the returned `gui_url`, `db_path`, `inbox_path`, and verification status.

### Otherwise

Read `$ENGINE/AGENTS.md` if it exists, otherwise `$ENGINE/SKILL.md`, then:

1. Read `$ENGINE/.agentlas/mode-map.json` and
   `$ENGINE/.agentlas/global-commands.json` when present.
2. Classify the request with the mode-classification skill as single-agent
   builder, multi-agent team builder, or agentlas-packager by independent
   ownership boundaries. If single↔multi is unclear, ask first in plain
   language: "이 일을 한 명의 전문가가 처음부터 끝까지 맡으면 되나요, 아니면
   조사/분석/검토처럼 여러 전문가가 나눠 맡고 마지막에 합쳐야 하나요?" Do
   not show non-technical users internal labels like ownership boundary,
   memory/context, synthesis, or produces/consumes.
3. Run the Builder Interview and Research Gate from
   `docs/builder-interview-research-gate.md` before writing substantial package
   files. Ask an 8-12 question first batch when the request is vague, continue
   follow-ups until the functional brief, ownership boundaries, role count,
   tool permission separation, synthesis need, and execution order are clear,
   research official sources, similar agent repositories or comparables,
   academic/professional theory, and plugin docs, compare selected and rejected
   tools/plugins, synthesize domain-expert behavior, and create
   `docs/builder-interview.md`,
   `docs/research-sources.md`, `docs/tool-selection.md`,
   `docs/domain-expert-synthesis.md`, `docs/prompt-performance-contract.md`, and
   `.agentlas/capability-eval-plan.json`.
4. If missing narrow details would change files, adapters, or the public/private
   boundary, run the clarify-question-loop skill first.
5. Generate or repair the smallest useful Agentlas package in the current
   workspace, then run `scripts/verify-team-package.sh <package-root>`. If it
   fails, do not report `completed`; correct the shape by collapsing to a valid
   single-agent package or adding orchestrator/HQ plus company-blueprint
   topology, then rerun the gate and verify it.
6. If the package exists in the current workspace, register its routing-card to
   local discovery so it can participate in local routing priority:

```bash
if [ -x "./bin/hephaestus" ]; then
  ./bin/hephaestus cards migrate . --tier local --overwrite
fi
```

Prefer the preflight-resolved `"$RUNNER" cards migrate . --tier local
--overwrite` when available.

7. Return `status`, `evidence`, `output`, `global_commands`,
   `interview_research`, and `blockers`.

## If no engine root was found

First report that the app-host auto-update preflight could not install or find
Hephaestus, including `/tmp/hephaestus-app-auto-update.log` if it exists. Only
then show the manual installer as a last resort:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Hephaestus/main/scripts/install-all-runtimes.sh | bash
```
