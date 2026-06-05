{
  "schemaVersion": "1.0",
  "kind": "agentlas-auto-activation",
  "state": "seed",
  "activationPolicy": {
    "explicitActivation": true,
    "repeatedUseThreshold": 2,
    "mergeOnly": true,
    "neverOverwriteWithoutApproval": true
  },
  "seedFiles": [
    ".agentlas/project-soul-memory.md",
    ".agentlas/sitemap.json",
    ".agentlas/memory-map.json",
    ".agentlas/memory-tickets.jsonl",
    ".agentlas/vault-references.json",
    ".agentlas/skill-registry.json",
    ".agentlas/skill-trials.jsonl",
    ".agentlas/curator-decisions.jsonl",
    ".agentlas/super-ontology-contract.json",
    ".agentlas/super-ontology-task-coverage.json",
    ".agentlas/super-ontology-causal-impact.json",
    ".agentlas/super-ontology-assurance-case.json",
    ".agentlas/super-ontology-replays.jsonl",
    ".agentlas/super-ontology-evidence.jsonl",
    ".agentlas/super-ontology-memory-bridge.jsonl"
  ],
  "safety": {
    "noSecrets": true,
    "noRawLogs": true,
    "noFullTranscripts": true,
    "vaultReferencesOnly": true
  }
}
