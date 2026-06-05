{
  "schemaVersion": "1.0",
  "kind": "agentlas-super-ontology-contract",
  "state": "export_only",
  "projectId": "{{projectId}}",
  "draftId": null,
  "runtimeGraphWriteEnabled": false,
  "zeroErrorClaim": false,
  "layers": [
    "source_intake",
    "evidence_packet",
    "belief_ledger",
    "knowledge_capsule",
    "affordance_action_binding",
    "agentlas_integration_contract",
    "promotion_readiness",
    "promotion_replay_drill",
    "architecture_sync_review"
  ],
  "evidenceLedgers": {
    "replays": ".agentlas/super-ontology-replays.jsonl",
    "promotionEvidence": ".agentlas/super-ontology-evidence.jsonl",
    "memoryTickets": ".agentlas/memory-tickets.jsonl"
  },
  "hardStops": [
    "zero_error_claim",
    "raw_source_to_graph_write",
    "forbidden_context_join",
    "whole_graph_exposure",
    "tool_authority_without_provenance",
    "appbridge_source_of_truth_write",
    "missing_rollback",
    "missing_shadow_or_canary_evidence"
  ],
  "promotionPolicy": {
    "shadowRequired": true,
    "canaryRequiredForMixedContext": true,
    "rollbackRequired": true,
    "syncReviewRequired": true,
    "appbridgeSourceWritesBlocked": true
  },
  "surfacePolicy": {
    "publicResearchRepo": {
      "defaultDecision": "candidate_only",
      "notes": "Research artifacts may be validated and inspected."
    },
    "publicCore": {
      "defaultDecision": "sync_review_required",
      "notes": "Only public-safe contracts may be mirrored."
    },
    "webRuntime": {
      "defaultDecision": "shadow_required",
      "notes": "Hosted ZIP/export behavior needs shadow replay before promotion."
    },
    "desktopTerminal": {
      "defaultDecision": "shadow_required",
      "notes": "Local seed/runtime behavior needs permission audit and replay."
    },
    "appbridge": {
      "defaultDecision": "blocked",
      "notes": "AppBridge remains a route adapter, never the source of truth."
    }
  }
}
