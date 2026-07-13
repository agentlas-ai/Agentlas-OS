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
  "allowRead": ["README.md", "AGENTS.md", "agent.md", "skills/**", ".agentlas/*.json"],
  "denyRead": [".env", ".env.*", "**/secrets/**", "**/credentials/**", "**/cookies/**", "**/*token*", "**/*secret*"],
  "publicExportPolicy": "clean-copy",
  "requiredRuntime": ["mcp-client"],
  "license": "call-only-default",
  "createdBy": "hephaestus-setup-wizard",
  "packageHashVersion": "agentlas-package-hash/v2",
  "assetContract": {
    "kind": "agent-definition",
    "schemaVersion": "agentlas.agent-definition.v1",
    "materialization": "hub-or-cloud-registration",
    "releaseAuthority": "registry"
  },
  "mcpPolicy": {
    "ref": ".agentlas/mcp-policy.json",
    "resolution": "system-global-first"
  }
}
