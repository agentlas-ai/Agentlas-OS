{
  "schemaVersion": "agentlas-capability-eval-plan/1.0",
  "positive_cases": [
    {
      "id": "cap-001",
      "prompt": "{{POSITIVE_PROMPT}}",
      "expected_artifacts": ["{{EXPECTED_ARTIFACT}}"],
      "pass_criteria": ["{{PASS_CRITERION}}"]
    }
  ],
  "negative_cases": [
    {
      "id": "anti-001",
      "prompt": "{{NEGATIVE_PROMPT}}",
      "expected_behavior": "{{EXPECTED_REFUSAL_OR_REROUTE}}"
    }
  ],
  "tool_smoke_checks": [
    {
      "tool_or_plugin": "{{TOOL_OR_PLUGIN}}",
      "check": "{{SMOKE_CHECK}}",
      "fallback": "{{FALLBACK}}"
    }
  ]
}
