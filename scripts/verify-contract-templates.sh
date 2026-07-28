#!/usr/bin/env bash
# Verify every contract template against the schema the contract binds it to.
#
# WHY this gate exists: `package-contract.json` binds each artifact to both a
# `template` and a `schema`, but nothing ever compared the two. A template is
# copied verbatim by `contract scaffold`, so every fixed value it carries is a
# value the built package ships. When `templates/routing-card.json.tpl` said
# `schemaVersion: "1.0"` while `schemas/routing-card.schema.json` pins the
# const `routing-card/2.0`, every package the three meta-agent builders produced
# to spec was hard-rejected at borrow (`workforce local-register` ->
# `routing_card_invalid`) and at upload — while this build gate and
# verify-routing-cards.sh both stayed green, because they only lint the
# hand-written cards already at 2.0. The drift had no gate of its own.
#
# The rule is not restated here: it delegates to the same
# `package_contract._schema_shape_errors` that `contract verify` (build) uses,
# so build, borrow and the templates cannot drift apart again.
#
# Placeholders ({{RISK_TIER}}) are the fill step's job, not the template's
# claim, so a finding is suppressed only for the specific field that still holds
# one — `contract verify` already blocks unfilled placeholders, and a required
# field genuinely absent from the template is still reported here.
#
# Usage:
#   scripts/verify-contract-templates.sh
#
# Exit codes: 0 = every bound template satisfies its schema; 1 = drift.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
import json
import re
import sys
from pathlib import Path

try:
    from agentlas_cloud.package_contract import _schema_shape_errors
except ImportError as err:  # pragma: no cover - surfaced to the operator, never skipped
    # Fail loudly: silently skipping would return this gate to the exact state
    # that let the schemaVersion drift ship.
    print(
        "verify-contract-templates: cannot import the shared shape check from "
        f"agentlas_cloud.package_contract ({err}). This gate must not be skipped — "
        "if _schema_shape_errors moved, point this script at its new home.",
        file=sys.stderr,
    )
    raise SystemExit(1)

PLACEHOLDER = re.compile(r"\{\{[A-Z0-9_]+\}\}")
root = Path.cwd()


def field_of(problem: str) -> str:
    if problem.startswith("missing required field: "):
        return problem.split(": ", 1)[1]
    return problem.split(" ", 1)[0]


contract = json.loads((root / "package-contract.json").read_text(encoding="utf-8"))
failed = 0
checked = 0

for artifact in contract.get("artifacts", []):
    template_ref = artifact.get("template")
    schema_ref = artifact.get("schema")
    if not template_ref or not schema_ref or not template_ref.endswith(".json.tpl"):
        continue
    template_path = root / template_ref
    schema_path = root / schema_ref
    for missing in (p for p in (template_path, schema_path) if not p.is_file()):
        print(
            f"verify-contract-templates: {artifact['path']} binds a file that does not "
            f"exist: {missing.relative_to(root)}",
            file=sys.stderr,
        )
        failed += 1
    if not (template_path.is_file() and schema_path.is_file()):
        continue

    try:
        document = json.loads(template_path.read_text(encoding="utf-8"))
    except ValueError as err:
        print(
            f"verify-contract-templates: {template_ref} is not valid JSON ({err}). "
            "`contract scaffold` copies it verbatim, so it must parse.",
            file=sys.stderr,
        )
        failed += 1
        continue

    checked += 1
    for problem in _schema_shape_errors(document, schema_path):
        value = document.get(field_of(problem))
        if isinstance(value, str) and PLACEHOLDER.search(value):
            continue  # still a placeholder: the fill step owns this field
        print(
            f"verify-contract-templates: {template_ref} violates {schema_ref}: {problem}",
            file=sys.stderr,
        )
        failed += 1

if failed:
    print(
        f"verify-contract-templates: {failed} template/schema disagreement(s). Every "
        "package scaffolded from these templates would carry the same value and be "
        "rejected at borrow (workforce local-register) and at upload.",
        file=sys.stderr,
    )
    raise SystemExit(1)

print(f"verify-contract-templates: {checked} contract template(s) match their schema.")
PY
