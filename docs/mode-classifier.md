# Mode Classifier

The mode classifier chooses which Agentlas meta-agent mode should handle a user
request before any package is generated.

Every runtime should use the same public classification order even if it
implements the classifier in code, prompts, buttons, or a local command.

## Output

Return exactly one mode:

- `single-agent-creator`
- `team-builder`
- `agentlas-packager`

If the request is too ambiguous to classify, run the clarify question loop
instead of guessing.

## Classification Order

### 1. Agentlas Packager

Choose `agentlas-packager` when the user already has something and wants it
converted, repaired, cleaned, imported, or released.

Strong signals:

- existing agent, prompt, team, repo, folder, ZIP, plugin, or adapter;
- "package this", "convert this", "repair this", "make it Agentlas-ready";
- "Claude agent", "Codex agent", "Gemini agent", "Cursor agent",
  `AGENTS.md`, `CLAUDE.md`, or `GEMINI.md`;
- public release, open-source cleanup, adapter creation, or compatibility pass;
- Korean equivalents such as `기존`, `이미 만든`, `패키징`, `Agentlas 구조로`,
  `레포`, `저장소`, `폴더`, `ZIP`.

Packaging wins over team-building. If the user says "this existing team", it is
still packager first because the first job is inspection and repair.

### 2. Team Builder

Choose `team-builder` when the user asks for multiple roles or an operating
team.

Strong signals:

- team, company, firm, org, department, HQ, conductor, swarm, roster;
- multiple named roles;
- debate, review gates, handoff, QA, eval, policy, PM, memory curator;
- parallel ownership or cross-functional workflow.

### 3. Single Agent Creator

Choose `single-agent-creator` when the request is for one installable worker.

Strong signals:

- one assistant, one specialist, one worker, one skill package;
- no requested roster or multi-role topology;
- a single goal that can be handled by one agent with multiple skills.

## Ambiguity Rule

Ask clarification when:

- the user asks for an "agent team" but names only one job;
- the user asks for an "agent" but also lists several independent departments;
- the user says "package" without providing or pointing to existing material;
- the target runtime or public/private boundary changes the output.

Use `docs/clarify-question-loop.md` for the question format.

## Examples

| Request | Mode | Why |
|---|---|---|
| "Make me a research agent" | `single-agent-creator` | one worker |
| "Build a marketing agency with strategist, copywriter, designer, QA" | `team-builder` | multi-role roster |
| "Convert this Claude agent repo into Agentlas architecture" | `agentlas-packager` | existing repo |
| "Package my local team for Codex and Claude" | `agentlas-packager` | existing team plus adapters |
| "Create an AI company that writes reports" | `team-builder` | company-style topology |

## Portable Pseudocode

```text
if prompt references existing agent/team/repo/folder/zip or asks to package/convert/repair:
  return agentlas-packager

if prompt asks for team/company/firm/org/HQ/roster/multiple roles:
  return team-builder

if prompt asks for one worker/specialist/helper or is otherwise simple:
  return single-agent-creator

return needs_clarification
```
