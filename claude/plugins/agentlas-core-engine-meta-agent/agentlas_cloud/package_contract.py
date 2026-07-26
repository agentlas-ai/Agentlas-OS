"""Machine-readable package contract: scaffold + verify.

Single source of truth for "what files must a generated Agentlas package
contain" lives in package-contract.json (validated by
schemas/package-contract.schema.json). Every build surface consumes it the
same way:

- ``hephaestus contract scaffold`` copies the artifact templates into a
  workspace before any model runs, so completeness never depends on a model
  remembering a prose checklist. Small local models then only FILL files.
- ``hephaestus contract verify`` re-checks the workspace after a build and
  emits a machine-readable blocker list a model can consume to self-repair.

Design rule (research-grounded): structure constrains VERIFICATION, never
free generation. Flagship builds keep their autonomous loop and only gain
the post-hoc gate; small-model pipelines use the scaffold + fill + repair
loop. Constrained decoding belongs only to ``fill``-shaped artifacts.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PLACEHOLDER_RE = re.compile(r"\{\{[A-Za-z0-9_]+\}\}")
CONTRACT_FILENAME = "package-contract.json"


def engine_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_contract(root: Path | None = None) -> dict[str, Any]:
    base = root or engine_root()
    payload = json.loads((base / CONTRACT_FILENAME).read_text(encoding="utf-8"))
    if payload.get("kind") != "agentlas-package-contract":
        raise ValueError("package-contract.json kind mismatch")
    return payload


def artifacts_for_mode(contract: dict[str, Any], mode: str) -> list[dict[str, Any]]:
    return [a for a in contract.get("artifacts", []) if mode in (a.get("modes") or [])]


def contract_prompt_lines(mode: str, root: Path | None = None) -> list[str]:
    """Render the contract as prompt bullet lines so prose surfaces
    (hep-build.md, Desktop Build) derive from the same source instead of
    hand-maintaining their own lists."""
    lines: list[str] = []
    for artifact in artifacts_for_mode(load_contract(root), mode):
        marker = "required" if artifact.get("required", True) else "optional"
        desc = artifact.get("description") or ""
        lines.append(f"- {artifact['path']} ({marker}): {desc}")
    return lines


def _default_substitutions(package_id: str, name: str, command: str, mode: str) -> dict[str, str]:
    return {
        "PACKAGE_ID": package_id,
        "PACKAGE_NAME": name,
        "NAME_KO": name,
        "COMMAND_SLUG": command,
        "TEAM_NAME": name,
        "ENTITY_TYPE": "team" if mode == "team" else "agent",
        "ORCHESTRATOR_AGENT_ID": f"{package_id}-orchestrator",
        "projectId": package_id,
        "project_id": package_id,
        "draft_id": f"{package_id}-draft",
        "AGENT_NAME": name,
        "AGENTLAS_MODE": mode,
    }


def scaffold(
    folder: str | Path,
    mode: str = "single",
    package_id: str = "",
    name: str = "",
    command: str = "",
    root: Path | None = None,
) -> dict[str, Any]:
    """Copy contract templates into ``folder`` (never overwriting existing
    files) and substitute the identity placeholders we already know. Model
    placeholders ({{TRIGGER_KO_1}}...) stay for the fill step."""
    base = root or engine_root()
    workspace = Path(folder).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    package_id = package_id or workspace.name.lower().replace(" ", "-")
    name = name or package_id
    command = (command or package_id).lstrip("/")
    subs = _default_substitutions(package_id, name, command, mode)

    created: list[str] = []
    skipped: list[str] = []
    missing_templates: list[str] = []
    for artifact in artifacts_for_mode(load_contract(base), mode):
        target = workspace / artifact["path"]
        if target.exists():
            skipped.append(artifact["path"])
            continue
        template_ref = artifact.get("template")
        if not template_ref:
            continue  # generate-only artifact with no skeleton (e.g. work-brief.json)
        template_path = base / template_ref
        if not template_path.is_file():
            missing_templates.append(template_ref)
            continue
        text = template_path.read_text(encoding="utf-8")
        for key, value in subs.items():
            text = text.replace("{{" + key + "}}", value)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        created.append(artifact["path"])
    return {
        "workspace": str(workspace),
        "mode": mode,
        "package_id": package_id,
        "created": created,
        "skipped_existing": skipped,
        "missing_templates": missing_templates,
    }


def _schema_required_errors(doc: Any, schema_path: Path) -> list[str]:
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"schema unreadable: {schema_path.name}"]
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["document must be a JSON object"]
    for field in schema.get("required", []):
        # Presence-only: an explicit empty list/string is a declared value
        # (e.g. skills: []), not an omission. Deep quality checks belong to
        # per-artifact lints (routing-card), not this shape gate.
        if field not in doc or doc.get(field) is None:
            errors.append(f"missing required field: {field}")
    return errors


def _verify_artifact(workspace: Path, artifact: dict[str, Any], base: Path) -> dict[str, Any]:
    path = workspace / artifact["path"]
    report: dict[str, Any] = {"path": artifact["path"], "required": artifact.get("required", True)}
    problems: list[str] = []
    if not path.is_file():
        problems.append("missing")
        report["problems"] = problems
        return report

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as err:
        report["problems"] = [f"unreadable: {err}"]
        return report

    leftover = sorted(set(PLACEHOLDER_RE.findall(text)))
    if leftover:
        problems.append(f"unfilled placeholders: {', '.join(leftover[:6])}")

    fmt = artifact.get("format")
    doc: Any = None
    if fmt == "json":
        try:
            doc = json.loads(text)
        except ValueError as err:
            problems.append(f"invalid JSON: {err}")
    elif fmt == "jsonl":
        lines = [line for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines, 1):
            try:
                json.loads(line)
            except ValueError:
                problems.append(f"invalid JSONL at line {index}")
                break
        report["lines"] = len(lines)

    min_lines = artifact.get("minLines")
    if min_lines:
        non_empty = sum(1 for line in text.splitlines() if line.strip())
        if non_empty < min_lines:
            problems.append(f"needs >={min_lines} non-empty lines (has {non_empty})")

    schema_ref = artifact.get("schema")
    if schema_ref and doc is not None:
        problems.extend(_schema_required_errors(doc, base / schema_ref))

    if artifact.get("lint") == "routing-card" and isinstance(doc, dict):
        from .networking.card_lint import lint_card

        # card_lint resolves a relative benchmark_fixtures path against the
        # card's source.ref (set by card_store on import). Inside a package
        # workspace that anchor is the workspace itself.
        source = dict(doc.get("source")) if isinstance(doc.get("source"), dict) else {}
        # A card exported before import carries an explicit ``"ref": null``, so
        # setdefault() would leave the anchor empty and every shipped benchmark
        # fixture would count as zero. Treat any falsy ref as "not anchored".
        if not source.get("ref"):
            source["ref"] = str(workspace)
        try:
            lint = lint_card({**doc, "source": source})
        except Exception as err:  # 카드가 어떤 모양이든 게이트는 크래시하지 않는다
            lint = {"errors": [f"lint crashed on malformed card: {err}"], "ready_blockers": []}
        report["routing_lint"] = lint
        problems.extend(f"routing-card: {err}" for err in lint.get("errors", []))
        problems.extend(f"routing-card: {blocker}" for blocker in lint.get("ready_blockers", []))

    report["problems"] = problems
    return report


def verify(folder: str | Path, mode: str = "single", root: Path | None = None) -> dict[str, Any]:
    """Machine-readable completeness gate. ``blockers`` is the list a model
    consumes for targeted self-repair; ``ok`` means routing-ready package."""
    base = root or engine_root()
    workspace = Path(folder).expanduser().resolve()
    reports = [
        _verify_artifact(workspace, artifact, base)
        for artifact in artifacts_for_mode(load_contract(base), mode)
    ]
    blockers = [
        f"{report['path']}: {problem}"
        for report in reports
        if report.get("required", True)
        for problem in report.get("problems", [])
    ]
    warnings = [
        f"{report['path']}: {problem}"
        for report in reports
        if not report.get("required", True)
        for problem in report.get("problems", []) if problem != "missing"
    ]
    return {
        "workspace": str(workspace),
        "mode": mode,
        "ok": not blockers,
        "artifacts": reports,
        "blockers": blockers,
        "warnings": warnings,
    }
