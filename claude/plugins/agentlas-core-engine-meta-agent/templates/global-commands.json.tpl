{
  "schemaVersion": "1.0",
  "packageId": "{{PACKAGE_ID}}",
  "canonicalCommand": "/{{COMMAND_SLUG}}",
  "commands": [
    {
      "runtime": "claude-code",
      "command": "/{{COMMAND_SLUG}}",
      "adapterPath": ".claude/commands/{{COMMAND_SLUG}}.md",
      "globalInstallPath": "~/.claude/commands/{{COMMAND_SLUG}}.md",
      "scope": "global",
      "status": "native-slash-command"
    },
    {
      "runtime": "codex",
      "command": "/{{COMMAND_SLUG}}",
      "adapterPath": "codex/plugins/{{PACKAGE_ID}}/commands/{{COMMAND_SLUG}}.md",
      "globalInstallPath": "Codex plugin install for {{PACKAGE_ID}}",
      "scope": "plugin",
      "status": "plugin-slash-command"
    },
    {
      "runtime": "gemini-cli",
      "command": "/{{COMMAND_SLUG}}",
      "adapterPath": "gemini/extension/commands/{{COMMAND_SLUG}}.toml",
      "globalInstallPath": "gemini extensions install <repo-or-path>",
      "scope": "global",
      "status": "extension-custom-command",
      "notes": "Fallback user command can also be installed at ~/.gemini/commands/{{COMMAND_SLUG}}.toml."
    },
    {
      "runtime": "antigravity",
      "command": "/{{COMMAND_SLUG}}",
      "adapterPath": "antigravity/workflows/{{COMMAND_SLUG}}.md",
      "globalInstallPath": "~/.gemini/antigravity/global_workflows/{{COMMAND_SLUG}}.md",
      "scope": "global",
      "status": "workflow-slash-command",
      "notes": "Project-scope fallback ships at .agents/workflows/{{COMMAND_SLUG}}.md. Antigravity also auto-loads AGENTS.md and .agents/skills/."
    },
    {
      "runtime": "generic-agents-md",
      "command": "/{{COMMAND_SLUG}}",
      "adapterPath": "AGENTS.md",
      "scope": "project",
      "status": "adapter-command-alias"
    },
    {
      "runtime": "agentlas-terminal",
      "command": "{{COMMAND_SLUG}}",
      "adapterPath": "bin/{{COMMAND_SLUG}}",
      "globalInstallPath": "agentlas run {{COMMAND_SLUG}}",
      "scope": "terminal",
      "status": "shell-command"
    }
  ],
  "postCreationUserMessage": {
    "required": true,
    "template": "global_commands: Claude Code /{{COMMAND_SLUG}}; Codex /{{COMMAND_SLUG}}; Gemini CLI /{{COMMAND_SLUG}}; Antigravity /{{COMMAND_SLUG}}; Agentlas terminal {{COMMAND_SLUG}} or agentlas run {{COMMAND_SLUG}}"
  }
}
