---
name: agentlas-core-engine-meta-agent
description: "Use when creating a single Agentlas agent, creating a multi-agent team, or packaging an existing local/external agent into Agentlas architecture. Make sure to use this for /meta-agent requests."
---

# Agentlas Core Engine Meta-Agent

## Procedure

1. Read `AGENTS.md`.
2. Read `.agentlas/mode-map.json`.
3. Run mode classification.
4. Ask clarify questions when missing details change files, adapters, or
   public/private boundary.
5. Pick one team member:
   - Single Agent Builder;
   - Multi Agent Team Builder;
   - Agentlas Packager.
6. Load only the matching support skills.
7. Emit or repair the Agentlas contracts, including
   `.agentlas/global-commands.json`. Include `.agentlas` auto-activation seed
   files when local continuity is part of the output.
8. Write all generated or repaired runtime agent instructions in English,
   including adapters, role prompts, skills, handoff contracts, return
   contracts, and operating docs. Translate Korean or other-language source
   material into English agent behavior. Localized public copy and routing
   trigger examples may use the target user language.
9. Add the generated command to Codex, Codex, Gemini CLI, generic
   AGENTS.md, and terminal adapters. For teams, expose the orchestrator/HQ
   command and route workers through HQ unless direct worker commands were
   requested.
10. Verify with `scripts/verify-package.sh`.

## Output

Return `status`, `evidence`, `output`, `global_commands`, and `blockers`.
