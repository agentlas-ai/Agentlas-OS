#!/usr/bin/env bash
# One 운영 절차 스킬이 **실제로 배달되는가** — PRD §3.6 재발 방지.
#
# 배경(2026-08-23 실측): 모든 호스트에 심는 One 지시문은
# "운영 절차는 ~/.agentlas/one/skills/agentlas-operations/SKILL.md 에 있다"고 말하는데,
#   · 런타임 홈 페이로드에 skills/ 가 없어 **씨앗의 원본 자체가 새 설치본에 없었고**
#     (~/.agentlas/runtime/current/skills 는 존재하지 않았다),
#   · 씨앗 복사는 "파일이 없을 때만" 이라 이미 받은 설치본은 3개월 전 판본에 얼어 있었으며
#     (설치본 8/11 vs 저장소 8/14·8/18: 도구 1개 누락 + 모델 배분 절차 전체 부재),
#   · 그 목록을 만드는 생성기는 어떤 게이트도 부르지 않았다.
# 셋 다 조용했다. 이 게이트는 그 세 가지를 각각 계약으로 지킨다.
set -uo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { echo "verify-ops-skill-delivery: $*" >&2; exit 1; }

PY=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done
[[ -n "$PY" ]] || fail "no python3/python on PATH"

# ── ① 지시문이 가리키는 파일이 저장소에 실재한다 ───────────────────────────
skill="$root/skills/agentlas-operations/SKILL.md"
index="$root/skills/agentlas-operations/INDEX.md"
[[ -f "$skill" ]] || fail "the One directive points at SKILL.md but the repo has none: $skill"
[[ -f "$index" ]] || fail "the operations skill index is missing: $index"
if ! grep -q "skills/agentlas-operations/SKILL.md" "$root/bin/agentlas-one"; then
  fail "the One directive no longer names the operations skill; this gate and the directive must move together"
fi

# ② 원본이 런타임 홈 페이로드에 실려 있다 — 설치기와 업데이터 **양쪽** 모두.
#    한쪽에만 넣으면 업데이트한 머신에서 조용히 사라진다.
grep -q 'source_dir/skills' "$root/scripts/install-all-runtimes.sh" \
  || fail "the installer does not copy skills/ into the runtime home"
grep -qE 'RUNTIME_(OPTIONAL_)?DIRS = \([^)]*"skills"' "$root/agentlas_cloud/update.py" \
  || fail "the updater does not carry skills/ into the runtime home"

# ③ 씨앗 복사가 "없을 때만"이 아니라 버전 비교 갱신이다(사용자 편집은 보존).
seed="$root/agentlas_cloud/one_workspace.py"
grep -q '.shipped-digests.json' "$seed" \
  || fail "the seed does not record what it shipped, so it cannot tell a user edit from a stale copy"
grep -q 'shipped.get(source.name) != current_digest' "$seed" \
  || fail "the seed must keep a user-edited skill and refresh an untouched one"

# ④ 색인은 손으로 쓰지 않는다 — 생성기를 돌려 저장소 사본과 일치해야 한다.
"$PY" - "$root" <<'PY' || exit 1
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1])
index = root / "skills" / "agentlas-operations" / "INDEX.md"
before = index.read_text(encoding="utf-8")
result = subprocess.run(
    [sys.executable, str(root / "scripts" / "generate-ops-skill-index.py")],
    cwd=root, capture_output=True, text=True,
)
if result.returncode != 0:
    print(f"verify-ops-skill-delivery: the index generator failed: {result.stderr.strip()}", file=sys.stderr)
    raise SystemExit(1)
after = index.read_text(encoding="utf-8")
if before != after:
    index.write_text(before, encoding="utf-8")  # 게이트는 저장소를 고치지 않는다 — 되돌린다.
    print(
        "verify-ops-skill-delivery: skills/agentlas-operations/INDEX.md is stale.\n"
        "  run: python3 scripts/generate-ops-skill-index.py  (and commit the result)",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY

echo "verify-ops-skill-delivery: the operations skill ships, refreshes, and its index is generated."
