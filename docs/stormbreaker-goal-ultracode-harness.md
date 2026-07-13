# Stormbreaker Goal + UltraCode Harness

Agentlas Core owns one portable execution harness for Stormbreaker. Desktop,
Terminal, Codex, Claude Code, Gemini, Cursor, OpenCode, OpenClaw, Hermes, and
future hosts consume this contract; they do not maintain local variants of Goal
mode or UltraCode mode.

## Source of truth

- Python contract: `agentlas_cloud/networking/stormbreaker_harness.py`
- JSON schema: `schemas/stormbreaker-goal-ultracode-harness.schema.json`
- Runtime delivery: `execution_harness` at the top level of every `hep-storm`
  result and at `execution_fabric.execution_harness` for pipeline routes
- Packet delivery: the complete contract in every `packet.json`, plus the
  compact identity and prompt digest in each work packet
- External executors: `STORMBREAKER_HARNESS_ID`,
  `STORMBREAKER_HARNESS_MODE`, `STORMBREAKER_HARNESS_PROMPT_SHA256`, and
  `STORMBREAKER_HARNESS_SYSTEM_PROMPT`

The `system_prompt` and its SHA-256 digest define identity. A host must apply
that prompt verbatim before planning or executing packets. Runtime adapters may
describe how to invoke tools or advertise sessions, but must not rewrite the
Goal mode or UltraCode mode instructions.

## Host-neutral behavior

The harness always enforces the same scope lock, acceptance checks, visible goal
ledger, dependency-aware packet execution, verification, bounded repair,
durable resume, and final completion gate. Host-specific differences are inputs,
not protocol forks:

- The host advertises its live runtimes and models with `--session-inventory` or
  `AGENTLAS_SESSION_INVENTORY`.
- When no inventory is available, Core emits the explicit `host:primary`
  fallback instead of inventing a model or session.
- The parent or leader AI chooses the smallest sufficient compatible runtime,
  exact model, and effort; deterministic Core code validates that decision.
- The host's own permission model governs consequential external actions.

## Completion boundary

Routing, scheduling, packet materialization, or a zero exit status without an
acceptance check is not completion. Success may be reported only when every
required packet is passing and `final_gate.can_report_success` is true.
