{
  "schemaVersion": "1.0",
  "projectId": "{{PACKAGE_ID}}",
  "purpose": "{{SUMMARY_EN}}",
  "nodes": [
    {
      "id": "task:{{PRIMARY_TASK_ID}}",
      "kind": "task",
      "produces": ["{{PRIMARY_OUTPUT_ARTIFACT}}"],
      "consumes": ["{{PRIMARY_INPUT_ARTIFACT}}"]
    }
  ],
  "edges": [],
  "taskBiases": [],
  "conceptCoverage": {}
}
