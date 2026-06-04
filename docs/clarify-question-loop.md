# Clarify Question Loop

The clarify question loop turns a rough request into enough information to
generate or package a useful Agentlas repo.

This is a public contract. Hosted web products may store sessions, meter usage,
or run background jobs. Local runtimes may ask inline. The question strategy
should stay portable.

## When To Ask

Ask clarification when the request is missing details that change the package
shape:

- mode is ambiguous;
- target runtime is unclear;
- public vs private release boundary is unclear;
- tools, APIs, credentials, or data sources are unclear;
- the user wants an existing repo packaged but has not provided its path or
  contents;
- the output might require destructive actions, paid APIs, public publishing, or
  sensitive data handling.

Do not ask when the missing detail can be safely defaulted and repaired later.

## Question Budget

Ask one to five questions. Prefer three.

Each question should:

- be answerable in one sentence or one choice;
- change the generated files or safety boundary;
- avoid asking for secrets;
- avoid asking the user to choose internal implementation details;
- include a default when there is a safe default.

## Shared Questions

Use these for all modes when relevant:

1. Target runtime: Codex, Claude Code, Gemini CLI, Cursor, generic
   `AGENTS.md`, or multiple?
2. Public boundary: local-only, private team, public open-source, or marketplace?
3. Data and tools: what files, APIs, websites, CLIs, or services should the
   agent use?
4. Success proof: what should count as a correct output?
5. Safety boundary: what must the agent never read, write, publish, or spend?

## Mode-Specific Questions

### Single Agent Creator

- What is the one job this worker owns?
- Who will use it?
- Should it include memory, scheduled refresh, or self-evolution proposals?
- What setup steps should be beginner-friendly?

### Team Builder

- What departments or roles are required?
- Who is the final orchestrator/HQ?
- What needs PM Soul continuity?
- What gates are required before release: policy, eval, QA, approval, or human
  review?

### Agentlas Packager

- Where is the existing prompt, agent, team, repo, folder, or ZIP?
- Should the package preserve current behavior exactly, repair weak structure,
  or prepare a public release?
- Which adapters are required: Codex, Claude, Gemini, Cursor, generic
  `AGENTS.md`, or all?
- What private files, logs, secrets, or local-only notes must be excluded?

## Answer Synthesis

After answers arrive:

1. Re-run mode classification if the answers changed the mode.
2. Generate or repair the smallest useful package.
3. Include public contracts: `AGENTS.md`, `.agentlas/`, mode files, skills,
   runtime adapters, memory map, and verification.
4. Preserve user-provided constraints exactly.
5. Record unresolved assumptions in the output.

## Output

Return:

- selected mode;
- answers used;
- assumptions;
- generated or repaired files;
- verification command;
- blockers, only when user input or external state is required.
