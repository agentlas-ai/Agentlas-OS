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
GENERATED_RUNTIME_PATHS = (
    ".agentlas/ontology-runtime.json",
    ".agentlas/ontology-sources.json",
    ".agentlas/ontology-inbox",
    ".agentlas/career-graph-sources.json",
    ".agentlas/career-graph-inbox",
)
GENERATED_RUNTIME_FILE_PREFIXES = (
    "ontology-runtime.sqlite",
    "career-graph.sqlite",
)


def is_generated_runtime_path(relative_path: str) -> bool:
    """Return whether a package path is rebuildable host-local runtime state."""

    normalized = relative_path.replace("\\", "/").strip("/")
    if any(
        normalized == candidate or normalized.startswith(f"{candidate}/")
        for candidate in GENERATED_RUNTIME_PATHS
    ):
        return True
    if not normalized.startswith(".agentlas/"):
        return False
    name = normalized.rsplit("/", 1)[-1]
    return any(name.startswith(prefix) for prefix in GENERATED_RUNTIME_FILE_PREFIXES)


def engine_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_contract(root: str | Path | None = None) -> dict[str, Any]:
    base = Path(root) if root else engine_root()
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
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Copy contract templates into ``folder`` (never overwriting existing
    files) and substitute the identity placeholders we already know. Model
    placeholders ({{TRIGGER_KO_1}}...) stay for the fill step."""
    base = Path(root) if root else engine_root()
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


def project_a2a_card(workspace: Path) -> dict[str, Any] | None:
    """Derive the A2A (Agent2Agent v1.0.1) card from agent-card.json + routing-card.json.

    Owner decision 2026-08-08 (R1): A2A/ never carries a hand-authored primary —
    a second identity file drifts from the real one exactly like every other
    duplicated-identity incident in this codebase. Returns None (nothing honest
    to project yet) until agent-card.json is actually filled, so a fresh
    scaffold does not ship a card full of ``{{PLACEHOLDER}}`` tokens.
    """
    agent_card_path = workspace / ".agentlas" / "agent-card.json"
    if not agent_card_path.is_file():
        return None
    try:
        raw = agent_card_path.read_text(encoding="utf-8")
        agent_card = json.loads(raw)
    except (OSError, ValueError):
        return None
    if PLACEHOLDER_RE.search(raw):
        return None

    routing_card: dict[str, Any] = {}
    routing_card_path = workspace / ".agentlas" / "routing-card.json"
    if routing_card_path.is_file():
        try:
            routing_card = json.loads(routing_card_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            routing_card = {}

    # R5: the identity anchor is the immutable agentId, never the mutable slug —
    # a rename must not orphan an external A2A reference. agentlas.json mints
    # agentId at first local build (runtime.run_setup_wizard), so it is usually
    # present; when it is not yet, say so explicitly instead of guessing a URL.
    agent_id = ""
    manifest_path = workspace / "agentlas.json"
    if manifest_path.is_file():
        try:
            agent_id = str(json.loads(manifest_path.read_text(encoding="utf-8")).get("agentId") or "").strip()
        except (OSError, ValueError):
            agent_id = ""
    url = f"https://agentlas.cloud/a2a/{agent_id}" if agent_id else "agentlas:pending-agent-id"

    capabilities = agent_card.get("capabilities")
    skills: list[dict[str, str]] = []
    seen_skill_ids: set[str] = set()

    def add_skill(skill_id: Any) -> None:
        if isinstance(skill_id, str) and skill_id and skill_id not in seen_skill_ids:
            seen_skill_ids.add(skill_id)
            skills.append({"id": skill_id, "name": skill_id.split(":")[-1].replace("_", " ").replace("-", " ")})

    if isinstance(capabilities, list):
        for item in capabilities:
            add_skill(item)
    elif isinstance(capabilities, dict):
        for item in capabilities.get("skills") or []:
            add_skill(item)
    workforce = routing_card.get("workforce")
    if isinstance(workforce, dict):
        for item in workforce.get("skills") or []:
            add_skill(item)

    card: dict[str, Any] = {
        "protocolVersion": "1.0.1",
        "name": agent_card.get("name") or agent_card.get("slug") or workspace.name,
        "description": agent_card.get("summary") or routing_card.get("summary") or "",
        "url": url,
        "provider": {"organization": "Agentlas", "url": "https://agentlas.cloud"},
        "capabilities": {"streaming": False, "pushNotifications": False},
        "skills": skills,
        "securitySchemes": {},
        "extensions": [],
        "_generated": {
            "note": "projected from .agentlas/agent-card.json + .agentlas/routing-card.json at build/verify time — never hand-author this file (R1, 2026-08-08)",
            "agentIdPending": not bool(agent_id),
        },
    }
    entrypoints = agent_card.get("entrypoints")
    if isinstance(entrypoints, dict) and entrypoints.get("agent"):
        card["_generated"]["entrypoint"] = entrypoints["agent"]
    return card


def write_a2a_projection(workspace: Path) -> str | None:
    """Write the A2A projection into the workspace; return its relative path, or
    None when agent-card.json is not filled yet (nothing to project)."""
    card = project_a2a_card(workspace)
    if card is None:
        return None
    target = workspace / "A2A" / "agent-card.a2a.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(card, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target.relative_to(workspace).as_posix()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _unfilled(*docs: dict[str, Any] | None) -> bool:
    return any(doc is not None and PLACEHOLDER_RE.search(json.dumps(doc)) for doc in docs)


def project_tools_requirements(workspace: Path) -> str | None:
    """tools/requirements.yaml — projected from .agentlas/mcp-policy.json +
    agentlas.json. Never hand-authored: mcp-policy.json is already the one
    place a build declares required tools/MCP servers (owner decision
    2026-08-08, #9 System Agents - Copy, Never Write: a package declares via
    its .agentlas/*.json, it never keeps a second copy of the same fact).
    Body is YAML-compatible JSON — PyYAML is not a dependency anywhere in this
    codebase, and valid JSON is valid YAML, so no new dependency is needed.
    """
    mcp_policy = _read_json(workspace / ".agentlas" / "mcp-policy.json")
    manifest = _read_json(workspace / "agentlas.json")
    if mcp_policy is None or manifest is None or _unfilled(mcp_policy, manifest):
        return None
    payload = {
        "_generated": "projected from .agentlas/mcp-policy.json + agentlas.json — edit those, not this",
        "requiredRuntime": manifest.get("requiredRuntime") or [],
        "mcpRequirements": mcp_policy.get("requirements") or [],
        "resolutionOrder": mcp_policy.get("registryResolutionOrder") or [],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def project_permissions_policy(workspace: Path) -> str | None:
    """permissions/policy.yaml — projected from agentlas.json's toolPermissions
    / allowRead / denyRead. Same never-hand-authored reasoning as tools/: those
    fields are already the live-enforced permission surface
    (upload._server_routing_problem and the host PreToolUse hook both read
    agentlas.json, not a second permissions file)."""
    manifest = _read_json(workspace / "agentlas.json")
    if manifest is None or _unfilled(manifest):
        return None
    tool_permissions = manifest.get("toolPermissions") or {}
    payload = {
        "_generated": "projected from agentlas.json — edit that, not this",
        "shell": tool_permissions.get("shell", "deny"),
        "network": tool_permissions.get("network", "ask"),
        "fileRead": tool_permissions.get("fileRead", "manifest-allowlist"),
        "payment": "deny",
        "allowRead": manifest.get("allowRead") or [],
        "denyRead": manifest.get("denyRead") or [],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def project_memory_upgrade_hook(workspace: Path) -> str | None:
    """hooks/memory-upgrade.yaml — declares (never implements) the memory
    lifecycle this package expects. Owner decision 2026-08-08 (#9): policy and
    judge logic belong only to the OS-resident system agents (the always-on
    curator, the host PreToolUse hook); a team/single package that authored its
    own enforcement here would duplicate that layer — the exact mistake #9 was
    written to stop (0/32 teams honoured the old verbatim-copy contract)."""
    memory_map = _read_json(workspace / ".agentlas" / "memory-map.json")
    if memory_map is None or _unfilled(memory_map):
        return None
    payload = {
        "_generated": "projected from .agentlas/memory-map.json — edit that, not this",
        "_enforcement": (
            "declarative only — the OS-resident memory curator enforces this "
            "(owner decision 2026-08-08, #9); this package never implements "
            "memory policy or judge logic itself"
        ),
        "writeOwners": memory_map.get("writeOwners") or {},
        "promotionPath": memory_map.get("promotionPath") or [],
        "trustLabels": memory_map.get("trustLabels") or [],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def project_on_stop_hook(workspace: Path) -> str | None:
    """hooks/on_stop.yaml — declares (never implements) session-end behavior.
    The host Stop hook per runtime performs the actual flush; this file only
    states what this package expects of it, same declare-not-implement rule as
    memory-upgrade.yaml above."""
    manifest = _read_json(workspace / "agentlas.json")
    if manifest is None or _unfilled(manifest):
        return None
    memory_policy = manifest.get("memoryPolicy") or {}
    payload = {
        "_generated": "projected from agentlas.json — edit that, not this",
        "_enforcement": "declarative only — the host Stop hook performs the actual flush/report",
        "onStop": {
            "flushMemoryTickets": True,
            "appendSoulLog": memory_policy.get("writeBack") != "deny",
            "reportPath": ".agentlas/memory-tickets.jsonl",
        },
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def project_provenance(workspace: Path) -> dict[str, Any] | None:
    """provenance.json — minted ONCE at first build, then preserved verbatim
    forever (same rule as agentId, R5 owner decision: a value that must survive
    every future rebuild cannot be recomputed on every build). Returns None
    when the file already exists (nothing to do) or the sources are not ready.

    Deliberately carries no wall-clock timestamp: `packageHash` must depend
    only on content that does not change between two builds of the same
    inputs (measured — test_local_source_hash_and_cloud_artifact_hash_have_
    explicit_distinct_contracts asserts re-scanning mutable evidence must not
    mint a different release; a `mintedAt` field here broke that on the very
    first run, because some callers re-derive this file from a fresh copy of
    the same source rather than reusing one written earlier). Creation order
    is already recorded outside the hashed artifact — git history, the Hub
    registration record — and does not need a second, hash-breaking copy here.
    """
    if (workspace / "provenance.json").is_file():
        return None
    manifest = _read_json(workspace / "agentlas.json")
    agent_card = _read_json(workspace / ".agentlas" / "agent-card.json")
    if manifest is None or agent_card is None or _unfilled(manifest, agent_card):
        return None
    agent_id = str(manifest.get("agentId") or "").strip()
    if not agent_id:
        return None
    return {
        "schemaVersion": "1.0",
        "agentId": agent_id,
        "name": agent_card.get("name") or agent_card.get("slug") or workspace.name,
        "license": manifest.get("license") or "call-only-default",
        "createdBy": manifest.get("createdBy") or "hephaestus-setup-wizard",
        "_generated": (
            "minted once at first build from agentlas.json + "
            ".agentlas/agent-card.json, then preserved verbatim — component "
            "changes must bump the package version, never this file"
        ),
    }


def _write_text_projection(workspace: Path, relative_path: str, generator: Any) -> str | None:
    content = generator(workspace)
    if content is None:
        return None
    target = workspace / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target.relative_to(workspace).as_posix()


def refresh_generated_projections(workspace: Path) -> list[str]:
    """Refresh every derived (never-hand-authored) artifact this package
    contract now owns. Called from verify() — never from scaffold(), whose
    sources are still unfilled ``{{PLACEHOLDER}}`` templates at that point —
    so the same verify() call always sees its own freshly written output."""
    written: list[str] = []
    a2a = write_a2a_projection(workspace)
    if a2a:
        written.append(a2a)
    for relative_path, generator in (
        ("tools/requirements.yaml", project_tools_requirements),
        ("permissions/policy.yaml", project_permissions_policy),
        ("hooks/memory-upgrade.yaml", project_memory_upgrade_hook),
        ("hooks/on_stop.yaml", project_on_stop_hook),
    ):
        result = _write_text_projection(workspace, relative_path, generator)
        if result:
            written.append(result)
    provenance = project_provenance(workspace)
    if provenance is not None:
        target = workspace / "provenance.json"
        target.write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append("provenance.json")
    return written


def _verify_skills_consistency(workspace: Path) -> list[str]:
    """Cross-check .agentlas/skill-registry.json against skills/*/SKILL.md on
    disk. Warning-only (never a blocker): a skill can legitimately be
    registered ahead of authoring it, or authored as a local draft before
    registration, so divergence is a thing to flag, not to fail a build over.
    repackage.py already globs skills/*/SKILL.md for sitemap/sources
    generation; this reads the same shape so the two never disagree."""
    registry = _read_json(workspace / ".agentlas" / "skill-registry.json")
    on_disk = {p.parent.name for p in sorted(workspace.glob("skills/*/SKILL.md"))}
    registered = set()
    if isinstance(registry, dict):
        for entry in registry.get("skills") or []:
            if isinstance(entry, dict) and isinstance(entry.get("slug"), str):
                registered.add(entry["slug"])
    warnings: list[str] = []
    for slug in sorted(on_disk - registered):
        warnings.append(f"skills/{slug}/SKILL.md: not listed in .agentlas/skill-registry.json skills[]")
    for slug in sorted(registered - on_disk):
        warnings.append(f".agentlas/skill-registry.json: registers '{slug}' but skills/{slug}/SKILL.md does not exist")
    return warnings


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
        except Exception as err:  # the gate must not crash no matter what shape the card is
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
        # A scanner that looks for private paths has to contain the shape of one.
        # `scripts/verify-package.sh` carries the literal `'/Users/[a-zA-Z]+/'`
        # as its own search pattern, and this check flagged it as a leak in 90
        # published packages — the code that prevents the defect being read as
        # the defect. A match inside a character class or a quoted regex is a
        # pattern, not a path: a real leak names a person, `[a-zA-Z]+` does not.
        if _looks_like_a_pattern_not_a_path(text, match):
            continue
        relative = path.relative_to(workspace).as_posix()
        blockers.append(
            f"{relative}: contains an absolute host path; replace it with a package-relative path or remove generated runtime state"
        )
    return blockers


def _looks_like_a_pattern_not_a_path(text: str, match: re.Match[str]) -> bool:
    """True when the matched text is a regex describing a path, not a path.

    Deliberately narrow. It exempts a match containing regex metacharacters in
    the user-name position — `[a-zA-Z]+`, `\\w+`, `(?:[^/]+)` — and nothing else.
    A literal home-directory path still blocks, which is the whole point.
    """

    matched = match.group(0)
    return bool(re.search(r"\[[^\]]+\]|\\w|\\S|\(\?:|\.\*|\.\+", matched))


def _generated_runtime_blockers(workspace: Path) -> list[str]:
    """Keep bootstrap indexes and databases out of portable agent packages."""
    blockers: list[str] = []
    for relative in GENERATED_RUNTIME_PATHS:
        if (workspace / relative).exists():
            blockers.append(
                f"{relative}: generated local runtime state must not ship; remove it before delivery"
            )

    agentlas_dir = workspace / ".agentlas"
    if agentlas_dir.is_dir():
        for path in sorted(agentlas_dir.iterdir()):
            if not path.is_file():
                continue
            if any(path.name.startswith(prefix) for prefix in GENERATED_RUNTIME_FILE_PREFIXES):
                relative = path.relative_to(workspace).as_posix()
                blockers.append(
                    f"{relative}: generated local runtime state must not ship; remove it before delivery"
                )
    return blockers


def verify(folder: str | Path, mode: str = "single", root: str | Path | None = None) -> dict[str, Any]:
    """Machine-readable completeness gate. ``blockers`` is the list a model
    consumes for targeted self-repair; ``ok`` means routing-ready package."""
    base = Path(root) if root else engine_root()
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
    # Owner decision 2026-08-08 (R1): the A2A projection regenerates on every
    # build/verify, not only at publish. Refresh every derived artifact before
    # reading artifacts so this same verify() call sees its own output — each
    # generator is a no-op (writes nothing) until its sources are filled.
    refresh_generated_projections(workspace)
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
    # Generated runtime state is a cleanup item, not a blocker. The product
    # writes it: run any Hephaestus command with a package folder as the working
    # directory and the ontology runtime lands an `ontology-runtime.sqlite` and
    # its inbox in that package's `.agentlas/`. Measured 2026-08-07: repairing a
    # published package with an agent took its blocker count from 8 to 12, and
    # all four new blockers were files the agent's own runtime had just created.
    #
    # It is also already handled where it matters: `upload.py` filters these
    # paths out of the delivered artifact (`is_generated_runtime_path`, two call
    # sites), so nothing here can reach a buyer. Blocking on it only stops a
    # build from finishing work the delivery path was going to clean anyway.
    cleanup = _generated_runtime_blockers(workspace)
    warnings = [
        f"{report['path']}: {problem}"
        for report in reports
        if not report.get("required", True)
        for problem in report.get("problems", []) if problem != "missing"
    ]
    warnings.extend(cleanup)
    warnings.extend(_verify_skills_consistency(workspace))
    return {
        "workspace": str(workspace),
        "mode": mode,
        "ok": not blockers,
        "artifacts": reports,
        "blockers": blockers,
        "warnings": warnings,
        "cleanup": cleanup,
    }
