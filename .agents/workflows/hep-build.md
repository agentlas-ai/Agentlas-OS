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

Hephaestus may live in this workspace OR in a global runtime cache. Resolve the
engine root before routing:

```bash
ENGINE=""
for candidate in \
  "${CLAUDE_PLUGIN_ROOT:-}" \
  "${CODEX_PLUGIN_ROOT:-}" \
  "${PLUGIN_ROOT:-}" \
  "$HOME/.agentlas/runtime/current/host_adapters/claude/plugins/agentlas-core-engine-meta-agent" \
  "$HOME/.agentlas/runtime/current/host_adapters/codex/plugins/agentlas-core-engine-meta-agent" \
  "$HOME/.agentlas/runtime/current" \
  "." \
  "$HOME/.claude/plugins/cache/agentlas-core-engine/hephaestus/"*/ \
  "${CODEX_HOME:-$HOME/.codex}/plugins/cache/agentlas-core-engine/hephaestus/"*/
do
  if [ -n "$candidate" ] && [ -f "$candidate/AGENTS.md" ] && [ -f "$candidate/package-contract.json" ] && [ -f "$candidate/contracts/builder-interview-research-gate.md" ]; then
    ENGINE="$candidate"
    break
  fi
done
echo "ENGINE=$ENGINE"
```

If `ENGINE` is empty, go to the final section ("not installed").

Resolve the runner once here. Every route below, including normal package
builds, uses this value:

```bash
RUNNER=""
for candidate in \
  "$HOME/.agentlas/runtime/current/bin/hephaestus" \
  "$ENGINE/bin/hephaestus" \
  "./bin/hephaestus" \
  "./claude/plugins/agentlas-core-engine-meta-agent/bin/hephaestus" \
  "./codex/plugins/agentlas-core-engine-meta-agent/bin/hephaestus"
do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then RUNNER="$candidate"; break; fi
done
if [ -z "$RUNNER" ]; then
  for cache in "$HOME/.claude/plugins/cache/agentlas-core-engine/hephaestus" \
               "${CODEX_HOME:-$HOME/.codex}/plugins/cache/agentlas-core-engine/hephaestus"; do
    newest="$(ls -d "$cache"/*/bin/hephaestus 2>/dev/null | sort -V | tail -1)"
    if [ -n "$newest" ] && [ -x "$newest" ]; then RUNNER="$newest"; break; fi
  done
fi
[ -n "$RUNNER" ] || { echo "Hephaestus runtime not found. Run the installer first." >&2; exit 1; }
```

## Route

### If the request is `ontology`

Open the project-local Knowledge/Memory panel:

```bash
"$RUNNER" ontology --gui .
```

Report the returned `gui_url`, `db_path`, `inbox_path`, and verification status.

### Otherwise

Read `$ENGINE/AGENTS.md`, then:

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
   `$ENGINE/contracts/builder-interview-research-gate.md` before writing
   substantial package files. Follow the briefing interview engine
   (`agentlas_cloud/interview/`): use the required anti-scope, done-signal, and
   stop-criterion lenses; stop only at ambiguity <= 0.2 with dimension floors
   met for two consecutive rounds; then run a coverage check and confirm a
   one-sentence goal. Write `.agentlas/work-brief.json` (`work-brief/1.0`) so
   `cards migrate` derives triggers and anti-triggers from confirmed answers.
   Ask an 8-12 question first batch when the request is vague, continue
   follow-ups until the functional brief, ownership boundaries, role count,
   tool permission separation, synthesis need, and execution order are clear,
   research official sources, similar agent repositories or comparables,
   academic/professional theory, and plugin docs, compare selected and rejected
   tools/plugins, synthesize domain-expert behavior, and create
   `docs/builder-interview.md`,
   `docs/research-sources.md`, `docs/tool-selection.md`,
   `docs/domain-expert-synthesis.md`, `docs/prompt-performance-contract.md`, and
   `.agentlas/capability-eval-plan.json`.
4. Write all generated or repaired runtime agent instructions in English:
   `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `agent.md`, skills,
   workflow/command adapters, runtime prompts, handoff contracts, return
   contracts, and operating docs. Translate Korean or other-language source
   material into English agent behavior. Localized marketplace copy, routing
   trigger examples, and sample user inputs may use the target user language.
5. If missing narrow details would change files, adapters, or the public/private
   boundary, run the clarify-question-loop skill first.
6. Take exactly one folder explicitly named or confirmed by the user as
   `PACKAGE_TARGET`. If none was named, or more than one folder could match,
   stop and ask; never use `.`, the cwd, or `$ENGINE`. Run
   `"$RUNNER" contract resolve-target "$PACKAGE_TARGET" --base "$PWD"` and set
   `PACKAGE_ROOT` only to the receipt's exact `package_root`. A nonzero exit or
   any status other than `ok` is a blocker.
7. Generate or repair the smallest useful Agentlas package at `PACKAGE_ROOT`.
   Before writing any package file, lay the contract down:
   `"$RUNNER" contract scaffold "$PACKAGE_ROOT" --mode single|team|package`.
   Then, as soon as the routing card exists, run
   `"$RUNNER" contract complete "$PACKAGE_ROOT" --mode single|team|package`.
   The engine fills artifacts already answered by the routing card, roster, and
   on-disk schemas without overwriting authored bodies or inventing facts. Run
   complete before verify, then fill every remaining named placeholder.
   `contract prompt --mode <mode>` lists the mode's artifacts.

   Run `"$RUNNER" contract verify "$PACKAGE_ROOT" --mode single|team|package`
   (this runs the team-shape rule too). If it
   fails, do not report `completed`; correct the shape by collapsing to a valid
   single-agent package or adding orchestrator/HQ plus company-blueprint
   topology, then rerun the gate and verify it.
8. If the package exists in the current workspace, register its routing-card to
   local discovery so it can participate in local routing priority:

```bash
"$RUNNER" cards migrate "$PACKAGE_ROOT" --tier local --overwrite
```

9. After verification and local discovery registration, ask exactly one final
   two-choice storage question, using structured choice controls when the host
   provides them:
   - **Cloud에 올리기** — owner-private Agent Cloud storage that the same
     account can restore on other Desktops. Mobile uses it only after a paired
     Desktop restores/installs it; Agent Cloud does not run the LLM.
   - **로컬에만 저장** — keep the completed package on this computer and make
     no network change.

   Never auto-upload. Missing input or non-interactive execution defaults to
   local-only. Only after explicit Cloud consent, resolve the trusted runner
   and execute `"$RUNNER" upload "$PACKAGE_ROOT" --visibility private-link`
   against the exact verified package root. Auth, offline, CAS, quota, or scan
   failure leaves the local package intact and must be reported with an exact
   retry command. Public Hub publishing remains a separate explicit action.
10. Return `status`, `evidence`, `output`, `global_commands`,
   `interview_research`, and `blockers`.

## If no engine root was found

Tell the user to run the one-touch installer from an OS terminal, then reopen
the workspace in Antigravity:

```bash
curl -fsSL https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh | bash
```
