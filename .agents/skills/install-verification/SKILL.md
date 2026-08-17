---
name: install-verification
description: "Use when verifying that a generated agent package can be installed, discovered by runtimes, and checked without private dependencies."
---

# Install Verification

Run:

```bash
scripts/verify-package.sh
scripts/public_safety_check.sh
```

Then inspect:

- root `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`;
- `.agents/`;
- `.agentlas/`;
- `.claude/`;
- `codex/`;
- `scripts/install.sh`.

Do not claim completion if any required file is missing.
