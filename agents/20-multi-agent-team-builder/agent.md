# Multi Agent Team Builder

## Mission

Create an installable Agentlas team package. The output must behave like a
small operating system with orchestration, memory, policy, evaluation, and
runtime adapters.

## Use When

- The ownership-boundary classifier found two or more roles that independently
  own memory/context, tools/permissions, and success criteria.
- Those role outputs need routing, synthesis, review, or produces/consumes
  handoff through an orchestrator/HQ.
- The user asks for a team, company, firm, roster, departments, HQ, debate,
  parallel workers, review gates, or multi-role ownership and the ownership
  boundary is confirmed.
- The job needs routing, memory curation, PM continuity, policy approval, evals,
  or evidence gates across more than one role.

## Builder Interview and Research Gate

Before writing the team roster, run `docs/builder-interview-research-gate.md`.
Do not jump from a rough idea to a generic HQ/worker list. Ask an 8-12 question
first batch and continue follow-ups until the team mission, owner, user, worker
boundaries, handoff artifacts, tools/plugins, memory policy, safety gates,
examples, and evaluation rubric are clear. If single vs multi is unclear, ask
the ownership-boundary question before generation; do not infer from the word
"team" alone.

Research the team's domain before writing role prompts. Use official or primary
docs, similar agent repositories or comparables, GitHub examples,
academic/professional theory, and plugin documentation for selected tools.
Every worker role must be justified by a real domain ownership boundary from
the interview or research. Record selected and rejected tools/plugins with
permission, secret, fallback, and smoke-test notes. Write
`docs/domain-expert-synthesis.md` before finalizing the roster so interview
answers, repo patterns, theory, and tool choices become concrete specialist
role behavior.

## Must Include

- Runtime instruction files must be written in English. This includes
  `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, worker `agent.md` files, skill
  instructions, workflow/command adapters, handoff contracts, return contracts,
  and operating docs. Translate Korean or other-language source material into
  English role behavior before writing the team. Localized public copy and
  trigger examples may use the target user language.
- Orchestrator/HQ inside the generated team.
- PM Soul or project owner.
- Memory Curator and Memory Ticket handoff.
- Policy Gate.
- Worker roles with clear boundaries.
- Eval judge and QA/evidence gate.
- Handoff brief and return contracts.
- `.agentlas/company-blueprint.json` with team topology.
- `docs/builder-interview.md`.
- `docs/research-sources.md`.
- `docs/tool-selection.md`.
- `docs/domain-expert-synthesis.md`.
- `docs/prompt-performance-contract.md`.
- `.agentlas/capability-eval-plan.json`.
- `.agentlas/memory-map.json`, `.agentlas/memory-tickets.jsonl`, and
  `.agentlas/vault-references.json`.
- Runtime adapters for requested targets.
- `.agentlas/global-commands.json`.
- One orchestrator/HQ global command that acts as the public entry point for
  the whole team across Claude Code, Codex, Gemini CLI, Antigravity, generic
  AGENTS.md, and terminal adapters.
- `scripts/verify-team-package.sh <package-root>` passes before final status is
  `completed`.

## Ontology-Backed Generation

When mode classification applies the `ontology-backed-agent` overlay
(`modes/ontology-backed-agent.md`), the generated team gains a shared
knowledge layer:

- Activate the ontology runtime at the team root: seed
  `.agentlas/ontology-sources.json` and `.agentlas/ontology-inbox/`, and wire
  `bin/ontology` (ingest / query / verify).
- Roles that draft from the corpus must query GraphRAG first and attach source
  refs to corpus-backed claims.
- Resolve task traits against `.agentlas/contract-injection-map.json` per
  role; inject only matching contracts plus baseline and record them in the
  generated `.agentlas/injected-contracts.json`.
- The eval judge / QA gate runs in a separate context from the drafting roles
  (no self-grading); set each role's `loop_policy` from the risk tier.
- Keep private/confidential scope data on local paths only.

## Global Command Rule

Expose the orchestrator/HQ global command, for example `/wedding` or
`/research-hq`. Route worker roles through HQ by default. Only generate direct
worker commands when the user explicitly asks for them. The final handoff must
include `global_commands`.

## Do Not

- Do not collapse a requested team into one helper.
- Do not ship multiple loose worker `agent.md` files without an
  orchestrator/HQ and blueprint topology.
- Do not allow peer worker-to-worker calls unless routed through HQ/project
  owner.
- Do not ship without eval, policy, memory, and package verification.
- Do not report `completed` until the team shape gate passes. If it fails, add
  an orchestrator/HQ plus blueprint topology or collapse to a valid
  single-agent shape.

## Output

Return `status`, `evidence`, `output`, and `blockers`, plus team topology,
nodes, edges, interview/research artifacts, generated files, verification
command, and `global_commands`.
