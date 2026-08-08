{
  "schemaVersion": "1.2",
  "projectId": "{{project_id}}",
  "sources": [],
  "canonicalMemoryRoots": {
    "project": [
      ".agentlas/project-soul-memory.md"
    ],
    "agent_repo": [
      "memory.md"
    ],
    "team_memory": [],
    "session": [
      ".agentlas/memory-tickets.jsonl"
    ],
    "curator_decisions": [
      ".agentlas/curator-decisions.jsonl"
    ],
    "sitemap": [
      ".agentlas/sitemap.json",
      ".agentlas/validation-ledger.jsonl"
    ],
    "code_map": [
      ".agentlas/code-map/project-map.json"
    ],
    "context_map": [
      ".agentlas/context-map.json"
    ],
    "recall_index": [
      ".agentlas/ontology-runtime.sqlite"
    ],
    "experience": [
      ".agentlas/experience-relations.jsonl"
    ]
  },
  "writeOwners": {
    "project": "pm-soul",
    "agent_repo": "memory-curator",
    "team_memory": "orchestrator",
    "session": "memory-curator",
    "curator_decisions": "memory-curator",
    "sitemap": "project bootstrap",
    "code_map": "project bootstrap",
    "context_map": "context map authoring (derived)",
    "recall_index": "ontology runtime",
    "experience": "experience intake"
  },
  "promotionPath": [
    "session ticket",
    "curator decision",
    "durable memory entry",
    "experience candidate",
    "experience pack"
  ],
  "trustLabels": [
    "verified",
    "memory_derived",
    "inferred",
    "stale_check_needed"
  ],
  "runtimeOwned": [
    "code_map",
    "context_map",
    "recall_index",
    "experience"
  ]
}
