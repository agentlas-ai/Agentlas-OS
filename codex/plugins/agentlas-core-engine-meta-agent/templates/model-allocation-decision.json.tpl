{
  "schemaVersion": "agentlas.model-allocation-decision.v1",
  "decisionId": "decision:model-allocation:example",
  "packetId": "pipeline:example:2:build",
  "agentId": "agent:example",
  "phase": "execute",
  "authoredBy": "parent-ai",
  "selectorVersion": "agentlas-parent-selector.v1",
  "inputFeatureHash": null,
  "features": {
    "complexity": "moderate",
    "risk": "moderate",
    "inputTokens": 12000,
    "expectedOutputTokens": 4000,
    "toolRequired": true,
    "multimodalRequired": false,
    "parallelFanout": 3
  },
  "selection": {
    "tier": "balanced",
    "modelClass": "terra",
    "effort": "high",
    "exactModelId": null,
    "provider": null,
    "fallbackTiers": ["economy"],
    "maxEscalations": 1
  },
  "reasonCodes": ["multi-file-execution", "tool-use-required"]
}
