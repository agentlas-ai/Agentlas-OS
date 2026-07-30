{
  "schemaVersion": "routing-card/2.0",
  "id": "local/{{PACKAGE_ID}}",
  "type": "{{ENTITY_TYPE}}",
  "name": "{{NAME_KO}}",
  "name_ko": "{{NAME_KO}}",
  "summary": "{{SUMMARY_EN}}",
  "summary_ko": "{{SUMMARY_KO}}",
  "capabilities": [
    "{{CAPABILITY_VERB_OBJECT_1}}",
    "{{CAPABILITY_VERB_OBJECT_2}}"
  ],
  "domains": [],
  "trigger_examples": [
    { "locale": "ko", "text": "{{TRIGGER_KO_1}}" },
    { "locale": "ko", "text": "{{TRIGGER_KO_2}}" },
    { "locale": "ko", "text": "{{TRIGGER_KO_3}}" },
    { "locale": "en", "text": "{{TRIGGER_EN_1}}" },
    { "locale": "en", "text": "{{TRIGGER_EN_2}}" },
    { "locale": "en", "text": "{{TRIGGER_EN_3}}" }
  ],
  "anti_triggers": [
    { "locale": "ko", "text": "{{ANTI_TRIGGER_KO_1}}" },
    { "locale": "ko", "text": "{{ANTI_TRIGGER_KO_2}}" },
    { "locale": "en", "text": "{{ANTI_TRIGGER_EN_1}}" },
    { "locale": "en", "text": "{{ANTI_TRIGGER_EN_2}}" }
  ],
  "required_inputs": [],
  "optional_inputs": [],
  "required_plugins": [],
  "entrypoints": {
    "canonical_command": "/{{COMMAND_SLUG}}",
    "agent": "agent.md"
  },
  "risk_profile": {
    "tier": "{{RISK_TIER}}",
    "notes": "{{RISK_NOTES}}"
  },
  "memory_behavior": {
    "reads": "project",
    "writes": "project",
    "exports_to_cloud": false
  },
  "workforce": {
    "communities": ["{{COMMUNITY_ID_1}}"],
    "roles": ["{{ROLE_ID_1}}"],
    "skills": ["{{SKILL_ID_1}}", "{{SKILL_ID_2}}"],
    "knowledge": ["{{KNOWLEDGE_ID_1}}"],
    "languages": ["ko", "en"],
    "modalities": ["text"]
  },
  "benchmark_fixtures": ".agentlas/routing-benchmarks.jsonl",
  "locale_coverage": {
    "primary": "ko",
    "ready": ["ko", "en"],
    "partial": []
  },
  "routing_status": "draft",
  "agent_card_ref": {
    "path": ".agentlas/agent-card.json",
    "slug": "{{COMMAND_SLUG}}",
    "content_hash": null
  }
}
