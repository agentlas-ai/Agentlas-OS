# Single Agent Builder

## Mission

Create one installable Agentlas worker package. The output may include multiple
skills, setup guides, memory contracts, runtime adapters, research refresh, and
self-evolution proposals, but it remains a single agent package.

## Use When

- The user asks for one agent, helper, worker, specialist, or personal tool.
- The agent may need several skills but does not need a roster or team topology.
- The user asks for self-evolving, keeps-learning, latest/current research, or
  periodic refresh behavior.

## Builder Interview and Research Gate

Before writing the single worker, run `docs/builder-interview-research-gate.md`.
Do not accept a vague one-line agent idea as the final prompt. Ask an 8-12
question first batch, then continue follow-ups until the worker's target user,
recurring tasks, inputs, outputs, tools/plugins, examples, failure modes, memory
policy, and evaluation rubric are clear.

Research the domain before writing `agent.md` or reusable skills. Use official
or primary docs, similar agent repositories or comparables, GitHub examples,
academic/professional theory, and plugin documentation for selected tools.
Record accepted and rejected tool or plugin choices with permission, secret,
fallback, and smoke-test notes. Write `docs/domain-expert-synthesis.md` before
the final worker prompt so interview answers, repo patterns, theory, and tool
choices become concrete specialist behavior.

## Must Include

- Runtime instruction files must be written in English. This includes
  `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `agent.md`, skill instructions,
  workflow/command adapters, handoff contracts, and operating docs. Translate
  Korean or other-language source material into English behavior before writing
  the package. Localized public copy and trigger examples may use the target
  user language.
- `AGENTS.md` as canonical core.
- `.agents/<agent-id>/agent.md` or equivalent single worker contract.
- `.agents/skills/<skill-id>/SKILL.md` for reusable capabilities.
- `docs/builder-interview.md`.
- `docs/research-sources.md`.
- `docs/tool-selection.md`.
- `docs/domain-expert-synthesis.md`.
- `docs/prompt-performance-contract.md`.
- `.agentlas/capability-eval-plan.json`.
- `.agentlas/agent-card.json`.
- `.agentlas/company-blueprint.json` with `single-agent` topology unless the
  user explicitly asks for a team.
- `.agentlas/memory-map.json`, `.agentlas/memory-tickets.jsonl`, and
  `.agentlas/vault-references.json`.
- Runtime adapters for requested targets.
- `.agentlas/global-commands.json`.
- One canonical global command for the worker, with matching Claude Code,
  Codex, Gemini CLI, Antigravity, generic AGENTS.md, and terminal command
  surfaces whenever those adapters are generated.

## Global Command Rule

Choose the command from the generated package slug, for example
`/research-agent`. Add the command while creating the package. Do not finish
without telling the user the command for each runtime in `global_commands`.

## Ontology-Backed Generation

When mode classification applies the `ontology-backed-agent` overlay
(`modes/ontology-backed-agent.md`), add these generation steps:

- Activate the ontology runtime for the package: seed
  `.agentlas/ontology-sources.json` and `.agentlas/ontology-inbox/`, and wire
  `bin/ontology` (ingest / query / verify).
- State a retrieval-first workflow in the generated `agent.md`: GraphRAG query
  before generation, source refs (source_id + span) attached to corpus-backed
  claims.
- Resolve task traits against `.agentlas/contract-injection-map.json` and
  inject only the matching contracts plus baseline. Write the resolved list to
  the generated `.agentlas/injected-contracts.json`. Never blanket-inject.
- Set `loop_policy` in the generated `agent.md` from the risk tier: `none`,
  `self-correct`, or `verified`. External writes/sends force `verified` with a
  separate-context verifier (no self-grading) and the side-effect-containment
  human gate.
- Keep private/confidential scope data on local paths only; cloud LLM hooks
  and the cloud Hub MCP never receive those chunks.

## Self-Evolution Rule

Self-evolution is proposal-first. The agent may collect sources, keep a
watchlist, generate repair kits, and propose patches. Human approval is required
before widening tools, adding connectors, changing secrets, or editing the
agent's own core instructions.

## Output

Return `status`, `evidence`, `output`, and `blockers`, plus the generated single
agent path, interview/research artifacts, verification command, and
`global_commands`.
