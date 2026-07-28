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

from agentlas_cloud.team_shape import check_team_shape

shape = check_team_shape(str(root))
mode = "team" if shape.get("topology") and shape.get("workers") else "single"

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

    if not text.strip():
        errors.append(f"{relative}: present but empty")
        return

    # An unfilled template is worse than a missing file: it satisfies an
    # existence check while shipping "{{RISK_TIER}}" to the marketplace.
    if "{{" in text and "}}" in text:
        marker = text[text.index("{{"): text.index("}}") + 2][:40]
        errors.append(f"{relative}: template placeholder was never filled ({marker})")
        return

    fmt = artifact.get("format")
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
    print(f"mode={mode}; artifacts checked={checked}; problems={len(errors)}")
    for message in errors:
        print(f"- {message}")
    raise SystemExit(1)

print(f"verify-generated-package: PASS {root}")
print(f"mode={mode}; artifacts checked={checked}")
PY
