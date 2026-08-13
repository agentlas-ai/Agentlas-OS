---
description: Build, repair, or package Agentlas agents and teams with Hephaestus.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus build surface


Raw arguments: `$ARGUMENTS`

Resolve the installed engine before reading contracts or invoking the runner:

```bash
ENGINE=""
for candidate in \
  "${CLAUDE_PLUGIN_ROOT:-}" "${CODEX_PLUGIN_ROOT:-}" "${PLUGIN_ROOT:-}" \
  "$HOME/.agentlas/runtime/current/host_adapters/claude/plugins/agentlas-core-engine-meta-agent" \
  "$HOME/.agentlas/runtime/current/host_adapters/codex/plugins/agentlas-core-engine-meta-agent" \
  "$HOME/.agentlas/runtime/current" "."
do
  if [ -n "$candidate" ] && [ -f "$candidate/AGENTS.md" ] && [ -f "$candidate/package-contract.json" ] && [ -f "$candidate/contracts/builder-interview-research-gate.md" ]; then
    ENGINE="$candidate"; break
  fi
done
[ -n "$ENGINE" ] || { echo "Hephaestus engine not found. Run the installer first." >&2; exit 1; }
RUNNER="$HOME/.agentlas/runtime/current/bin/hephaestus"
[ -x "$RUNNER" ] || RUNNER="$ENGINE/bin/hephaestus"
[ -x "$RUNNER" ] || { echo "Hephaestus runner not found under $ENGINE." >&2; exit 1; }
```

Read contracts only from `$ENGINE`. Take exactly one user-named or confirmed
folder as `PACKAGE_TARGET`; if none or multiple candidates exist, stop and ask.
Never default to `.`, cwd, or `$ENGINE`. Run `"$RUNNER" contract resolve-target
"$PACKAGE_TARGET" --base "$PWD"` and set `PACKAGE_ROOT` only to the status-`ok`
receipt's exact `package_root`. If the arguments are `ontology`, run `"$RUNNER"
ontology --gui .`. Otherwise classify the request as
single-agent-builder, multi-agent-team-builder, or agentlas-packager by
independent ownership boundaries, execute the meta-agent procedure on
`$ARGUMENTS`, and include `global_commands` for the created agent or team in
the final response. If single↔multi is unclear, ask first in plain language:
"이 일을 한 명의 전문가가 처음부터 끝까지 맡으면 되나요, 아니면 조사/분석/검토처럼
여러 전문가가 나눠 맡고 마지막에 합쳐야 하나요?" Do not show
non-technical users internal labels like ownership boundary, memory/context,
synthesis, or produces/consumes.

Before writing substantial package files, run the Builder Interview and
Research Gate from `$ENGINE/contracts/builder-interview-research-gate.md`.
Follow the briefing interview engine (`agentlas_cloud/interview/`) and write
`.agentlas/work-brief.json` (`work-brief/1.0`). Ask an 8-12 question first batch
when the request is vague, continue follow-ups until the
functional brief is clear, research official sources, similar agent
repositories or comparables, academic/professional theory, and plugin docs,
compare selected and rejected tools/plugins, synthesize domain-expert behavior,
and create `docs/builder-interview.md`, `docs/research-sources.md`,
`docs/tool-selection.md`, `docs/domain-expert-synthesis.md`,
`docs/prompt-performance-contract.md`, and `.agentlas/capability-eval-plan.json`.
Include `interview_research` evidence in the final response.
For an explicitly requested minimal private scaffold, require user confirmation
and write only the complete `.agentlas/build-profile.json` opt-out receipt from
the gate contract. Never infer this profile; malformed receipts remain strict.

Write all generated or repaired runtime agent instructions in English:
`AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `agent.md`, skills, workflow/command
adapters, runtime prompts, handoff contracts, return contracts, and operating
docs. Translate Korean or other-language source material into English agent
behavior. Localized marketplace copy, routing trigger examples, and sample user
inputs may use the target user language.

After creating or repairing a package, run
Before writing any package file, lay the contract down:
`"$RUNNER" contract scaffold "$PACKAGE_ROOT" --mode single|team|package`.
Then, as soon as the routing card exists, run
`"$RUNNER" contract complete "$PACKAGE_ROOT" --mode single|team|package` — the engine fills every
artifact the package already answers (`agent.md`, work brief, sitemap, routing
benchmarks, capability eval plan, builder interview, research sources, output
example) from the routing card, the roster, and the schemas on disk. It never
overwrites an authored body and never invents a fact. Run it BEFORE
`contract verify`, so verify reports only the genuinely authored half.
It copies every required artifact into place with named `{{PLACEHOLDER}}` holes and
never overwrites. Skipping it is how a build ends with 5 of 18 required artifacts
and still reports success. `contract prompt --mode <mode>` lists what each one is for.

`"$RUNNER" contract verify "$PACKAGE_ROOT" --mode single|team|package` (this runs the team-shape rule too). If it fails, do not report
`completed`; correct the shape by collapsing to a valid single-agent package or
adding orchestrator/HQ plus company-blueprint topology, then rerun the gate.
Public or marketplace intent also requires `public_marketplace_ready: true` in
the verify receipt; never promote a `minimal-private` result.

This is the clearer build-focused name for the older Hephaestus command.

If a package was created or repaired in the current workspace, register it to
local discovery immediately so it is included in local search:

```bash
"$RUNNER" cards migrate "$PACKAGE_ROOT" --tier local --overwrite
```

Include the migration result in `evidence`.

After verification and local registration, ask exactly one final two-choice
storage question, using structured controls when available:

- **Cloud에 올리기** — save owner-private in Agent Cloud for restore by the
  same account; this is storage, not hosted LLM execution.
- **로컬에만 저장** — keep the completed package on this computer with no
  network mutation.

Never upload by default. Missing input or non-interactive execution is
local-only. Only after explicit Cloud consent run `"$RUNNER" upload
"$PACKAGE_ROOT" --visibility private-link`. Keep the local package on every
auth, offline, CAS, quota, or scan failure and report the exact retry command.
Public Hub publication remains a separate explicit action.
