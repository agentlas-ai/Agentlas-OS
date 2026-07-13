{
  "schemaVersion": "1.0",
  "kind": "agentlas-super-ontology-invariant-verification",
  "state": "export_only",
  "runtimePromotionAllowed": false,
  "defaultDecision": "runtime_monitor_required_before_graph_memory_tool_route_release_or_public_write",
  "eventStreams": [
    "source_intake",
    "evidence_packet",
    "belief_update",
    "semantic_alignment",
    "resilience_mode",
    "memory_ticket",
    "graph_write",
    "tool_call",
    "public_export",
    "route_sync",
    "release_seed",
    "rollback",
    "emergency_stop"
  ],
  "invariantTypes": [
    "safety",
    "liveness",
    "ordering",
    "separation",
    "cardinality",
    "idempotency",
    "provenance",
    "authority",
    "consent",
    "rollback",
    "audit",
    "determinism"
  ],
  "temporalOperators": [
    "always",
    "never",
    "eventually",
    "until",
    "before",
    "after",
    "within",
    "once"
  ],
  "monitors": [
    "json_schema",
    "event_sequence",
    "state_machine",
    "temporal_logic",
    "property_test",
    "shadow_replay",
    "model_check",
    "sync_check",
    "curator_ticket_audit",
    "human_owner_review"
  ],
  "violationActions": [
    "block",
    "reject",
    "quarantine",
    "rollback",
    "emergency_stop",
    "ask_clarify",
    "review_required",
    "shadow_only"
  ],
  "researchBasis": [
    "runtime_verification",
    "temporal_logic",
    "model_checking",
    "contract_based_design",
    "assume_guarantee_contracts",
    "finite_state_monitor",
    "agent_runtime_monitoring",
    "formal_methods_for_planning",
    "formal_skill_verification",
    "multi_agent_safety_invariants",
    "memory_safety_invariants",
    "audit_log_invariants"
  ],
  "hardStops": [
    "memory_write_without_ticket_invariant",
    "graph_write_without_evidence_invariant",
    "tool_action_without_authority_invariant",
    "public_export_without_flow_invariant",
    "route_sync_without_source_contract_invariant",
    "rollback_not_observed_after_violation",
    "emergency_stop_transition_bypassed",
    "unordered_multi_agent_write",
    "non_idempotent_replay_mutation"
  ]
}

