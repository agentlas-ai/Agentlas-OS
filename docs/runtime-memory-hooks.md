# Runtime memory hooks

`bin/agentlas-memory-hook` is the portable, fail-open bridge from raw host
conversation events to the local Ontology Runtime. It does not add another
memory authority. It recalls from the current project's
`.agentlas/ontology-runtime.sqlite` and, only for an exact validated agent
slug, its rebuildable `hub-agents/<slug>/memory/experience.sqlite` projection.

## Host contract matrix

| Host | Event path | Context delivery | Current limit |
|---|---|---|---|
| Claude Code | plugin `SessionStart`, `UserPromptSubmit` | `hookSpecificOutput.additionalContext` | Requires a plugin build that supports command hooks. |
| Codex | mirrored plugin hooks | same additional-context JSON contract | The plugin root environment variable remains `CLAUDE_PLUGIN_ROOT`; custom prompts are unrelated. |
| Antigravity | global named `PreInvocation` hook | `injectSteps[].ephemeralMessage` | The documented payload does not guarantee current user-prompt text. When absent, recall uses a fixed project-state query rather than reading the transcript. |
| OpenCode | global local plugin `chat.message` | `experimental.chat.system.transform` | The system-transform and compaction APIs are experimental and must be rechecked on host upgrades. |
| Grok | global passive `SessionStart`, `UserPromptSubmit` hooks | workspace cache plus managed `~/.grok/AGENTS.md` pointer | Grok explicitly ignores passive-hook stdout. This is a refreshed local capsule and static read pointer, not direct dynamic injection. |

## Retrieval boundary

The hook:

1. resolves the current working directory from documented event fields;
2. walks only its ancestors for an Agentlas project marker: a project ontology
   database or a routing card with an exact verified agent projection; it exits
   successfully when neither recall source exists;
3. extracts only a direct current-prompt field and never opens a transcript;
4. calls `OntologyRuntime.query(..., record_memory=False)` with
   `public`/`internal` project scopes;
5. accepts private experience only when `.agentlas/routing-card.json` is
   `routing_ready` or `trusted`, the SHA-256 for its in-project
   `agent_card_ref` verifies, both cards name the same normalized slug, that
   slug maps to the exact per-agent database directory, and query isolation
   matches `hub:<slug>`;
6. redacts common credentials, bounds every snippet and the final capsule, and
   renders recalled text as evidence that cannot override host or project
   policy.

Host-native instruction sources (`AGENT.md`, `AGENTS.md`, `CLAUDE.md`,
`CLAUDE.local.md`, and `GEMINI.md`) are excluded by source basename even if the
ontology indexed them. The host loads the live files through its native policy
path; the memory capsule does not create a stale duplicate.

There are no network imports, server embedding calls, runtime model downloads,
or Memory Curator writes in this path. Vector selection stays with the
canonical local runtime. A verified bundled Model2Vec asset is used when
available; the hashing fallback is explicit as `retrieval=degraded_hash`.

## Deduplication and compaction

The capsule body is deterministic and carries a content digest. Hosts should
treat equal digests as one active context item. Point-of-need hosts inject the
current capsule every turn, so compaction cannot permanently discard it.
OpenCode also adds the active capsule to its compaction context. Grok's cache
index lists exact workspace paths and instructs the model to ignore all
non-matching entries, preventing one concurrent workspace from becoming
another workspace's memory.

## Installer ownership

The installer writes only Agentlas-owned surfaces or a named/marked entry:

- `~/.gemini/config/hooks.json`: merge the `agentlas-memory` named hook;
- `~/.grok/hooks/agentlas-memory.json`: replace only that file;
- `~/.grok/AGENTS.md`: replace only the managed Agentlas memory marker block;
- `~/.config/opencode/plugins/agentlas-memory.js`: replace only that plugin.

All other hooks, named configurations, rules, and plugins remain untouched.
