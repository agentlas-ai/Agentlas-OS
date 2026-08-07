# Builder Interview and Research Gate

This gate protects the functional quality of agents built with
`/hep-build`. The package architecture can be correct while the actual
agent behavior is weak; this gate is about the agent's job design, prompts,
tools, examples, and evaluation pressure. The goal is to make rough user
requests produce strong agents by forcing interview, comparable-agent research,
academic or professional theory research, tool selection, and prompt synthesis
before generation.

## When It Applies

Run this gate before writing or repairing substantial generated package files
for all three build modes:

- `single-agent-creator`;
- `team-builder`;
- `agentlas-packager`.

Skip only for trivial adapter repairs, command-file repairs, or inspection-only
tasks that do not change agent behavior. If the user explicitly asks for a
minimal scaffold, record that opt-out in the final evidence and keep the package
below marketplace/public-ready status.

## Gate 1 - Builder Interview

Do not treat the user's first rough prompt as enough specification. First
classify the mode, then interview the user before generation.

Ask a first batch of 8-12 high-leverage questions. Continue with follow-ups
until these dimensions are no longer ambiguous:

- single-agent vs team shape: whether each role needs independent
  memory/context, or whether one worker can own the whole job with multiple
  skills;
- role count and ownership boundaries;
- tool and permission separation by role;
- whether role outputs must be synthesized by an orchestrator/HQ;
- execution order: sequential produces/consumes pipeline vs independent
  parallel packets;
- target user and buyer;
- job-to-be-done and top recurring tasks;
- inputs the agent receives, including files, APIs, chats, repos, docs, and
  user-provided examples;
- exact output artifacts, schemas, file formats, and handoff expectations;
- examples of excellent and unacceptable output;
- domain principles, professional methods, legal/safety constraints, and
  vocabulary the agent must know;
- required tools, plugins, connectors, local files, browser actions, and
  external services;
- forbidden tools, unavailable credentials, paid services, privacy boundaries,
  and actions requiring user confirmation;
- memory behavior, refresh cadence, source freshness needs, and stale-check
  policy;
- failure modes, refusal behavior, escalation path, and rollback behavior;
- evaluation cases, scoring rubric, benchmarks, and success metrics;
- runtime targets and the public global command.

If a user cannot answer a question, propose a conservative default, label it as
`assumption`, and ask whether that default is acceptable. Do not bury unknowns
inside the generated agent instructions.

### Interview mechanics (briefing interview engine)

Question generation, scoring and the stop decision follow the briefing
interview engine (`agentlas_cloud/interview/`):

- **Waves + tension rule.** Wave 1 covers basics (goal, constraints, done
  signal), wave 2 covers edges/conflicts, wave 3 covers contradictions and
  unverified assumptions. The wave plan is a tool, not the goal: when an answer
  reveals a contradiction, an avoidance or an untested assumption, abandon the
  wave order and follow that thread.
- **Lenses.** Pick questions from the lens table
  (`interview.render_lens_table("hep-build")`) — scope/system/intent/challenge.
  The `anti_scope`, `done_signal` and `stop_criterion` lenses are REQUIRED for
  builds: the user's own words about what the agent must NOT do become the
  routing card's `anti_triggers` verbatim.
- **Scoring + stop gates.** After each round, run the engine's scoring prompt
  (`interview.build_scoring_prompt("hep-build")`) and compose the ambiguity
  score. The interview may end only when: overall ambiguity <= 0.2, every
  dimension (goal/constraints/success/context) clears its floor, and both held
  for 2 consecutive rounds. A low score is permission to AUDIT the close, not
  permission to close.
- **Closing.** One coverage question ("anything I missed?"), then restate the
  goal as one sentence and confirm "would someone reading only this line reach
  the same result?" before generation starts.
- **Every risk noted in an interim summary must become a concrete question in
  the next wave** — or be recorded as deferred with a named reason. Deliberate
  deferrals ("나중에 정할게") are never treated as ambiguity.

If the prompt is only a domain label plus "team" (for example, "stock research
team") and the ownership boundaries are unclear, do not start generation until
the first batch answers the shape questions above.

Ask those shape questions in plain language. Do not show users internal labels
like ownership boundary, memory/context, synthesis, or produces/consumes. The
first question should be understandable by a non-technical operator:

> 이 일을 한 명의 전문가가 처음부터 끝까지 맡으면 되나요, 아니면 조사/분석/검토처럼
> 여러 전문가가 나눠 맡고 마지막에 합쳐야 하나요?

Then ask only the practical follow-ups that matter: what roles are needed, what
files/accounts/tools each role can use, whether one person must combine the
results, and whether the work is sequential or can happen at the same time.

Write the result into the generated package as `docs/builder-interview.md`
(human-readable) AND as `.agentlas/work-brief.json` (machine-readable Work
Brief, schemaVersion `work-brief/1.0`): one-line goal, constraints, verifiable
acceptance criteria, anti_scope, the assumption ledger with source tags
(`user|code|memory|research|default`), deferred topics, weighted
evaluation_principles, exit_conditions, and the final ambiguity score in
metadata. `cards migrate` consumes the Work Brief as its first-choice source
for trigger_examples and anti_triggers.

## Gate 2 - Research Dossier

Before writing role prompts, skills, or operating loops, research the domain and
turn sources into design decisions.

Minimum useful source set:

- official documentation or primary sources for the domain and every selected
  tool or API;
- similar agent repositories, GitHub repositories, examples, benchmark suites,
  or issue threads. Use at least 3 comparable agents, repositories, systems, or
  benchmarks for public or marketplace-ready output. If direct comparables do
  not exist, record the exact no-match search terms and the nearest useful
  analogs;
- academic papers, standards, laws, professional frameworks, mature industry
  playbooks, or domain textbooks. Use at least 2 theory sources for substantial
  builds: one general agent-design source from
  `docs/builder-quality-research-basis.md`, plus one domain-specific academic,
  standard, legal, or professional source when available. If no domain-specific
  theory source exists, record the failed search and fall back to the baseline
  agent-theory sources;
- existing Agentlas packages, AppBridge agents, or public-agent examples only
  as comparables, not as a substitute for domain research;
- current plugin or connector documentation for every plugin the agent may use.

Record sources in `docs/research-sources.md` with:

- source title and URL or local path;
- source type: official, GitHub, academic, legal, benchmark, competitor,
  internal-comparable, or user-provided;
- freshness status: `verified`, `memory_derived`, `inferred`, or
  `stale_check_needed`;
- the specific agent-design implication.

If network access is unavailable, use local/user-provided sources and mark
current facts as `stale_check_needed`. Block public, legal, medical, financial,
or compliance-ready claims until current sources are verified.

## Gate 3 - Tool and Plugin Selection

Agents are only useful when their tool plan matches the user's environment.
Before selecting plugins or connectors:

1. Inventory available local tools, plugins, MCP servers, and runtime-specific
   capabilities.
2. For each required capability, compare at least one selected option and one
   rejected alternative when alternatives exist.
3. Record secrets, account state, permission scope, paid-service dependency,
   fallback behavior, and smoke-test plan.
4. Prefer official or widely maintained integrations over shallow wrappers.
5. Reject plugins that require unavailable credentials, unsupported paid
   accounts, unclear permissions, or unverifiable behavior.

Write this as `docs/tool-selection.md`.

## Gate 4 - Domain Expert Synthesis

Do not write final role prompts immediately after research. First combine the
interview answers, similar-agent/repository findings, academic or professional
theory, and tool/plugin review into `docs/domain-expert-synthesis.md`.

This synthesis must include:

- target expertise and concrete non-goals;
- user interview requirements that materially shaped the agent;
- similar agents, repositories, systems, or benchmarks studied, including
  accepted and rejected patterns;
- academic, standard, legal, or professional theory that changed the agent's
  operating loop or heuristics;
- tool and plugin reasoning that explains why selected tools beat rejected
  alternatives;
- prompt architecture decisions, including reasoning/action loop, memory
  policy, output schema, handoff behavior, and refusal/escalation behavior;
- domain heuristics and decision rules that make the agent behave like a
  strong specialist instead of a generic assistant;
- examples, counterexamples, and evaluation cases derived from the interview
  and research.

If the synthesis cannot be written because key interview answers are missing,
return `needs_clarification` instead of generating a generic agent.

## Gate 5 - Prompt Performance Contract

Every generated agent or role must get a performance-oriented prompt contract,
not just a role title.

The package must include `docs/prompt-performance-contract.md` covering:

- agent identity and non-goals;
- operating loop;
- input contract and output contract;
- tool policy and plugin policy;
- memory policy and source freshness policy;
- domain heuristics and decision rules copied from
  `docs/domain-expert-synthesis.md`;
- examples of good and bad behavior;
- evaluation rubric and benchmark cases;
- escalation and refusal rules;
- concrete trigger and anti-trigger language.

Teams must apply this to the orchestrator and every worker role. Single agents
apply it to the worker and every reusable skill. Packager mode must preserve the
source behavior, then add the missing domain-expert synthesis and
prompt-performance contract.

## Gate 6 - Capability Evaluation Plan

Every generated or repaired package that changes agent behavior must include
`.agentlas/capability-eval-plan.json` with:

- at least 10 positive capability cases for public or marketplace-ready output;
- at least 5 negative or anti-trigger cases;
- expected artifacts and pass criteria;
- tool/plugin smoke checks where tools are involved;
- stale-source and missing-credential cases where relevant.

The generated `scripts/verify-package.sh` must check the presence of the
interview, research, tool-selection, domain-expert-synthesis,
prompt-performance, and capability-eval files unless the package is explicitly
marked as a minimal private scaffold.

## Final Handoff Evidence

The final `/hep-build` response must report:

- interview status and unresolved assumptions;
- research sources used;
- selected and rejected tool/plugin choices;
- domain-expert synthesis location;
- prompt-performance contract location;
- capability eval plan location;
- verification commands and results;
- blockers that require user input or external account state.
