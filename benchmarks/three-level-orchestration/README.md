# Three-level orchestration benchmark

This benchmark separates model quality from Agentlas routing and execution.
Both backends receive the same safe dependency-CLI fixture, Work Brief,
Stormbreaker route, packet contract, shell loop, and deterministic verifier.

It records four distinct proof layers:

1. the route receipt and selected Hub/Core stages;
2. the materialized plan/build/verify packet contracts;
3. per-model invocation receipts and packet executor results;
4. the Stormbreaker final gate plus the deterministic CLI verifier.

Run Terra through the local Codex backend:

```bash
python3 benchmarks/three-level-orchestration/run_core_benchmark.py \
  --backend codex \
  --model gpt-5.6-terra \
  --project /private/tmp/agentlas-core-terra \
  --force
```

Run the locally installed Qwen model through Ollama's OpenAI-compatible API:

```bash
python3 benchmarks/three-level-orchestration/run_core_benchmark.py \
  --backend openai \
  --model qwen3:30b-a3b \
  --api-base http://127.0.0.1:11434/v1 \
  --project /private/tmp/agentlas-core-qwen \
  --force
```

No benchmark result is passing merely because Hub routing or an API request
succeeded. The run passes only when every required packet is passing and the
Stormbreaker final gate reports `can_report_success=true`.
