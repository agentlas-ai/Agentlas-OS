---
description: Turn the persistent Agentlas One personal agent on or off, or rename it.
argument-hint: '[on <name> | off | uninstall [--purge] | name <name> | status [--runtimes] | install]'
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

# 인자는 **문자 그대로** 받는다. `"$ONE" $ARGUMENTS` 는 치환된 텍스트가 명령 위치에서
# 다시 해석돼 명령 주입이 된다(따옴표를 어떻게 붙여도 치환이 먼저라 막을 수 없다).
# 인용 구분자 heredoc 은 내용을 리터럴로 붙잡고, 그 뒤 **변수 확장**은 bash 가 재파싱하지
# 않으므로 낱말 나눔만 일어난다 — 두 낱말 이름도 그대로 전달된다.
AGENTLAS_ONE_ARGS="$(cat <<'AGENTLAS_ONE_ARGV_5F3A9C'
$ARGUMENTS
AGENTLAS_ONE_ARGV_5F3A9C
)"
set -f  # 인자 안의 * 가 파일명으로 펼쳐지지 않게
# shellcheck disable=SC2086
"$ONE" $AGENTLAS_ONE_ARGS
one_status=$?
set +f
exit $one_status
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
- `uninstall [--purge]` removes every One footprint (hook entries in Claude/Codex/Cursor/
  Antigravity, marker blocks, status line, state) after writing a timestamped tar.gz backup;
  it is idempotent and prints the restore command. `--purge` also deletes the One workspace.
- `status --runtimes [--json]` prints the per-runtime support matrix (grade, install level,
  present/directive/hook on this machine, ACP transport, access path).
- Never claim an action the script did not perform.
