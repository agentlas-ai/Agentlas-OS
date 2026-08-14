{
  "schemaVersion": "1.0",
  "kind": "agentlas-super-ontology-task-coverage",
  "state": "export_only",
  "taskFamilies": [
    "retrieve_answer",
    "summarize_synthesize",
    "draft_artifact",
    "transform_format",
    "analyze_decide",
    "plan_sequence",
    "coordinate_social",
    "execute_tool",
    "monitor_repair",
    "personalize_memory",
    "regulated_boundary",
    "multimodal_generate",
    "physical_or_sensor",
    "software_change",
    "financial_or_compliance",
    "education_or_coaching"
  ],
  "affordanceTypes": ["read", "draft", "write", "publish", "execute", "physical", "train"],
  "evidenceModes": [
    "citation",
    "current_approved_source",
    "owner_authority",
    "policy_or_law",
    "measurement_or_dataset",
    "license_or_consent",
    "runtime_test",
    "rollback_plan"
  ],
  "defaultDecision": "classify_before_action",
  "runtimePromotionAllowed": false,
  "hardStops": [
    "missing_task_family",
    "missing_affordance_type",
    "missing_evidence_mode",
    "write_without_rollback",
    "publish_execute_physical_or_train_without_authority"
  ]
}
