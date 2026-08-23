#!/usr/bin/env bash
# One 이 호스트에 남기는 것들이 정직하고 유한한가 — PRD §4.15 §4.17 §4.18 §4.19 §4.21 §4.22.
#
# 여기 모인 여섯은 성격이 같다: **조용히 틀리거나 조용히 쌓였다.**
#   §4.15 꺼져 있는데 상태 파일은 켜짐이라 기억 훅이 계속 주입했다
#   §4.17 서랍 쓰기 관문이 도구 이름에 걸려 셸로 우회됐고, 오류면 열린 채 통과했고, codex 엔 없었다
#   §4.18 슬래시 명령 인자가 그대로 셸에 들어갔고(주입), 두 낱말 이름은 잘렸다
#   §4.19 시작 시각을 못 구하면 "배운 게 있다"가 항상 참이 돼 macOS 밖에서는 신호가 죽었다
#   §4.21 설정 백업이 무한히 쌓였다(실측 ~/.gemini 400개)
#   §4.22 런타임 홈 버전이 무한히 쌓였다(실측 124개 9.1GB)
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { echo "verify-one-host-hygiene: $*" >&2; exit 1; }
has() { grep -q "$1" "$root/$2" || fail "$3"; }
hasnt() { grep -q "$1" "$root/$2" && fail "$3"; return 0; }

# ── §4.15 상태 저장은 실제 상태를 쓴다 ─────────────────────────────────────
has 'ONE_ON="\${2:-}"' bin/agentlas-one "state_write must accept the real on/off state instead of always writing on"
hasnt '"on": True,' bin/agentlas-one "the unconditional on:true state write must not come back"
has 'state_write "\$name" true' bin/agentlas-one "turning One on must record on=true explicitly"
grep -A2 'cmd_name() {' "$root/bin/agentlas-one" >/dev/null || fail "cmd_name is missing"
# 이름 변경은 켜기가 아니다 — cmd_name 은 상태 인자를 넘기지 않아야 한다.
awk '/^cmd_name\(\) \{/,/^\}/' "$root/bin/agentlas-one" | grep -q 'state_write "\$name"$' \
  || fail "renaming One must preserve its current on/off state"

# ── §4.18 인자는 리터럴로 받는다 ───────────────────────────────────────────
for command_file in "claude/plugins/agentlas-core-engine-meta-agent/commands/agentlas-one.md" ".claude/commands/agentlas-one.md"; do
  grep -q 'AGENTLAS_ONE_ARGV_' "$root/$command_file" \
    || fail "$command_file must capture \$ARGUMENTS literally (a quoted heredoc), not paste it into a command position"
  grep -qE '^"\$ONE" \$ARGUMENTS$' "$root/$command_file" \
    && fail "$command_file still pastes \$ARGUMENTS straight into the command position (shell injection)"
done
awk '/^  name\)/{print}' "$root/bin/agentlas-one" | grep -q 'cmd_name "\$\*"' \
  || fail "a two-word name must reach cmd_name whole"

# ── §4.17 서랍 관문: 행동으로 걸고, 실패는 닫고, 모든 호스트에 ─────────────
guard="$root/bin/agentlas-one-drawer-guard"
[[ -x "$guard" ]] || fail "the One drawer guard must exist and be executable"
grep -q 'shell_writes_into' "$guard" || fail "the guard must judge shell writes, not only edit-tool names"
grep -q 'emit(host, True)' "$guard" || fail "the guard must fail closed"
for hooks in hooks/claude/hooks.json hooks/codex/hooks.json; do
  grep -q 'agentlas-one-drawer-guard' "$root/$hooks" || fail "$hooks does not call the One drawer guard"
  grep -q '"matcher": "[^"]*Bash' "$root/$hooks" || fail "$hooks must gate shell writes too"
  grep -q 'refusing the write until it is restored' "$root/$hooks" \
    || fail "$hooks must deny when the guard is missing instead of passing open"
done
# 실동작 — 계약은 문자열이 아니라 이 네 가지 답이다.
run_guard() { printf '%s' "$1" | "$guard" --host "${2:-claude}"; }
run_guard '{"tool_input":{"file_path":"~/.agentlas/one/soul.md"}}' | grep -q '"deny"' \
  || fail "an edit into the One drawer must be denied"
run_guard '{"tool_input":{"file_path":"/tmp/elsewhere.md"}}' | grep -q '^{}$' \
  || fail "an edit outside the drawer must pass"
run_guard '{"tool_input":{"command":"echo x >> ~/.agentlas/one/soul.md"}}' | grep -q '"deny"' \
  || fail "a shell write into the drawer must be denied"
run_guard 'not json' | grep -q '"deny"' \
  || fail "an unreadable payload must fail closed"

# ── §4.19 못 재는 것을 잰 척하지 않는다 ────────────────────────────────────
has 'if since_epoch <= 0:' agentlas_cloud/one_workspace.py "the capsule check must refuse to judge without a real session start time"
has '"gap": bool(substantial and capsule_written is False)' agentlas_cloud/one_workspace.py \
  "unknown must never be recorded as a learning gap"

# ── §4.20 큐레이션은 원장 잠금 안에서 ──────────────────────────────────────
has '_LedgerLock(decisions_path)' agentlas_cloud/one_workspace.py "curation must hold the decisions ledger lock"
has 'curator_busy' agentlas_cloud/one_workspace.py "a concurrent stop must skip instead of double-writing"

# ── §4.21 / §4.22 무한히 쌓이지 않는다 ─────────────────────────────────────
has 'one_backup_file()' bin/agentlas-one "config backups must go through a rotating helper"
hasnt 'one-backup-\$(date +%s)" 2>/dev/null || true' bin/agentlas-one "raw unbounded backup copies must not come back"
has 'prune_runtime_homes()' scripts/install-all-runtimes.sh "the installer must prune old runtime homes"
has '_prune_runtime_homes' agentlas_cloud/update.py "the updater must prune old runtime homes too"

echo "verify-one-host-hygiene: state, arguments, drawer gate, observability, and retention are bounded and honest."
