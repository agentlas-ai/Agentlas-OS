# AI-authored model allocation

Agentlas separates workload judgment from runtime enforcement.

1. A parent or leader AI judges each child packet using structured features only: complexity, risk, context size, output size, tools, multimodal input, and fan-out.
2. It receives the host's live inventory and emits
   `agentlas.model-allocation-decision.v1` with an exact advertised model ID, a
   provider-neutral cost tier (`economy`, `balanced`, or `frontier`), effort,
   and reason codes.
3. The host resolver checks the actual inventory, explicit user/agent/division/firm pins, context and tool support, and cost ceilings.
4. The host records `agentlas.model-allocation-receipt.v1`. Raw prompts and transcripts are forbidden in this receipt.

Core contains no vendor model-name table and never infers cost or capability
from a model ID. The host supplies those attributes with its live inventory.
When more than one compatible model exists in a requested tier, the parent AI
must return `exactModelId`; Core refuses to choose one by lexical order or a
provider preference. A matching current model or a single unambiguous live
candidate may be preserved without inventing a new model choice.

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
