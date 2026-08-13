---
description: Build, repair, or package Agentlas agents and teams with Hephaestus.
argument-hint: <request, or "ontology">
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus build surface


Raw arguments: `$ARGUMENTS`

Use the `agentlas-core-engine-meta-agent` skill from the Hephaestus plugin.
Expose `/prompts:hep-build` as the public Codex build prompt next to
`/prompts:hep-network` and `/prompts:hep-cloud`.

Resolve the installed engine first:

```bash
ENGINE=""
for candidate in \
  "${CODEX_PLUGIN_ROOT:-}" "${CLAUDE_PLUGIN_ROOT:-}" "${PLUGIN_ROOT:-}" \
  "$HOME/.agentlas/runtime/current/host_adapters/codex/plugins/agentlas-core-engine-meta-agent" \
  "$HOME/.agentlas/runtime/current/host_adapters/claude/plugins/agentlas-core-engine-meta-agent" \
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
receipt's exact `package_root` before any package command.

- If the arguments are `ontology`, resolve the runner exactly as in
  `/prompts:hep-network` and run `"$RUNNER" ontology`.
- Otherwise classify the request as single-agent-builder,
  multi-agent-team-builder, or agentlas-packager by independent ownership
  boundaries and execute the meta-agent procedure on: `$ARGUMENTS`. If
  single↔multi is unclear, ask first in plain language: "이 일을 한 명의
  전문가가 처음부터 끝까지 맡으면 되나요, 아니면 조사/분석/검토처럼 여러
  전문가가 나눠 맡고 마지막에 합쳐야 하나요?" Do not expose internal labels
  like ownership boundary, memory/context, synthesis, or produces/consumes.
- Before writing substantial package files, run the Builder Interview and
  Research Gate from `$ENGINE/contracts/builder-interview-research-gate.md`.
  Follow the briefing interview engine (`agentlas_cloud/interview/`) and write
  `.agentlas/work-brief.json` (`work-brief/1.0`). Ask an 8-12 question first
  batch when the request is vague, continue follow-ups until the
  functional brief is clear, research official sources, similar agent
  repositories or comparables, academic/professional theory, and plugin docs,
  compare selected and rejected tools/plugins, synthesize domain-expert
  behavior, and create `docs/builder-interview.md`,
  `docs/research-sources.md`, `docs/tool-selection.md`,
  `docs/domain-expert-synthesis.md`, `docs/prompt-performance-contract.md`,
  and `.agentlas/capability-eval-plan.json`.
- Write all generated or repaired runtime agent instructions in English:
  `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `agent.md`, skills, workflow/command
  adapters, runtime prompts, handoff contracts, return contracts, and operating
  docs. Translate Korean or other-language source material into English agent
  behavior. Localized marketplace copy, routing trigger examples, and sample
  user inputs may use the target user language.
- After creating or repairing a package, run
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
  `completed`; correct the shape by collapsing to a valid single-agent package
  or adding orchestrator/HQ plus company-blueprint topology.
- Include `global_commands` for the created agent or team in the final
  response, plus `interview_research` evidence.
- If a package was created/repaired in the current workspace, register it to
  local discovery immediately: run `"$RUNNER" cards migrate "$PACKAGE_ROOT" --tier local
  --overwrite` (or the same `hephaestus` runner in cache if local binary is
  unavailable), and include migration result in `evidence`.

If runtime discovery migration isn't needed, still validate that the package has
`./.agentlas/routing-card.json` and include that local-card artifact in `evidence`
when skipping migration.

After the package is verified and saved locally, use the host's structured
choice UI when available and ask exactly one final question:

- **Cloud에 올리기** — owner-private Agent Cloud storage, restorable on the
  same account's other Desktops. Mobile can use it only through a paired
  Desktop after that Desktop restores/installs it; this is not hosted model
  execution.
- **로컬에만 저장** — keep the completed package on this computer with no
  network mutation.

Do not upload automatically. A missing answer or non-interactive host defaults
to local-only. On explicit Cloud consent, run the resolved Hephaestus runner as
`"$RUNNER" upload "$PACKAGE_ROOT" --visibility private-link`, where
`PACKAGE_ROOT` is the exact verified package root, never a guessed parent.
Cloud auth/offline/CAS/security failure must not delete or roll back the local
package; report the failure and exact retry command. Public Hub publication is
a separate explicit action and must not appear as a third choice here.
