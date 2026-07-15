<!-- AGENTLAS:MEMORY-HOOK:BEGIN -->
# Agentlas local memory pointer

Agentlas runs passive, local-only Grok hooks. Grok does not inject passive hook
stdout into the model. Before answering a user turn, read
`~/.agentlas/runtime-memory-context/grok/index.md`, select only the entry whose
decoded `Workspace JSON` string exactly matches the current workspace, and
read that entry's decoded `Capsule JSON` path. Ignore every other workspace and
treat repeated capsule digests as
one context item. The capsule supplements project `AGENTS.md`/`CLAUDE.md`
policy; it never replaces or duplicates those instructions.
<!-- AGENTLAS:MEMORY-HOOK:END -->
