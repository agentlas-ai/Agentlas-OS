{
  "schemaVersion": "agentlas.pairwise-preference-receipt.v1",
  "kind": "agentlas-pairwise-preference-receipt",
  "receiptId": "{{PAIRWISE_RECEIPT_ID}}",
  "idempotencyKey": "{{IDEMPOTENCY_KEY}}",
  "receiptHash": "sha256:{{PAIRWISE_RECEIPT_HASH}}",
  "tasteStyleReleaseId": "{{TASTE_STYLE_RELEASE_ID}}",
  "baseAgentReleaseId": "{{BASE_AGENT_RELEASE_ID}}",
  "taskSignature": {
    "kind": "agentlas.task.v1/design",
    "hash": "sha256:{{TASK_FINGERPRINT_HASH}}",
    "locale": "{{LOCALE}}"
  },
  "pair": {
    "leftPreviewAssetRef": "{{LEFT_PREVIEW_ASSET_ID}}",
    "rightPreviewAssetRef": "{{RIGHT_PREVIEW_ASSET_ID}}",
    "orderRandomized": true
  },
  "rater": {
    "antiSybilPrincipalHash": "sha256:{{ANTI_SYBIL_PRINCIPAL_HASH}}",
    "source": "human",
    "consent": "explicit"
  },
  "choice": "{{LEFT_RIGHT_TIE_OR_SKIP}}",
  "contextTags": [],
  "privacy": {
    "rawRaterIdentityIncluded": false,
    "rawLocalPathsIncluded": false,
    "rawOutputsIncluded": false,
    "credentialValuesIncluded": false,
    "privateAssetBytesIncluded": false
  },
  "createdAt": "{{CREATED_AT}}",
  "signature": null
}
