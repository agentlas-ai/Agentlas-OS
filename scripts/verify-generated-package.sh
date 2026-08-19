#!/usr/bin/env bash
# Verify a GENERATED package against package-contract.json.
#
# The contract already listed 19 artifacts a built package must carry, and
# nothing ever compared a package to it. `verify-package.sh` checks this engine
# repository's own files (README.ko.md, modes/team-builder.md, ...), which is a
# different job, and `verify-contract-templates.sh` compares templates to the
# schemas they bind — also a different job. So "required" was a wish.
#
# Measured on the live catalogue when this was written: of 247 published
# packages, `.agentlas/capability-eval-plan.json` was present in 4%,
# `.agentlas/mcp-policy.json` in 50%, and a routing benchmark in 76% — all three
# marked required since the contract was written. Builds also drifted on where
# the benchmark lives (`benchmarks/`, `.agentlas/routing-benchmark.jsonl`,
# `.agentlas/routing-benchmarks.jsonl`), so even a present file could not be
# found by path. A contract nothing enforces produces exactly that spread.
#
# Usage:
#   scripts/verify-generated-package.sh [folder]      # default: .
#
# Exit codes: 0 = the package satisfies the contract, 1 = it does not.
set -euo pipefail

engine_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="${1:-.}"

if [[ ! -d "$target" ]]; then
  echo "verify-generated-package: FAIL - target is not a directory: $target" >&2
  exit 1
fi

AGENTLAS_ENGINE_ROOT="$engine_root" python3 - "$target" <<'PY'
import json
import os
import sys
from pathlib import Path

# Resolve the rule from THIS engine checkout, ahead of the cwd python prepends
# for a stdin script — the gate is pointed at a package directory and must never
# load some other agentlas_cloud or contract that happens to sit there.
engine = Path(os.environ["AGENTLAS_ENGINE_ROOT"])
sys.path.insert(0, str(engine))

root = Path(sys.argv[1]).resolve()
contract = json.loads((engine / "package-contract.json").read_text(encoding="utf-8"))

# A gate that cannot perform its check must fail, not pass quietly. Schema
# binding is half of what this contract promises; skipping it on an import error
# would report PASS for a package nobody validated.
try:
    from jsonschema import Draft202012Validator
except ImportError:
    print("verify-generated-package: FAIL - jsonschema is required to check bound schemas")
    print("- install it (pip install jsonschema) or the contract's `schema` bindings go unchecked")
    raise SystemExit(1)

from agentlas_cloud.package_contract import _minimal_private_profile_active
from agentlas_cloud.team_shape import check_team_shape

# The runtime's verify() honours the user-confirmed minimal-private opt-out
# (`.agentlas/build-profile.json`) and the contract's per-artifact
# `optionalWhen`. This gate did not, so the same workspace was ok=True in the
# runtime and FAIL here — the strict receipt check is shared with the runtime
# so a model-asserted or incomplete opt-out still verifies as standard.
build_profile = "minimal-private" if _minimal_private_profile_active(root) else "standard"

shape = check_team_shape(str(root))
mode = (
    "team"
    if shape.get("topology") not in (None, "", "single-agent") and shape.get("workers")
    else "single"
)

errors: list[str] = []
checked = 0


def resolve(pattern: str) -> list[Path]:
    """Contract paths are literal or a single glob (agents/*/agent.md)."""
    if "*" in pattern:
        return sorted(p for p in root.glob(pattern) if p.is_file())
    candidate = root / pattern
    return [candidate] if candidate.is_file() else []


def check_body(path: Path, artifact: dict) -> None:
    relative = path.relative_to(root)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        errors.append(f"{relative}: unreadable ({exc})")
        return

    fmt = artifact.get("format")
    # An append-only JSONL ledger can be required as a contract surface while
    # correctly carrying zero rows at export time. Row requirements stay
    # explicit through minLines (for example, routing benchmarks require 10).
    if not text.strip() and not (fmt == "jsonl" and not artifact.get("minLines")):
        errors.append(f"{relative}: present but empty")
        return

    # An unfilled template is worse than a missing file: it satisfies an
    # existence check while shipping "{{RISK_TIER}}" to the marketplace.
    if "{{" in text and "}}" in text:
        marker = text[text.index("{{"): text.index("}}") + 2][:40]
        errors.append(f"{relative}: template placeholder was never filled ({marker})")
        return

    parsed = None
    if fmt == "json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(f"{relative}: invalid JSON ({exc.msg} at line {exc.lineno})")
            return
    elif fmt == "jsonl":
        lines = [line for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines, start=1):
            try:
                json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{relative}: line {index} is not valid JSON ({exc.msg})")
                return
        minimum = artifact.get("minLines")
        if minimum and len(lines) < minimum:
            errors.append(f"{relative}: {len(lines)} lines, contract requires >= {minimum}")
            return
    elif fmt == "markdown":
        minimum = artifact.get("minLines")
        lines = [line for line in text.splitlines() if line.strip()]
        if minimum and len(lines) < minimum:
            errors.append(f"{relative}: {len(lines)} non-empty lines, contract requires >= {minimum}")
            return

    schema_ref = artifact.get("schema")
    if schema_ref and parsed is not None:
        schema_path = engine / schema_ref
        if not schema_path.is_file():
            errors.append(f"{relative}: bound schema {schema_ref} is missing from the engine")
            return
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        problems = sorted(
            Draft202012Validator(schema).iter_errors(parsed),
            key=lambda issue: list(issue.path),
        )
        for issue in problems[:3]:
            where = "/".join(str(part) for part in issue.path) or "(root)"
            errors.append(f"{relative}: {where}: {issue.message}")


for artifact in contract["artifacts"]:
    if mode not in artifact.get("modes", []):
        continue
    if build_profile in (artifact.get("optionalWhen") or []):
        continue
    if not artifact.get("required"):
        continue
    matches = resolve(artifact["path"])
    if not matches:
        errors.append(f"{artifact['path']}: missing - {artifact.get('description', '')}".rstrip(" -"))
        continue
    for match in matches:
        checked += 1
        check_body(match, artifact)

if errors:
    print(f"verify-generated-package: FAIL {root}")
    print(f"mode={mode}; artifacts checked={checked}; problems={len(errors)}; build_profile={build_profile}")
    for message in errors:
        print(f"- {message}")
    raise SystemExit(1)

# ★"올릴 수 있다"는 **재는 것**이지 선언하는 것이 아니다.
#
#   예전에는 build_profile 이 standard 이기만 하면 public_marketplace_ready=true 라고
#   찍었다. 절대경로 스캔도, 블로커도 보지 않았다. 그래서 빌드는 "마켓플레이스 준비
#   완료"라고 말하고 업로드는 같은 패키지를 거절했다 — 실측 2026-08-19:
#   drug-discovery-research-agent 가 여기서는 PASS/ready=true, upload 가 쓰는
#   package_contract.verify() 에서는 ok=False/ready=False (tools/ 파일에 박힌
#   /Users/... 절대경로). 만든 사람은 올릴 때가 되어서야 안다.
#
#   판정 규칙을 여기 다시 쓰지 않는다 — 업로드가 쓰는 그 함수를 그대로 부른다.
#   두 벌을 두면 오늘과 같은 불일치가 다시 생긴다.
try:
    from agentlas_cloud.package_contract import verify as _canonical_verify
    canonical = _canonical_verify(str(root), mode=mode)
except Exception as exc:  # noqa: BLE001 - 검사를 못 하면 통과가 아니라 실패다
    print(f"verify-generated-package: FAIL {root}")
    print(f"- canonical contract check could not run: {exc}")
    raise SystemExit(1)

canonical_blockers = list(canonical.get("blockers") or [])
if canonical_blockers:
    print(f"verify-generated-package: FAIL {root}")
    print(f"mode={mode}; artifacts checked={checked}; problems={len(canonical_blockers)}; build_profile={build_profile}")
    for message in canonical_blockers:
        print(f"- {message}")
    raise SystemExit(1)

ready = bool(canonical.get("public_marketplace_ready"))
print(f"verify-generated-package: PASS {root}")
print(
    f"mode={mode}; artifacts checked={checked}; build_profile={build_profile}; "
    f"public_marketplace_ready={'true' if ready else 'false'}"
)
PY
