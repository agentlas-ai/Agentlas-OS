{
  "schemaVersion": "1.0",
  "kind": "agentlas-super-ontology-contextual-flow",
  "state": "export_only",
  "runtimePromotionAllowed": false,
  "defaultDecision": "contextual_flow_required_before_boundary_crossing",
  "flowStages": [
    "user_to_agent",
    "agent_to_tool",
    "tool_to_agent",
    "agent_to_agent",
    "agent_to_memory",
    "agent_to_output",
    "agent_to_public_surface"
  ],
  "contexts": [
    "personal",
    "company",
    "customer",
    "public",
    "regulated",
    "agent_internal"
  ],
  "requiredParameters": [
    "source_context",
    "target_context",
    "sender_role",
    "recipient_role",
    "subject_role",
    "attribute_type",
    "transmission_principle",
    "purpose",
    "authority_basis",
    "sensitivity",
    "retention_policy",
    "audit_refs"
  ],
  "decisions": [
    "allow",
    "redact",
    "aggregate_only",
    "review_required",
    "block"
  ],
  "researchBasis": [
    "contextual_integrity",
    "privacy_flow_graph",
    "multi_agent_contextual_privacy",
    "compositional_privacy",
    "information_flow_control",
    "nist_ai_rmf_gai_profile",
    "w3c_prov",
    "stpa_mode_confusion"
  ],
  "hardStops": [
    "same_user_means_all_contexts_joinable",
    "tool_response_as_need_to_know",
    "public_output_after_private_handoff",
    "raw_prompt_or_transcript_to_memory",
    "customer_data_to_public_surface_without_consent",
    "regulated_data_to_training_without_consent_delete_path",
    "agent_internal_trace_to_user_output",
    "cross_project_join_without_scope_review"
  ]
}
