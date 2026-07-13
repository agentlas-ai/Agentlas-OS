{
  "schemaVersion": "agentlas.run-receipt.v1",
  "kind": "agentlas-run-receipt",
  "receiptId": "{{RUN_RECEIPT_ID}}",
  "idempotencyKey": "{{IDEMPOTENCY_KEY}}",
  "receiptHash": "sha256:{{RECEIPT_HASH}}",
  "runId": "{{RUN_ID}}",
  "agentDefinitionReleaseId": "{{BASE_AGENT_RELEASE_ID}}",
  "experiencePackReleaseId": null,
  "variantId": null,
  "taskSignature": {
    "kind": "{{TASK_KIND}}",
    "hash": "sha256:{{TASK_SIGNATURE_HASH}}",
    "locale": "{{LOCALE}}"
  },
  "environment": {
    "runtime": "{{RUNTIME}}",
    "os": "{{OS}}",
    "arch": "{{ARCH}}",
    "fingerprintHash": "sha256:{{ENVIRONMENT_FINGERPRINT_HASH}}"
  },
  "resources": {
    "mcp": [],
    "skills": [],
    "model": { "provider": "{{MODEL_PROVIDER}}", "modelId": "{{MODEL_ID}}" }
  },
  "outcome": { "status": "failed", "failureCode": null },
  "verification": {
    "verdict": "unverified",
    "method": "none",
    "verifierRef": null,
    "evidenceRefs": []
  },
  "metricsEligible": false,
  "metrics": {
    "promptTokens": 0,
    "completionTokens": 0,
    "totalTokens": 0,
    "durationMs": 0,
    "retryCount": 0
  },
  "sideEffects": { "occurred": false, "adverse": false, "evidenceRefs": [] },
  "privacy": {
    "rawPromptIncluded": false,
    "rawTranscriptIncluded": false,
    "rawLocalPathsIncluded": false,
    "credentialValuesIncluded": false
  },
  "createdAt": "{{CREATED_AT}}",
  "signature": null
}
