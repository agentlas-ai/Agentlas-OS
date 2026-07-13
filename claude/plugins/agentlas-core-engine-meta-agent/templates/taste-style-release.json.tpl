{
  "schemaVersion": "agentlas.taste-style-release.v1",
  "kind": "agentlas-taste-style-release",
  "tasteStyleId": "{{TASTE_STYLE_ID}}",
  "releaseId": "{{TASTE_STYLE_RELEASE_ID}}",
  "ownerRef": "{{TASTE_STYLE_OWNER_REF}}",
  "version": "{{TASTE_STYLE_VERSION}}",
  "title": "{{TASTE_STYLE_TITLE}}",
  "summary": "{{TASTE_STYLE_SUMMARY}}",
  "baseCompatibility": {
    "agentDefinitionId": "{{AGENT_DEFINITION_ID}}",
    "compatibleBaseReleaseIds": ["{{BASE_AGENT_RELEASE_ID}}"]
  },
  "taskSignatures": ["agentlas.task.v1/design"],
  "preferenceAxes": ["composition"],
  "rules": [
    {
      "ruleId": "{{TASTE_STYLE_RULE_ID}}",
      "axis": "composition",
      "polarity": "prefer",
      "statement": "{{GENERALIZED_PREFERENCE_RULE}}",
      "contexts": ["context:presentation"],
      "confidence": 0.5
    }
  ],
  "pairwiseEvidenceReceiptIds": [],
  "previewAssetRefs": [],
  "audienceTags": [],
  "aggregate": {
    "sampleCount": 0,
    "distinctRaterCount": 0,
    "ruleAlignedCount": 0,
    "alternativeCount": 0,
    "tieCount": 0,
    "skipCount": 0,
    "disagreement": 1.0
  },
  "privacy": {
    "rawRaterIdentityIncluded": false,
    "rawLocalPathsIncluded": false,
    "rawOutputsIncluded": false,
    "credentialValuesIncluded": false,
    "privateAssetBytesIncluded": false
  },
  "contentHash": "sha256:{{TASTE_STYLE_CONTENT_HASH}}",
  "visibility": "private",
  "status": "draft",
  "createdAt": "{{CREATED_AT}}",
  "releasedAt": null,
  "withdrawnAt": null
}
