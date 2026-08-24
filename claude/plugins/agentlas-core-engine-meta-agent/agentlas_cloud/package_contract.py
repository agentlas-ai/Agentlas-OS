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
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

PLACEHOLDER_RE = re.compile(r"\{\{[A-Za-z0-9_]+\}\}")
CONTRACT_FILENAME = "package-contract.json"
HOST_PATH_RE = re.compile(
    r"(?:file://)?/(?:Users|home)/[^/\s\"'<>]+(?:/[^\s\"'<>]+)*"
    r"|[A-Za-z]:\\+Users\\+[^\\\s\"'<>]+(?:\\+[^\\\s\"'<>]+)*"
)
TEXT_SCAN_LIMIT_BYTES = 2 * 1024 * 1024
PACKAGE_PATH_SCAN_LIMIT = 10_000
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
        optional_when = artifact.get("optionalWhen") or []
        if marker == "required" and optional_when:
            marker += f"; optional only for explicit {', '.join(optional_when)} profile"
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
        # AGENTS.md carries a `## Team` section for every mode, and a single
        # agent has no team to list. Leaving `{{TEAM_ROLES}}` for the builder to
        # fill asked it to invent colleagues that do not exist, and every single
        # build failed verify on this one placeholder until it wrote something
        # untrue (measured 2026-08-17). Answer it here, correctly, for the modes
        # where the answer is already known.
        **(
            {}
            if mode == "team"
            else {"TEAM_ROLES": "This package is one agent. It has no internal roster;"
                                " collaboration happens through Agentlas staffing, not through"
                                " roles declared inside this package."}
        ),
    }


def _workspace_symlink_error(workspace: Path) -> dict[str, str] | None:
    """Reject package trees that could redirect a later mutation.

    Contract scaffold/complete/verify all write derived files.  A containment
    check on the final path is insufficient because an existing intermediate
    directory can be replaced by a symlink.  Walk without following links and
    fail before the first package write.  The bound matches the upload walk's
    fail-closed posture and prevents an adversarial tree from making preflight
    unbounded.
    """

    walked = 0
    pending = [workspace]
    while pending:
        directory = pending.pop()
        try:
            entries = os.scandir(directory)
        except OSError as error:
            return {
                "error": "workspace_unreadable",
                "message": f"package workspace could not be inspected safely: {directory}: {error}",
            }
        with entries:
            for entry in entries:
                walked += 1
                if walked > PACKAGE_PATH_SCAN_LIMIT:
                    return {
                        "error": "workspace_scan_limit",
                        "message": (
                            f"package workspace has more than {PACKAGE_PATH_SCAN_LIMIT} paths; "
                            "use a focused package folder"
                        ),
                    }
                relative = Path(entry.path).relative_to(workspace).as_posix()
                if entry.is_symlink():
                    return {
                        "error": "workspace_symlink_forbidden",
                        "message": f"symbolic links are not allowed in a mutable package workspace: {relative}",
                    }
                try:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                except OSError as error:
                    return {
                        "error": "workspace_unreadable",
                        "message": f"package path could not be inspected safely: {relative}: {error}",
                    }
    return None


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
    prohibited = {Path(workspace.anchor).resolve(), Path.home().resolve(), engine_root().resolve()}
    if workspace in prohibited:
        return {
            "error": "package_target_too_broad",
            "message": f"refusing broad or engine package target: {workspace}",
        }
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
    return _workspace_symlink_error(workspace)


def workspace_path_problem(folder: str | Path, *, must_exist: bool = True) -> dict[str, str] | None:
    """Public path preflight shared by CLI contract actions."""

    requested = Path(folder).expanduser()
    if requested.is_symlink():
        return {
            "error": "workspace_symlink_forbidden",
            "message": f"package workspace itself may not be a symbolic link: {requested}",
        }
    workspace = requested.resolve(strict=False)
    return _workspace_path_error(workspace, must_exist=must_exist)


def _require_safe_mutation_workspace(folder: str | Path) -> Path:
    problem = workspace_path_problem(folder, must_exist=True)
    if problem:
        raise ValueError(f"{problem['error']}: {problem['message']}")
    return Path(folder).expanduser().resolve()


def resolve_package_target(target: str, *, base: str | Path | None = None) -> dict[str, str]:
    """Resolve one explicit user-confirmed package target without guessing.

    Build adapters call this before any scaffold/complete/verify operation.  A
    missing value, shell glob, shorthand for the current directory, filesystem
    root, home directory, or the engine checkout is ambiguous or dangerously
    broad and must never collapse to the host's current working directory.
    """

    raw = str(target or "").strip()
    base_path = Path(base or Path.cwd()).expanduser().resolve()
    if not raw:
        return {
            "status": "error",
            "error": "package_target_required",
            "message": "an exact package folder must be explicitly named or confirmed by the user",
        }
    if any(character in raw for character in ("\x00", "\n", "\r")):
        return {
            "status": "error",
            "error": "package_target_invalid",
            "message": "package target contains a control character",
        }
    if any(character in raw for character in ("*", "?", "[", "]", "{", "}")):
        return {
            "status": "error",
            "error": "package_target_ambiguous",
            "message": "package target must name exactly one folder; globs and alternatives are not allowed",
        }
    normalized = raw.replace("\\", "/").rstrip("/") or "/"
    if normalized in {".", ".."} or normalized.startswith("../"):
        return {
            "status": "error",
            "error": "package_target_ambiguous",
            "message": "package target may not default to the current or parent workspace; provide the exact folder",
        }

    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = base_path / candidate
    if candidate.is_symlink():
        return {
            "status": "error",
            "error": "workspace_symlink_forbidden",
            "message": f"package workspace itself may not be a symbolic link: {candidate}",
        }
    package_root = candidate.resolve(strict=False)
    prohibited = {Path(package_root.anchor).resolve(), Path.home().resolve(), engine_root().resolve()}
    if package_root in prohibited:
        return {
            "status": "error",
            "error": "package_target_too_broad",
            "message": f"refusing broad or engine package target: {package_root}",
        }
    path_problem = _workspace_path_error(package_root, must_exist=False)
    if path_problem:
        return {"status": "error", **path_problem}
    return {
        "status": "ok",
        "package_target": raw,
        "package_root": str(package_root),
        "base": str(base_path),
    }


def _interview_evidence_problem(
    work_brief: str | Path | None,
    minimal_private_reason: str,
) -> dict[str, Any] | None:
    """Refuse to lay down package files before the interview happened.

    The interview was a request written in prose, and prose is optional: measured
    2026-08-17, two packages built through the same command came out 0 and 30
    blockers apart, and neither owner had been asked a question — one of them
    shipped a fully written `docs/builder-interview.md` for an interview that never
    took place. Blocking at `verify` is too late; by then the model has already
    written a package around answers nobody gave.

    Scaffold is the only sanctioned way to create the contract artifacts, so it is
    the chokepoint. No brief, no files.
    """
    if minimal_private_reason.strip():
        return None
    if not work_brief:
        return {
            "error": "interview_required",
            "message": (
                "Scaffold needs the interview result. Run the Builder Interview and "
                "Research Gate first, write the answers to a work-brief JSON, and pass "
                "--work-brief <path>. For an explicit user-confirmed minimal scaffold "
                "pass --minimal-private-reason \"<the user's own words>\"."
            ),
        }
    brief_path = Path(work_brief).expanduser()
    if not brief_path.is_file():
        return {"error": "work_brief_missing", "message": f"work brief not found: {brief_path}"}
    try:
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 - the caller needs the reason verbatim
        return {"error": "work_brief_unreadable", "message": str(exc)}
    if not isinstance(brief, dict):
        return {"error": "work_brief_invalid", "message": "work brief must be a JSON object"}
    goal = str(brief.get("goal") or "").strip()
    acceptance = brief.get("acceptance_criteria") or brief.get("acceptanceCriteria") or []
    if not goal or not isinstance(acceptance, list) or len(acceptance) == 0:
        return {
            "error": "work_brief_incomplete",
            "message": "work brief needs a non-empty `goal` and at least one `acceptance_criteria` entry",
        }
    return None


def scaffold(
    folder: str | Path,
    mode: str = "single",
    package_id: str = "",
    name: str = "",
    command: str = "",
    root: str | Path | None = None,
    work_brief: str | Path | None = None,
    minimal_private_reason: str = "",
) -> dict[str, Any]:
    """Copy contract templates into ``folder`` (never overwriting existing
    files) and substitute the identity placeholders we already know. Model
    placeholders ({{TRIGGER_KO_1}}...) stay for the fill step.

    Refuses without interview evidence — see ``_interview_evidence_problem``."""
    gate = _interview_evidence_problem(work_brief, minimal_private_reason)
    if gate:
        return {
            "workspace": str(Path(folder).expanduser()),
            "mode": mode,
            "package_id": package_id,
            "created": [],
            "skipped_existing": [],
            "missing_templates": [],
            **gate,
        }
    base = Path(root) if root else engine_root()
    requested_workspace = Path(folder).expanduser()
    workspace = requested_workspace.resolve(strict=False)
    path_error = workspace_path_problem(requested_workspace, must_exist=False)
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

    artifacts = artifacts_for_mode(load_contract(base), mode)
    for artifact in artifacts:
        if "*" in artifact["path"]:
            continue
        _, target_problem = _safe_package_target(workspace, artifact["path"], label="artifact path")
        if target_problem:
            return {
                "workspace": str(workspace),
                "mode": mode,
                "package_id": package_id,
                "created": [],
                "skipped_existing": [],
                "missing_templates": [],
                "error": "workspace_symlink_forbidden",
                "message": target_problem,
            }

    created: list[str] = []
    skipped: list[str] = []
    missing_templates: list[str] = []
    missing_required_templates: list[str] = []
    for artifact in artifacts:
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
            if artifact.get("required", True):
                missing_required_templates.append(template_ref)
            continue
        text = template_path.read_text(encoding="utf-8")
        for key, value in subs.items():
            text = text.replace("{{" + key + "}}", value)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        created.append(artifact["path"])
    # The work brief is both the evidence that an interview happened and a
    # required artifact of the package. Scaffold used to read it only as
    # evidence and then throw it away, so a build that answered every question
    # still failed verify on `.agentlas/work-brief.json: missing` and the model
    # was asked to rewrite, from memory, the answers the host already had on
    # disk (measured 2026-08-17). Copy it in — it is never overwritten, so a
    # brief the builder has since improved always wins.
    if work_brief:
        brief_target = workspace / ".agentlas" / "work-brief.json"
        if not brief_target.exists():
            try:
                brief_doc = json.loads(Path(work_brief).expanduser().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                brief_doc = None
            if isinstance(brief_doc, dict):
                brief_target.parent.mkdir(parents=True, exist_ok=True)
                brief_target.write_text(
                    json.dumps(brief_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
                )
                created.append(".agentlas/work-brief.json")
    # ★어느 엔진으로 지었는지를 패키지에 남긴다. 이게 없으면 그 패키지는 나중에
    #   자기가 낡았다고 말할 수 없다 — 실측 2026-08-19: 로컬 에이전트 7개 중 6개가
    #   지금 계약에 떨어지는데, 어느 것도 언제 지어졌는지 몰라 리패징 대상인지
    #   판단할 근거가 없었다. 엔진 버전을 모르면 찍지 않는다("unknown" 을 찍으면
    #   그 값이 나중에 거짓 드리프트를 만든다).
    try:
        from .engine_stamp import STAMP_REL, write_stamp  # noqa: PLC0415

        if write_stamp(workspace):
            created.append(str(STAMP_REL))
    except Exception:
        pass  # 스탬프 실패가 빌드를 막지는 않는다 — 없으면 unstamped 로 보고된다
    adapter_report = materialize_declared_command_adapters(workspace, package_id)
    report: dict[str, Any] = {
        "workspace": str(workspace),
        "mode": mode,
        "package_id": package_id,
        "created": created,
        "skipped_existing": skipped,
        "missing_templates": missing_templates,
        "created_adapters": adapter_report["written"],
        "adapter_warnings": adapter_report["warnings"],
    }
    if missing_required_templates:
        report.update(
            {
                "error": "required_template_missing",
                "message": "required package template(s) are missing from the engine",
                "missing_required_templates": sorted(set(missing_required_templates)),
            }
        )
    return report


def _safe_package_target(
    workspace: Path, relative_path: str, *, label: str = "package path"
) -> tuple[Path | None, str | None]:
    """Resolve one package-relative mutation target without following links."""

    raw = str(relative_path or "").strip().replace("\\", "/")
    if not raw:
        return None, f"{label} must be a non-empty package-relative path"
    if raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        return None, f"{label} must be package-relative: {raw}"
    relative = Path(raw)
    if any(part in {"", ".", ".."} for part in relative.parts):
        return None, f"{label} contains an unsafe segment: {raw}"
    target = workspace.joinpath(*relative.parts)
    try:
        target.resolve(strict=False).relative_to(workspace.resolve())
    except (OSError, ValueError):
        return None, f"{label} escapes the package: {raw}"
    cursor = workspace
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            return None, f"{label} traverses a symbolic link: {raw}"
    return target, None


def _safe_adapter_target(workspace: Path, adapter_path: str) -> tuple[Path | None, str | None]:
    """Resolve a declared adapter path without allowing package escape."""

    return _safe_package_target(workspace, adapter_path, label="adapterPath")


def _command_adapter_body(runtime: str, command: str, slug: str, target: Path) -> str:
    command_name = command.lstrip("/") or slug
    if target.suffix == ".toml":
        return (
            f'description = "Run {command_name} from its Agentlas package contract."\n'
            'prompt = """\n'
            f"Run `/{command_name}` by reading the package-root `AGENTS.md` first.\n"
            "Treat `.agentlas/global-commands.json` as the command declaration and keep\n"
            "all package reads and writes inside the package root.\n"
            '"""\n'
        )
    if runtime == "agentlas-terminal" or target.parts[-2:-1] == ("bin",):
        return (
            "#!/usr/bin/env sh\n"
            "set -eu\n"
            f'exec "${{AGENTLAS_CLI:-agentlas}}" run "{command_name}" "$@"\n'
        )
    return (
        f"# /{command_name}\n\n"
        "Read the package-root `AGENTS.md` as the canonical instructions.\n\n"
        "Use `.agentlas/global-commands.json` for this command's runtime declaration.\n"
        "Keep package reads and writes inside the package root and preserve authored files.\n"
    )


def materialize_declared_command_adapters(workspace: Path, slug: str = "") -> dict[str, list[str]]:
    """Create missing files promised by `.agentlas/global-commands.json`.

    The command table is executable package structure, not documentation. This
    pass never overwrites authored content; it only creates absent thin adapters
    and restores the executable bit on a declared terminal adapter.
    """

    workspace = _require_safe_mutation_workspace(workspace)
    commands_path = workspace / ".agentlas" / "global-commands.json"
    try:
        payload = json.loads(commands_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"written": [], "warnings": []}
    rows = payload.get("commands") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return {"written": [], "warnings": []}

    package_slug = str(slug or payload.get("packageId") or workspace.name).strip()
    written: list[str] = []
    warnings: list[str] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not row.get("adapterPath"):
            continue
        relative = str(row["adapterPath"]).replace("\\", "/")
        target, problem = _safe_adapter_target(workspace, relative)
        if problem or target is None:
            warnings.append(f"commands[{index}]: {problem}")
            continue
        runtime = str(row.get("runtime") or "")
        if target.exists():
            if runtime == "agentlas-terminal" and target.is_file() and not os.access(target, os.X_OK):
                target.chmod(target.stat().st_mode | 0o111)
                written.append(f"{relative} (made executable)")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            _command_adapter_body(runtime, str(row.get("command") or ""), package_slug, target),
            encoding="utf-8",
        )
        if runtime == "agentlas-terminal":
            target.chmod(target.stat().st_mode | 0o111)
        written.append(relative)
    return {"written": written, "warnings": warnings}


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
    workspace = _require_safe_mutation_workspace(workspace)
    card = project_a2a_card(workspace)
    if card is None:
        return None
    target, target_problem = _safe_package_target(
        workspace, "A2A/agent-card.a2a.json", label="A2A projection path"
    )
    if target_problem or target is None:
        raise ValueError(target_problem or "unsafe A2A projection path")
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
    target, target_problem = _safe_package_target(
        workspace, relative_path, label="generated projection path"
    )
    if target_problem or target is None:
        raise ValueError(target_problem or f"unsafe generated projection path: {relative_path}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target.relative_to(workspace).as_posix()


def refresh_generated_projections(workspace: Path) -> list[str]:
    """Refresh every derived (never-hand-authored) artifact this package
    contract now owns. Called from verify() — never from scaffold(), whose
    sources are still unfilled ``{{PLACEHOLDER}}`` templates at that point —
    so the same verify() call always sees its own freshly written output."""
    workspace = _require_safe_mutation_workspace(workspace)
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
        target, target_problem = _safe_package_target(
            workspace, "provenance.json", label="provenance projection path"
        )
        if target_problem or target is None:
            raise ValueError(target_problem or "unsafe provenance projection path")
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


@lru_cache(maxsize=8)
def _local_schema_registry(schema_directory: str) -> Any:
    """Build a no-network registry for every schema shipped with this engine."""

    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012

    registry = Registry()
    for candidate in sorted(Path(schema_directory).glob("*.schema.json")):
        payload = json.loads(candidate.read_text(encoding="utf-8"))
        resource = Resource.from_contents(payload, default_specification=DRAFT202012)
        uris = {candidate.resolve().as_uri(), payload.get("$id")}
        for uri in sorted(value for value in uris if isinstance(value, str) and value):
            registry = registry.with_resource(uri, resource)
    return registry


def _schema_shape_errors(doc: Any, schema_path: Path) -> list[str]:
    """Validate an artifact with the complete declared JSON Schema draft.

    Draft 2020-12 is the default for schemas without an explicit meta-schema;
    older declared drafts remain standards-complete through ``validator_for``.
    References resolve only from the bundled schema directory, so validation
    never performs a network fetch. Missing validator dependencies, malformed
    schemas, and unresolved references fail closed as package blockers.
    """

    # Scaffold placeholders are already an explicit blocker. Deferring schema
    # validation until they are filled avoids reporting secondary oneOf and
    # pattern failures for a document that is not an instance yet.
    if PLACEHOLDER_RE.search(json.dumps(doc, ensure_ascii=False)):
        return []

    try:
        from jsonschema import Draft202012Validator
        from jsonschema.exceptions import SchemaError
        from jsonschema.validators import validator_for

        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        validator_class = validator_for(schema, default=Draft202012Validator)
        validator_class.check_schema(schema)
        validator = validator_class(
            schema,
            registry=_local_schema_registry(str(schema_path.parent.resolve())),
            format_checker=validator_class.FORMAT_CHECKER,
        )
        issues = sorted(
            validator.iter_errors(doc),
            key=lambda issue: (
                tuple(str(part) for part in issue.absolute_path),
                tuple(str(part) for part in issue.absolute_schema_path),
            ),
        )
    except ImportError as error:
        # This stays a blocker: a schema nobody checked is not a schema that
        # passed. But the user is not the one who broke it, and the old message
        # ("schema validation unavailable: rpds") named a transitive dependency
        # and left them nothing to do — measured 2026-08-17 on a build where
        # three of the remaining blockers were this line and the package itself
        # was fine. Say which interpreter is missing what, and how to fix it.
        import sys as _sys

        missing = error.name or str(error)
        return [
            f"schema validation unavailable: {_sys.executable} cannot import '{missing}'."
            f" Install it for that interpreter (`{_sys.executable} -m pip install jsonschema`)"
            " and run this check again — the package is not being judged until it can run."
        ]
    except (OSError, ValueError, SchemaError) as error:
        return [f"schema invalid or unreadable: {schema_path.name}: {error}"]
    except Exception as error:
        return [f"schema validation failed closed: {schema_path.name}: {error}"]

    problems: list[str] = []
    for issue in issues:
        location = "$"
        for part in issue.absolute_path:
            location += f"[{part}]" if isinstance(part, int) else f".{part}"
        problems.append(f"{location}: {issue.message}")
    return problems


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


QUALITY_DOC_SECTIONS: dict[str, tuple[str, ...]] = {
    "builder-interview": ("## Request", "## Mode", "## Answers", "## Assumptions", "## Follow-Ups"),
    "research-sources": (
        "## Similar Agent And Repository Research",
        "## Academic Or Professional Theory Research",
        "## Synthesis",
        "## Rejected Sources Or Ideas",
    ),
    "tool-selection": ("## Fallbacks", "## Blocked Or Unavailable Tools"),
    "domain-expert-synthesis": (
        "## Target Expertise",
        "## Interview-Derived Requirements",
        "## Similar Agent And Repository Patterns",
        "## Academic Or Professional Theory Basis",
        "## Tool And Plugin Reasoning",
        "## Prompt Architecture Decisions",
        "## Domain Heuristics And Decision Rules",
        "## Examples And Counterexamples",
        "## Evaluation Cases Derived From Research",
        "## Open Assumptions",
    ),
    "prompt-performance-contract": (
        "## Identity",
        "## Non-Goals",
        "## Operating Loop",
        "## Input Contract",
        "## Output Contract",
        "## Tool And Plugin Policy",
        "## Memory And Freshness Policy",
        "## Domain Heuristics",
        "## Source-To-Prompt Trace",
        "## Examples",
        "## Evaluation Rubric",
        "## Escalation And Refusal",
    ),
}


def _quality_doc_problems(text: str, lint_name: str) -> list[str]:
    return [f"missing required section: {heading}" for heading in QUALITY_DOC_SECTIONS[lint_name] if heading not in text]


def _work_brief_problems(doc: dict[str, Any]) -> list[str]:
    from .interview.schema import work_brief_problem

    problems: list[str] = []
    consumer_problem = work_brief_problem(doc)
    if consumer_problem:
        problems.append(consumer_problem)
        return problems
    for field in ("constraints", "acceptance_criteria", "anti_scope", "assumptions", "deferred", "evaluation_principles", "exit_conditions"):
        if field not in doc:
            problems.append(f"missing interview field: {field}")
        elif not isinstance(doc[field], list):
            problems.append(f"{field} must be a list")
    for field in ("acceptance_criteria", "anti_scope", "evaluation_principles", "exit_conditions"):
        if isinstance(doc.get(field), list) and not doc[field]:
            problems.append(f"{field} must not be empty")
    metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
    if metadata.get("surface") != "hep-build":
        problems.append("metadata.surface must be 'hep-build'")
    score = metadata.get("ambiguity_score")
    try:
        ambiguity = float(score)
    except (TypeError, ValueError):
        problems.append("metadata.ambiguity_score must be numeric")
    else:
        if ambiguity > 0.2:
            problems.append(f"metadata.ambiguity_score must be <= 0.2 (found {ambiguity:g})")
    return problems


def _capability_eval_problems(doc: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    if doc.get("schemaVersion") != "agentlas-capability-eval-plan/1.0":
        problems.append("schemaVersion must be agentlas-capability-eval-plan/1.0")
    positive = doc.get("positive_cases")
    negative = doc.get("negative_cases")
    if not isinstance(positive, list):
        problems.append("positive_cases must be a list")
        positive = []
    if not isinstance(negative, list):
        problems.append("negative_cases must be a list")
        negative = []
    if len(positive) < 10:
        problems.append(f"positive_cases needs >=10 cases (has {len(positive)})")
    if len(negative) < 5:
        problems.append(f"negative_cases needs >=5 cases (has {len(negative)})")
    for index, case in enumerate(positive):
        if not isinstance(case, dict):
            problems.append(f"positive_cases[{index}] must be an object")
            continue
        if not str(case.get("prompt") or "").strip():
            problems.append(f"positive_cases[{index}].prompt is required")
        if not isinstance(case.get("expected_artifacts"), list) or not case["expected_artifacts"]:
            problems.append(f"positive_cases[{index}].expected_artifacts must not be empty")
        if not isinstance(case.get("pass_criteria"), list) or not case["pass_criteria"]:
            problems.append(f"positive_cases[{index}].pass_criteria must not be empty")
    for index, case in enumerate(negative):
        if not isinstance(case, dict):
            problems.append(f"negative_cases[{index}] must be an object")
            continue
        if not str(case.get("prompt") or "").strip():
            problems.append(f"negative_cases[{index}].prompt is required")
        if not str(case.get("expected_behavior") or "").strip():
            problems.append(f"negative_cases[{index}].expected_behavior is required")
    if not isinstance(doc.get("tool_smoke_checks"), list):
        problems.append("tool_smoke_checks must be a list")
    return problems


def _minimal_private_profile_active(workspace: Path) -> bool:
    """Recognize only the complete user-confirmed private opt-out receipt.

    This deliberately duplicates the security-significant constants from the
    JSON Schema.  Verification must decide artifact requiredness before it can
    produce per-artifact schema reports, so an incomplete, misspelled, or
    model-asserted opt-out always falls back to the strict profile.
    """

    profile = _read_json(workspace / ".agentlas" / "build-profile.json")
    if not isinstance(profile, dict):
        return False
    opt_out = profile.get("minimalPrivateOptOut")
    return bool(
        profile.get("schemaVersion") == "agentlas-build-profile/1.0"
        and profile.get("profile") == "minimal-private"
        and isinstance(opt_out, dict)
        and opt_out.get("requestedBy") == "user"
        and opt_out.get("confirmed") is True
        and opt_out.get("publicMarketplaceReady") is False
        and isinstance(opt_out.get("reason"), str)
        and opt_out["reason"].strip()
    )


def _global_command_adapter_problems(workspace: Path, doc: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    rows = doc.get("commands")
    if not isinstance(rows, list):
        return problems
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or "adapterPath" not in row:
            continue
        relative = str(row.get("adapterPath") or "").replace("\\", "/")
        target, problem = _safe_adapter_target(workspace, relative)
        if problem or target is None:
            problems.append(f"commands[{index}]: {problem}")
            continue
        if not target.is_file():
            problems.append(f"commands[{index}].adapterPath missing: {relative}")
            continue
        try:
            target.resolve().relative_to(workspace.resolve())
        except (OSError, ValueError):
            problems.append(f"commands[{index}].adapterPath escapes the package: {relative}")
            continue
        if row.get("runtime") == "agentlas-terminal" and not os.access(target, os.X_OK):
            problems.append(f"commands[{index}].adapterPath is not executable: {relative}")
    return problems


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

    lint_name = artifact.get("lint") or {
        ".agentlas/global-commands.json": "global-command-adapters",
        ".agentlas/capability-eval-plan.json": "capability-eval-plan",
        ".agentlas/work-brief.json": "work-brief",
        "docs/builder-interview.md": "builder-interview",
        "docs/research-sources.md": "research-sources",
        "docs/tool-selection.md": "tool-selection",
        "docs/domain-expert-synthesis.md": "domain-expert-synthesis",
        "docs/prompt-performance-contract.md": "prompt-performance-contract",
    }.get(str(artifact.get("path") or ""))
    if lint_name in QUALITY_DOC_SECTIONS:
        problems.extend(_quality_doc_problems(text, str(lint_name)))
    if lint_name == "work-brief" and isinstance(doc, dict):
        problems.extend(_work_brief_problems(doc))
    if lint_name == "capability-eval-plan" and isinstance(doc, dict):
        problems.extend(_capability_eval_problems(doc))
    if lint_name == "global-command-adapters" and isinstance(doc, dict):
        problems.extend(_global_command_adapter_problems(workspace, doc))

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


def _restamp_package_hashes(workspace: Path) -> None:
    """Make verify() the local build's "last writer is last hasher" chokepoint.

    upload.py already enforces this ordering for published packages (its wizard
    is the last writer AND the last hasher), but a locally built package never
    runs that path, so `agentlas.json.packageHash` and the routing card's
    `source.package_hash` stayed frozen at whatever byte snapshot existed when
    each was first stamped. verify() itself then mutated the tree via
    refresh_generated_projections(). Measured 2026-08-12 on both `.builds`
    packages: three different stamped hashes for one tree. Restamping here —
    after the projections, before the artifact checks — means a green verify
    always leaves every stamped hash describing the final bytes.

    Safe against self-reference: `agentlas.json` is in
    PACKAGE_HASH_EXCLUDED_PATHS and the routing card's own refresh excludes the
    card file from its hash.
    """
    manifest_path = workspace / "agentlas.json"
    manifest = _read_json(manifest_path)
    if manifest is None:
        return
    # `packageHash` is the one placeholder this function exists to fill, so it
    # must not be a reason to skip. The template ships
    # `"packageHash": "sha256:{{PACKAGE_HASH}}"`, `_unfilled()` saw that token and
    # returned early, and the only code able to replace it never ran — so every
    # locally built package carried an unfillable blocker forever, and the model
    # was left to invent a sixty-four character hash by hand (measured
    # 2026-08-17: `agentlas.json: unfilled placeholders: {{PACKAGE_HASH}}` on a
    # package whose every other file was complete).
    #
    # Any OTHER placeholder still means the package is mid-build: hashing a tree
    # with unfilled prose in it would stamp a number that stops describing the
    # package the moment someone finishes writing it.
    without_hash = {key: value for key, value in manifest.items() if key != "packageHash"}
    if _unfilled(without_hash):
        return
    # Card first, manifest second — the card refresh WRITES the routing card,
    # so stamping the manifest before it would hash a tree that is about to
    # change (the exact ordering bug upload.py documents for its wizard).
    if (workspace / ".agentlas" / "routing-card.json").is_file():
        from .upload import refresh_routing_card_metadata

        # Settle the card's semantic content (workforce block) first, then
        # re-project A2A from the settled card, then hash. Without the middle
        # step the A2A written earlier in verify() described the pre-settle
        # card, so the SECOND verify changed A2A and every hash with it —
        # verify was not a fixed point (measured 2026-08-12).
        refresh_routing_card_metadata(workspace)
        write_a2a_projection(workspace)
        refresh_routing_card_metadata(workspace)
    from .runtime import collect_package_files, package_hash, package_hash_includes

    manifest["packageHash"] = package_hash(
        [item for item in collect_package_files(workspace) if package_hash_includes(item.path)]
    )
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _engine_drift(workspace: Path) -> dict[str, Any]:
    """엔진 스탬프 판정. 이 검사가 실패해도 계약 검증 전체를 죽이지 않는다."""
    try:
        from .engine_stamp import drift  # noqa: PLC0415

        return drift(workspace)
    except Exception as exc:  # noqa: BLE001
        return {"state": "unknown_engine", "builtWith": None, "engineVersion": None,
                "action": f"엔진 스탬프를 읽지 못했습니다: {exc}"}


def verify(folder: str | Path, mode: str = "single", root: str | Path | None = None) -> dict[str, Any]:
    """Machine-readable completeness gate. ``blockers`` is the list a model
    consumes for targeted self-repair; ``ok`` means routing-ready package."""
    base = Path(root) if root else engine_root()
    workspace = Path(folder).expanduser().resolve(strict=False)
    path_error = workspace_path_problem(folder, must_exist=True)
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
    _restamp_package_hashes(workspace)
    build_profile = "minimal-private" if _minimal_private_profile_active(workspace) else "standard"
    reports = []
    for artifact in artifacts_for_mode(load_contract(base), mode):
        effective_artifact = dict(artifact)
        if build_profile in (artifact.get("optionalWhen") or []):
            effective_artifact["required"] = False
        reports.append(_verify_artifact(workspace, effective_artifact, base))
    # 신품 맥(시스템 파이썬 3.9, jsonschema 미설치)에서는 스키마 검증 의존성이
    # 없어 모든 verify 가 영구 차단됐다 — 실측 2026-08-24 격리 신규 환경.
    # 로컬 verify 에서는 이를 '검증 축소' 경고로 강등해 작업을 막지 않되,
    # 보고서에 schemaValidation="unavailable" 을 남겨 발행(upload) 경로가
    # 그대로 차단할 수 있게 한다 — 검증 안 된 패키지가 시장에 나가면 안 된다.
    blockers = []
    schema_unavailable: list[str] = []
    for report in reports:
        if not report.get("required", True):
            continue
        for problem in report.get("problems", []):
            line = f"{report['path']}: {problem}"
            if problem.startswith("schema validation unavailable:"):
                schema_unavailable.append(line)
            else:
                blockers.append(line)
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
    if build_profile == "minimal-private":
        warnings.append(
            "minimal-private opt-out is active; this package is private-only and is not public or marketplace ready"
        )
    warnings.extend(schema_unavailable)
    return {
        "workspace": str(workspace),
        "mode": mode,
        "ok": not blockers,
        "artifacts": reports,
        "blockers": blockers,
        "warnings": warnings,
        "cleanup": cleanup,
        "build_profile": build_profile,
        # "full" 은 스키마 검증이 실제로 돌았다는 뜻이고, "unavailable" 은 이
        # 환경에 검증기가 없어 축소 검증만 했다는 뜻이다. 발행 경로는 이 값이
        # unavailable 이면 차단한다.
        "schemaValidation": "unavailable" if schema_unavailable else "full",
        "public_marketplace_ready": bool(
            not blockers and not schema_unavailable and build_profile == "standard"
        ),
        # ★이 패키지가 어느 엔진으로 지어졌는지, 지금 엔진과 어긋나는지. 판정만 싣고
        #   자동으로 고치지 않는다 — 무엇을 고칠지는 위 blockers 가 이미 말한다.
        #   실측 2026-08-19: 로컬 에이전트 7개 중 6개가 계약에 떨어졌는데, 어느 것도
        #   자기가 낡았다고 말할 수 없었다(패키지에 엔진 버전이 없었다).
        "engine_drift": _engine_drift(workspace),
    }
