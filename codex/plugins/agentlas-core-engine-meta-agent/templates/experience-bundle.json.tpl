{
  "schemaVersion": "agentlas.experience-bundle.v1",
  "kind": "agentlas-experience-bundle",
  "bundleId": "exb_{{48_HEX_DERIVED_FROM_BUNDLE_HASH}}",
  "bundleHash": "sha256:{{64_HEX_CANONICAL_BUNDLE_HASH}}",
  "requestedVisibility": "private",
  "pack": {{CANONICAL_EXPERIENCE_PACK_OBJECT}},
  "items": [{{CANONICAL_EXPERIENCE_ITEM_OBJECTS}}],
  "sourceAttestations": [
    {
      "kind": "user-attested",
      "experienceItemId": "{{EXPERIENCE_ITEM_ID}}",
      "evidenceHash": "sha256:{{64_HEX_LOCAL_EVIDENCE_HASH}}"
    }
  ],
  "privacy": {
    "basePackageMaterialIncluded": false,
    "rawPromptIncluded": false,
    "rawTranscriptIncluded": false,
    "rawLocalPathsIncluded": false,
    "credentialValuesIncluded": false
  }
}
