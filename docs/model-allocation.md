# AI-authored model allocation

Agentlas separates workload judgment from runtime enforcement.

1. A parent or leader AI judges each child packet using structured features only: complexity, risk, context size, output size, tools, multimodal input, and fan-out.
2. It receives the host's live inventory and emits
   `agentlas.model-allocation-decision.v1` with an exact advertised model ID, a
   provider-neutral cost tier (`economy`, `balanced`, or `frontier`), effort,
   and reason codes.
3. The host resolver checks the actual inventory, explicit user/agent/division/firm pins, context and tool support, and cost ceilings.
4. The host records `agentlas.model-allocation-receipt.v1`. Raw prompts and transcripts are forbidden in this receipt.

Every invocation has one host-owned role:

- `plan`, `route`, `clarify`, `verify`, and `synthesize` are
  `orchestrator`;
- `execute` is `worker`;
- unknown host stages stay on `orchestrator` instead of silently lowering
  quality.

The caller may propose an allocation decision, but it cannot change the
host-owned stage. A decision whose phase differs from the canonical stage
phase records `phase_stage_mismatch` and is not used as a valid tier decision.

Core contains no vendor model-name table and never infers cost or capability
from a model ID. The host supplies those attributes with its live inventory.
When more than one compatible model exists in a requested tier, the parent AI
must return `exactModelId`; Core refuses to choose one by lexical order or a
provider preference. A matching current model or a single unambiguous live
candidate may be preserved without inventing a new model choice.

High-risk work does not automatically force Frontier. The receipt instead sets `independentVerificationRequired`; hosts must combine model choice with a separate verifier, narrower permissions, and operator approval for consequential side effects.

If a parent decision is absent or invalid, Core follows the role policy and
then keeps the host's current compatible session as the final legacy fallback.
A missing worker policy inherits the orchestrator policy for quality. An
orchestrator policy never inherits a worker policy.

The allocation receipt always records `role`. Allocation happens before the
runner call, so `usage` is `null` at this point. A later invocation or run
receipt records observed input/output usage; Core must not write zero tokens as
if they were observed.

## MCP trust boundary

`model_allocation_decisions` may arrive from the parent/leader AI through the
MCP route request. Cost ceilings and pins may not. The stdio MCP server ignores
any legacy caller-supplied `model_allocation_policy` field.

The operator configures host guardrails when launching the MCP server with
`AGENTLAS_MODEL_ALLOCATION_POLICY_JSON`. The preferred form is role scoped:

```json
{
  "orchestrator": {
    "pinnedProvider": "codex",
    "pinnedModelId": "gpt-sol",
    "maxTier": "frontier",
    "maxEffort": "xhigh"
  },
  "worker": {
    "pinnedProvider": "local",
    "pinnedModelId": "luna",
    "maxTier": "economy",
    "maxEffort": "low"
  }
}
```

`worker: {"inherit": true}` explicitly inherits the orchestrator. Omitting the
worker block has the same quality-first behavior. Legacy flat
`pinnedModelId`, `pinnedProvider`, `maxTier`, `maxEffort`, and
`requiredCapabilities` remain the orchestrator-compatible policy.

The names above are illustrative opaque host inventory values, not Core
registrations. The same contract can point to Codex, Claude, Gemini, a BYOK
provider, Ollama, or another local runtime. For example, a host may advertise
`fable` or `opus` for orchestrator and `sonnet` or `haiku` for worker without
adding provider-specific code to Core.

Fresh Codex and Claude Workforce sessions call
`model.resolve_allocation` before each planner/manager, worker, synthesis, and
verifier invocation. The tool accepts a host-owned `stage`, live
`session_inventory`, and an optional parent decision. It does not accept model
pins or cost ceilings in tool arguments; those remain operator environment
policy.

For Codex, put the policy on the MCP server itself:

```toml
[mcp_servers.hephaestus-network.env]
AGENTLAS_MODEL_ALLOCATION_POLICY_JSON = '{"orchestrator":{"pinnedProvider":"codex","pinnedModelId":"gpt-5.6-sol"},"worker":{"pinnedProvider":"codex","pinnedModelId":"gpt-5.3-codex-spark"}}'
```

An outer shell export is not a portable substitute because the host controls
which environment reaches its MCP child. The Agentlas installer preserves the
operator-owned `mcp_servers.hephaestus-network.env` subtable when it refreshes
the canonical command and arguments. A changed policy takes effect in a fresh
host session.
