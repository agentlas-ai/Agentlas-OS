---
name: agent-team-design
description: "Use when designing a new multi-agent team, visible agents folder, role boundaries, handoff flow, PM Soul, Memory Curator, Policy Gate, or evaluation role. Use for agent-team repo creation even when the user only says they want a meta-agent or agent operating system."
---

# Agent Team Design

## Procedure

1. Define the user job and target runtime.
2. Start with one agent. Add team roles only when routing, memory, review,
   policy, or parallel ownership is useful.
3. Use a visible public tree:
   - `agents/10-single-agent-builder/agent.md`
   - `agents/20-multi-agent-team-builder/agent.md`
   - `agents/30-agentlas-packager/agent.md`
   - `agents/40-session-agent-builder/agent.md`
4. Add `skills/<capability>/SKILL.md` for reusable procedures.
5. Add `.agentlas/company-blueprint.json` for topology.

## Output

Return the role list, handoff direction, memory owner, policy owner, and eval
owner.
