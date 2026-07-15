# Agent Workforce Ontology difficult benchmark

`difficult-payment-platform.json` is the shared routing and execution benchmark
for frontier and local-model runs.  It deliberately needs five occupational
families and includes unrelated communities that must not be recalled.

The host runtime must save one JSON object with these exact keys:

- `workOrder`
- `candidateSet`
- `selection`
- `selectionValidation`
- `selectionReceipt`
- `executionReceipt`

Run the scorer from the Core repository root:

```bash
python3 benchmarks/workforce-ontology/score_run.py /path/to/real-run.json
```

The scorer cannot create a selection or repair model output.  It requires the
three Hub MCP calls in order, two completed host-LLM leader turns, an accepted
frozen selection with no substitutions or history influence, structured
planner output without fallback, distinct nested worker invocations, completed
synthesis, and a passing verifier.
