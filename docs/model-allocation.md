# AI-authored model allocation

Agentlas separates workload judgment from runtime enforcement.

1. A parent or leader AI judges each child packet using structured features only: complexity, risk, context size, output size, tools, multimodal input, and fan-out.
2. It emits `agentlas.model-allocation-decision.v1` with a provider-neutral tier (`economy`, `balanced`, or `frontier`), effort, and reason codes.
3. The host resolver checks the actual inventory, explicit user/agent/division/firm pins, context and tool support, and cost ceilings.
4. The host records `agentlas.model-allocation-receipt.v1`. Raw prompts and transcripts are forbidden in this receipt.

Provider-neutral mappings are compatibility classes, not task heuristics:

- Economy: Haiku or Luna
- Balanced: Sonnet or Terra (`tera` is accepted as an input alias)
- Frontier: Opus or Sol

High-risk work does not automatically force Frontier. The receipt instead sets `independentVerificationRequired`; hosts must combine model choice with a separate verifier, narrower permissions, and operator approval for consequential side effects.

If a parent decision is absent or invalid, Core keeps the host's current compatible session and marks the packet `awaiting-parent-ai` / `fallback-current`. It never silently upgrades every worker to a flagship model.

## MCP trust boundary

`model_allocation_decisions` may arrive from the parent/leader AI through the
MCP route request. Cost ceilings and pins may not. The stdio MCP server ignores
any legacy caller-supplied `model_allocation_policy` field.

The operator configures host guardrails when launching the MCP server with
`AGENTLAS_MODEL_ALLOCATION_POLICY_JSON`. Only `pinnedModelId`, `maxTier`,
`maxEffort`, and `requiredCapabilities` are accepted. The current runtime model
is derived by the host execution fabric, not accepted from this environment or
from tool arguments.
