# Runtime Sync Boundaries

This document explains what belongs in this public core repo, what belongs only
in hosted web products, and what belongs only in local desktop or terminal
runtimes.

The public core repo is meant for people who download an open-source Agentlas
meta-agent team and use it anywhere: Codex-compatible apps, Claude-compatible
apps, Gemini-style CLIs, Hermes-style local runtimes, OpenClo or Antigravity
style tools, Cursor-like editors, and any runtime that can read `AGENTS.md`.

## Public Core

Public core owns the portable contract:

- the three modes: `single-agent-creator`, `team-builder`,
  `agentlas-packager`;
- visible package foldering;
- `.agentlas` contracts;
- Memory Tickets, PM Soul, Memory Curator, sitemap/task-bias, policy, eval, QA,
  and runtime adapter rules;
- skill lifecycle registry, trial evidence, and Curator promotion decision
  contracts;
- public-safe schemas, templates, docs, skills, and verification scripts.

Public core should be runnable as a Markdown-first agent team. It should not
require Agentlas Web accounts, Agentlas Desktop storage, or private deployment
state.

## Shared Contracts

These concepts may appear in public core, hosted web, and local runtimes. The
public core contract is the public version they should all mirror:

| Contract | Public core | Hosted web | Desktop/terminal |
|---|---|---|---|
| Mode names | canonical | mirrors | mirrors |
| Mode auto-detection | public rule | may implement in code | may implement in code |
| Clarify question loop | public rule | may store sessions and meter usage | may run locally |
| Generated folder layout | canonical | emits ZIPs | installs or imports |
| `.agentlas` memory files | canonical | emits in exports | creates/maintains locally |
| `.agentlas` skill lifecycle files | canonical export contract | emits candidate registry and empty ledgers | may merge locally as candidate metadata |
| PM Soul / Memory Curator | generated role contract | may package into exports | may ship built-in agents |
| Sitemap/task-bias | generated contract | may package into exports | may maintain local project state |
| Runtime adapters | public adapters | emitted in ZIPs | used to invoke local runners |
| Verification | public scripts | may run before export/publish | may run before local install |

## Web-Only Implementation

Hosted web products may own implementation details that should not be copied into
this public repo:

- account, workspace, invite, and session logic;
- billing, subscriptions, credits, top-up wallets, and spend limits;
- hosted model provider keys and provider-cost telemetry;
- rate limits and abuse controls;
- database storage for drafts, profiles, jobs, scans, governance approvals, and
  usage events;
- private OAuth flows, encrypted token storage, and compliance exports;
- public marketplace approval workflow;
- server routes that turn prompts into saved drafts or ZIP downloads.

Public core can document compatible contracts, but it must not include hosted
SaaS billing, customer data, production credentials, private deployment config,
or account-state implementation.

## Desktop And Terminal-Only Implementation

Local desktop and terminal runtimes may own local execution details that should
not be copied into this public repo as product code:

- local SQLite or app database schema;
- keychain, vault, cookie, or local session storage;
- runtime detection for Claude, Codex, Gemini, BYOK, Ollama, or other local
  runners;
- Electron IPC, windows, menus, updater, renderer state, and app registry;
- local App Factory and Tool Factory implementation;
- filesystem materialization of installed agents;
- automation scheduler and local surface registry.

Public core can define public activation and package contracts. Local runtimes
choose how to store and execute them.

## Public Sync Additions

The following formerly runtime-owned behaviors are now public contracts:

1. Mode auto-detection: see `docs/mode-classifier.md` and
   `skills/mode-classification/SKILL.md`.
2. Clarify question loop: see `docs/clarify-question-loop.md` and
   `skills/clarify-question-loop/SKILL.md`.
3. `.agentlas` auto-activation: see `docs/agentlas-auto-activation.md` and
   `skills/agentlas-auto-activation/SKILL.md`.
4. Skill lifecycle promotion metadata: see
   `docs/skill-lifecycle-promotion.md` and
   `skills/skill-lifecycle-promotion/SKILL.md`.

These are contract-level syncs. They do not move hosted billing, account state,
private storage, or local Electron implementation into public core.

## Rule Of Thumb

If the behavior helps any runtime create better Agentlas packages, put the
contract here. If the behavior depends on one company's accounts, payments,
server state, key storage, app windows, or local database, keep only a public
interface here and leave the implementation in that runtime.
