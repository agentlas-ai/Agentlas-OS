---
description: Build, repair, or package Agentlas agents and teams with Hephaestus.
argument-hint: <request, or "ontology">
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

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
  "$HOME/.agentlas/runtime/current/bin/hephaestus" \
  "${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/bin/hephaestus}" \
  "${CODEX_PLUGIN_ROOT:+$CODEX_PLUGIN_ROOT/bin/hephaestus}" \
  "${PLUGIN_ROOT:+$PLUGIN_ROOT/bin/hephaestus}" \
  "${GEMINI_EXTENSION_ROOT:+$GEMINI_EXTENSION_ROOT/bin/hephaestus}" \
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
  echo "Hephaestus runtime not found. Run the installer first." >&2
  exit 1
fi
"$RUNNER" ontology --gui .
```

3. Report the returned `gui_url`, `db_path`, `inbox_path`, and verification status.

If the first argument is not `ontology`, route to the Agentlas Core Engine
Meta-Agent team.

**Step 0 — resolve the engine root, and read the engine's own contracts from it.**
Every path in steps 1, 2 and 4 belongs to Hephaestus, not to the user's project.
Read relatively and in someone else's repository you find nothing — or worse,
you find their `AGENTS.md` and follow it. Measured 2026-08-07: three packages
built outside this engine's own repository shipped 5 of 18 required artifacts,
because these reads silently returned nothing and the model improvised the rest.

The marker is `AGENTS.md` **and** `package-contract.json` together. The installed
runtime root carries the contract and the code but not the instructions — those
travel in its `host_adapters/` bundle — so testing for the contract alone selects
a root where every read in steps 1, 2 and 4 comes back empty.

```bash
ENGINE=""
for candidate in \
  "${CLAUDE_PLUGIN_ROOT:-}" \
  "${CODEX_PLUGIN_ROOT:-}" \
  "${PLUGIN_ROOT:-}" \
  "${GEMINI_EXTENSION_ROOT:-}" \
  "$HOME/.agentlas/runtime/current/host_adapters/claude/plugins/agentlas-core-engine-meta-agent" \
  "$HOME/.agentlas/runtime/current/host_adapters/codex/plugins/agentlas-core-engine-meta-agent" \
  "$HOME/.agentlas/runtime/current" \
  "."
do
  if [ -n "$candidate" ] && [ -f "$candidate/AGENTS.md" ] && [ -f "$candidate/package-contract.json" ] && [ -f "$candidate/contracts/builder-interview-research-gate.md" ]; then
    ENGINE="$candidate"; break
  fi
done
[ -z "$ENGINE" ] && { echo "Hephaestus engine not found. Run the installer first." >&2; exit 1; }
RUNNER=""
for candidate in "$HOME/.agentlas/runtime/current/bin/hephaestus" "$ENGINE/bin/hephaestus"; do
  if [ -x "$candidate" ]; then RUNNER="$candidate"; break; fi
done
[ -n "$RUNNER" ] || { echo "Hephaestus runner not found." >&2; exit 1; }
echo "ENGINE=$ENGINE"
```

Report the resolved `ENGINE` in the final `evidence`. If a file below is missing
from it, say so as a blocker — do not carry on and improvise it.

1. Read `$ENGINE/AGENTS.md`.
2. Read `$ENGINE/.agentlas/mode-map.json` and the mode contract it names under
   `$ENGINE/modes/`.
3. Classify the request as single-agent builder, multi-agent team builder, or
   packager by independent ownership boundaries: one role owning
   memory/context, tools/permissions, and success criteria is single-agent;
   two or more such roles plus routing/synthesis/handoff is team-builder;
   existing material repair/conversion is packager. If single↔multi is
   unclear, ask first in plain language: "이 일을 한 명의 전문가가 처음부터
   끝까지 맡으면 되나요, 아니면 조사/분석/검토처럼 여러 전문가가 나눠 맡고
   마지막에 합쳐야 하나요?" Do not show non-technical users internal labels
   like ownership boundary, memory/context, synthesis, or produces/consumes.
4. Run the Builder Interview and Research Gate in
   `$ENGINE/contracts/builder-interview-research-gate.md` before writing substantial
   package files. Ask an 8-12 question first batch when the request is vague; continue
   follow-ups until target user, tasks, inputs, outputs, examples,
   tools/plugins, memory, failure modes, ownership boundaries, execution order,
   and evals are clear. Question selection, ambiguity scoring and the stop
   decision follow the briefing interview engine (`agentlas_cloud/interview/`):
   lens-table questions (anti_scope / done_signal / stop_criterion are
   required), stop only at ambiguity <= 0.2 with all dimension floors met for 2
   consecutive rounds, then one coverage check plus a one-sentence goal restate. Research official
   or primary docs, similar agent repositories or comparables, GitHub examples,
   academic/professional theory, and tool/plugin docs. Record selected and
   rejected tools/plugins with permission, secret, fallback, and smoke-test
   notes, then synthesize domain-expert behavior before writing prompts.
5. **Resolve exactly one package target before writing anything.** Take one
   folder explicitly named or confirmed by the user as `PACKAGE_TARGET`. If no
   exact folder was named, or multiple candidates exist, stop and ask. Never
   default to `.`, the cwd, or `$ENGINE`. Run
   `"$RUNNER" contract resolve-target "$PACKAGE_TARGET" --base "$PWD"` and set
   `PACKAGE_ROOT` only to the status-`ok` receipt's exact `package_root`. A
   nonzero exit or any error receipt is a blocker. Then:

   ```bash
   "$RUNNER" contract scaffold "$PACKAGE_ROOT" --mode single|team|package
   ```

   Then, as soon as the routing card exists, let the engine answer every hole it
   can from the package's own declarations:

   ```bash
   "$RUNNER" contract complete "$PACKAGE_ROOT" --mode single|team|package
   ```

   This writes `agent.md`, `.agentlas/work-brief.json`, `.agentlas/sitemap.json`,
   `.agentlas/routing-benchmarks.jsonl`, `.agentlas/capability-eval-plan.json`,
   `docs/builder-interview.md`, `docs/research-sources.md`, and
   `contracts/output.example.json` from the routing card, the roster, and the
   schemas that are already on disk. It never overwrites a body a person wrote
   and never invents a fact - every value it writes is one the package already
   states somewhere else. Run it BEFORE `contract verify`, so what verify still
   reports is the genuinely authored half, not paperwork the engine could have
   done. Measured 2026-08-07: the published corpus was missing these eight
   artifacts almost universally, and every one of them was derivable.

   This copies the engine's templates into place and never overwrites an
   existing file. It is the step that puts every required artifact on disk with
   named `{{PLACEHOLDER}}` holes, which is what turns "the model forgot a file"
   into "the model has a hole to fill". Skipping it is how a build ends with 5
   of 18 required artifacts and still reports success.

   Then fill the holes. `contract prompt --mode <mode>` prints the artifact list
   with what each one is for.

6. Generate `.agentlas/work-brief.json` (Work Brief `work-brief/1.0` — the
   machine-readable interview output; `cards migrate` consumes its anti_scope
   and goal/acceptance as routing-card triggers), plus
   `docs/builder-interview.md`, `docs/research-sources.md`,
   `docs/tool-selection.md`, `docs/domain-expert-synthesis.md`,
   `docs/prompt-performance-contract.md`, and
   `.agentlas/capability-eval-plan.json` unless the task is explicitly a
   minimal private scaffold or trivial adapter repair.
   For a minimal private scaffold, do not infer the exception: require the
   user's explicit request and confirmation, then write the exact
   `.agentlas/build-profile.json` receipt defined by the Builder Interview and
   Research Gate. Any missing or malformed receipt remains `standard`.
7. Load only the matching public skills.
8. Generate or repair `.agentlas/global-commands.json` and matching runtime
   command files or aliases.
9. If a package was created or repaired, register it to local discovery before
   reporting. Pass `$PACKAGE_ROOT`, never `.`:

   ```bash
   "$RUNNER" cards migrate "$PACKAGE_ROOT" --tier local --overwrite
   ```

   With `.` this step resolves a different root than the verified package and
   overwrites its output — measured: `id` becomes `local/agent`, `workforce`
   becomes `null`, and `routing_status` promotes itself from draft to trusted.
   An absolute path does not reproduce any of it.

10. Run the package contract gate before reporting completion:

   ```bash
   "$RUNNER" contract verify "$PACKAGE_ROOT" --mode single|team|package
   ```

   This is the same contract step 5 scaffolded from, so its blockers name the
   exact artifact and the exact unfilled hole, and for a team it runs the
   team-shape rule as well. Fix every blocker and rerun until the list is empty.
   **A non-empty blocker list means you may not report `completed`** — report
   `blocked` and list them verbatim. Public or marketplace intent additionally
   requires `public_marketplace_ready: true`; a `minimal-private` receipt is
   never public-ready and must not be promoted by this command.
11. After the verified package has been written and registered locally, ask one
    final storage question. Prefer the host's structured two-choice UI when it
    exists, and use these choices without adding a public-Hub option:
    - **Cloud에 올리기** — save the package owner-private in Agent Cloud so it
      can be restored on the same account's other Desktops. Mobile can use it
      only after a paired Desktop restores/installs it; Agent Cloud is not a
      hosted LLM executor.
    - **로컬에만 저장** — keep the already completed package on this computer
      and perform no network mutation.

    Never upload by default. If the host is non-interactive or the user does
    not answer, choose local-only. Only after explicit Cloud consent, run the
    resolved Hephaestus runner against the exact verified package root:

    ```bash
    "$RUNNER" upload "$PACKAGE_ROOT" --visibility private-link
    ```

    `PACKAGE_ROOT` is the exact gate-verified package, never the workspace or a
    guessed parent folder. Authentication, offline, CAS-conflict, quota, or
    security-scan failure must leave the local package intact; report the
    failure and the exact retry command. Public Hub publication remains a
    separate explicit `/hep-upload ... --visibility marketplace` action.
12. Return `status`, `evidence`, `output`, `global_commands`,
   `interview_research`, and `blockers`. `evidence` must carry the resolved
   `ENGINE`, the `contract scaffold` receipt, and the final `contract verify`
   blocker list — a build that cannot show those three did not run this flow.
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
