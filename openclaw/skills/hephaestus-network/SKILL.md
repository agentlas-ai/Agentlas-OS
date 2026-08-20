---
name: hephaestus-network
description: "Use when the user asks OpenClaw to staff a durable goal from registered Local, owner Cloud, and public Hub agents or teams. The active host LLM chooses the exact roster, which remains goal-bound until explicit completion."
metadata: {"openclaw": {"emoji": "🔨", "requires": {"bins": ["python3"]}, "homepage": "https://github.com/agentlas-ai/Agentlas-OS"}}
---

# Hephaestus Agent Workforce Network

The active host LLM staffs the task. Agentlas Core federates content menus from
registered Local, owner Cloud, and public Hub inventory. No source and no
deterministic layer is the decision-maker or a server-side LLM executor.

Source scopes are exact:

- `network`: Local + Cloud + Hub;
- `local`: registered Local packages only;
- `cloud`: the signed-in owner's Cloud packages only;
- `hub`: public Hub packages only.

Public demos and distribution proof use explicit `hub` scope. They must not use
private Local/Cloud inventory as evidence of public availability.

## Resolve the runner and sign in

Network can query owner Cloud and public Hub inventory, so establish the same
saved Agentlas session before staffing:

```bash
RUNNER=""
for c in \
  "$HOME/.agentlas/runtime/current/bin/hephaestus" \
  ./bin/hephaestus
do [ -x "$c" ] && RUNNER="$c" && break; done
if [ -z "$RUNNER" ]; then
  for cache in \
    "$HOME/.claude/plugins/cache/agentlas-core-engine/hephaestus" \
    "$HOME/.codex/plugins/cache/agentlas-core-engine/hephaestus"; do
    newest="$(ls -d "$cache"/*/bin/hephaestus 2>/dev/null | sort -V | tail -1)"
    [ -n "$newest" ] && [ -x "$newest" ] && RUNNER="$newest" && break
  done
fi
if [ -n "$RUNNER" ] && [ "${HEPHAESTUS_AUTH_AUTOPOPUP:-1}" != "0" ]; then
  "$RUNNER" auth ensure --timeout 180 >/dev/null 2>&1 || true
fi
```

The browser opens only when no reusable local sign-in exists. In CI or another
headless environment, set `HEPHAESTUS_AUTH_AUTOPOPUP=0`.

## Required MCP sequence

First confirm the typed tool menu contains `workforce.preflight_work_order` and
that its `_meta.protocolVersion` is at least `2026-08-20.1`. If the tool is
absent, the host is still attached to a preflight-less runtime. Do not fall back
to model-authoring the strict wire WorkOrder and do not retry the same invalid
call. Return the machine-readable boundary
`workforce_protocol_upgrade_required`; let the runtime's normal verified
auto-update finish, then reload the host/MCP session. An explicit
`hephaestus hep-update` remains an operator action, never an implicit skill
side effect.

Use the Agentlas Core Workforce contracts in this order:

```text
workforce.preflight_work_order(taskBrief=..., roles=..., edges=...)
workforce.search_candidates(workOrderRef=..., sourceScope="network")
workforce.expand_candidates(selectionSessionId=..., candidates=[{slotId, candidateOrdinal}])
workforce.validate_selection(decision={selectionSessionId, decisionAuthor, assignments})
workforce.prepare_execution(selection=..., federatedSelectionDigest=..., projectDir=..., goalId=activeGoalId?, fullDossier=false)
workforce.validate_execution_receipt(receipt=..., executionPlan=..., toolInventory=...)
```

Call these exact typed tools directly. Do not enumerate, serialize, print, or
search the host's complete `ALL_TOOLS` registry: the sequence and tool names are
already specified here, and dumping unrelated schemas spends context without
improving staffing.

The source-internal `workforce.fetch_runtime_bundle` call is performed by Core
from the pinned original source session/digest. The host must not call it
directly or replace it with a slug/`latest` lookup.

The default search response is a projected decision menu. Preserve its source
receipts and `selectionSessionId`, but do not echo that projection as
`federationResult`; Core resolves and revalidates the full pinned result by
session. The final receipt call is local, bounded, and read-only. It validates
host-produced evidence and never executes workers or creates a receipt.

The current CLI equivalent is `workforce search --scope network`. A host adapter
that does not yet expose typed `sourceScope` must report that wiring gap; it
must not silently call public Hub-only search and label it Network. Do not call
the legacy lexical router first. Do not turn install count, ratings, invocation
history, source precedence, or a deterministic top score into the staffing
decision. If a source is unavailable, preserve its finite failure receipt.

## 1. Perform job analysis

Act as the active top-level orchestrator. Convert the user's task into one
compact semantic draft for `workforce.preflight_work_order`. Core compiles it
into the exact redacted `agentlas.workforce-work-order.v1`, generates finite
WorkOrder/slot/artifact identifiers, fills omitted empty arrays, pins the
ontology version, validates the privacy boundary, and returns a one-hour
`workOrderRef`. Keep raw local files, secrets, memory, and private prompt details
on the host. Create one `roles` entry per materially distinct responsibility.
Each role may identify:

- role/community and required skill or knowledge concepts, written as plain
  English phrases when no ontology id is obvious — Core normalizes them into
  schema-valid concept ids and reports every rewrite as `normalizedConcepts`;
- required MCP/tool capabilities;
- collaboration edges by 1-based role ordinal. An edge is a declaration of
  handoff, never a qualification requirement: only what you actually write as a
  required skill/role/tool filters candidates. Requiring an artifact almost no
  published agent declares does not narrow a menu, it empties it;
- runtime, language, modality, and entity-kind constraints;
- required and forbidden authority;
- cardinality, criticality, and collaboration edges;
- the minimum evidence level: declared, checked, demonstrated, or attested.

Do not create decorative roles. A single specialist is valid for a genuinely
single-role task; a composite task should become a real temporary task force.
Executable slots allow only `agent` or `team`; `group` is discovery-only until
an authoritative group execution contract exists.

Omit unconstrained runtime, authority, language, and modality arrays. Never
invent prefixed finite values such as `language:ko` or custom slot/artifact IDs;
the draft schema exposes the finite values and Core owns mechanical IDs. Use the
default candidate policy (2 minimum, 8 maximum per role) unless the task has a
concrete recall reason to widen it. Protocol receipt verification is already an
independent gate, so do not add a decorative verifier role merely to restate it.

The user never has to write the word `goal` or enable a goal mode. Before a new
search, call `workforce.goal_context` for the current project. If an active
binding is the same ongoing work, treat its `goalId` and roster as incumbent.
Only create a new WorkOrder when no active binding covers the work or the
incumbent has a real gap.

## 2. Retrieve the menu, then make the LLM decision

Before calling any remote source, call `workforce.preflight_work_order`. Its
deterministic compiler and WorkOrder boundary cover every schema-declared string
and structured identifier, including nested roles, skills, tools, authorities,
artifacts, edges, runtime/language, and policy fields—not only prose fields. A
path, personal/account identifier,
credential URL, private concept identifier, or secret-like value returns only
path/class repair evidence with `hubCalls=0` and a null rejected-object digest;
never trust a draft's prose, echo the rejected value, or compute/display a
digest over rejected data. Ask Core for `sourceScope="network"` with the returned
`workOrderRef` only after that boundary accepts. Do not echo the compiled
WorkOrder. Each source returns a bounded shortlist by default; narrow it, then
use `workforce.expand_candidates` only for the candidates worth a full-card
comparison. Each source's complete menu remains pinned in Core;
Core validates and unions them using canonical identity ordering. It performs
no semantic rerank. Read the exact roles,
skills, MCP tools, inputs/outputs, authority, eval evidence, communities,
release version, package hash, content digest, source receipt, and provenance.

Source precedence is not ranking. It applies only when the same
`agentDefinitionId` has verified identical lineage issuer/digest and the exact
same release version, package hash, content digest, and entity kind at multiple
sources. Then and only then shadow Local > Cloud > Hub. Similar names/slugs are
never deduplicated. Missing lineage or different releases fail closed for that
collided identity: Core quarantines the ambiguous definition and preserves
unrelated Local/Cloud/Hub candidates with finite aggregate conflict evidence.

You, the active host LLM, choose the ideal roster. Consider complementary
coverage and handoffs, not a scalar top-1 score. Return
`agentlas.workforce-selection.v1` with `decisionAuthor.kind = "host_llm"`, the
real host model id, exact slot/release assignments, graph edges, alternatives,
and short reason codes. Some nondeterminism in final judgment is intentional;
hard constraints are not.

If a required slot has inadequate coverage, use at most two same-host semantic
WorkOrder refinements across the whole decision. A provisional Selection may
request content expansion through `requestExpansionForSlots`; the adapter gives
the host only aggregate slot/count/gap data, never candidate identities. Never
fill a post with a semantically unrelated agent or repeat an exhausted request.

## 3. Validate and pin exact releases

Send the compact `decision` — `selectionSessionId`, `decisionAuthor`, and one
`assignments` row per post naming the candidate by its menu `candidateOrdinal`
with reason codes. Core resolves the pinned WorkOrder, federated CandidateSet
and federation receipt from that session, fills the candidate-set digest and the
arrays that are empty in a normal decision, and compiles the exact
`agentlas.workforce-selection.v1`. Re-plan on rejection. The validator may
reject constraints, cardinality, cycles, drift, out-of-menu releases, or a
source-pin mismatch; it must never pick for you.

An accepted receipt can still carry `unmetRequirementCount`. That is not a
rejection and Core will not choose for you, but it is not noise either: read
`selectionValidation.unmetRequirements`, then either accept the gap on purpose
or pick a different candidate. Never report an accepted validation as if
nothing were unmet.

Do not send the merged CandidateSet to remote Hub/Cloud validation or
preparation: it is not one of their source sessions. Core pins every assignment
to the original source's selection session and candidate-set digest, then
fetches the exact release/package/content claims from that source. Call Core
federated preparation only after acceptance. Preparation must
return `agentlas.workforce-execution-plan.v5`, status `prepared`, an exact
`preparationReceiptId`, and an `executionRoster` whose release version,
package hash, and content digest match the candidate set. It returns BYOM
`directiveBundle` records. Every row must declare
`bundleDigestSchema=agentlas.workforce-runtime-bundle-digest.v4`; recompute its
canonical digest before execution and fail closed on mismatch. Digest values
allow only Unicode-scalar strings, booleans, null, arrays, and ASCII-keyed
objects; numbers, invalid keys, and `__proto__`/`prototype`/`constructor` fail
closed. A row must also carry a nonblank top-level `systemPrompt`,
`instructions`, or `agentMd`, a first-class digest-bound `permissionPolicy`,
and an agent-null/team-authoritative `executionGraph`. Missing permission
declarations become an explicit deny-all policy, never inherited host access;
incomplete claimed allowlists fail. The plan's digest-bound `executionContext`
must preserve every validated slot demand, WorkOrder/Selection edge and
artifact kind, assignment and reason code. Missing or
changed releases create unfilled posts; there is no silent substitution.

## 4. Bind the roster to the durable goal

Exact preparation must include `projectDir` and the incumbent `goalId` when one
exists. Core rejects a preparation without a project and automatically binds
every successful exact plan before it can be executed. On first contact, when
the host has no durable Task/conversation id, Core derives a content-free
stable id from the already-required WorkOrder id. Therefore “the user did not
explicitly say goal” is never a valid reason to omit continuity. Later
accepted preparations with the incumbent `goalId` append only newly recruited
exact releases. Never replace or silently remove an incumbent release.

At the start of every later turn, read `workforce.goal_context` (the installed
SessionStart/UserPromptSubmit hooks also project the same bounded context).
Pass `knownRevisions` with the `goalId -> rosterRevision` pairs already in this
conversation: unchanged goals come back as one line instead of a full roster,
which is what makes a continuity read cheap enough to actually do every turn.
Read `pendingExecution` in that response — those releases were prepared and
never executed, and the session-end checkpoint reports the same fact to the
user, so it cannot be quietly carried forward.
The active host LLM must choose exactly one turn posture:

- `reuse`: the bound roster plus local skills can handle this turn;
- `local-only`: no bound worker invocation is useful for this turn;
- `recruit`: a real role/tool/modality gap requires another Network cycle,
  followed by another additive `workforce.bind_goal`;
- `standby`: no worker needs to execute, but the roster remains bound;
- `blocked`: the goal cannot progress safely.

Record that content-free decision with `workforce.record_goal_turn`. A turn
ending, session closing, runtime restarting, context compaction, worker
invocation completing, or a 24-hour Hub lease expiring must not release the
roster. The Hub/Web account authority alone decides whether the next actual
remote preparation is covered by an existing same-account lease or creates a
new charge. Never manufacture lease state locally.

`standby` means a durable roster binding available to later turns. It does not
mean a continuously running model, process, socket, or background token burn.
Only actual worker invocations accumulate their normal Memory Curator and
Experience records.

Call `workforce.complete_goal` only after the user or authoritative host goal
state explicitly marks the whole goal completed or cancelled. It requires
`explicitCompletion=true`; lease expiry and successful completion of one model
turn are invalid completion signals.

## 5. Resolve the model for every invocation

Before every bound planner/manager, worker, synthesis, and verifier invocation,
advertise the current host's real available sessions and call
`model.resolve_allocation`. The host owns the invocation stage:

- `planner`, `manager-plan`, and `nested-manager` resolve as `orchestrator`;
- `worker`, `execute`, `delegate`, and `task` resolve as `worker`;
- `manager-synthesis` and `synthesis` resolve as `orchestrator`;
- `verifier` resolves as `orchestrator`.

Model pins and ceilings come only from the MCP server's operator policy in
`AGENTLAS_MODEL_ALLOCATION_POLICY_JSON`; a task, Hub bundle, or tool argument
must not override them. Prefer role-scoped `orchestrator` and `worker` policy
objects. A missing worker policy inherits the orchestrator for quality;
orchestrator never falls through to a cheaper worker policy.

Use the allocation receipt's exact provider, model, session, and effort for the
invocation. The pre-invocation receipt has `usage: null`; record observed usage
only in the later invocation/run receipt. A resolved allocation proves policy
selection, not that a worker model ran. If the host cannot launch the selected
provider/model as a distinct invocation, stop at allocation-only evidence and
report that boundary.

## 6. Execute the real task force

Run the prepared roster through the current host runtime:

1. planner/manager creates structured worker assignments;
2. each selected worker runs in a distinct model invocation with its exact
   release directive and only the needed local grounding;
3. workers emit explicit handoff artifacts;
4. synthesis runs after dependencies complete;
5. an independent verifier checks the requested result.

When a prepared release is itself a Team, honor its authoritative
manager/worker/synthesis graph; do not flatten it into one prompt. Follow the
row policy intersected with the host policy for all side effects. Unsupported
enforcement blocks execution. `zero-tools` requires an actually empty tool
inventory; a residual primitive isolated by forced read-only/no-filesystem is
`no-authority-sandbox`, not zero-tools.

Snapshot the just-in-time policy-filtered local tool menu as a private
`agentlas.workforce-tool-inventory.v1` artifact and give only that menu to the
executor planner. Never send the snapshot to Hub. The host LLM, not Hub or a
lexical rule, records the pair-scoped `capabilityBindingPlan`; its context,
tool-inventory, and planner-bound digests must validate before execution. Every
required tool capability maps to an exact snapshot entry and permitted tool.
A package policy mentioning a tool is not inventory proof, and a required
binding cannot run under no-authority enforcement.

If the host cannot create distinct child invocations, stop at `prepared` and
say so. A route id, bundle id, process exit code, or prose that imitates several
roles is not execution proof.

Preparation is not delivery. A turn that pinned a roster and produced no worker
output has not answered the user's request, and the session-end checkpoint says
so in the user's own view. Either run the roster and record the turn with
`workforce.record_goal_turn`, or tell the user plainly that the team is prepared
but not executed and what remains.

## 7. Truthful receipts

For an executed task force, retain one joined
`agentlas.workforce-execution-receipt.v2` joined to the exact v5 plan containing:

- selection and preparation receipt ids;
- orchestrator and planner model/invocation ids;
- `planner.parseSuccess`, `planner.fallbackUsed`, `toolInventoryDigest`, and
  `capabilityBindingPlanDigest`;
- every roster row's exact release/package/content/bundle/policy/graph digests,
  capability bindings, and handoff artifact refs;
- either one real direct invocation or a nested receipt proving manager-plan
  parse/no-fallback, exact declared workers in graph order, and
  manager-synthesis; never fabricate one aggregate team invocation;
- every actual model/provider/runtime, requested/applied effort with evidence,
  globally unique invocation id, and permission-enforcement evidence whose
  exact granted tool ids and inventory digest match the binding plan;
- synthesis and verifier invocation ids and verifier verdict.

Never report success when planner JSON fell back, child receipts are missing,
or verification did not pass. In the user-facing summary, name the actual
workers and distinguish `selected`, `prepared`, and `executed`.
