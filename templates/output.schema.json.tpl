{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://agentlas.ai/schemas/{{PACKAGE_ID}}/output.schema.json",
  "title": "{{NAME}} Output",
  "description": "Output contract: what the requester ends up holding. A compiler reads only this file's TOPOLOGY - arity and value spaces - to derive routing facts, so nothing downstream depends on the words chosen here.",
  "type": "object",
  "additionalProperties": false,
  "required": ["status", "findings"],
  "properties": {
    "status": {
      "type": "string",
      "enum": ["ok", "needs_review", "blocked", "other"]
    },
    "findings": {
      "type": "array",
      "description": "One record per thing the method judged.",
      "items": {
        "type": "object",
        "required": ["subject", "verdict"],
        "properties": {
          "subject": { "type": "string" },
          "verdict": {
            "type": "string",
            "enum": ["{{OUTPUT_VERDICT_1}}", "{{OUTPUT_VERDICT_2}}", "other"]
          },
          "evidence": { "type": "string" }
        }
      }
    }
  }
}
