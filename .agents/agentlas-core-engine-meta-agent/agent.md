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
   - `30-agentlas-packager`.
6. Read `.agentlas/memory-map.json`.
7. Select relevant skills from `.agents/skills`.
8. Use `.agents/skills/agentlas-auto-activation/SKILL.md` when local project
   continuity or `.agentlas` activation is part of the output.
9. Verify with `scripts/verify-package.sh`.

## Output

Return `status`, `evidence`, `output`, and `blockers`.
