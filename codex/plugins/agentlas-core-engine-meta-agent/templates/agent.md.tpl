# {{AGENT_NAME}}

## Role

{{ROLE}}

## Agentlas Mode

{{AGENTLAS_MODE}}

## Responsibilities

{{RESPONSIBILITIES}}

## Architecture Contract

- Single-agent packages stay one worker unless the user asks for a team.
- Team packages include an orchestrator/HQ hierarchy, worker handoffs, eval
  judge, QA/evidence gate, memory contracts, and runtime adapters. System
  agents (PM Soul, Memory Curator, Policy Gate) are OS-resident — installed by
  the wizard, never copied into a package (owner decision 2026-08-08, #9);
  packages hold only their outputs.
- Existing agents keep useful behavior while gaining Agentlas contracts during
  packaging.

## Output

{{OUTPUT_CONTRACT}}
