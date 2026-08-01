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
HOST_PATH_RE = re.compile(
    r"(?:file://)?/(?:Users|home)/[^/\s\"'<>]+(?:/[^\s\"'<>]+)*"
    r"|[A-Za-z]:\\+Users\\+[^\\\s\"'<>]+(?:\\+[^\\\s\"'<>]+)*"
)
TEXT_SCAN_LIMIT_BYTES = 2 * 1024 * 1024


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


def _workspace_path_error(workspace: Path, *, must_exist: bool) -> dict[str, str] | None:
    """Say why a user-supplied workspace path is unusable, or None if it is fine.

    WHY: verify() used to resolve the path and go straight to the per-artifact
    checks, so a typo'd or wrong-cwd path produced a confident report with every
    required artifact marked "missing" — byte-identical in shape to a real
    half-written package. The user then starts writing AGENTS.md/agent.md into
    the wrong place, or concludes the package lost every file. scaffold() had
    the mirror hole: its mkdir() raised a raw FileExistsError traceback at the
    user when the path was an existing file. Both surfaces now name the path
    instead, the same gate upload.package_agent already enforces
    ("agent folder not found"). Report the path, never diagnose a package that
    was never looked at.
    """
    if not workspace.exists():
        if not must_exist:
            return None  # scaffold creates the workspace; absence is expected
        return {
            "error": "workspace_not_found",
            "message": (
                f"folder not found: {workspace} — check the path (typo or wrong working "
                f"directory), or run `hephaestus contract scaffold {workspace}` to create "
                "the package there"
            ),
        }
    if not workspace.is_dir():
        return {
            "error": "workspace_not_a_folder",
            "message": f"not a folder: {workspace} — a package workspace must be a directory",
        }
    return None


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
    path_error = _workspace_path_error(workspace, must_exist=False)
    if path_error:
        return {
            "workspace": str(workspace),
            "mode": mode,
            "package_id": package_id,
            "created": [],
            "skipped_existing": [],
            "missing_templates": [],
            **path_error,
        }
    workspace.mkdir(parents=True, exist_ok=True)
    package_id = package_id or workspace.name.lower().replace(" ", "-")
    name = name or package_id
    command = (command or package_id).lstrip("/")
    subs = _default_substitutions(package_id, name, command, mode)

    created: list[str] = []
    skipped: list[str] = []
    missing_templates: list[str] = []
    for artifact in artifacts_for_mode(load_contract(base), mode):
        if "*" in artifact["path"]:
            # A roster row (agents/*/agent.md) names a variable-count set the
            # builder must author, not one skeleton to copy. It still appears in
            # the prompt lines and in verify, so it can never be silently
            # dropped — there is just nothing to scaffold.
            continue
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


def _schema_shape_errors(doc: Any, schema_path: Path) -> list[str]:
    """Check the artifact against the shape its schema already declares.

    WHY (both halves matter):

    Presence: an explicit empty list/string is a declared value (e.g.
    skills: []), not an omission, so required-key checking stays presence-only.
    Deep quality checks belong to per-artifact lints (routing-card), not here.

    Declared values: this gate used to check presence ONLY, which left every
    ``const``/``enum`` in the schema unenforced anywhere in the build path. A
    routing card carrying ``schemaVersion: "1.0"`` (what the scaffold template
    itself wrote) passed ``contract verify`` with ok=true and lint
    routing_ready, and was then hard-rejected at borrow
    (workforce/package_adapter.inspect_package) and at upload
    (upload._server_routing_problem) — a package the build gate certified could
    not be registered or published. A const/enum is a value the contract has
    already fixed, so reading it here invents nothing; it just puts build,
    borrow and upload back on one source of truth.
    """
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [f"schema unreadable: {schema_path.name}"]
    errors: list[str] = []

    def walk(value: Any, spec: Any, path: str) -> None:
        if not isinstance(spec, dict):
            return
        placeholder = isinstance(value, str) and PLACEHOLDER_RE.search(value)
        if placeholder:
            return
        expected = spec.get("type")
        allowed_types = expected if isinstance(expected, list) else [expected] if expected else []
        type_ok = (
            not allowed_types
            or ("object" in allowed_types and isinstance(value, dict))
            or ("array" in allowed_types and isinstance(value, list))
            or ("string" in allowed_types and isinstance(value, str))
            or ("integer" in allowed_types and isinstance(value, int) and not isinstance(value, bool))
            or ("number" in allowed_types and isinstance(value, (int, float)) and not isinstance(value, bool))
            or ("boolean" in allowed_types and isinstance(value, bool))
            or ("null" in allowed_types and value is None)
        )
        if not type_ok:
            errors.append(f"{path} has invalid type")
            return
        if "const" in spec and value != spec["const"]:
            errors.append(f"{path} must be {spec['const']!r} (found {value!r})")
        if isinstance(spec.get("enum"), list) and value not in spec["enum"]:
            errors.append(f"{path} must be one of {spec['enum']!r} (found {value!r})")
        if isinstance(value, str) and isinstance(spec.get("pattern"), str):
            if re.fullmatch(spec["pattern"], value) is None:
                errors.append(f"{path} does not match required pattern")
        if isinstance(value, list):
            if isinstance(spec.get("minItems"), int) and len(value) < spec["minItems"]:
                errors.append(f"{path} needs at least {spec['minItems']} items")
            if isinstance(spec.get("maxItems"), int) and len(value) > spec["maxItems"]:
                errors.append(f"{path} allows at most {spec['maxItems']} items")
            for index, item in enumerate(value):
                walk(item, spec.get("items"), f"{path}[{index}]")
        if isinstance(value, dict):
            required = spec.get("required") if isinstance(spec.get("required"), list) else []
            for field in required:
                if field not in value or value.get(field) is None:
                    errors.append(f"missing required field: {path}.{field}")
            properties = spec.get("properties") if isinstance(spec.get("properties"), dict) else {}
            if spec.get("additionalProperties") is False:
                for field in value:
                    if field not in properties:
                        errors.append(f"{path}.{field} is not allowed")
            for field, child in properties.items():
                if field in value:
                    walk(value[field], child, f"{path}.{field}")

    walk(doc, schema, "$")
    return errors


def _verify_team_shape(workspace: Path, artifact: dict[str, Any]) -> dict[str, Any]:
    """Verify a variable-count roster artifact (path contains ``*``).

    WHY this exists: every other row in the contract is one literal file, so a
    team's actual substance — a roster of worker agents, an orchestrator/HQ, a
    declared topology — could not be expressed here at all. The result was that
    ``contract verify --mode team`` reported ok=True for a package with zero
    workers while ``scripts/verify-team-package.sh``, mandatory in the very same
    documented flow, rejected it. A fill/repair loop that trusts this gate then
    ships a degenerate team and hits a shell failure that maps back to no
    contract artifact to repair. Delegate to the one shared rule so both gates
    agree, and report its findings against this contract row so every blocker
    still names an artifact.
    """
    from .team_shape import check_team_shape

    shape = check_team_shape(workspace)
    return {
        "path": artifact["path"],
        "required": artifact.get("required", True),
        "team_shape": shape,
        "problems": list(shape["errors"]),
    }


def _verify_artifact(workspace: Path, artifact: dict[str, Any], base: Path) -> dict[str, Any]:
    if artifact.get("lint") == "team-shape":
        return _verify_team_shape(workspace, artifact)

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
        problems.extend(_schema_shape_errors(doc, base / schema_ref))

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


def _portable_path_blockers(workspace: Path) -> list[str]:
    """Reject host-specific paths that make an exported package non-portable.

    The Build prompt already forbids serializing the current working directory,
    but a prompt is not a gate. Project bootstrap metadata can otherwise leave
    ``/Users/<name>/...`` (or the Windows equivalent) in an apparently clean
    package. Static security scanning correctly treats those strings as
    non-malicious, so the package contract owns this portability invariant.

    Only small UTF-8 text files are inspected. Databases and other binary
    runtime state are never parsed or executed by this verifier.
    """
    blockers: list[str] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            if path.stat().st_size > TEXT_SCAN_LIMIT_BYTES:
                continue
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        match = HOST_PATH_RE.search(text)
        if match is None:
            continue
        relative = path.relative_to(workspace).as_posix()
        blockers.append(
            f"{relative}: contains an absolute host path; replace it with a package-relative path or remove generated runtime state"
        )
    return blockers


def verify(folder: str | Path, mode: str = "single", root: Path | None = None) -> dict[str, Any]:
    """Machine-readable completeness gate. ``blockers`` is the list a model
    consumes for targeted self-repair; ``ok`` means routing-ready package."""
    base = root or engine_root()
    workspace = Path(folder).expanduser().resolve()
    path_error = _workspace_path_error(workspace, must_exist=True)
    if path_error:
        return {
            "workspace": str(workspace),
            "mode": mode,
            "ok": False,
            # No artifact rows: the gate never looked at a package, so it must
            # not report on one. ``blockers`` still carries exactly one
            # actionable line so every self-repair consumer keeps working.
            "artifacts": [],
            "blockers": [path_error["message"]],
            "warnings": [],
            **path_error,
        }
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
    blockers.extend(_portable_path_blockers(workspace))
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
