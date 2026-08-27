---
name: agentlas-build
description: "Use when the user types /agentlas-build, /agentlas build, or /hep-build to design, build, and package a single agent or multi-agent team."
---

# Agentlas Build (/agentlas-build, /hep-build)

Design, assemble, and package installable single agents or multi-agent teams.
Alias for `/agentlas build` and `/hep-build`.

Guides the workflow through:
1. Mode classification (`single-agent-creator`, `team-builder`, `agentlas-packager`, `session-agent-builder`)
2. Interview/research gate
3. Routing card and soul authoring
4. Runtime adapter generation (Codex, Claude, Gemini, Antigravity)
5. Package verification

When the request is `session` in an interactive host, use the current
conversation as the source, ask for an alternate destination only if needed,
and default to the global Agentlas agent home when no alternate folder is
named. JSON/JSONL is only an optional explicit terminal or headless export
route.
