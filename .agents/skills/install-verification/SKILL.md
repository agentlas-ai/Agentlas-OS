---
name: install-verification
description: "Use when verifying that a generated agent package can be installed, discovered by runtimes, and checked without private dependencies."
---

# Install Verification

Resolve `ENGINE` using `/hep-build` Step 0 and set `PACKAGE_ROOT` to the
generated agent repository. Run:

```bash
bash "$ENGINE/scripts/verify-generated-package.sh" "$PACKAGE_ROOT"
bash "$ENGINE/scripts/verify-team-package.sh" "$PACKAGE_ROOT"
(cd "$PACKAGE_ROOT" && bash "$ENGINE/scripts/public_safety_check.sh")
```

Then inspect the generated package's selected adapters and install files:

- root `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`;
- `.agents/`;
- `.agentlas/`;
- `.claude/`;
- `codex/`;
- `scripts/install.sh`.

Do not claim completion if any required file is missing.
