#!/usr/bin/env bash
# The worker memory directive lives in three places and must be byte-identical:
#
#   1. system-agents/worker-memory-protocol.md               canonical (fenced block)
#   2. agentlas_cloud/runtime.py                             local/hep emitter
#   3. sibling agentlas/.../agentlas-cloud/runtime-bundle.ts Hub emitter
#
# Two emitters ship the directive to borrowed agents; the canonical body is what
# builders, gates, and humans read. If they drift, the spec describes behaviour that
# nothing actually asks for, and the two surfaces ask for different things - which is
# the same class of failure as the entry limit that read 8,000 on one side and 16,000
# on the other while both looked correct in isolation.
#
# This gate FAILS when it cannot read a copy it can reach. The one sanctioned skip is
# the sibling web checkout being absent entirely (CI checks out this repo alone); a
# present sibling with a missing or drifted file is a FAIL, never a skip. A sync gate
# that cannot read a reachable subject must not report PASS.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

python3 - "$ROOT" <<'PY'
import re, sys
from pathlib import Path

root = Path(sys.argv[1])
canon_path = root / "system-agents/worker-memory-protocol.md"
py_path = root / "agentlas_cloud/runtime.py"
sibling_root = root.parent / "agentlas"
ts_path = sibling_root / "AgentsAtlas/app/src/lib/agentlas-cloud/runtime-bundle.ts"

failures: list[str] = []


def read(path: Path) -> str | None:
    if not path.exists():
        failures.append(f"missing source: {path}")
        return None
    return path.read_text(encoding="utf-8")


def extract(text: str | None, pattern: str, label: str) -> str | None:
    if text is None:
        return None
    match = re.search(pattern, text, re.DOTALL)
    if not match:
        failures.append(f"{label}: directive block not found - the gate cannot verify it")
        return None
    return match.group(1).strip()


canon = extract(read(canon_path), r"```text\n(## Memory protocol \(platform\).*?)```", "canonical")
py = extract(read(py_path), r'WORKER_MEMORY_DIRECTIVE = """(.*?)"""', "runtime.py")

if sibling_root.is_dir():
    ts = extract(read(ts_path), r"WORKER_MEMORY_DIRECTIVE = `(.*?)`;", "runtime-bundle.ts")
    # The TS copy escapes backticks for its template literal; compare the text, not
    # the escaping the host language happens to require.
    if ts is not None:
        ts = ts.replace("\\`", "`")
    emitters = (("runtime.py", py), ("runtime-bundle.ts", ts))
else:
    print(f"SKIP (sibling agentlas checkout not present): {ts_path}")
    emitters = (("runtime.py", py),)

for label, body in emitters:
    if canon is None or body is None:
        continue
    if body != canon:
        canon_lines = canon.splitlines()
        body_lines = body.splitlines()
        where = next(
            (i for i, (a, b) in enumerate(zip(canon_lines, body_lines)) if a != b),
            min(len(canon_lines), len(body_lines)),
        )
        failures.append(
            f"{label}: drifted from the canonical block at line {where + 1}\n"
            f"    canonical: {canon_lines[where] if where < len(canon_lines) else '<end of block>'}\n"
            f"    {label}: {body_lines[where] if where < len(body_lines) else '<end of block>'}"
        )

if failures:
    print("[sync-worker-memory-directive] FAIL")
    for failure in failures:
        print(f"  - {failure}")
    raise SystemExit(1)

print("[sync-worker-memory-directive] PASS - canonical body and reachable emitters are byte-identical")
PY
