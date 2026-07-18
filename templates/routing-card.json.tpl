{
  "schemaVersion": "1.0",
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
    { "locale": "en", "text": "{{ANTI_TRIGGER_EN_1}}" },
    { "locale": "en", "text": "{{ANTI_TRIGGER_EN_2}}" }
  ],
  "required_inputs": [],
  "optional_inputs": [],
  "required_plugins": [],
  "supported_runtimes": ["claude-code", "codex", "gemini-cli", "ollama"],
  "entrypoints": {
    "canonical_command": "/{{COMMAND_SLUG}}",
    "agent": "agent.md"
  },
  "risk_profile": {
    "tier": "{{RISK_TIER}}",
    "notes": "{{RISK_NOTES}}"
  },
  "memory_behavior": "{{MEMORY_BEHAVIOR}}",
  "benchmark_fixtures": null,
  "locale_coverage": ["ko", "en"],
  "routing_status": "draft",
  "agent_card_ref": ".agentlas/agent-card.json"
}
