# Agent Workforce Ontology difficult benchmark

`difficult-payment-platform.json` is the shared routing and execution benchmark
for frontier and local-model runs.  It deliberately needs five occupational
families and includes unrelated communities that must not be recalled.

An expected role family may be evidenced by a slot's required or optional
community declarations, or its required or optional skills. Optional expertise
remains a staffing preference rather than a hard eligibility requirement, and
each expected family must still map to a distinct role slot.

The fixture's forbidden communities are hidden negative-recall probes, not an
exhaustive list the host must copy into its WorkOrder. A probed community fails
the benchmark when a role slot positively requests it as required or optional,
or when a returned candidate belongs to it.

The fixture is pinned to Core ontology menu `awo:2026-07-15.2` and raw snapshot
SHA-256 `d6d30d45fe8d35fb785e165d1e80c6471a72436f0160c3933c21d4a31bf2fb32`.
The scorer fails closed when either the fixture or captured work-order and
candidate-set versions drift; it does not reinterpret an older menu.

The host runtime must save one JSON object with these exact keys:

- `workOrder`
- `candidateSet`
- `selection`
- `selectionValidation`
- `selectionReceipt`
- `preparedExecution`
- `toolInventorySnapshot`
- `executionReceipt`

Run the scorer from the Core repository root:

```bash
python3 benchmarks/workforce-ontology/score_run.py /path/to/real-run.json
```

The scorer cannot create a selection or repair model output.  It requires the
three Hub MCP calls in order, two completed host-LLM leader turns, an accepted
frozen selection with no substitutions or history influence, structured
planner output without fallback, a v5 prepared execution context and digest-bound
permission/graph rows, distinct direct or nested worker invocations, completed
synthesis, and a passing verifier. A flat selected-team row without its declared
manager-plan, graph-worker, and manager-synthesis receipts fails.

`toolInventorySnapshot` is the exact local, private
`agentlas.workforce-tool-inventory.v1` artifact observed immediately before the
host-LLM binding decision. The scorer passes it separately as
`tool_inventory=run["toolInventorySnapshot"]`, recomputes its portable digest,
and rejects missing tools, wrong pair/policy/runtime scope, digest drift, or
grants not equal to the selected bindings. It must be retained beside the
benchmark receipt for historical replay and must never be sent to Hub.
