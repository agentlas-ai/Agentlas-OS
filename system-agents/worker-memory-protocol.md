# Worker Memory Protocol

Every agent that does substantial work follows this, whatever host runs it.

This exists because the recall half and the write half live in different places.
Recall is delivered by the host: a session-start capsule injects relevant project
memory before the first turn. Emission is the agent's job, and when the agent runs
on a host that does not carry the Agentlas hook, nothing else will do it. An
invocation still leaves a provenance record (request hash) without this protocol,
but the learning itself is lost. Measured 2026-07-29: task learnings that piled up
outside the shared folder layer starved the Soul and the Curator.

## Preflight - before acting

1. Read the injected memory capsule first. Do not re-derive facts it already states
   and do not re-litigate diagnoses it records as settled.
2. Treat retrieved memory as a starting frame, not as proof. It reflects what was
   true when it was written.
3. Verify any stale or high-risk fact before relying on it. If a memory names a
   file, flag, path, or certificate, confirm that thing still exists.
4. When retrieved memory contradicts what you observe now, the observation wins and
   the contradiction is itself worth emitting.

## Emission - after substantial work

Substantial means a multi-file change, a debugging session, a corrected
misdiagnosis, a release or build, or a non-obvious gotcha. Conversational and
trivial turns emit nothing.

Write durable learnings as markdown in `.agentlas/pm/learnings/`. This folder is a
shared layer that both the backstop index and the Desktop index embed, so a
learning written here flows back into recall for every host and product starting
the next session.

Each entry carries one learning and states its kind. The Curator classifies with the
same vocabulary, so using it here means nothing has to be guessed later:

`fact` · `decision` · `preference` · `risk` · `procedure` · `hypothesis` ·
`evidence` · `deprecation` · `conflict`

`fact`, `decision`, and `procedure` require evidence: a file and line, a command, or
its output. Without evidence the entry is a `hypothesis` and must say so.

Use `deprecation` when something is retired and `conflict` when a new observation
disagrees with recorded memory - those two carry the correction forward instead of
leaving a wrong entry in place.

## Append rules

- **Append only.** Never rewrite or compact existing entries. Compaction is a
  deliberate act by the owner, not a side effect of writing.
- **One entry per learning.** A session that produced a payment gotcha, a store API
  quirk, and a new bug pattern appends three entries, not one long one.
- **Absolute dates.** Convert every relative date from the conversation to `YYYY-MM-DD`
  before writing it. "Last Tuesday" is unreadable six months later.
- **Record the why, not the what.** "Fixed a null check in foo.ts" teaches nothing.
  "Receipt validation returns 21002 when the sandbox flag flips mid-build, so we branch
  on env in receipt_validator.ts" teaches the mechanism. An entry without a mechanism is
  a log line, not a memory.

## Entry shape

Each entry carries: a dated title, what was being attempted, what happened, the
mechanism that explains why, what to do next time, and a reference - a file and line, a
command, or a commit. Same six every time, so the corpus stays searchable instead of
becoming one shape per author.

When the work crossed folders, keep the situation that created it: the working
directory at the time, the target project and path, and the fact that it was
cross-context. Future agents find memory by the situation as often as by the topic.

## Never emit

Secrets, credentials, tokens, key material, environment values, raw private logs,
or full transcripts. A location or profile name may be recorded; the value never is.

## Conflict and correction

When a new learning contradicts an existing entry, update that entry and say why it
changed. Never silently overwrite. When an earlier entry turns out to be a
misdiagnosis, correct it immediately - a stale wrong entry costs more than a missing
one, because the next session will act on it.

## Handoff to the Curator

Emission is delivery, not judgment. Deciding what becomes durable team or project
memory belongs to the Memory Curator, and routing project writes belongs to PM Soul.
A worker does not write to team or project memory directly, and does not wait for
curation to answer the user - the ticket carries its own acknowledgement.

When the runtime exposes a memory ticket tool, emit through it and let the ledger at
`.agentlas/memory-tickets.jsonl` record the handoff. When it does not, the markdown
entry above is the delivery, and the Curator picks it up from the shared folder.

## Injected directive (verbatim)

This protocol reaches a borrowed agent as a platform-injected directive prepended to
the bundle entry, the same mechanism the binding directive uses. It is injected once
by the runtime rather than authored into each package, so it reaches every agent
without 178 packages having to carry it, and its budget is reserved before the entry
is clamped so platform text never evicts the author's own rules.

The text below is the artifact. A gate byte-compares the injected string against this
block, so the two cannot drift.

```text
## Memory protocol (platform)

Before acting: the injected memory capsule is a starting frame, not proof. Treat
retrieved memories as references, not rules: re-verify against the current context
and make an independent decision. Verify any stale or high-risk fact, and when a
memory names a file, flag, or path, confirm it still exists. What you observe now
outranks what was recorded.

After substantial work - a multi-file change, a debugging session, a corrected
misdiagnosis, a release, or a non-obvious gotcha, but not conversational turns -
record one learning per entry as markdown in `.agentlas/pm/learnings/`. State its kind:
fact, decision, preference, risk, procedure, hypothesis, evidence, deprecation, or
conflict. A fact, decision, or procedure needs evidence - a file and line, a command,
or its output; without evidence, mark it a hypothesis.

Shape every entry the same way so the corpus stays searchable: a dated title
(YYYY-MM-DD, never a relative date), what was attempted, what happened, the mechanism
that explains why, what to do next time, and a reference. Record the why, not the what
- "fixed a null check" teaches nothing; "the sandbox flag flips mid-build, so receipt
validation returns 21002" teaches the mechanism. Append; never rewrite or compact an
existing entry, and write one entry per learning rather than one long one.

Never record secrets, credentials, tokens, environment values, raw logs, or
transcripts. When a finding contradicts an existing entry, record it as a conflict and
correct that entry; never silently overwrite it.

When the learning was made while acting as a hired Hub agent, add `"agent_slug":
"<that agent's slug>"` to the Memory Events candidate so the runtime routes it into
that agent's own experience drawer instead of the host's.
```

## Team Context (editable)

Domain-specific emission rules for this agent go here. They may add to the
protocol above; they may not weaken the Never emit list or the evidence requirement.
