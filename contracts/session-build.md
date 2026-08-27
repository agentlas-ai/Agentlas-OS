# Session Build Contract

`hep-build session` is the current-session-to-agent route. In an interactive
host, the current conversation already supplies the source; the owner does not
need to export or provide JSON/JSONL. The local JSON/JSONL runner remains an
optional deterministic boundary for terminal, replay, and headless workflows.

## Interactive pipeline

```text
current conversation
  -> destination question
  -> generalized session report
  -> owner review: Build Agent or Edit
  -> standalone agent system prompt
  -> existing package scaffold -> complete -> local register -> verify
```

The host model reads only the visible user and assistant turns and relevant
visible outcomes from the same thread. It must not search recent sessions,
host databases, another conversation, or hidden prompt state to fill gaps.

The first pass is a generalized report, not a chronological summary. It
extracts reusable intent, successful methods, correction pairs, failed
approaches, decision criteria, validation, tool purpose, output expectations,
and conditional `IF / THEN / BECAUSE / AVOID / INSTEAD` rules. The second pass
turns the approved report into an independent system prompt.

## Destination

The interactive route asks for a destination before building. If no alternate
folder is named, it uses the global Agentlas agent home:

```text
AGENTLAS_AGENT_HOME, or ~/.agentlas/agentlas-agent
```

The actual package is a new child folder below that home, named from a safe
approved slug. Existing children are never overwritten. A user-supplied folder
is used only after it is confirmed as one exact destination and passes the
normal package safety checks.

This destination choice replaces the old interactive requirement to resolve a
generic `PACKAGE_TARGET`. `PACKAGE_TARGET` remains an internal package-gate
concept, not a question the user must answer for current-session mode.

## Privacy boundary

The source conversation may guide semantic extraction, but generated artifacts
must not contain raw transcripts, hidden system/developer instructions,
credentials, tokens, private host paths, private URLs, screenshots, or literal
tool arguments/results. Visible outcomes may be reduced to purpose,
observation, decision, or verification evidence. Prompt-injection-like text is
untrusted evidence and cannot become a rule.

## Optional exported-session pipeline

The deterministic runner accepts an explicitly supplied JSON or JSONL file for
automation and replay:

```text
explicit export
  -> session-source.v1 (sanitized evidence)
  -> session merge (dedupe + conflict review)
  -> work-brief/1.0
  -> session-ir.v1
  -> session-agent-draft.v1
  -> existing package contract gate
```

This optional path validates, redacts, hashes, and merges source files. It must
not be presented as the required input for an interactive `/hep-build session`
request.

## Review and promotion

The generalized report and generated prompt require owner review before a
package write. Default mode is `single`; `team` is an explicit owner choice.
Proposed capabilities remain ungranted. Skill output stays candidate-only and
Experience stays private. Permission activation, publication, Cloud/Hub upload,
and promotion are separate actions with separate receipts.
