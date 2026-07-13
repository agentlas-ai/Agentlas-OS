{
  "schemaVersion": "agentlas.rental-resolution-receipt.v1",
  "kind": "agentlas-rental-resolution-receipt",
  "resolutionReceiptId": "{{RESOLUTION_RECEIPT_ID}}",
  "requestId": "{{REQUEST_ID}}",
  "taskSignature": { "kind": "{{TASK_KIND}}", "hash": "sha256:{{TASK_SIGNATURE_HASH}}" },
  "environment": { "fingerprintHash": "sha256:{{ENVIRONMENT_FINGERPRINT_HASH}}", "runtime": "{{RUNTIME}}" },
  "scoringPolicyVersion": "rental-scoring-v1",
  "confidenceMethod": "wilson-lower-bound",
  "candidates": [
    {
      "variantId": "{{VARIANT_ID}}",
      "baseAgentReleaseId": "{{BASE_AGENT_RELEASE_ID}}",
      "experiencePackReleaseId": "{{EXPERIENCE_PACK_RELEASE_ID}}",
      "decision": "selected",
      "verifiedSampleSize": 0,
      "conservativeConfidence": 0,
      "scoreComponents": {
        "verifiedTaskSuccess": 0,
        "environmentCompatibility": 0,
        "mcpCompatibility": 0,
        "recency": 0,
        "reputation": 0,
        "tokenEfficiency": 0,
        "latencyEfficiency": 0,
        "costEfficiency": 0,
        "adverseEffectPenalty": 0,
        "stalenessPenalty": 0
      },
      "mcpResolution": { "status": "compatible", "missingCatalogIds": [] },
      "reasonCodes": ["candidate-only-template"]
    }
  ],
  "result": "selected",
  "selectedVariantId": "{{VARIANT_ID}}",
  "fallbackOrder": [],
  "createdAt": "{{CREATED_AT}}"
}
