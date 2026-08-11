# Experience

Sealed-chip storage only. This folder is the Hub upload staging area for
Secret-Free DTO experience chips (ontology chips, playbooks) — never raw
memory.

Rules, non-negotiable (Agentlas 2.5, `experience_contracts.py` /
`experience_privacy.py`):

- No host-absolute paths (`/Users/<name>/...`, `C:\Users\<name>\...`).
- No secrets — `api_key|secret|token|password|cookie`-shaped values are
  rejected, not masked.
- No PII — `scan_public_field` runs on every candidate before it can leave
  this folder.
- Raw memory (`.agentlas/memory-tickets.jsonl`, curator decisions, the
  project soul log) belongs in `.agentlas/`, never here — this folder is a
  publish staging area, not a memory store.

Chips are written here by the experience pipeline at runtime, not by the
builder that scaffolded this package. An empty `experience/` is the normal
starting state.
