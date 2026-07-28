"""Safely import one explicit local agent root into OS-owned storage.

There is intentionally no discovery scan in this module.  A caller supplies a
single root.  Native packages are copied without modifying their routing card;
legacy packages are wrapped and migrated only inside Agentlas-owned staging.
"""

from __future__ import annotations

import errno
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..experience_contracts import ContractValidationError, validate_mcp_policy
from ..networking.bootstrap import atomic_write_json, read_json
from ..networking.card_lint import VALID_STATUSES, VERB_CAPABILITY_RE, lint_card
from ..networking.card_migrate import migrate_package
from ..runtime import (
    PackageFile,
    SECRET_PATTERNS,
    TEXT_FILE_ALLOW,
    build_manifest,
    is_value_free_credential_template,
    package_hash,
)


LOCAL_PACKAGE_ADAPTER_VERSION = "agentlas.local-package-adapter.v1"
_AGENT_MARKERS = ("agent.md", "AGENT.md", "AGENTS.md", "CLAUDE.md")
_TEAM_MARKERS = ("TEAM.md", "team.md")
_IGNORED_DIRS = frozenset({".git", "node_modules", "__pycache__", ".pytest_cache"})
_MAX_SOURCE_FILES = 4096
_MAX_SOURCE_BYTES = 32 * 1024 * 1024
# Built from the limits themselves so the numbers the user is told can never
# drift from the numbers actually enforced.
_SOURCE_LIMIT_REMEDIATION = (
    f"A registrable root may snapshot at most {_MAX_SOURCE_FILES} text files and "
    f"{_MAX_SOURCE_BYTES // (1024 * 1024)} MB in total. Register the package folder itself rather than a "
    "parent workspace, or move build output and vendored dependencies out of it."
)
_ALLOWED_HIDDEN_ROOTS = frozenset({".agentlas", ".agents", ".claude", ".codex", ".gemini"})
_ALLOWED_EXTENSIONLESS = frozenset(
    {*_AGENT_MARKERS, *_TEAM_MARKERS, "README", "LICENSE", "NOTICE"}
)
_SENSITIVE_NAMES = frozenset(
    {
        ".env",
        ".npmrc",
        ".pypirc",
        ".netrc",
        "credentials.json",
        "credentials",
        "secrets.json",
        "secrets",
        "cookies.json",
        "id_rsa",
        "id_ed25519",
    }
)
_SENSITIVE_NAME_RE = re.compile(r"(?:^|[._-])(secret|credential|password|private[-_]?key|access[-_]?token)(?:[._-]|$)", re.I)
_SECURE_DIR_FD_AVAILABLE = bool(
    os.name != "nt"
    and getattr(os, "O_DIRECTORY", 0)
    and getattr(os, "O_NOFOLLOW", 0)
    and os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
    and os.scandir in os.supports_fd
)


class PackageAdaptationError(ValueError):
    """One refusal carrying the code, the human reason, and how to fix it.

    ``code`` is the machine reason a projection consumer switches on; the
    message has always been written here but only the code reached the user,
    so `workforce local-register` refused with `source_missing` and a digest
    and never said the folder does not exist. Remediation belongs at the raise
    site because only this code knows what would make the source acceptable —
    a table of remediation strings kept elsewhere drifts away from the check.
    Same contract the sibling `agentlas-cloud package` surface already honors
    per finding: message plus optional remediation.
    """

    def __init__(self, code: str, message: str, remediation: str | None = None):
        self.code = code
        self.remediation = remediation
        super().__init__(message)


def refusal_fields(error: BaseException) -> dict[str, str]:
    """Forward the words a coded refusal already wrote, beside its code.

    `_quarantine` was not the only emitter that reduced one of these errors to
    `error.code`. Every generic workforce handler does `getattr(exc, "code",
    str(exc))`, which prefers the internal enum and discards the sentence the
    raise site wrote — so the same `source_missing` reaches the CLI and the MCP
    host as a bare token by a second route. Adding fields is safe for consumers
    that switch on the code, so emitters keep `error` and gain the words.

    Closed wire enumerations (`WorkforceSourceError`, `ContextMapError`)
    construct their message *as* the code; they carry no extra sentence, so
    this returns nothing for them rather than echoing the code twice. Errors
    without a code (plain `OSError`) already surface `str(exc)` as the error
    itself and are likewise left alone.
    """

    code = getattr(error, "code", "")
    if not isinstance(code, str) or not code:
        return {}
    fields: dict[str, str] = {}
    message = str(error)
    if message and message != code:
        fields["message"] = message
    remediation = getattr(error, "remediation", None)
    if isinstance(remediation, str) and remediation:
        fields["remediation"] = remediation
    return fields


@dataclass(frozen=True)
class PackageInspection:
    source_root: Path
    source_kind: str
    entity_kind: str
    name: str
    summary: str
    entrypoint: str
    package_hash: str
    routing_card: dict[str, Any] | None
    manifest: dict[str, Any]
    mcp_requirements: tuple[dict[str, Any], ...]
    team_graph: dict[str, Any] | None
    source_files: tuple[PackageFile, ...]
    skill_names: tuple[str, ...]
    worker_names: tuple[str, ...]


@dataclass(frozen=True)
class AdaptedPackage:
    package_root: Path
    routing_card: dict[str, Any]
    manifest: dict[str, Any]
    mcp_requirements: tuple[dict[str, Any], ...]
    team_graph: dict[str, Any] | None


def _json_object(path: Path) -> dict[str, Any]:
    """Read an Agentlas-owned staging file, never an import source file."""

    value = read_json(path, default=None)
    return dict(value) if isinstance(value, Mapping) else {}


def _snapshot_file_map(files: tuple[PackageFile, ...]) -> dict[str, str]:
    """Return the one immutable source snapshot used by every parser."""

    return {item.path: item.content for item in files}


def _snapshot_json(files: Mapping[str, str], relative_path: str) -> dict[str, Any]:
    raw = files.get(relative_path)
    if raw is None:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


def _safe_source_files(root: Path) -> tuple[PackageFile, ...]:
    """Read one bounded snapshot anchored to a no-follow root directory fd.

    ``os.walk`` plus ``O_NOFOLLOW`` on only the final filename is not enough:
    an attacker can replace an already-inspected ancestor directory with a
    symlink between the walk and the file open.  Every lookup below is relative
    to a held directory fd, so renames do not retarget later reads.
    """

    if not _secure_dir_fd_available():
        # A path-based fallback would silently reintroduce the ancestor-swap
        # race (notably on Windows, where Python's dir_fd APIs are absent).
        raise PackageAdaptationError(
            "source_secure_snapshot_unavailable",
            "this platform cannot safely snapshot a mutable local package",
            "This OS/Python build lacks the directory-handle APIs the safe snapshot needs, so no local root can be registered here. Use a host where they are available, or borrow the package from Cloud/Hub instead of registering it locally.",
        )
    absolute_root = Path(os.path.abspath(os.fspath(root.expanduser())))
    root_fd = _open_absolute_directory(absolute_root)
    files: list[PackageFile] = []
    total = 0
    read_files = 0

    def visit(directory_fd: int, relative_parts: tuple[str, ...]) -> None:
        nonlocal read_files, total
        try:
            with os.scandir(directory_fd) as entries:
                names = sorted(entry.name for entry in entries)
        except OSError as exc:
            raise PackageAdaptationError(
                "source_read_failed", "package directory could not be read safely"
            ) from exc

        directories: list[str] = []
        regular_files: list[str] = []
        for name in names:
            try:
                metadata = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError as exc:
                raise PackageAdaptationError(
                    "source_changed_during_snapshot",
                    "package changed while its safe snapshot was being captured",
                ) from exc
            if stat.S_ISLNK(metadata.st_mode):
                raise PackageAdaptationError(
                    "source_symlink_forbidden", "package paths cannot be symlinks"
                )
            if stat.S_ISDIR(metadata.st_mode):
                if name in _IGNORED_DIRS:
                    continue
                if not relative_parts and name.startswith(".") and name not in _ALLOWED_HIDDEN_ROOTS:
                    continue
                directories.append(name)
            elif stat.S_ISREG(metadata.st_mode):
                regular_files.append(name)

        # Match os.walk's stable ordering: files in this directory first, then
        # each child directory recursively.
        for name in regular_files:
            parts = (*relative_parts, name)
            relative_path = "/".join(parts)
            lowered = name.lower()
            suffix = Path(name).suffix
            # The Output Contract orders the packager to emit these; refusing
            # them refuses the OS's own build product. They stay under the
            # SECRET_PATTERNS content scan below, which is the check that
            # actually reads values.
            contract_template = is_value_free_credential_template(relative_path)
            if not contract_template and (
                lowered in _SENSITIVE_NAMES
                or lowered.startswith(".env.")
                # A name rule cannot tell a credential store from prose about
                # one. Markdown in this OS is documentation by construction —
                # ARCHITECTURE.md lists `docs/local-credential-store.md` in the
                # canonical core — so for Markdown the content scan decides.
                or (_SENSITIVE_NAME_RE.search(lowered) and suffix.lower() != ".md")
            ):
                raise PackageAdaptationError(
                    "source_sensitive_file_forbidden",
                    "package contains a credential-like file",
                    "Refused at "
                    + relative_path
                    + ". Move credential files out of the package root (or under an ignored directory) and register again."
                    + " The value-free templates the Output Contract asks for — .env.example, signing/README.md,"
                    + " credentials/README.md — are accepted as-is.",
                )
            # A contract template keeps a suffix the text allowlist does not
            # know (`.example`). Dropping it here would register a package
            # silently missing the file that tells a borrower which keys to set.
            if not contract_template and (
                (not suffix and name not in _ALLOWED_EXTENSIONLESS)
                or (suffix and suffix not in TEXT_FILE_ALLOW)
            ):
                continue
            if read_files >= _MAX_SOURCE_FILES:
                raise PackageAdaptationError(
                    "source_too_large",
                    "package exceeds local import limits",
                    _SOURCE_LIMIT_REMEDIATION,
                )
            read_files += 1
            raw = _bounded_regular_file_bytes_at(
                directory_fd,
                name,
                remaining=_MAX_SOURCE_BYTES - total,
            )
            # Invalid UTF-8 is not packaged, but it still consumed source I/O
            # and therefore must count against the aggregate snapshot budget.
            total += len(raw)
            try:
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                continue
            if any(pattern.search(text) for pattern in SECRET_PATTERNS):
                raise PackageAdaptationError(
                    "source_secret_material_forbidden",
                    "package text contains secret-like material",
                    "Refused at "
                    + "/".join(parts)
                    + ". Replace the literal key/token with a placeholder or an env-var reference and register again.",
                )
            files.append(PackageFile("/".join(parts), text))

        for name in directories:
            child_fd = _open_directory_at(directory_fd, name)
            try:
                visit(child_fd, (*relative_parts, name))
            finally:
                os.close(child_fd)

    try:
        visit(root_fd, ())
    finally:
        os.close(root_fd)
    return tuple(files)


def _secure_dir_fd_available() -> bool:
    return _SECURE_DIR_FD_AVAILABLE


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _open_absolute_directory(path: Path) -> int:
    """Open every canonical path component without following a symlink."""

    if not path.is_absolute():
        raise PackageAdaptationError("source_read_failed", "package root must be absolute")
    flags = _directory_open_flags()
    try:
        descriptor = os.open(path.anchor, flags)
    except OSError as exc:
        raise PackageAdaptationError("source_read_failed", "package root could not be opened safely") from exc
    try:
        for component in path.parts[1:]:
            child = _open_directory_at(descriptor, component, root_lookup=True)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _open_directory_at(parent_fd: int, name: str, *, root_lookup: bool = False) -> int:
    try:
        descriptor = os.open(name, _directory_open_flags(), dir_fd=parent_fd)
    except OSError as exc:
        if root_lookup and exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise PackageAdaptationError(
                "source_symlink_forbidden",
                "package root and its path ancestors cannot be symlinks",
                "Register the real folder this path resolves to instead of a symlinked path.",
            ) from exc
        if root_lookup and exc.errno == errno.ENOENT:
            raise PackageAdaptationError(
                "source_missing",
                "local package root does not exist",
                "Check the path for a typo and register a folder that exists on this machine.",
            ) from exc
        raise PackageAdaptationError(
            "source_changed_during_snapshot",
            "package directory changed while its safe snapshot was being captured",
        ) from exc
    metadata = os.fstat(descriptor)
    if not stat.S_ISDIR(metadata.st_mode):
        os.close(descriptor)
        raise PackageAdaptationError(
            "source_read_failed",
            "package path is not a directory",
            "Register the folder that contains the agent or team, not a file inside it.",
        )
    return descriptor


def _bounded_regular_file_bytes_at(directory_fd: int, name: str, *, remaining: int) -> bytes:
    """Read one regular file through a no-follow openat within the budget."""

    if remaining < 0:
        raise PackageAdaptationError(
            "source_too_large",
            "package exceeds local import limits",
            _SOURCE_LIMIT_REMEDIATION,
        )
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise PackageAdaptationError(
            "source_changed_during_snapshot",
            "package file changed while its safe snapshot was being captured",
        ) from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise PackageAdaptationError("source_read_failed", "package file is not regular")
        if metadata.st_size > remaining:
            raise PackageAdaptationError(
                "source_too_large",
                "package exceeds local import limits",
                _SOURCE_LIMIT_REMEDIATION,
            )
        chunks: list[bytes] = []
        observed = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, remaining - observed + 1))
            if not chunk:
                break
            observed += len(chunk)
            if observed > remaining:
                raise PackageAdaptationError(
                    "source_too_large",
                    "package exceeds local import limits",
                    _SOURCE_LIMIT_REMEDIATION,
                )
            chunks.append(chunk)
        return b"".join(chunks)
    except OSError as exc:
        raise PackageAdaptationError("source_read_failed", "package file could not be read safely") from exc
    finally:
        os.close(descriptor)


def snapshot_package_hash(root: Path | str) -> str:
    """Hash the exact safe text snapshot used by local execution."""

    return package_hash(list(_safe_source_files(Path(root))))


def _frontmatter(text: str, field: str) -> str | None:
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end < 0:
        return None
    match = re.search(
        rf"^\s*{re.escape(field)}\s*:\s*(.+?)\s*$",
        text[3:end],
        re.MULTILINE | re.IGNORECASE,
    )
    return match.group(1).strip().strip("\"'")[:500] if match else None


def _markdown_identity(text: str, fallback: str) -> tuple[str, str]:
    name = _frontmatter(text, "name")
    description = _frontmatter(text, "description")
    body = text
    if body.startswith("---"):
        end = body.find("\n---", 3)
        body = body[end + 4 :] if end >= 0 else body
    if not name:
        heading = re.search(r"^#\s+(.+?)\s*$", body, re.MULTILINE)
        name = heading.group(1).strip() if heading else None
    if not description:
        for paragraph in re.split(r"\n\s*\n", body):
            compact = " ".join(line.strip() for line in paragraph.splitlines() if line.strip())
            if compact and not compact.startswith(("#", "```")):
                description = compact
                break
    clean_name = (name or fallback.replace("-", " ").replace("_", " ") or "Local Agent")[:200]
    return clean_name, (description or f"Local workforce package for {clean_name}")[:500]


def _mcp_requirements(files: Mapping[str, str]) -> tuple[dict[str, Any], ...]:
    relative_path = ".agentlas/mcp-policy.json"
    if relative_path not in files:
        return ()
    value = _snapshot_json(files, relative_path)
    if not isinstance(value, Mapping) or not isinstance(value.get("requirements"), list):
        raise PackageAdaptationError("mcp_policy_invalid", "MCP policy must contain requirements")
    try:
        validate_mcp_policy(value)
    except ContractValidationError as exc:
        raise PackageAdaptationError("mcp_policy_invalid", "MCP policy failed validation") from exc
    if any(not isinstance(item, Mapping) for item in value["requirements"]):
        raise PackageAdaptationError("mcp_policy_invalid", "MCP requirements must be objects")
    return tuple(dict(item) for item in value["requirements"])


def _node_id(value: Any) -> str | None:
    if isinstance(value, Mapping):
        value = value.get("id") or value.get("slug") or value.get("name")
    slug = re.sub(r"[^a-z0-9._:@/-]+", "-", str(value or "").strip().lower()).strip("-")
    return f"node:{slug}" if slug else None


def _team_graph(
    files: Mapping[str, str],
    card: Mapping[str, Any],
    inferred: list[str] | None = None,
) -> dict[str, Any] | None:
    if card.get("type") != "team":
        return None
    explicit = _snapshot_json(files, ".agentlas/team-graph.json")
    if explicit:
        manager = _node_id(explicit.get("manager"))
        workers = [node for node in (_node_id(row) for row in explicit.get("workers") or []) if node]
        edges = [dict(row) for row in explicit.get("edges") or [] if isinstance(row, Mapping)]
        return {
            "authoritative": bool(explicit.get("authoritative") and manager and workers),
            "manager": manager,
            "workers": workers,
            "edges": edges,
        }
    agent_card = _snapshot_json(files, ".agentlas/agent-card.json")
    manager = _node_id(agent_card.get("orchestrator") or agent_card.get("manager"))
    workers = [node for node in (_node_id(row) for row in (agent_card.get("workers") or inferred or [])) if node]
    return {
        "authoritative": bool(manager and workers and agent_card),
        "manager": manager,
        "workers": workers,
        "edges": [
            {"from": worker, "to": manager, "relation": "reportsTo"}
            for worker in workers
            if manager and worker != manager
        ],
    }


def _safe_entrypoint(value: str, files: Mapping[str, str]) -> str:
    entrypoint = value or "AGENTS.md"
    entry_path = Path(entrypoint)
    if entry_path.is_absolute() or ".." in entry_path.parts or "\\" in entrypoint:
        raise PackageAdaptationError(
            "routing_card_invalid",
            "agent entrypoint must be root-relative",
            f"The entrypoint {entrypoint!r} must be a forward-slash path inside the package root, with no '..' and no absolute prefix.",
        )
    if entry_path.as_posix() not in files:
        raise PackageAdaptationError(
            "routing_card_invalid",
            "agent entrypoint is not in the safe snapshot",
            f"No readable file {entry_path.as_posix()!r} exists in the package root. Point the entrypoint at a committed text file, not a generated or ignored one.",
        )
    return entry_path.as_posix()


def _snapshot_worker_names(files: Mapping[str, str]) -> tuple[str, ...]:
    workers = {
        Path(relative_path).parent.name
        for relative_path in files
        if len(Path(relative_path).parts) >= 3
        and Path(relative_path).parts[0] == "agents"
        and Path(relative_path).name == "agent.md"
    }
    return tuple(sorted(name for name in workers if name))


ROUTING_CARD_SCHEMA_VERSION = "routing-card/2.0"


def _routing_card_problem(
    card: Mapping[str, Any], report: Mapping[str, Any]
) -> tuple[str, str] | None:
    """Name the failing field, or None when the card is acceptable.

    WHY: these checks used to be one `or`-chain raising a single
    "routing card failed structural validation", so `workforce local-register`
    answered a wrong schemaVersion with the bare code `routing_card_invalid` —
    no field, no expected value, nothing the user could act on. The value the
    check compares against is the only place that knows what would make the card
    acceptable, so each branch states it here (same contract _safe_entrypoint
    below already honors).
    """
    schema_version = card.get("schemaVersion")
    if schema_version != ROUTING_CARD_SCHEMA_VERSION:
        return (
            f"routing card schemaVersion must be {ROUTING_CARD_SCHEMA_VERSION!r} "
            f"(found {schema_version!r})",
            f"Set \"schemaVersion\": \"{ROUTING_CARD_SCHEMA_VERSION}\" in "
            ".agentlas/routing-card.json, or rebuild an older card with "
            "`hephaestus cards migrate <package> --tier local --overwrite`.",
        )
    if card.get("type") not in {"agent", "team", "plugin"}:
        return (
            f"routing card type must be agent, team, or plugin (found {card.get('type')!r})",
            'Set "type" in .agentlas/routing-card.json to the entity this package ships.',
        )
    if card.get("routing_status") not in VALID_STATUSES:
        return (
            f"routing card routing_status must be one of {', '.join(VALID_STATUSES)} "
            f"(found {card.get('routing_status')!r})",
            'Set "routing_status" in .agentlas/routing-card.json — a new package starts at "draft".',
        )
    capabilities = card.get("capabilities")
    if not isinstance(capabilities, list) or not capabilities:
        return (
            "routing card capabilities must be a non-empty array",
            'List what the package does as verb_object entries, e.g. "capabilities": '
            '["summarize_release_notes"].',
        )
    malformed = [
        item
        for item in capabilities
        if not isinstance(item, str) or not VERB_CAPABILITY_RE.fullmatch(item)
    ]
    if malformed:
        return (
            f"routing card capabilities must be verb_object snake_case: {malformed[:3]}",
            "Rewrite each capability as lowercase verb_object with at least two words, "
            'e.g. "draft_team_digest".',
        )
    lint_errors = list(report.get("errors") or [])
    if lint_errors:
        return (
            "routing card failed lint: " + "; ".join(str(err) for err in lint_errors[:3]),
            "Fix the listed fields in .agentlas/routing-card.json, then run "
            "`hephaestus cards lint <package>` until it reports no errors.",
        )
    return None


def inspect_package(source_root: Path | str) -> PackageInspection:
    # Do not resolve again here. LocalWorkforceRegistry already canonicalizes
    # the explicit root for its scope check; a second resolve would follow a
    # symlink installed by an attacker between that check and this snapshot.
    root = Path(os.path.abspath(os.fspath(Path(source_root).expanduser())))
    files = _safe_source_files(root)
    snapshot = _snapshot_file_map(files)
    content_hash = package_hash(list(files))
    worker_names = _snapshot_worker_names(snapshot)
    if ".agentlas/routing-card.json" in snapshot:
        card = _snapshot_json(snapshot, ".agentlas/routing-card.json")
        report = lint_card(card)
        problem = _routing_card_problem(card, report)
        if problem:
            raise PackageAdaptationError("routing_card_invalid", problem[0], problem[1])
        name = str(card.get("name") or root.name)
        manifest = _snapshot_json(snapshot, "agentlas.json") or _snapshot_json(snapshot, "manifest.json")
        if not manifest:
            manifest = build_manifest(list(files), name).to_json()
        default_entry = next(
            (name for name in (*_TEAM_MARKERS, *_AGENT_MARKERS) if name in snapshot),
            "AGENTS.md",
        )
        entrypoint = _safe_entrypoint(
            str((card.get("entrypoints") or {}).get("agent") or manifest.get("entry") or default_entry),
            snapshot,
        )
        return PackageInspection(
            source_root=root,
            source_kind="native",
            entity_kind=str(card["type"]),
            name=name,
            summary=str(card.get("summary") or name),
            entrypoint=entrypoint,
            package_hash=content_hash,
            routing_card=card,
            manifest=manifest,
            mcp_requirements=_mcp_requirements(snapshot),
            team_graph=_team_graph(snapshot, card, list(worker_names)),
            source_files=files,
            skill_names=tuple(str(item) for item in manifest.get("skills") or []),
            worker_names=worker_names,
        )

    root_agents = [name for name in _AGENT_MARKERS if name in snapshot]
    root_teams = [name for name in _TEAM_MARKERS if name in snapshot]
    skill_files = sorted(
        relative_path
        for relative_path in snapshot
        if Path(relative_path).name == "SKILL.md"
    )
    if len(root_agents) > 1:
        raise PackageAdaptationError(
            "source_ambiguous",
            "multiple root agent entrypoints require a routing card",
            "This root has "
            + ", ".join(root_agents)
            + ". Add .agentlas/routing-card.json naming the one entrypoint, or keep a single root agent file.",
        )
    if not root_agents and not root_teams and not skill_files:
        # Name the exact markers this check looks for, derived from the same
        # tuples it tests, so the eligibility rule cannot drift from the words
        # the user is given.
        raise PackageAdaptationError(
            "source_ineligible",
            "no agent, team, or skill marker exists",
            "A registrable root needs one of: "
            + ", ".join(_AGENT_MARKERS)
            + " (agent), "
            + ", ".join(_TEAM_MARKERS)
            + " (team), or any SKILL.md (skill). Point at the package folder that holds one of these.",
        )
    marker = (root_teams or root_agents or skill_files)[0]
    text = snapshot[marker]
    name, summary = _markdown_identity(text, root.name)
    entity_kind = "team" if root_teams or any(Path(path).parts[0] == "agents" for path in snapshot) else "agent"
    manifest = _snapshot_json(snapshot, "agentlas.json") or _snapshot_json(snapshot, "manifest.json")
    if not manifest:
        manifest = build_manifest(list(files), name).to_json()
    inferred_card = {"type": entity_kind}
    return PackageInspection(
        source_root=root,
        source_kind="adapted",
        entity_kind=entity_kind,
        name=name,
        summary=summary,
        entrypoint=marker,
        package_hash=content_hash,
        routing_card=None,
        manifest=manifest,
        mcp_requirements=_mcp_requirements(snapshot),
        team_graph=_team_graph(snapshot, inferred_card, list(worker_names)),
        source_files=files,
        skill_names=tuple(dict.fromkeys(Path(path).parent.name for path in skill_files)),
        worker_names=worker_names,
    )


def _snapshot(files: tuple[PackageFile, ...], destination: Path) -> None:
    validated: list[tuple[tuple[str, ...], str]] = []
    seen: set[str] = set()
    total = 0
    if len(files) > _MAX_SOURCE_FILES:
        raise PackageAdaptationError(
            "source_too_large",
            "package exceeds local import limits",
            _SOURCE_LIMIT_REMEDIATION,
        )
    for item in files:
        if not isinstance(item.path, str) or not isinstance(item.content, str):
            raise PackageAdaptationError(
                "source_snapshot_path_invalid", "snapshot entries must be text files"
            )
        raw_path = item.path
        parts = tuple(raw_path.split("/"))
        if (
            not raw_path
            or raw_path.startswith("/")
            or "\\" in raw_path
            or ":" in raw_path
            or "\x00" in raw_path
            or any(part in {"", ".", ".."} for part in parts)
        ):
            raise PackageAdaptationError(
                "source_snapshot_path_invalid",
                "snapshot paths must stay beneath the package root",
            )
        portable_identity = raw_path.casefold()
        if portable_identity in seen:
            raise PackageAdaptationError(
                "source_snapshot_path_invalid", "snapshot paths must be unique"
            )
        seen.add(portable_identity)
        total += len(item.content.encode("utf-8"))
        if total > _MAX_SOURCE_BYTES:
            raise PackageAdaptationError(
                "source_too_large",
                "package exceeds local import limits",
                _SOURCE_LIMIT_REMEDIATION,
            )
        validated.append((parts, item.content))

    destination.mkdir(parents=True, exist_ok=False)
    for parts, content in validated:
        target = destination.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def materialize_package(
    inspection: PackageInspection,
    destination: Path | str,
    *,
    definition_id: str,
    release_id: str,
) -> AdaptedPackage:
    """Create an immutable OS-owned snapshot or wrapper in staging."""

    target = Path(destination)
    if target.exists():
        raise PackageAdaptationError("adapter_destination_exists", "staging destination already exists")
    _snapshot(inspection.source_files, target)
    if inspection.source_kind == "native":
        assert inspection.routing_card is not None
        return AdaptedPackage(
            package_root=target,
            routing_card=deep_detach(inspection.routing_card),
            manifest=deep_detach(inspection.manifest),
            mcp_requirements=inspection.mcp_requirements,
            team_graph=deep_detach(inspection.team_graph) if inspection.team_graph else None,
        )

    agent_card: dict[str, Any] = {
        "name": inspection.name,
        "description": inspection.summary,
        "version": inspection.package_hash.removeprefix("sha256:")[:12],
        "runtime_targets": inspection.manifest.get("requiredRuntime")
        or ["claude-code", "codex", "terminal", "agents-md"],
        "capabilities": list(inspection.skill_names) or [inspection.name],
    }
    # Worker discovery was captured by the same bounded source snapshot as the
    # package hash. Never traverse the writable import source after inspection.
    inferred_workers = list(inspection.worker_names)
    if inspection.entity_kind == "team" and inferred_workers:
        agent_card["workers"] = inferred_workers
    atomic_write_json(target / ".agentlas" / "agent-card.json", agent_card)
    manifest = deep_detach(inspection.manifest)
    manifest["packageHash"] = inspection.package_hash
    atomic_write_json(target / "agentlas.json", manifest)
    atomic_write_json(
        target / ".agentlas" / "source-adapter.json",
        {
            "schemaVersion": LOCAL_PACKAGE_ADAPTER_VERSION,
            "agentDefinitionId": definition_id,
            "agentReleaseId": release_id,
            "sourceRoot": str(inspection.source_root),
            "sourcePackageHash": inspection.package_hash,
            "entrypoint": inspection.entrypoint,
        },
    )
    if not migrate_package(target, tier="local", card_type=inspection.entity_kind, home=None, overwrite=True):
        raise PackageAdaptationError("adapter_migration_failed", "routing-card migration failed")
    card = _json_object(target / ".agentlas" / "routing-card.json")
    stable = re.sub(r"[^a-z0-9._-]+", "-", inspection.name.lower()).strip("-") or "agent"
    card["id"] = f"local/{stable}-{definition_id.rsplit(':', 1)[-1][:12]}"
    card["canonical_id"] = card["id"]
    card["name"] = inspection.name
    card["summary"] = inspection.summary[:240]
    card.setdefault("entrypoints", {})["agent"] = inspection.entrypoint
    card["source"] = {
        "kind": "agentlas_adapter",
        "ref": str(target),
        "origin_ref": str(inspection.source_root),
        "package_hash": inspection.package_hash,
        "package_version": inspection.package_hash.removeprefix("sha256:")[:12],
    }
    if lint_card(card)["errors"]:
        raise PackageAdaptationError("adapter_routing_card_invalid", "generated routing card is invalid")
    atomic_write_json(target / ".agentlas" / "routing-card.json", card)
    return AdaptedPackage(
        package_root=target,
        routing_card=card,
        manifest=manifest,
        mcp_requirements=inspection.mcp_requirements,
        team_graph=deep_detach(inspection.team_graph) if inspection.team_graph else None,
    )


def deep_detach(value: Any) -> Any:
    """Detach JSON-like metadata without accepting executable object types."""

    import json

    return json.loads(json.dumps(value, ensure_ascii=False))


__all__ = [
    "AdaptedPackage",
    "LOCAL_PACKAGE_ADAPTER_VERSION",
    "PackageAdaptationError",
    "PackageInspection",
    "inspect_package",
    "materialize_package",
    "snapshot_package_hash",
]
