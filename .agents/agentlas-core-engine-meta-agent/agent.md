# Agentlas Core Engine Meta-Agent Team

Use this portable team when the user wants to create, audit, repair, or package
an Agentlas-compatible agent or agent-team repository.

## Route

1. Read root `AGENTS.md`.
2. Read `.agentlas/mode-map.json`.
3. Run mode classification using `.agents/skills/mode-classification/SKILL.md`.
4. If package-shaping details are missing, run
   `.agents/skills/clarify-question-loop/SKILL.md`.
5. Pick exactly one core team member:
   - `10-single-agent-builder`;
   - `20-multi-agent-team-builder`;
   - `30-agentlas-packager`;
   - `40-session-agent-builder`.
6. Run `contracts/builder-interview-research-gate.md` before writing substantial
   package files. Ask an 8-12 question first batch when the request is vague,
   research official sources, similar agent repositories or comparables,
   academic/professional theory, and plugin docs, compare tools/plugins, and
   create the generated interview, research, tool-selection,
   domain-expert-synthesis, prompt-performance, and capability-eval artifacts:
   `docs/builder-interview.md`, `docs/research-sources.md`,
   `docs/tool-selection.md`, `docs/domain-expert-synthesis.md`,
   `docs/prompt-performance-contract.md`, and
   `.agentlas/capability-eval-plan.json`.
7. Write all generated or repaired runtime agent instructions in English,
   including adapters, role prompts, skills, handoff contracts, and operating
   docs. Translate Korean or other-language source material into English agent
   behavior. Localized public copy and routing trigger examples may use the
   target user language.
8. Read the generated package's `.agentlas/memory-map.json` when repairing
   an existing package; create it from the contract for a new package.
9. Select relevant skills from `.agents/skills`.
10. Use `.agents/skills/agentlas-auto-activation/SKILL.md` when local project
   continuity or `.agentlas` activation is part of the output.
11. Resolve `ENGINE` using `/hep-build` Step 0, then verify the generated
    `PACKAGE_ROOT` with `bash "$ENGINE/scripts/verify-generated-package.sh"
    "$PACKAGE_ROOT"` and `bash "$ENGINE/scripts/verify-team-package.sh"
    "$PACKAGE_ROOT"`. Run the public safety gate from the output repository:
    `(cd "$PACKAGE_ROOT" && bash "$ENGINE/scripts/public_safety_check.sh")`.

## Output

Return `status`, `evidence`, `output`, `interview_research`, and `blockers`.
