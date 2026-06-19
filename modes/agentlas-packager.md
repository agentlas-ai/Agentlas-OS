# Agentlas Packager

## Purpose

Convert or repair existing agents and teams into Agentlas architecture. Inputs
may come from local prompts, Claude folders, Codex skills, Gemini skills,
Cursor rules, another public repo, a ZIP, or an ad hoc Markdown structure.

## Required Structure

- `AGENTS.md` as canonical core.
- Runtime adapters only as thin mappings.
- `docs/builder-interview.md` when source behavior or target use is unclear.
- `docs/research-sources.md` for public, marketplace, or domain-expert output.
- `docs/tool-selection.md` for selected/rejected tools, plugins, permissions,
  secrets, fallbacks, and smoke tests.
- `docs/domain-expert-synthesis.md` when behavior changes or the package
  claims domain expertise, combining source behavior, interview gaps,
  similar agent research, repository research, academic or professional theory,
  and tool choices.
- `docs/prompt-performance-contract.md` preserving source behavior and adding
  explicit input/output/tool/memory/eval rules.
- `.agentlas/capability-eval-plan.json` for behavior-changing repairs or
  marketplace/public-ready output.
- `.agentlas/agent-card.json`.
- `.agentlas/company-blueprint.json`.
- `.agentlas/mode-map.json`.
- `.agentlas/memory-map.json`.
- `.agentlas/memory-tickets.jsonl`.
- `.agentlas/vault-references.json`.
- `.agentlas/global-commands.json`.
- `manifest.json`.
- `scripts/verify-package.sh`.
- `scripts/public_safety_check.sh` for public release.

## Packaging Decisions

1. Decide whether the source is a single-agent package or team package.
2. Preserve useful source behavior.
3. Run `docs/builder-interview-research-gate.md` if the source does not
   already prove target users, tasks, tools/plugins, output artifacts, and
   evaluation quality.
4. Add missing Agentlas contracts.
5. Preserve or derive a canonical global command and add runtime command files.
6. Remove private or unsafe material before public release.
7. Add Codex plugin, Claude adapter, Gemini adapter, Antigravity workflow, and
   terminal install surfaces when requested.

## Do Not

- Do not claim runtime parity when an adapter only maps the canonical core.
- Do not copy local-only research notes into public output.
- Do not store secret values or raw logs.
- Do not wrap a shallow prompt into a polished package without asking missing
  interview questions and adding domain-expert-synthesis, prompt-performance,
  and capability-eval pressure.
- Do not finish without reporting `global_commands` to the user.
