{
  "schemaVersion": "1.0",
  "name": "{{PACKAGE_NAME}}",
  "packageHash": "sha256:{{PACKAGE_HASH}}",
  "runtimeBundleVersion": "1.0",
  "entry": "AGENTS.md",
  "skills": [],
  "toolPermissions": {
    "network": "ask",
    "shell": "deny",
    "fileRead": "manifest-allowlist"
  },
  "memoryPolicy": {
    "writeBack": "ask",
    "publicCopy": "reset"
  },
  "memory": [".agentlas/memory-map.json", ".agentlas/agent-card.json"],
  "allowRead": ["README.md", "AGENTS.md", "agent.md", "skills/**", "agents/**", ".agents/**", "docs/**", "benchmarks/**", "contracts/**", ".agentlas/*.json", ".agentlas/*.jsonl", "provenance.json", "A2A/**", "tools/**", "permissions/**", "hooks/**", "evals/**", "experience/**", "knowledge/**", "schemas/**", "sandbox/**", "examples/**"],
  "denyRead": [".env", ".env.*", "secrets/**", "**/secrets/**", "credentials/**", "**/credentials/**", "cookies/**", "**/cookies/**"],
  "publicExportPolicy": "clean-copy",
  "requiredRuntime": ["mcp-client"],
  "license": "call-only-default",
  "createdBy": "hephaestus-setup-wizard"
}
