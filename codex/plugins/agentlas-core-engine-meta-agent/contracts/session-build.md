# Session Build Contract

`hep-build session` is a source-controlled build submode. It accepts only an
explicit JSON or JSONL export and turns it into a bounded, reviewable candidate
for the existing Agentlas package builder.

## Pipeline

```text
explicit source
  -> session-source.v1 (sanitized evidence)
  -> session merge (dedupe + unresolved conflicts)
  -> work-brief/1.0 (owner review)
  -> session-ir.v1 (declarative candidate graph)
  -> session-agent-draft.v1
  -> candidate skill / private Experience candidate
  -> contract scaffold -> complete -> verify
```

The `session` prefix is a submode of `/hep-build`; it is not a new package
mode and it does not alter Agentlas One persistence. `single` remains the
default. `team` is explicit and creates the existing orchestrator/worker shape.

## Source boundary

The source file is read locally and hashed. The derived source contains only
bounded user/assistant text after deterministic redaction, coarse tool
capabilities, error types, event references, and security findings. It never
contains a raw transcript, hidden prompt, tool argument/result, credential,
host path, URL, binary, screenshot, or audio payload. Prompt-injection-like
events are retained only as untrusted metadata and cannot become rules.

Malformed, binary, non-UTF-8, oversized, symlinked, empty, or unsupported input
fails closed. A source is never selected from “recent” or “current” session
state by inference.

## Review and promotion

Preview and merge do not write a package. Compile requires an owner-approved
Work Brief or `--approve` for the current source digest set. A changed source
set invalidates an older report. Conflicting constraints stay visible and
require explicit acknowledgement; they are never resolved by recency, a vote,
or a model confidence score.

Skills are written as `SKILL.md` candidates with `tier: candidate` and
first-class recall disabled. Experience output is a private candidate item.
Neither is promoted automatically. Promotion requires replayable passed trials,
uncontaminated holdouts, an independent validator, a rollback snapshot, low
risk, and explicit owner approval; a passing request remains
`promotion_pending` for curator action.

Package materialization is staged into one exact empty target. Existing package
folders are never overwritten. The target is moved into place only after the
existing Agentlas contract verifier passes. Permissions, MCP activation,
publication, Cloud/Hub upload, and canonical AO materialization are outside this
command.
