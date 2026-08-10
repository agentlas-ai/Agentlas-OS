---
description: Turn the persistent Agentlas One personal agent on or off, or rename it.
argument-hint: '[on <name> | off | name <name> | status | install]'
allowed-tools: Bash
---

# /agentlas-one

Request: `$ARGUMENTS`

This command controls Agentlas One session persistence. **Execute it without explaining it first.**

## Execution

Find the runner in this order and invoke it directly:

```bash
ONE=""
for c in \
  "$HOME/.agentlas/runtime/current/bin/agentlas-one" \
  "${CLAUDE_PLUGIN_ROOT:+$CLAUDE_PLUGIN_ROOT/bin/agentlas-one}"
do
  if [ -n "$c" ] && [ -x "$c" ]; then ONE="$c"; break; fi
done
[ -n "$ONE" ] || { echo "Could not find the agentlas-one runner"; exit 1; }
"$ONE" $ARGUMENTS
```

Treat an empty argument list as `status`.

## Rules

- Relay the script output verbatim. Do not summarize or embellish it.
- Immediately after `on`, add only: **"This takes effect next session."** The
  current session does not gain the response prefix because directives load at session start.
- `install` configures `statusLine` in `~/.claude/settings.json`. If another
  status line exists, the script refuses to overwrite it. Show the existing command and ask how to proceed.
- `off` removes the state file and the `AGENTLAS-ONE` block from `~/.claude/CLAUDE.md`.
  Backups are created automatically.
- Never claim an action the script did not perform.
