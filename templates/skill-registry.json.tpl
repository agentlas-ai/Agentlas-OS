{
  "schemaVersion": "1.0",
  "kind": "agentlas-skill-lifecycle-registry",
  "state": "export_only",
  "projectId": "{{project_id}}",
  "draftId": "{{draft_id}}",
  "defaultTier": "candidate",
  "runtimeFirstClassRecallEnabled": false,
  "predicatesRequired": true,
  "curatorQuarantineRequired": true,
  "evidenceLedgers": {
    "trials": ".agentlas/skill-trials.jsonl",
    "curatorDecisions": ".agentlas/curator-decisions.jsonl",
    "memoryEvents": ".agentlas/memory-tickets.jsonl"
  },
  "hardStops": [
    "permission_change",
    "credential_change",
    "payment_or_billing_effect",
    "regulated_or_irreversible_side_effect",
    "same_authority_patch_and_validator",
    "holdout_contamination",
    "missing_rollback_snapshot"
  ],
  "effectiveErrorBudgetTerms": [
    "first_class_error_mass",
    "quarantine_false_accept_estimate",
    "blind_spot_estimate",
    "drift_estimate"
  ],
  "niches": [],
  "skills": [],
  "rolloutPolicy": {
    "staticOnlyCanApprove": false,
    "sandboxRequired": true,
    "holdoutRequired": true,
    "shadowRequiredForFastPathChanges": true,
    "lowRiskCanaryOnly": true,
    "severeFailureTolerance": 0
  }
}
