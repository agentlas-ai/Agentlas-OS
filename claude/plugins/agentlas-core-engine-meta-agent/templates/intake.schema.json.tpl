{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "https://agentlas.ai/schemas/{{PACKAGE_ID}}/intake.schema.json",
  "title": "{{NAME}} Intake",
  "description": "Input contract: what a requester must hand over before this method can start. Direction is carried by the filename, because a schema whose direction has to be guessed cannot be matched against a request.",
  "type": "object",
  "additionalProperties": false,
  "required": ["objective"],
  "properties": {
    "objective": {
      "type": "string",
      "description": "{{INTAKE_OBJECTIVE_QUESTION}}"
    },
    "subject": {
      "type": "string",
      "description": "{{INTAKE_SUBJECT_QUESTION}}"
    },
    "scope": {
      "type": "string",
      "enum": ["{{INTAKE_SCOPE_1}}", "{{INTAKE_SCOPE_2}}", "other"],
      "description": "Every enum reachable from matching ends in \"other\". A closed list is how one stated requirement took a three-candidate inventory to zero on eight probes out of eight."
    }
  }
}
