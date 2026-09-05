"""Runtime update checks for the Hephaestus CLI.

The explicit ``hephaestus hep-update`` command can install the latest runtime into
``~/.agentlas/runtime/<version>`` and atomically point ``current`` at it. Normal
command paths start a detached, fail-silent auto-update worker at most once per
metadata-check window so the user's command does not wait on network or install work.
"""

from __future__ import annotations

import errno
from functools import cmp_to_key
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

LATEST_RELEASE_URL = os.environ.get(
    "HEPHAESTUS_LATEST_RELEASE_URL",
    "https://api.github.com/repos/agentlas-ai/Agentlas-OS/releases/latest",
)
DEFAULT_TTL_SECONDS = 24 * 60 * 60
METADATA_TTL_SECONDS = 15 * 60
UPDATE_RETRY_SECONDS = (60, 5 * 60, 15 * 60)
LOCK_STALE_SECONDS = 60 * 60
HEALTHCHECK_TIMEOUT_SECONDS = 15
MEMORY_HOOK_SYNC_TIMEOUT_SECONDS = 30
MAX_RUNTIME_ARCHIVE_BYTES = 256 * 1024 * 1024
# schemas/ carries the Workforce/Network contract files (workforce-work-order
# and others). Measured 2026-07-16: the release archive includes and enforces
# this, but it was missing from this list, so it was lost entirely from
# installs — a managed runtime's hep-network then stopped on a missing schema.
RUNTIME_DIRS = ("bin", "agentlas_cloud", "career_graph", "contracts", "ontology", "templates")
# Runtime-home payloads that the installer copies and the updater must copy too,
# or a machine that installed once and then only ever auto-updated loses them on
# its next update — silently, because every consumer below degrades rather than
# raises:
#   system-agents/ — one_workspace._ruleset_paths() resolves the canonical
#     curator-ruleset.json as <runtime>/system-agents/curator-ruleset.json.
#     Without it load_ruleset() falls back to the embedded defaults and stamps
#     sha="embedded" into every decision receipt.
#   goose/, openclaw/ — bin/agentlas-one's hook_asset_root() looks for
#     <runtime>/goose/plugins/agentlas-one and <runtime>/openclaw/hooks/
#     agentlas-one. When neither is present it returns 1 and the caller
#     `return 0`s, so `agentlas-one on` reports success having installed no
#     hooks for those two hosts. (These also travel inside host_adapters/, but
#     that is the adapter bundle — not the path the runner reads.)
# Optional rather than required on purpose: an archive predating the release
# allowlist entry must still be installable, and a hard requirement here turns a
# silent degradation into a total update outage. scripts/verify-runtime-home-
# parity.sh is what keeps this list honest against the installer.
#   skills/ — one_workspace._seed_operations_skill() copies the product-shipped
#     operations skill from <runtime>/skills/agentlas-operations. Without it the
#     One directive points at a file that was never created (PRD §3.6). Measured
#     2026-08-23: ~/.agentlas/runtime/current/skills did not exist at all.
RUNTIME_OPTIONAL_DIRS = ("schemas", "system-agents", "goose", "openclaw", "skills")
RUNTIME_FILES = ("package-contract.json", "release-provenance.json")
RUNTIME_BRIDGE_FILES = (
    "desktop-update-bridge-v1.json",
    "scripts/install-memory-hooks.py",
)
HOST_ADAPTER_BUNDLE_DIR = "host_adapters"
# Fallback only. The bundle set is declared once, in
# contracts/runtime-registry.json -> hostAdapters, and _host_adapter_dirs()
# reads it out of the release source being installed. This tuple exists because
# an archive built before that block was added still has to be installable, and
# a hard requirement here would turn one stale archive into a total update
# outage. tests/test_installer_registry_parity.py fails when it stops matching
# the contract, so the fallback can never become a second source of truth.
HOST_ADAPTER_DIRS = (
    ".agents",
    ".claude",
    ".claude-plugin",
    ".gemini",
    "antigravity",
    "claude",
    "codex",
    "copilot-cli",
    "cursor",
    "gemini",
    "goose",
    "grok",
    "hermes",
    "hooks",
    "kimi",
    "openclaw",
    "opencode",
    "skills",
)
HOST_ADAPTER_CONTRACT_PATH = Path("contracts") / "runtime-registry.json"
COMMAND_REGISTRY_CONTRACT_PATH = Path("contracts") / "command-registry.v2.json"
RELEASE_PROVENANCE_FILE = "release-provenance.json"
RELEASE_PROVENANCE_REQUIRED_SINCE = "1.2.36"
_HOST_ADAPTER_NAME_RE = re.compile(r"^\.?[a-z0-9][a-z0-9._-]*$")
_COMMAND_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


def _host_adapter_dirs(source: Path) -> tuple[str, ...]:
    """The host-adapter bundle set declared by the release being installed.

    Reads contracts/runtime-registry.json out of ``source`` so the updater
    stages exactly what that release declares, and falls back to
    HOST_ADAPTER_DIRS for archives predating the contract. A malformed or
    unsafe entry is dropped rather than staged: names go straight into a path
    join, so traversal and absolute components must never survive.
    """
    try:
        block = json.loads(
            (source / HOST_ADAPTER_CONTRACT_PATH).read_text(encoding="utf-8")
        ).get("hostAdapters")
    except (OSError, ValueError):
        return HOST_ADAPTER_DIRS
    if not isinstance(block, dict):
        return HOST_ADAPTER_DIRS
    dirs = block.get("dirs")
    if not isinstance(dirs, list):
        return HOST_ADAPTER_DIRS
    names = tuple(
        name
        for name in dirs
        if isinstance(name, str)
        and name not in (".", "..")
        and _HOST_ADAPTER_NAME_RE.match(name)
    )
    return names or HOST_ADAPTER_DIRS


MODEL2VEC_ASSET_NAME = "potion-multilingual-128M-int8"
LEGACY_MODEL2VEC_ASSET_NAME = "potion-base-8M-int8"
MODEL2VEC_ASSET_NAMES = (MODEL2VEC_ASSET_NAME, LEGACY_MODEL2VEC_ASSET_NAME)
RELEASE_MODEL2VEC_PATH = Path("assets") / "model2vec" / MODEL2VEC_ASSET_NAME
RUNTIME_MODEL2VEC_PATH = Path("models") / "model2vec" / MODEL2VEC_ASSET_NAME
# Fallback only. The managed command set is DERIVED from the release (see
# _managed_command_names) because a hardcoded list here silently froze three
# commands: `agentlas`, `agentlas-one` and `hep-graph` were absent from this
# tuple, so a machine that installed once and then only ever auto-updated kept
# those three files at their first-install content forever — and nothing
# reported it, because a name that is not in the list is never even considered.
# The installer already derives its set; this path must agree with it.
# The floor of commands the updater must guarantee on every installed machine.
# `_managed_command_names` unions this with what the release ships and what the
# machine already has, so the floor is the ONLY way a command that never landed
# on a given machine can still arrive: a destination-only sweep cannot invent a
# name it does not already see. Leaving a shipped command out of this tuple is
# therefore silent — measured, `hep-orch` and `hep-update` were renderable,
# installable and documented, yet absent from this user's global commands while
# every other command was present. `tests/test_installer_registry_parity.py`
# fails if this drifts from the rendered set again.
HEP_COMMANDS = (
    "agentlas",
    "agentlas-browser",
    "agentlas-build",
    "agentlas-call",
    "agentlas-cloud",
    "agentlas-connect",
    "agentlas-graph",
    "agentlas-hub",
    "agentlas-local",
    "agentlas-login",
    "agentlas-network",
    "agentlas-one",
    "agentlas-orch",
    "agentlas-search",
    "agentlas-storm",
    "agentlas-update",
    "agentlas-upload",
    "hep-browser",
    "hep-build",
    "hep-call",
    "hep-cloud",
    "hep-connect",
    "hep-graph",
    "hep-hub",
    "hep-local",
    "hep-login",
    "hep-network",
    "hep-orch",
    "hep-search",
    "hep-storm",
    "hep-update",
    "hep-upload",
)


def _command_registry_names(source: Path | None = None) -> set[str]:
    """Read command filenames from commandId's registry when available.

    The literal HEP_COMMANDS tuple above remains an install-floor fallback for
    archives released before command-registry.v2. New releases cannot silently
    omit a command from the updater just because this tuple was not edited.
    """

    roots = [source] if source is not None else []
    roots.append(Path(__file__).resolve().parent.parent)
    for root in roots:
        if root is None:
            continue
        try:
            data = json.loads((root / COMMAND_REGISTRY_CONTRACT_PATH).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        result: set[str] = set()
        for command in data.get("commands", []) if isinstance(data, dict) else []:
            if not isinstance(command, dict):
                continue
            terminal = command.get("terminalCommand")
            if not isinstance(terminal, str) or not terminal.startswith("hep-"):
                continue
            verb = terminal[len("hep-"):]
            if _COMMAND_NAME_RE.fullmatch(verb):
                result.update({terminal, f"agentlas-{verb}"})
        if result:
            return result
    return set()

# Repo-own adapter surfaces that are never installed as user-global commands.
# Must stay identical to `project_only_commands` in scripts/install-all-runtimes.sh.
PROJECT_ONLY_COMMANDS = frozenset({"meta-agent"})


def _managed_command_names(source: Path | None = None, home: Path | None = None) -> tuple[str, ...]:
    """The managed command set, derived rather than typed out again.

    `source` is a release bundle: read `.claude/commands/*.md`, which is the same
    directory the installer derives from. `home` is an installed machine: read
    what is actually present so a destination-only sweep covers every command
    that reached this user, including ones added after their last full install.
    Both are unioned with HEP_COMMANDS so a stripped bundle can only ever widen
    the set, never shrink it below the historical floor.
    """

    names: set[str] = set(HEP_COMMANDS)
    for registry_root in (source, None):
        names.update(_command_registry_names(registry_root))
    for directory in (
        source / ".claude" / "commands" if source is not None else None,
        home / ".claude" / "commands" if home is not None else None,
    ):
        if directory is None or not directory.is_dir():
            continue
        try:
            entries = sorted(directory.glob("*.md"))
        except OSError:
            continue
        for entry in entries:
            if entry.stem and entry.stem not in PROJECT_ONLY_COMMANDS:
                names.add(entry.stem)
    return tuple(sorted(names))
# Every AgentSkills surface installed by the one-touch installer. Keep graph and
# upload in the same updater-owned set as network/cloud/storm so an update can
# never leave a first-install copy frozen indefinitely.
HEP_SKILLS = (
    "agentlas",
    "agentlas-one",
    "hephaestus-network",
    "hephaestus-cloud",
    "hephaestus-storm",
    "hephaestus-graph",
    "hephaestus-upload",
)


def _managed_skill_names(source: Path | None = None) -> tuple[str, ...]:
    """Use command-registry.v2's universalSkills, with an old-release fallback."""

    roots = [source] if source is not None else []
    roots.append(Path(__file__).resolve().parent.parent)
    for root in roots:
        if root is None:
            continue
        try:
            data = json.loads((root / COMMAND_REGISTRY_CONTRACT_PATH).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        skills = data.get("universalSkills") if isinstance(data, dict) else None
        if isinstance(skills, list) and skills and all(
            isinstance(name, str) and _COMMAND_NAME_RE.fullmatch(name) for name in skills
        ):
            return tuple(dict.fromkeys(skills))
    return HEP_SKILLS


PYTHON_CACHE_IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")
AUTO_UPDATE_MARKER = "auto-update.json"

# Legacy in-adapter auto-update preflight. Older releases shipped command
# adapters that began with an ``if [ "${HEPHAESTUS_APP_AUTO_UPDATE ...; then
# ... curl <install-all-runtimes.sh> | HEPHAESTUS_FORCE=1 bash ... fi`` stanza.
# Host permission classifiers (e.g. Claude Code auto mode) block piping a remote
# script into bash on *every* machine, so the preflight is dead weight that can
# never succeed. The runner's own urllib-based self-update replaces it, so the
# durable fix is to strip the stanza from installed adapters in place — network
# free and independent of which release is published.
LEGACY_PREFLIGHT_START = 'if [ "${HEPHAESTUS_APP_AUTO_UPDATE'
LEGACY_PREFLIGHT_MARKERS = (
    "HEPHAESTUS_APP_AUTO_UPDATE",
    "NEEDS_HEP_UPDATE",
    "HEPHAESTUS_FORCE=1 bash",
    "hephaestus-app-auto-update",
)


def _strip_legacy_preflight(text: str) -> tuple[str, bool]:
    """Remove the legacy ``curl | bash`` auto-update preflight stanza.

    The stanza is a self-contained ``if ...; then ... fi`` block (with nested
    ``if`` statements) that opens with :data:`LEGACY_PREFLIGHT_START`. We locate
    that opener and consume lines until the matching ``fi`` returns nesting depth
    to zero, then swallow a single trailing blank line. Everything before and
    after — the still-valid runner resolution body — is preserved verbatim.
    Returns ``(new_text, changed)``.
    """

    lines = text.splitlines(keepends=True)
    start = None
    for index, line in enumerate(lines):
        if line.lstrip().startswith(LEGACY_PREFLIGHT_START):
            start = index
            break
    if start is None:
        return text, False

    depth = 0
    end = None
    for index in range(start, len(lines)):
        stripped = lines[index].strip()
        if stripped.startswith("if ") and stripped.endswith("then"):
            depth += 1
        elif stripped == "fi":
            depth -= 1
            if depth == 0:
                end = index
                break
    if end is None:
        return text, False

    cut_end = end + 1
    if cut_end < len(lines) and lines[cut_end].strip() == "":
        cut_end += 1
    new_text = "".join(lines[:start] + lines[cut_end:])
    return new_text, new_text != text


# Stale "runner not found" message that older adapters emitted; it references the
# now-removed preflight log. Normalize it so a sanitized adapter carries none of
# the legacy markers and the staleness scan skips it on the next pass.
LEGACY_NOT_FOUND_MESSAGE = (
    "Hephaestus runtime not found after app auto-update preflight. "
    "See /tmp/hephaestus-app-auto-update.log if it exists."
)
CLEAN_NOT_FOUND_MESSAGE = "Hephaestus runtime not found. Run the installer first."


def _sanitize_adapter_text(text: str) -> tuple[str, bool]:
    """Apply every legacy-preflight repair to one adapter's text.

    Strips the ``curl | bash`` stanza and normalizes the stale not-found message
    so the result is free of all :data:`LEGACY_PREFLIGHT_MARKERS`. Returns
    ``(new_text, changed)``.
    """

    new_text, _ = _strip_legacy_preflight(text)
    if LEGACY_NOT_FOUND_MESSAGE in new_text:
        new_text = new_text.replace(LEGACY_NOT_FOUND_MESSAGE, CLEAN_NOT_FOUND_MESSAGE)
    return new_text, new_text != text


def _adapter_paths(home: Path) -> list[Path]:
    """Enumerate installed hep-* command and skill adapter files across runtimes.

    Both command adapters (``.md`` / ``.toml``) and skill adapters
    (``SKILL.md``) shipped the legacy preflight, so both must be scanned.
    Destinations only — derivable from ``home`` without a release source, so the
    staleness scan stays network free.
    """

    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    paths: list[Path] = []
    # Destination-only sweep: derive from what this machine actually has, so a
    # command installed after the last full update is still swept. Versioned
    # plugin-cache directories are intentionally excluded: once a host has
    # loaded one, changing even a single command file under that old version
    # breaks the cache-name/content invariant. The next exact-version cache is
    # sanitized in the release payload and becomes active after reload.
    managed_commands = _managed_command_names(home=home)
    for command in managed_commands:
        paths.extend(
            [
                home / ".claude" / "commands" / f"{command}.md",
                codex_home / "prompts" / f"{command}.md",
                home / ".cursor" / "commands" / f"{command}.md",
                home / ".config" / "opencode" / "commands" / f"{command}.md",
                home / ".gemini" / "antigravity" / "global_workflows" / f"{command}.md",
                home / ".gemini" / "antigravity-ide" / "global_workflows" / f"{command}.md",
                home / ".gemini" / "commands" / f"{command}.toml",
                home / ".gemini" / "hephaestus-extension-source" / "commands" / f"{command}.toml",
            ]
        )
    managed_skills = _managed_skill_names()
    for skill in managed_skills:
        paths.extend(
            [
                home / ".agents" / "skills" / skill / "SKILL.md",
                home / ".cursor" / "skills" / skill / "SKILL.md",
                home / ".openclaw" / "skills" / skill / "SKILL.md",
                home / ".hermes" / "skills" / skill / "SKILL.md",
                home / ".gemini" / "config" / "plugins" / "agentlas-os" / "skills" / skill / "SKILL.md",
                home / ".gemini" / "hephaestus-extension-source" / "skills" / skill / "SKILL.md",
            ]
        )
    return paths


def reconcile_adapters(home: Path | None = None) -> dict[str, Any]:
    """Strip the legacy curl|bash auto-update preflight from installed adapters.

    Network free and release independent: repairs adapters in place so the
    permission-blocked preflight is purged on any machine — even one already on
    the latest runtime, where version-gated adapter sync never fires. Fail-silent
    per file; a single unreadable adapter never aborts the sweep.
    """

    home_dir = home or Path.home()
    sanitized: list[str] = []
    for path in _adapter_paths(home_dir):
        try:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            if not any(marker in text for marker in LEGACY_PREFLIGHT_MARKERS):
                continue
            new_text, changed = _sanitize_adapter_text(text)
            if not changed:
                continue
            tmp = path.with_name(f".{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
            tmp.write_text(new_text, encoding="utf-8")
            tmp.replace(path)
            sanitized.append(str(path))
        except Exception:
            continue
    return {"sanitized": sanitized, "count": len(sanitized)}


def current_release(root: Path | None = None) -> str | None:
    runtime_root = root or Path(__file__).resolve().parent.parent
    marker = runtime_root / "RELEASE"
    if not marker.exists():
        return None
    value = marker.read_text(encoding="utf-8").strip()
    return value or None


class UpdateUnavailableError(RuntimeError):
    """A user-invoked update could not complete for an environmental reason.

    ``maybe_auto_update``/``maybe_print_update_notice`` may swallow an offline
    GitHub because nobody asked them to run. The explicit ``hep-update`` command
    is the opposite case: the user asked, so the failure must come back as a
    sentence they can act on plus a machine-readable payload — never as a
    traceback. Carrying the payload on the exception keeps the CLI free of a
    second copy of the wording.
    """

    def __init__(self, payload: dict[str, Any], message: str) -> None:
        super().__init__(message)
        self.payload = payload
        self.message = message


def _denied_write_path(exc: BaseException) -> str | None:
    """Return the denied path when ``exc`` chains down to a permission denial.

    Host sandboxes surface as ``EPERM``/``EACCES`` on ordinary local writes, a
    failure class the network/disk wording must never claim. ``None`` means
    "not a permission problem"; an empty string is a denial without a filename.
    """

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, OSError) and current.errno in (errno.EPERM, errno.EACCES):
            return str(current.filename or "")
        current = current.__cause__ or current.__context__
    return None


def _release_source_host() -> str:
    """Name the release host in user-facing text; never invent a default."""

    return urllib.parse.urlsplit(LATEST_RELEASE_URL).netloc or LATEST_RELEASE_URL


def _current_release_phrase(current: str | None) -> str:
    return f"You are still on {current}" if current else "This runtime has no RELEASE marker"


def _install_or_report(release: dict[str, Any], current: str | None) -> dict[str, Any]:
    """Install ``release``, converting environmental failures into user text.

    The download is a second network stage: a reachable GitHub that dies
    mid-transfer (or a full disk, or a digest mismatch) used to raise straight
    through ``run_update`` and print the same raw traceback as the offline
    check. Both stages are reported the same way. ``detail`` carries the real
    error text verbatim so nothing is hidden, only unwrapped from the stack.
    """

    try:
        return install_latest_runtime(release)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, tarfile.TarError, RuntimeError) as exc:
        tag = str(release.get("tag_name") or "the latest release")
        denied = _denied_write_path(exc)
        if denied is not None:
            where = f" to {denied}" if denied else ""
            raise UpdateUnavailableError(
                {
                    "status": "install_blocked_sandboxed",
                    "current": current,
                    "latest": release.get("tag_name"),
                    "error": f"a sandbox denied a local write needed to install {tag}",
                    "denied_path": denied,
                    "detail": str(exc),
                    "install_command": "hephaestus hep-update",
                },
                f"Could not install {tag}: this process was denied write access{where}. "
                "A host sandbox (Claude Code, Codex, Cursor, ...) is blocking writes outside "
                "the workspace — this is not a network or disk problem. "
                f"{_current_release_phrase(current)}. "
                "Run this from a regular unsandboxed terminal: hephaestus hep-update",
            ) from exc
        raise UpdateUnavailableError(
            {
                "status": "install_failed",
                "current": current,
                "latest": release.get("tag_name"),
                "error": f"could not install {tag}",
                "detail": str(exc),
                "install_command": "hephaestus hep-update",
            },
            f"Could not install {tag}: {exc}. "
            f"{_current_release_phrase(current)}. "
            "Check your network connection and free disk space, then run: hephaestus hep-update",
        ) from exc


def _installed_outcome_status(success_status: str, installed: dict[str, Any]) -> str:
    activation = installed.get("activation") if isinstance(installed, dict) else None
    if not isinstance(activation, dict):
        return success_status
    if activation.get("status") == "blocked":
        return "update_incomplete"
    if activation.get("status") == "pending_reload":
        return f"{success_status}_pending_reload"
    return success_status


def _apply_observed_install_state(
    result: dict[str, Any],
    installed: dict[str, Any],
    previous_release: str | None,
) -> None:
    """Merge an install receipt and expose the release observed after activation."""

    result.update(installed)
    result["previous"] = previous_release
    observed = current_release(_runtime_base() / "current")
    if observed:
        result["current"] = observed


def _canonical_update_marker(
    previous: dict[str, Any],
    result: dict[str, Any],
    runtime_root: Path,
) -> dict[str, Any]:
    """Build a marker from re-read state instead of retaining stale fields."""

    checked_epoch = int(result.get("last_checked_epoch") or time.time())
    canonical: dict[str, Any] = {
        "markerSchemaVersion": "agentlas.auto-update.v2",
        "status": result.get("status"),
        "last_checked_epoch": checked_epoch,
    }
    for field in ("last_started_epoch", "last_maintenance_epoch"):
        if isinstance(previous.get(field), (int, float)):
            canonical[field] = previous[field]
    for key in (
        "reason",
        "html_url",
        "install_command",
        "desktop_repair",
        "desktop_updater_cleanup",
        "archive_digest",
        "digest_verified",
        "archive_asset",
        "adapter_sync",
        "memory_hook_sync",
        "global_router_sync",
        "activation",
    ):
        if key in result:
            canonical[key] = result[key]

    current_link = _runtime_base() / "current"
    observed_root = current_link if _path_present(current_link) else runtime_root
    observed_release = current_release(observed_root)
    if observed_release:
        try:
            resolved_root = observed_root.resolve()
        except OSError:
            resolved_root = observed_root
        canonical.update(
            {
                "current": observed_release,
                "targetVersion": observed_release,
                "updated_to": observed_release,
                "last_applied_tag": observed_release,
                "runtime_root": str(resolved_root),
                "current_link": str(current_link),
            }
        )
        model_root = result.get("model_root") or resolved_root / RUNTIME_MODEL2VEC_PATH
        canonical["model_root"] = str(model_root)
        if result.get("last_applied_tag") == observed_release and isinstance(
            result.get("last_applied_epoch"), (int, float)
        ):
            canonical["last_applied_epoch"] = result["last_applied_epoch"]
        elif previous.get("last_applied_tag") == observed_release and isinstance(
            previous.get("last_applied_epoch"), (int, float)
        ):
            canonical["last_applied_epoch"] = previous["last_applied_epoch"]
        else:
            canonical["last_applied_epoch"] = checked_epoch
    else:
        canonical["current"] = result.get("current")
        if result.get("latest"):
            canonical["latest"] = result["latest"]

    reconciliation = result.get("reconciliation") if isinstance(result.get("reconciliation"), dict) else {}
    host_sync = result.get("host_plugin_sync") or reconciliation.get("hostPluginSync")
    cache_sync = result.get("plugin_cache_sync") or reconciliation.get("pluginCacheSync")
    if isinstance(host_sync, dict):
        canonical["host_plugin_sync"] = host_sync
    if isinstance(cache_sync, dict):
        canonical["plugin_cache_sync"] = cache_sync
    pending_hosts = result.get("pendingHosts")
    if pending_hosts is None and isinstance(host_sync, dict):
        pending_hosts = host_sync.get("pendingHosts")
    canonical["pendingHosts"] = sorted(set(pending_hosts or []))
    canonical["reloadRequired"] = bool(
        result.get("reloadRequired")
        or (isinstance(host_sync, dict) and host_sync.get("reloadRequired"))
    )
    if "latest" in result:
        canonical["latest"] = result["latest"]
    return canonical


def _persist_update_marker(previous: dict[str, Any], result: dict[str, Any], runtime_root: Path) -> None:
    _write_json(
        _runtime_base() / AUTO_UPDATE_MARKER,
        _canonical_update_marker(previous, result, runtime_root),
    )


def run_update(check_only: bool = False, root: Path | None = None) -> dict[str, Any]:
    runtime_root = root or Path(__file__).resolve().parent.parent
    current = current_release(runtime_root)
    try:
        latest = fetch_latest_release(force=True)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        # force=True deliberately bypasses the TTL cache, so there is no cached
        # answer to fall back to and inventing one would be a silent fallback.
        # Report the failure in words instead of raising into the CLI.
        denied = _denied_write_path(exc)
        if denied is not None:
            # A permission denial is a local sandbox boundary, not connectivity;
            # blaming the network here would misdirect the user.
            where = f" to {denied}" if denied else ""
            raise UpdateUnavailableError(
                {
                    "status": "check_blocked_sandboxed",
                    "current": current,
                    "error": "a sandbox denied a local write during the update check",
                    "denied_path": denied,
                    "detail": str(exc),
                    "install_command": "hephaestus hep-update",
                },
                f"Could not finish the update check: this process was denied write access{where}. "
                "A host sandbox (Claude Code, Codex, Cursor, ...) is blocking writes outside "
                "the workspace — this is not a network problem. "
                f"{_current_release_phrase(current)}; nothing was changed. "
                "Run this from a regular unsandboxed terminal: hephaestus hep-update",
            ) from exc
        host = _release_source_host()
        raise UpdateUnavailableError(
            {
                "status": "check_failed",
                "current": current,
                "error": f"could not reach {host} to check for a newer runtime",
                "detail": str(exc),
                "install_command": "hephaestus hep-update",
            },
            f"Could not reach {host} to check for a newer Hephaestus runtime. "
            f"{_current_release_phrase(current)}; nothing was changed. "
            "Check your network or proxy settings, then run: hephaestus hep-update",
        ) from exc
    status = _release_status(current, latest.get("tag_name"))
    result: dict[str, Any] = {
        "status": status,
        "current": current,
        "latest": latest.get("tag_name"),
        "html_url": latest.get("html_url"),
        "install_command": "hephaestus hep-update",
    }
    if not check_only:
        reconciled = reconcile_adapters()
        if reconciled["count"]:
            result["adapters_sanitized"] = reconciled["sanitized"]
    if check_only:
        return result
    if status not in {"update_available", "missing_release_marker"}:
        reconciliation = reconcile_current_installation(runtime_root)
        result["reconciliation"] = reconciliation
        if _requires_current_release_rehydrate(current, latest.get("tag_name"), reconciliation):
            installed = _install_or_report(latest, current)
            _apply_observed_install_state(result, installed, current)
            result["status"] = _installed_outcome_status("repaired_current", installed)
        _persist_update_marker(_read_json(_runtime_base() / AUTO_UPDATE_MARKER), result, runtime_root)
        return result

    installed = _install_or_report(latest, current)
    _apply_observed_install_state(result, installed, current)
    success_status = "updated" if status == "update_available" else "recovered_missing_release_marker"
    result["status"] = _installed_outcome_status(success_status, installed)
    result["last_applied_tag"] = latest.get("tag_name")
    result["last_applied_epoch"] = int(time.time())
    _persist_update_marker(_read_json(_runtime_base() / AUTO_UPDATE_MARKER), result, runtime_root)
    return result


def maybe_auto_update(root: Path | None = None, *, background: bool = True) -> None:
    """Start a fail-silent runtime auto-update check.

    This function intentionally returns ``None`` for every outcome. It never
    raises, never prints, and by default never performs network or install work
    in the caller process.
    """

    try:
        # v1.1.63 briefly installed an independent six-hour OS scheduler. The
        # intended contract is command/Desktop-triggered, fail-silent updating,
        # so retire any legacy scheduler before doing normal local maintenance.
        try:
            from .auto_update_service import retire_auto_update_service

            retire_auto_update_service()
        except Exception:
            pass
        # Always self-heal stale command adapters first. This is network free
        # and must run even when version auto-update is disabled, because the
        # legacy curl|bash preflight is blocked by host classifiers on every
        # machine and would otherwise persist forever once the runtime is
        # already current (version-gated adapter sync never re-fires).
        try:
            reconcile_adapters()
        except Exception:
            pass
        if _auto_update_disabled():
            return
        runtime_root = root or Path(__file__).resolve().parent.parent
        current = current_release(runtime_root)
        if current is not None and not _is_comparable_release(current):
            return
        base = _runtime_base()
        # ★업데이트할 런타임이 없으면 아무것도 만들지 않는다.
        #
        #   설치본이 없는 호스트(플러그인만 쓰는 경우, 격리 실행)에서도 이 검사가
        #   `~/.agentlas/runtime/` 에 마커를 써서 디렉터리를 만들어 냈다. 업데이트할
        #   대상이 없는데 그 대상의 집을 짓는 셈이고, "격리 실행은 런타임 홈을 만들지
        #   않는다"는 계약이 그 자리에서 깨진다(tests/test_memory_hook.py 의
        #   isolated-home 단언이 이것을 잡고 있었다).
        #
        #   검사 자체가 무의미하지도 않다 — 런타임이 없으면 올릴 것도 없다.
        if not base.is_dir():
            return
        lock_path = base / ".update.lock"
        recovered_stale_lock = False
        if _path_present(lock_path):
            if not _remove_stale_lock(lock_path):
                return
            recovered_stale_lock = True
        # Serialize admission only; installation retains its separate lock.
        check_lock = base / ".update-check.lock"
        try:
            check_token = _acquire_lock(check_lock)
        except RuntimeError:
            return
        try:
            marker_path = base / AUTO_UPDATE_MARKER
            marker = _read_json(marker_path)
            failures = marker.get("failure_count", 0)
            retry_delay = METADATA_TTL_SECONDS
            if isinstance(failures, int) and failures > 0:
                retry_delay = UPDATE_RETRY_SECONDS[min(failures - 1, len(UPDATE_RETRY_SECONDS) - 1)]
            if not recovered_stale_lock and _marker_recent(marker.get("last_started_epoch"), retry_delay):
                return
            _write_json(marker_path, {**marker, "last_started_epoch": int(time.time()),
                                      "current": current, "runtime_root": str(runtime_root)})
            if background:
                try:
                    _spawn_auto_update_worker(runtime_root)
                except Exception:
                    _record_auto_update_failure("spawn_failed")
            else:
                _run_auto_update_guarded(runtime_root)
        finally:
            _release_lock(check_lock, check_token)
    except Exception:
        return


def maybe_print_update_notice(root: Path | None = None) -> None:
    if os.environ.get("HEPHAESTUS_UPDATE_CHECK", "1") == "0":
        return
    runtime_root = root or Path(__file__).resolve().parent.parent
    current = current_release(runtime_root)
    if not current:
        return
    try:
        latest = fetch_latest_release(force=False)
    except Exception:
        return
    latest_tag = latest.get("tag_name")
    if _release_status(current, latest_tag) != "update_available":
        return
    print(
        f"Hephaestus update available: {latest_tag} (current {current}). Run: hephaestus hep-update",
        file=sys.stderr,
    )


def fetch_latest_release(force: bool = False, ttl_seconds: int = METADATA_TTL_SECONDS) -> dict[str, Any]:
    cache_path = _runtime_base() / "update-check.json"
    if not force:
        cached = _read_json(cache_path)
        epoch = cached.get("epoch") if isinstance(cached, dict) else None
        release = cached.get("release") if isinstance(cached, dict) else None
        if isinstance(epoch, (int, float)) and isinstance(release, dict) and 0 <= time.time() - float(epoch) < ttl_seconds:
            return release

    request = urllib.request.Request(
        LATEST_RELEASE_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "hephaestus-runtime-update-check",
        },
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        release = json.loads(response.read().decode("utf-8"))
    if not isinstance(release, dict) or not release.get("tag_name"):
        raise ValueError("latest release response missing tag_name")
    try:
        # ★캐시는 최적화일 뿐이므로, 그것 때문에 런타임 홈을 새로 만들지 않는다.
        #   설치본이 없는 호스트에서 이 한 줄이 `~/.agentlas/runtime/` 을 지어 냈고,
        #   "격리 실행은 런타임 홈을 만들지 않는다"는 계약이 거기서 깨졌다.
        if cache_path.parent.is_dir():
            _write_json(cache_path, {"epoch": int(time.time()), "release": release})
    except OSError:
        # The TTL cache is an optimization, never part of the answer. Host
        # sandboxes (Claude Code, Codex, Cursor, ...) deny writes outside the
        # workspace, and a denied cache write must not discard a release fetch
        # that already succeeded — measured 2026-07-29: this write was killing
        # hep-update --check entirely inside a sandbox.
        pass
    return release


def _post_activation_state(
    target: Path,
    release_tag: str,
    model_path: Path,
    host_plugin_sync: dict[str, Any],
    plugin_cache_sync: dict[str, Any],
) -> dict[str, Any]:
    """Re-read the state that an update claims to have activated."""

    expected = _runtime_version_dir_name(release_tag)
    current_path = _runtime_base() / "current"
    try:
        current_target = current_path.resolve()
    except OSError:
        current_target = current_path
    runtime_current = (
        current_release(current_path) == release_tag
        and current_release(target) == release_tag
        and _canonical_path(current_target) == _canonical_path(target)
    )
    model_current = model_path.is_dir()
    host_blockers: list[dict[str, Any]] = []
    for host in host_plugin_sync.get("hosts") or []:
        if not host.get("detected"):
            continue
        if host.get("host") == "codex" and not host.get("exactCacheCurrent"):
            host_blockers.append({"host": "codex", "reason": "exact_target_cache_missing"})
        elif host.get("host") == "codex" and not host.get("nextLoadCurrent"):
            host_blockers.append({"host": "codex", "reason": "persistent_registry_not_current"})
        if host.get("host") == "claude":
            if not host.get("exactCacheCurrent"):
                host_blockers.append({"host": "claude", "reason": "exact_target_cache_missing"})
            elif not host.get("ledgerCurrent"):
                host_blockers.append({"host": "claude", "reason": "target_ledger_not_current"})
            elif not host.get("nextLoadCurrent"):
                host_blockers.append({"host": "claude", "reason": "persistent_registry_not_current"})
    pending_hosts = sorted(set(host_plugin_sync.get("pendingHosts") or []))
    blockers: list[dict[str, Any]] = []
    if not runtime_current:
        blockers.append({"component": "runtime", "reason": "current_link_or_release_mismatch"})
    if not model_current:
        blockers.append({"component": "model", "reason": "installed_model_missing"})
    blockers.extend(host_blockers)
    if plugin_cache_sync.get("status") not in {"pass", "pending_reload", "not_run"}:
        blockers.append({"component": "plugin_cache", "reason": "cache_reconciliation_incomplete"})
    status = "blocked" if blockers else "pending_reload" if pending_hosts else "pass"
    return {
        "schemaVersion": "agentlas.post-activation.v1",
        "status": status,
        "release": f"v{expected}",
        "runtimeCurrent": runtime_current,
        "currentLink": str(current_path),
        "currentTarget": str(current_target),
        "modelCurrent": model_current,
        "modelPath": str(model_path),
        "persistentHostStateCurrent": not host_blockers,
        "reloadRequired": bool(pending_hosts),
        "pendingHosts": pending_hosts,
        "blockers": blockers,
    }


def install_latest_runtime(release: dict[str, Any]) -> dict[str, Any]:
    tag = str(release.get("tag_name") or "").strip()
    if not tag:
        raise ValueError("release tag_name is required")
    archive_asset = _verified_runtime_archive_asset(release)
    tarball_url = archive_asset["url"]
    expected_sha256 = archive_asset["sha256"]
    expected_size = archive_asset["size"]

    base = _runtime_base()
    target = base / _runtime_version_dir_name(tag)
    lock = base / ".update.lock"
    adapter_sync: dict[str, Any] = {
        "updated": [],
        "skipped_missing": [],
        "failed": [],
        "plugin_cache": {"updated": [], "added": [], "preserved": []},
    }
    host_plugin_sync: dict[str, Any] = {"status": "not_run", "hosts": []}
    plugin_cache_sync: dict[str, Any] = {"status": "not_run", "hosts": []}
    memory_hook_sync: dict[str, Any] = {"status": "not_run", "installed": {}, "errors": {}}
    global_router_sync: dict[str, Any] = {"status": "not_run"}
    archive_sha256 = ""
    staged_target: Path | None = None
    installed_model_path: Path | None = None
    lock_token = _acquire_lock(lock)
    try:
        with tempfile.TemporaryDirectory(prefix="hephaestus-update-") as tmp:
            tmp_path = Path(tmp)
            archive = tmp_path / "source.tar.gz"
            _download(tarball_url, archive)
            actual_size = archive.stat().st_size
            if actual_size != expected_size:
                raise ValueError(
                    "release archive size mismatch: "
                    f"expected {expected_size} bytes, got {actual_size} bytes"
                )
            archive_sha256 = _sha256_file(archive)
            if archive_sha256 != expected_sha256:
                raise ValueError(
                    "release archive digest mismatch: "
                    f"expected sha256:{expected_sha256}, got sha256:{archive_sha256}"
                )
            with tarfile.open(archive, "r:gz") as tf:
                _safe_extract(tf, tmp_path)
            source_dirs = [item for item in tmp_path.iterdir() if item.is_dir()]
            if len(source_dirs) != 1:
                raise ValueError("downloaded release must contain exactly one source directory")
            source = source_dirs[0]
            source_model = _validate_runtime_layout(source, release_source=True)

            staged_target = _unique_sibling(target, "staged")
            staged_target.mkdir(parents=True)
            for name in RUNTIME_DIRS:
                src = source / name
                shutil.copytree(src, staged_target / name, ignore=PYTHON_CACHE_IGNORE)
            for name in RUNTIME_OPTIONAL_DIRS:
                src = source / name
                if src.is_dir():
                    shutil.copytree(src, staged_target / name, ignore=PYTHON_CACHE_IGNORE)
            for name in RUNTIME_FILES:
                src = source / name
                if src.is_file():
                    shutil.copy2(src, staged_target / name)
            for relative_name in RUNTIME_BRIDGE_FILES:
                src = source / relative_name
                dest = staged_target / relative_name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
            adapter_bundle = staged_target / HOST_ADAPTER_BUNDLE_DIR
            adapter_bundle.mkdir()
            for name in _host_adapter_dirs(source):
                src = source / name
                if src.is_dir():
                    shutil.copytree(src, adapter_bundle / name, ignore=PYTHON_CACHE_IGNORE)
            for name in ("manifest.json", "RELEASE"):
                src = source / name
                if src.is_file():
                    shutil.copy2(src, adapter_bundle / name)
            hook_installer = source / "scripts" / "install-memory-hooks.py"
            if hook_installer.is_file():
                (adapter_bundle / "scripts").mkdir(exist_ok=True)
                shutil.copy2(hook_installer, adapter_bundle / "scripts" / hook_installer.name)
            (adapter_bundle / "RELEASE").write_text(f"{tag}\n", encoding="utf-8")
            _validate_host_adapter_bundle(adapter_bundle, tag)
            runtime_model = staged_target / "models" / "model2vec" / source_model.name
            runtime_model.parent.mkdir(parents=True)
            shutil.copytree(source_model, runtime_model, ignore=PYTHON_CACHE_IGNORE)
            installed_model_path = target / "models" / "model2vec" / source_model.name
            (staged_target / "RELEASE").write_text(f"{tag}\n", encoding="utf-8")
            write_python_shims(staged_target / "bin", sys.executable)
            # The archive carries bash scripts only; Windows needs a .cmd for
            # each one or the commands disappear from cmd.exe on every update.
            write_windows_command_shims(staged_target / "bin")
            _healthcheck_runtime(staged_target)
            _activate_runtime(staged_target, target)
            staged_target = None
            adapter_sync = sync_installed_runtime_adapters(source)
            from .host_update import reconcile_host_plugins

            host_plugin_sync = reconcile_host_plugins(target / HOST_ADAPTER_BUNDLE_DIR, tag)
            plugin_cache_sync = _prune_installed_plugin_caches(
                tag,
                pending_hosts=host_plugin_sync.get("pendingHosts") or [],
            )
            memory_hook_sync = sync_installed_memory_hooks(source)
            global_router_sync = _sync_installed_global_router(target)
    finally:
        if staged_target is not None and _path_present(staged_target):
            _remove_path(staged_target)
        _release_lock(lock, lock_token)

    model_path = installed_model_path or target / RUNTIME_MODEL2VEC_PATH
    activation = _post_activation_state(
        target,
        tag,
        model_path,
        host_plugin_sync,
        plugin_cache_sync,
    )
    return {
        "runtime_root": str(target),
        "current_link": str(base / "current"),
        "updated_to": tag,
        "archive_digest": f"sha256:{archive_sha256}",
        "digest_verified": True,
        "archive_asset": archive_asset["name"],
        "model_root": str(model_path),
        "model_verified": bool(activation["modelCurrent"]),
        "adapter_sync": adapter_sync,
        "host_plugin_sync": host_plugin_sync,
        "plugin_cache_sync": plugin_cache_sync,
        "memory_hook_sync": memory_hook_sync,
        "global_router_sync": global_router_sync,
        "activation": activation,
        "reloadRequired": bool(activation["reloadRequired"]),
        "pendingHosts": activation["pendingHosts"],
    }


def sync_installed_runtime_adapters(source: Path, home: Path | None = None) -> dict[str, Any]:
    """Refresh already-installed command and skill adapters from ``source``.

    A surface the user never set up is still never created. But "did the user
    set this surface up" is a question about the DIRECTORY, not about each file
    in it. Keyed per file, the answer was always "no" for a command that did not
    exist yet, so a newly shipped command could never reach an existing machine
    through an update — measured: `hep-orch` and `hep-update` sat in the verified
    adapter bundle while `~/.claude/commands/` held seventeen of their siblings,
    and two consecutive updates reported success without adding them. Completing
    the install floor did not help either, because this loop never got as far as
    consulting it.

    So the question is asked of the directory: if the destination directory
    exists, that host surface exists on this machine and a managed file missing
    from it is filled in. If the directory does not exist, nothing is created
    and the surface stays absent, exactly as before.

    Existence, not contents. An empty managed directory is not evidence that the
    user declined our files — measured, `~/.codex/prompts` existed and held
    nothing, and a contents-based rule skipped all 14 commands for a host the
    machine plainly has set up.
    """

    home_dir = home or Path.home()
    updated: list[str] = []
    added: list[str] = []
    skipped_missing: list[str] = []
    failed: list[dict[str, str]] = []
    cache_updated: list[str] = []
    cache_added: list[str] = []
    cache_preserved: list[str] = []

    # A host-owned plugin cache is immutable once its version directory exists.
    # A Claude/Codex MCP process may still have modules loaded from any old
    # directory, and a directory named for one release must never silently carry
    # another release's bytes. Materialize only the exact new version target;
    # ledgers and live-process inspection decide whether that target itself may
    # be repaired and when the host can switch over.
    protected_cache_paths = _installed_plugin_cache_ledger_paths(home_dir)
    active_cache_paths = _active_plugin_cache_paths(home_dir)
    if active_cache_paths is None:
        # Process inspection is unavailable (notably on some Windows hosts).
        # Keep every existing managed cache until a later run can prove it is
        # safe to prune; this is deliberately conservative and still permits a
        # new target directory to be created for the next host process.
        protected_cache_paths.update(
            _canonical_path(child)
            for _, child in _existing_plugin_cache_children(home_dir)
        )
    else:
        protected_cache_paths.update(active_cache_paths)

    for src_rel, dest in _installed_adapter_file_targets(source, home_dir):
        src = source / src_rel
        if not src.exists():
            skipped_missing.append(str(dest))
            continue
        existed = dest.exists()
        if not existed and not dest.parent.is_dir():
            skipped_missing.append(str(dest))
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            (updated if existed else added).append(str(dest))
        except Exception as exc:
            failed.append({"path": str(dest), "error": str(exc)})

    for src_rel, dest in _installed_adapter_dir_targets(source, home_dir):
        src = source / src_rel
        if not src.is_dir() or not dest.exists():
            skipped_missing.append(str(dest))
            continue
        try:
            _replace_directory(src, dest)
            updated.append(str(dest))
        except Exception as exc:
            failed.append({"path": str(dest), "error": str(exc)})

    source_release = _source_release_tag(source)
    for src_rel, dest in _installed_plugin_cache_targets(
        source,
        home_dir,
        protected_paths=protected_cache_paths,
    ):
        src = source / src_rel
        if not src.is_dir() or (dest.exists() and (not dest.is_dir() or dest.is_symlink())):
            skipped_missing.append(str(dest))
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            existed = dest.is_dir()
            _replace_directory(src, dest)
            if source_release:
                (dest / "RELEASE").write_text(f"{source_release}\n", encoding="utf-8")
            write_python_shims(dest / "bin", sys.executable)
            write_windows_command_shims(dest / "bin")
            updated.append(str(dest))
            (cache_updated if existed else cache_added).append(str(dest))
        except Exception as exc:
            failed.append({"path": str(dest), "error": str(exc)})

    target_cache_name = _runtime_version_dir_name(source_release) if source_release else None
    for _, child in _existing_plugin_cache_children(home_dir):
        if child.name != target_cache_name or _canonical_path(child) in protected_cache_paths:
            cache_preserved.append(str(child))

    grok_result = _sync_grok_marketplace_cache(home_dir)
    updated.extend(grok_result["updated"])
    failed.extend(grok_result["failed"])

    return {
        "updated": updated,
        # Named separately from `updated` so a receipt can show that a surface
        # gained a command it did not have, rather than burying it in a refresh
        # count that looks identical whether or not anything arrived.
        "added": added,
        "skipped_missing": skipped_missing,
        "failed": failed,
        "plugin_cache": {
            "updated": cache_updated,
            "added": cache_added,
            "preserved": cache_preserved,
        },
    }


def _legacy_in_place_plugin_cache_paths(
    release_tag: str,
    home: Path,
) -> dict[str, list[str]]:
    """Find cache paths that the v1.2.32 updater rewrote under an old name."""

    target = _runtime_version_dir_name(release_tag)
    result: dict[str, list[str]] = {"claude": [], "codex": []}
    for host, _, cache_root in _plugin_cache_roots(home):
        if not cache_root.is_dir() or cache_root.is_symlink():
            continue
        try:
            children = list(cache_root.iterdir())
        except OSError:
            continue
        for child in children:
            if not child.is_dir() or child.is_symlink() or child.name == target:
                continue
            try:
                marker = (child / "RELEASE").read_text(encoding="utf-8").strip().lstrip("vV")
            except OSError:
                marker = ""
            manifest = (
                child / ".claude-plugin" / "plugin.json"
                if host == "claude"
                else child / ".codex-plugin" / "plugin.json"
            )
            try:
                manifest_version = str(
                    json.loads(manifest.read_text(encoding="utf-8")).get("version") or ""
                ).strip().lstrip("vV")
            except (OSError, ValueError, AttributeError):
                manifest_version = ""
            if marker == target and manifest_version == target:
                result[host].append(str(child))
    return {host: sorted(paths) for host, paths in result.items() if paths}


def _materialize_exact_plugin_caches(
    source: Path,
    release_tag: str,
    home: Path,
) -> dict[str, Any]:
    """Create only exact-version Codex/Claude caches, without vendor commands."""

    target_name = _runtime_version_dir_name(release_tag)
    ledger_paths = _installed_plugin_cache_ledger_paths(home)
    active_paths = _active_plugin_cache_paths(home)
    protected = set(ledger_paths)
    if active_paths is None:
        protected.update(_canonical_path(path) for _, path in _existing_plugin_cache_children(home))
    else:
        protected.update(active_paths)
    hosts: list[dict[str, Any]] = []
    added: list[str] = []
    current: list[str] = []
    preserved: list[str] = []
    failed: list[dict[str, str]] = []
    for host, src_rel, cache_root in _plugin_cache_roots(home):
        src = source / src_rel
        row: dict[str, Any] = {"host": host, "root": str(cache_root)}
        if not cache_root.is_dir() or cache_root.is_symlink():
            row["status"] = "not_installed"
            hosts.append(row)
            continue
        target = cache_root / target_name
        if _plugin_cache_payload_matches(target, release_tag):
            row.update({"status": "current", "target": str(target)})
            current.append(str(target))
            hosts.append(row)
            continue
        if not src.is_dir():
            error = {"path": str(src), "error": "target_plugin_payload_missing"}
            row.update({"status": "blocked", "reason": error["error"]})
            failed.append(error)
            hosts.append(row)
            continue
        if target.exists() and _canonical_path(target) in protected:
            error = {"path": str(target), "error": "protected_target_cache_invalid"}
            row.update({"status": "blocked", "reason": error["error"]})
            preserved.append(str(target))
            failed.append(error)
            hosts.append(row)
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            _replace_directory(src, target)
            (target / "RELEASE").write_text(f"v{target_name}\n", encoding="utf-8")
            write_python_shims(target / "bin", sys.executable)
            write_windows_command_shims(target / "bin")
            if not _plugin_cache_payload_matches(target, release_tag):
                raise ValueError("materialized_target_cache_failed_verification")
            added.append(str(target))
            row.update({"status": "added", "target": str(target)})
        except Exception as exc:
            error = {"path": str(target), "error": str(exc)}
            failed.append(error)
            row.update({"status": "blocked", "reason": str(exc)})
        hosts.append(row)
    return {
        "schemaVersion": "agentlas.plugin-cache-materialize.v1",
        "status": "blocked" if failed else "pass",
        "release": f"v{target_name}",
        "bounded": True,
        "vendorCliInvoked": False,
        "hosts": hosts,
        "added": added,
        "current": current,
        "preserved": preserved,
        "failed": failed,
    }


def reconcile_legacy_host_plugin_transition(
    source: Path,
    runtime_root: Path,
    release_tag: str,
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    """Repair the first hop executed by the still-running v1.2.32 updater.

    This is intentionally separate from ``reconcile_current_installation``:
    the latter invokes the memory-hook installer and would recurse when called
    from the target archive's post-activation bridge subprocess.
    """

    home_dir = (home or Path.home()).expanduser().resolve()
    target_root = runtime_root.expanduser().resolve()
    bundle = target_root / HOST_ADAPTER_BUNDLE_DIR
    release_commit_sha = _release_provenance_commit(source)
    if _release_requires_provenance(source) and release_commit_sha is None:
        return {
            "schemaVersion": "agentlas.legacy-host-plugin-transition.v1",
            "status": "blocked",
            "reason": "release_provenance_missing_or_invalid",
            "bounded": True,
            "vendorCliInvoked": False,
        }
    if release_commit_sha is not None:
        try:
            _write_json(
                target_root / RELEASE_PROVENANCE_FILE,
                {
                    "schemaVersion": "agentlas.release-provenance.v1",
                    "commit": release_commit_sha,
                },
            )
        except OSError as exc:
            return {
                "schemaVersion": "agentlas.legacy-host-plugin-transition.v1",
                "status": "blocked",
                "reason": "release_provenance_persist_failed",
                "error": str(exc),
                "bounded": True,
                "vendorCliInvoked": False,
            }
    try:
        _validate_host_adapter_bundle(bundle, release_tag)
    except (OSError, ValueError) as exc:
        return {
            "schemaVersion": "agentlas.legacy-host-plugin-transition.v1",
            "status": "blocked",
            "reason": "host_adapter_bundle_invalid",
            "error": str(exc),
            "bounded": True,
            "vendorCliInvoked": False,
        }
    legacy = _legacy_in_place_plugin_cache_paths(release_tag, home_dir)
    caches = _materialize_exact_plugin_caches(source, release_tag, home_dir)
    from .host_update import reconcile_host_plugin_transition_without_cli

    persistent = reconcile_host_plugin_transition_without_cli(
        bundle,
        release_tag,
        home=home_dir,
        unsafe_legacy_paths=legacy,
        release_commit_sha=release_commit_sha,
    )
    plugin_cache = _prune_installed_plugin_caches(
        release_tag,
        home=home_dir,
        pending_hosts=persistent.get("pendingHosts") or [],
    )
    preserved_legacy = sorted(
        path
        for paths in legacy.values()
        for path in paths
        if Path(path).is_dir()
    )
    blocked = (
        caches.get("status") != "pass"
        or persistent.get("status") == "blocked"
        or plugin_cache.get("status") == "partial"
    )
    pending = bool(persistent.get("reloadRequired"))
    return {
        "schemaVersion": "agentlas.legacy-host-plugin-transition.v1",
        "status": "blocked" if blocked else "pending_reload" if pending else "pass",
        "release": release_tag if str(release_tag).startswith("v") else f"v{release_tag}",
        "bounded": True,
        "vendorCliInvoked": False,
        "reloadRequired": pending,
        "unsafeLegacyInPlace": bool(legacy),
        "unsafeLegacyPaths": sorted(path for paths in legacy.values() for path in paths),
        "preservedLegacyPaths": preserved_legacy,
        "cacheMaterialization": caches,
        "pluginCacheSync": plugin_cache,
        "persistentState": persistent,
    }


def reconcile_current_installation(
    runtime_root: Path | None = None,
    *,
    home: Path | None = None,
) -> dict[str, Any]:
    """Retry every installed host from the persisted verified adapter bundle."""

    selected_root = runtime_root or Path(__file__).resolve().parent.parent
    release = current_release(selected_root)
    bundle = selected_root / HOST_ADAPTER_BUNDLE_DIR
    if not release or not bundle.is_dir():
        return {
            "status": "not_available",
            "reason": "verified_host_adapter_bundle_missing",
            "release": release,
        }
    try:
        _validate_host_adapter_bundle(bundle, release)
    except (OSError, ValueError) as exc:
        return {"status": "blocked", "reason": "host_adapter_bundle_invalid", "error": str(exc)}

    adapters = sync_installed_runtime_adapters(bundle, home=home)
    from .host_update import reconcile_host_plugins

    plugins = reconcile_host_plugins(bundle, release, home=home)
    plugin_cache = _prune_installed_plugin_caches(
        release,
        home=home,
        pending_hosts=plugins.get("pendingHosts") or [],
    )
    hooks = sync_installed_memory_hooks(bundle, home=home)
    global_router = _sync_installed_global_router(selected_root, home=home)
    pending_hosts = sorted(set(plugins.get("pendingHosts") or []))
    failed = (
        bool(adapters.get("failed"))
        or plugins.get("status") == "partial"
        or plugin_cache.get("status") == "partial"
        or hooks.get("status") == "fail"
        or global_router.get("status") == "failed"
    )
    return {
        "status": "partial" if failed else "pending_reload" if pending_hosts else "pass",
        "release": release,
        "reloadRequired": bool(pending_hosts),
        "pendingHosts": pending_hosts,
        "adapterSync": adapters,
        "hostPluginSync": plugins,
        "pluginCacheSync": plugin_cache,
        "memoryHookSync": hooks,
        "globalRouterSync": global_router,
    }


def _requires_current_release_rehydrate(
    current: str | None,
    latest: Any,
    reconciliation: dict[str, Any],
) -> bool:
    """Recover users upgraded by an older updater that lacked host_adapters.

    Releases before the all-host updater can activate the new runtime but
    cannot persist its verified adapter bundle. The next run is already on the
    latest version, so it must safely reinstall that exact same digest-verified
    release once instead of remaining permanently unable to reconcile host
    plugin registries.
    """

    latest_tag = str(latest or "").strip()
    return (
        bool(current)
        and str(current).strip() == latest_tag
        and reconciliation.get("status") == "not_available"
        and reconciliation.get("reason") == "verified_host_adapter_bundle_missing"
    )


def _sync_installed_global_router(runtime_root: Path, *, home: Path | None = None) -> dict[str, Any]:
    home_dir = (home or Path.home()).expanduser().resolve()
    managed_files = (
        home_dir / ".codex" / "AGENTS.md",
        home_dir / ".claude" / "CLAUDE.md",
        home_dir / ".gemini" / "GEMINI.md",
    )
    if not any(path.is_file() and "HEPHAESTUS:GLOBAL-ROUTER:BEGIN" in path.read_text(encoding="utf-8", errors="ignore") for path in managed_files):
        return {"status": "not_installed"}
    runner = runtime_root / "bin" / ("hephaestus.cmd" if os.name == "nt" else "hephaestus")
    if not runner.is_file():
        return {"status": "failed", "reason": "runner_missing"}
    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    env["HEPHAESTUS_AUTO_UPDATE"] = "0"
    try:
        completed = subprocess.run(
            [str(runner), "global", "install"],
            cwd=str(home_dir),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "failed", "reason": type(exc).__name__}
    return {"status": "updated" if completed.returncode == 0 else "failed", "exitCode": completed.returncode}


def sync_installed_memory_hooks(source: Path, home: Path | None = None) -> dict[str, Any]:
    """Install merge-safe memory hooks for hosts detected on this machine.

    Claude and Codex hook manifests live inside their plugin bundles and are
    refreshed by :func:`sync_installed_runtime_adapters`. Antigravity, Grok,
    and OpenCode use global host files, so a runtime self-update must invoke the
    same owned-key/managed-block installer as the one-touch install. Hook repair
    is reported independently: an invalid user config is preserved and does not
    roll back an otherwise healthy, digest-verified runtime update.
    """

    installer = source / "scripts" / "install-memory-hooks.py"
    home_dir = (home or Path.home()).expanduser().resolve()
    if not installer.is_file():
        return {
            "status": "fail",
            "installed": {},
            "errors": {"installer": f"missing hook installer: {installer}"},
        }

    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        completed = subprocess.run(
            [
                sys.executable,
                str(installer),
                "--source-dir",
                str(source),
                "--home",
                str(home_dir),
                "--hosts",
                "auto",
            ],
            cwd=str(source),
            env=env,
            capture_output=True,
            text=True,
            timeout=MEMORY_HOOK_SYNC_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"status": "fail", "installed": {}, "errors": {"installer": str(exc)}}

    try:
        payload = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError):
        detail = (completed.stderr or completed.stdout or "invalid installer output").strip()[-500:]
        return {"status": "fail", "installed": {}, "errors": {"installer": detail}}
    if not isinstance(payload, dict):
        return {
            "status": "fail",
            "installed": {},
            "errors": {"installer": "hook installer returned a non-object response"},
        }
    installed = payload.get("installed") if isinstance(payload.get("installed"), dict) else {}
    errors = payload.get("errors") if isinstance(payload.get("errors"), dict) else {}
    status = "pass" if completed.returncode == 0 and payload.get("status") == "pass" else "fail"
    if status == "fail" and not errors:
        detail = (completed.stderr or "hook installer failed without an error record").strip()[-500:]
        errors = {"installer": detail}
    desktop_repair = payload.get("desktop_repair")
    if not isinstance(desktop_repair, dict):
        desktop_repair = {"status": "not_applicable", "reason": "not_reported"}
    desktop_updater_cleanup = payload.get("desktop_updater_cleanup")
    if not isinstance(desktop_updater_cleanup, dict):
        desktop_updater_cleanup = {"status": "not_applicable", "reason": "not_reported"}
    return {
        "status": status,
        "installed": installed,
        "errors": errors,
        "desktop_repair": desktop_repair,
        "desktop_updater_cleanup": desktop_updater_cleanup,
    }


def retry_installed_desktop_repair(source: Path, home: Path | None = None) -> dict[str, Any]:
    marker = source / "desktop-update-bridge-v1.json"
    installer = source / "scripts" / "install-memory-hooks.py"
    if marker.is_file() and installer.is_file():
        result = sync_installed_memory_hooks(source, home)
        repair = result.get("desktop_repair")
        return repair if isinstance(repair, dict) else {"status": "not_applicable", "reason": "not_reported"}

    # Desktop v0.8.58/v0.8.59 ship the v1.1.50 updater. It copies the complete
    # agentlas_cloud package but not newly added root bridge files. The embedded
    # module and exact marker therefore remain available for every later app
    # launch even if the freshly extracted one-shot repair did not finish.
    try:
        from agentlas_cloud.desktop_repair import repair_installed_desktop_python_cache_seal

        return repair_installed_desktop_python_cache_seal(source, home)
    except (ImportError, OSError):
        return {"status": "not_applicable", "reason": "bridge_not_installed"}


def retry_installed_desktop_updater_cleanup(source: Path, home: Path | None = None) -> dict[str, Any]:
    """Retry the v0.8.65/v0.8.66 stale updater cleanup from managed Core."""

    marker = source / "agentlas_cloud" / "desktop-updater-cleanup-bridge-v1.json"
    if not marker.is_file():
        return {"status": "not_applicable", "reason": "bridge_not_installed"}
    try:
        from agentlas_cloud.desktop_updater_cleanup import repair_installed_desktop_updater_cache

        return repair_installed_desktop_updater_cache(source, home)
    except (ImportError, OSError):
        return {"status": "not_applicable", "reason": "bridge_not_installed"}
    except Exception:
        # The runtime updater remains fail-silent and can try again later. Do
        # not let a Desktop cache repair failure block a verified OS update.
        return {"status": "blocked", "reason": "bridge_failed"}


def _selected_python_resources(executable: Path) -> Path | None:
    parts = executable.parts
    for index, part in enumerate(parts):
        if (
            part.endswith(".app")
            and index + 2 < len(parts)
            and parts[index + 1] == "Contents"
            and parts[index + 2] == "Resources"
        ):
            return Path(*parts[: index + 3])
    for index, part in enumerate(parts):
        if part.lower() == "resources":
            return Path(*parts[: index + 1])
    return None


def _validated_python_executable(executable: str) -> tuple[str, Path | None]:
    if any(character in executable for character in ("\r", "\n", "\x00")):
        raise ValueError("Python executable path is not representable safely")

    # Package-contract tests and POSIX release builders intentionally generate
    # Windows launchers without executing the referenced interpreter. Permit
    # only a canonical drive-rooted .exe path in that non-native case. Native
    # hosts still require the executable to resolve to a real regular file.
    windows_path = PureWindowsPath(executable)
    if os.name != "nt" and windows_path.is_absolute():
        if not re.fullmatch(r"[A-Za-z]:", windows_path.drive):
            raise ValueError("Non-native Windows Python executable must be drive-rooted")
        if windows_path.suffix.lower() != ".exe":
            raise ValueError("Non-native Windows Python executable must name an .exe")
        if any(character in executable for character in ('"', "%")):
            raise ValueError("Windows Python executable path is not representable safely")
        reserved = {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{index}" for index in range(1, 10)),
            *(f"LPT{index}" for index in range(1, 10)),
        }
        for part in windows_path.parts[1:]:
            if (
                not part
                or part in (".", "..")
                or part.endswith((" ", "."))
                or any(ord(character) < 32 or character in '<>:"|?*' for character in part)
                or part.split(".", 1)[0].upper() in reserved
            ):
                raise ValueError("Non-native Windows Python executable path is invalid")
        return executable, None

    if os.name == "nt" and any(character in executable for character in ('"', "%")):
        raise ValueError("Windows Python executable path is not representable safely")
    selected = Path(executable).expanduser().resolve(strict=True)
    if not selected.is_file():
        raise ValueError("Python executable is not a regular file")
    return str(selected), selected


def _safe_python_cache_prefix(executable: str, home: Path | None = None) -> Path:
    _, selected = _validated_python_executable(executable)
    user_home = (home or Path.home()).expanduser()
    if not user_home.is_absolute():
        raise ValueError("Python cache home must be absolute")
    resolved_home = user_home.resolve(strict=True)
    if not resolved_home.is_dir():
        raise ValueError("Python cache home is not a directory")
    if os.name == "nt":
        prefix = resolved_home / "AppData" / "Local" / "Agentlas" / "PythonCache"
    elif sys.platform == "darwin":
        prefix = resolved_home / "Library" / "Caches" / "Agentlas" / "python"
    else:
        prefix = resolved_home / ".cache" / "agentlas" / "python"
    resolved_prefix = prefix.resolve(strict=False)
    resources = _selected_python_resources(selected) if selected is not None else None
    if resources is not None and (
        resolved_prefix == resources or resources in resolved_prefix.parents
    ):
        raise ValueError("Python cache directory resolves inside selected runtime resources")
    text = str(resolved_prefix)
    if any(character in text for character in ("\r", "\n", "\x00")):
        raise ValueError("Python cache directory is not representable safely")
    if os.name == "nt" and any(character in text for character in ('"', "%")):
        raise ValueError("Python cache directory is not representable safely on Windows")
    return resolved_prefix


def _is_shipped_interpreter(executable: str) -> bool:
    """Whether this interpreter travels with Agentlas rather than with the user.

    Only these may ignore user site-packages — see the comment in
    ``write_python_shims``.
    """
    try:
        resolved = str(Path(executable).resolve(strict=False))
    except (OSError, ValueError):
        return False
    markers = (
        f"{os.sep}python-runtime{os.sep}",
        f"{os.sep}.agentlas{os.sep}runtime{os.sep}",
        f"{os.sep}Agentlas.app{os.sep}",
    )
    return any(marker in resolved for marker in markers)


def write_python_shims(bin_dir: Path, executable: str) -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    shell_shim = bin_dir / "python3"
    cmd_shim = bin_dir / "python3.cmd"
    cmd_runner = bin_dir / "hephaestus.cmd"
    env_cmd = bin_dir / "hephaestus-env.cmd"
    executable_text, _ = _validated_python_executable(executable)
    cache_prefix = _safe_python_cache_prefix(executable)
    shell_executable = shlex.quote(executable_text)
    shell_cache_prefix = shlex.quote(str(cache_prefix))
    if os.name == "nt":
        cmd_cache = f'set "PYTHONPYCACHEPREFIX={cache_prefix}"\r\n'
    else:
        cmd_cache = (
            'if defined LOCALAPPDATA (set "PYTHONPYCACHEPREFIX=%LOCALAPPDATA%\\Agentlas\\PythonCache") '
            'else (set "PYTHONPYCACHEPREFIX=%TEMP%\\Agentlas-PythonCache")\r\n'
        )
    # The bash shim keeps LF and stays on write_text; only .cmd files need the
    # CRLF-preserving writer.
    # A shipped interpreter brings its own libraries and must not read the
    # user's. Measured 2026-08-17: the bundled 3.12 runtime loaded
    # ~/.local/lib/python3.12/site-packages ahead of its own, found an x86_64
    # `rpds` left there by some earlier install, and `import jsonschema` died on
    # an architecture mismatch — so every package build reported "schema
    # validation unavailable" blockers no user could act on.
    #
    # This applies ONLY to an interpreter we ship. A system Python resolved from
    # PATH belongs to the user, and its jsonschema most likely lives in exactly
    # the directory this would hide.
    isolate_user_site = "PYTHONNOUSERSITE=1" if _is_shipped_interpreter(executable_text) else ""
    shell_shim.write_text(
        '#!/usr/bin/env bash\n'
        'export PYTHONDONTWRITEBYTECODE=1\n'
        f"export PYTHONPYCACHEPREFIX={shell_cache_prefix}\n"
        + (f"export {isolate_user_site}\n" if isolate_user_site else "")
        + f'exec {shell_executable} "$@"\n',
        encoding="utf-8",
    )
    shell_shim.chmod(0o755)
    _write_cmd_text(
        cmd_shim,
        '@echo off\r\n'
        'setlocal\r\n'
        'set "PYTHONDONTWRITEBYTECODE=1"\r\n'
        f"{cmd_cache}"
        f'"{executable_text}" %*\r\n'
        'exit /b %ERRORLEVEL%\r\n',
    )
    _write_cmd_runner(cmd_runner, cache_prefix)
    _write_cmd_text(
        env_cmd,
        '@echo off\r\n'
        'set "PYTHONUTF8=1"\r\n'
        'set "PYTHONIOENCODING=utf-8"\r\n'
        'set "PYTHONDONTWRITEBYTECODE=1"\r\n'
        f"{cmd_cache}"
        'set "PYTHONPATH=%~dp0..;%PYTHONPATH%"\r\n',
    )


def _write_cmd_text(path: Path, text: str) -> None:
    """Write a .cmd file with its CRLF line endings intact.

    Path.write_text() opens with newline=None, which re-translates every "\n" to
    os.linesep — on Windows that turns the "\r\n" these files require into
    "\r\r\n". Its `newline=` parameter only exists from Python 3.10 and the
    launchers accept 3.9, so open() is used explicitly instead of passing it.
    """

    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def write_windows_command_shims(bin_dir: Path) -> list[str]:
    """Give every bash command in the runtime a `.cmd` sibling on Windows.

    This exists in BOTH install paths on purpose. scripts/install-all-runtimes.sh
    writes these wrappers, and then this module — the updater — replaces the whole
    runtime directory from the release archive. Measured: an auto-update triggered
    during a fresh install removed all 17 wrappers the installer had just written,
    because only python3/hephaestus shims were rewritten here. On Windows that
    silently takes every command back out of cmd.exe and PowerShell.

    cmd.exe cannot execute a shebang script, so each wrapper hands the script to
    bash by absolute path (bash.exe is usually not on the PATH cmd.exe sees).
    Returns the wrapper names written; empty off Windows or when bash is absent.
    """
    if os.name != "nt":
        return []
    bash = shutil.which("bash") or shutil.which("bash.exe")
    if not bash:
        return []
    # A path cmd.exe cannot execute is worse than a bare name: MSYS answers with
    # its own virtual mount path (/usr/bin/bash), which resolves nowhere outside
    # MSYS. Fall back to letting cmd.exe resolve `bash` from PATH.
    if not re.match(r"^[A-Za-z]:[\\/]", bash):
        bash = "bash"
    # python3/hephaestus own native .cmd entrypoints from write_python_shims, and
    # agentlas-python-cache-boundary is a sourced library, not a command.
    skip = {"python3", "hephaestus", "Hephaestus", "agentlas-python-cache-boundary"}
    written: list[str] = []
    for script in sorted(bin_dir.iterdir()):
        if not script.is_file() or script.suffix == ".cmd" or script.name in skip:
            continue
        try:
            first_line = script.read_text(encoding="utf-8", errors="replace").split("\n", 1)[0]
        except OSError:
            continue
        if not first_line.startswith("#!") or "sh" not in first_line:
            continue
        target = bin_dir / f"{script.name}.cmd"
        _write_cmd_text(
        target,
            "@echo off\r\n"
            "setlocal\r\n"
            f'"{bash}" "{script}" %*\r\n'
            "exit /b %ERRORLEVEL%\r\n",
        )
        written.append(target.name)
    return written


def _write_cmd_runner(path: Path, cache_prefix: Path | None = None) -> None:
    if cache_prefix is not None and os.name == "nt":
        cmd_cache = f'set "PYTHONPYCACHEPREFIX={cache_prefix}"\r\n'
    else:
        cmd_cache = (
            'if defined LOCALAPPDATA (set "PYTHONPYCACHEPREFIX=%LOCALAPPDATA%\\Agentlas\\PythonCache") '
            'else (set "PYTHONPYCACHEPREFIX=%TEMP%\\Agentlas-PythonCache")\r\n'
        )
    _write_cmd_text(
        path,
        '@echo off\r\n'
        'setlocal\r\n'
        'set "PYTHONUTF8=1"\r\n'
        'set "PYTHONIOENCODING=utf-8"\r\n'
        'set "PYTHONDONTWRITEBYTECODE=1"\r\n'
        f"{cmd_cache}"
        'set "PYTHONPATH=%~dp0..;%PYTHONPATH%"\r\n'
        'if defined HEPHAESTUS_PYTHON goto use_env_python\r\n'
        'if exist "%~dp0python3.cmd" goto use_python3_shim\r\n'
        'where py >nul 2>nul\r\n'
        'if not errorlevel 1 goto use_py_launcher\r\n'
        'where python >nul 2>nul\r\n'
        'if not errorlevel 1 goto use_path_python\r\n'
        'echo hephaestus: Python 3.9+ not found. Install Python from python.org and rerun hephaestus doctor. 1>&2\r\n'
        'exit /b 127\r\n'
        '\r\n'
        ':use_env_python\r\n'
        '"%HEPHAESTUS_PYTHON%" -m agentlas_cloud %*\r\n'
        'exit /b %ERRORLEVEL%\r\n'
        '\r\n'
        ':use_python3_shim\r\n'
        'call "%~dp0python3.cmd" -m agentlas_cloud %*\r\n'
        'exit /b %ERRORLEVEL%\r\n'
        '\r\n'
        ':use_py_launcher\r\n'
        'py -3 -m agentlas_cloud %*\r\n'
        'exit /b %ERRORLEVEL%\r\n'
        '\r\n'
        ':use_path_python\r\n'
        'python -m agentlas_cloud %*\r\n'
        'exit /b %ERRORLEVEL%\r\n',
    )


_SEMVER_RE = re.compile(
    r"^[vV]?(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?$"
)


def _parse_semver(value: Any) -> tuple[str, str, str, tuple[str, ...]] | None:
    if not isinstance(value, str):
        return None
    match = _SEMVER_RE.fullmatch(value.strip())
    if not match:
        return None
    prerelease = tuple(match.group(4).split(".")) if match.group(4) else ()
    if any(item.isascii() and item.isdigit() and len(item) > 1 and item.startswith("0") for item in prerelease):
        return None
    return match.group(1), match.group(2), match.group(3), prerelease


def _compare_numeric_identifier(left: str, right: str) -> int:
    if len(left) != len(right):
        return -1 if len(left) < len(right) else 1
    if left == right:
        return 0
    return -1 if left < right else 1


def _compare_semver(left: Any, right: Any) -> int | None:
    """Return SemVer 2.0.0 precedence; build metadata does not affect it."""

    parsed_left = _parse_semver(left)
    parsed_right = _parse_semver(right)
    if parsed_left is None or parsed_right is None:
        return None
    for left_core, right_core in zip(parsed_left[:3], parsed_right[:3]):
        compared = _compare_numeric_identifier(left_core, right_core)
        if compared:
            return compared
    left_pre = parsed_left[3]
    right_pre = parsed_right[3]
    if not left_pre and not right_pre:
        return 0
    if not left_pre:
        return 1
    if not right_pre:
        return -1
    for index in range(max(len(left_pre), len(right_pre))):
        if index >= len(left_pre):
            return -1
        if index >= len(right_pre):
            return 1
        left_item = left_pre[index]
        right_item = right_pre[index]
        if left_item == right_item:
            continue
        left_numeric = left_item.isascii() and left_item.isdigit()
        right_numeric = right_item.isascii() and right_item.isdigit()
        if left_numeric and right_numeric:
            return _compare_numeric_identifier(left_item, right_item)
        if left_numeric != right_numeric:
            return -1 if left_numeric else 1
        return -1 if left_item < right_item else 1
    return 0


def _release_status(current: str | None, latest: Any) -> str:
    if not latest:
        return "unknown"
    if not current:
        return "missing_release_marker"
    comparison = _compare_semver(str(latest), current)
    if comparison is None:
        return "unknown"
    if comparison > 0:
        return "update_available"
    return "current"


def _is_comparable_release(value: str | None) -> bool:
    return _parse_semver(value) is not None


def _runtime_base() -> Path:
    return Path(os.environ.get("HEPHAESTUS_RUNTIME_BASE") or Path.home() / ".agentlas" / "runtime")


def _auto_update_disabled() -> bool:
    return os.environ.get("HEPHAESTUS_AUTO_UPDATE", "1") == "0" or os.environ.get("HEPHAESTUS_UPDATE_CHECK", "1") == "0"


def _marker_recent(epoch: Any, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
    return isinstance(epoch, (int, float)) and 0 <= time.time() - float(epoch) < ttl_seconds


def _run_auto_update_once(root: Path | None = None) -> dict[str, Any]:
    runtime_root = root or Path(__file__).resolve().parent.parent
    current = current_release(runtime_root)
    marker_path = _runtime_base() / AUTO_UPDATE_MARKER
    marker = _read_json(marker_path)
    # Metadata checks must not increase the cadence of legacy repair work.
    maintenance_due = not _marker_recent(marker.get("last_maintenance_epoch"))
    desktop_repair = marker.get("desktop_repair") or {"status": "deferred"}
    desktop_updater_cleanup = marker.get("desktop_updater_cleanup") or {"status": "deferred"}
    if maintenance_due:
        marker["last_maintenance_epoch"] = int(time.time())
        _write_json(marker_path, marker)
        try:
            from .auto_update_service import retire_auto_update_service

            retire_auto_update_service()
        except Exception:
            pass
        desktop_repair = retry_installed_desktop_repair(runtime_root)
        desktop_updater_cleanup = retry_installed_desktop_updater_cleanup(runtime_root)
    if current is not None and not _is_comparable_release(current):
        result = {
            "status": "skipped",
            "reason": "uncomparable_release",
            "current": current,
            "desktop_repair": desktop_repair,
            "desktop_updater_cleanup": desktop_updater_cleanup,
        }
        result["last_checked_epoch"] = int(time.time())
        _persist_update_marker(marker, result, runtime_root)
        return result

    latest = fetch_latest_release(force=False)
    latest_tag = latest.get("tag_name")
    status = _release_status(current, latest_tag)
    result: dict[str, Any] = {
        "status": status,
        "current": current,
        "latest": latest_tag,
        "last_checked_epoch": int(time.time()),
        "desktop_repair": desktop_repair,
        "desktop_updater_cleanup": desktop_updater_cleanup,
    }
    if status not in {"update_available", "missing_release_marker"}:
        reconciliation = reconcile_current_installation(runtime_root) if maintenance_due else {}
        result["reconciliation"] = reconciliation
        if _requires_current_release_rehydrate(current, latest_tag, reconciliation):
            installed = install_latest_runtime(latest)
            _apply_observed_install_state(result, installed, current)
            result["status"] = _installed_outcome_status("repaired_current", installed)
            result["last_applied_tag"] = latest_tag
            result["last_applied_epoch"] = int(time.time())
        _persist_update_marker(marker, result, runtime_root)
        return result
    if marker.get("last_applied_tag") == latest_tag and _marker_recent(marker.get("last_applied_epoch")):
        result["status"] = "skipped"
        result["reason"] = "already_applied_recently"
        _persist_update_marker(marker, result, runtime_root)
        return result

    installed = install_latest_runtime(latest)
    _apply_observed_install_state(result, installed, current)
    success_status = "updated" if status == "update_available" else "recovered_missing_release_marker"
    result["status"] = _installed_outcome_status(success_status, installed)
    result["last_applied_tag"] = latest_tag
    result["last_applied_epoch"] = int(time.time())
    _persist_update_marker(marker, result, runtime_root)
    return result


def _record_auto_update_failure(code: str) -> None:
    # Never persist exception text: it can contain URLs, paths or credentials.
    marker_path = _runtime_base() / AUTO_UPDATE_MARKER
    marker = _read_json(marker_path)
    previous = marker.get("failure_count", 0)
    count = min(previous + 1, len(UPDATE_RETRY_SECONDS)) if isinstance(previous, int) and previous >= 0 else 1
    _write_json(marker_path, {**marker, "status": "failed", "errorCode": code,
                              "failure_count": count, "last_failed_epoch": int(time.time())})


def _run_auto_update_guarded(runtime_root: Path) -> None:
    try:
        _run_auto_update_once(runtime_root)
    except (urllib.error.URLError, TimeoutError):
        _record_auto_update_failure("network_unavailable")
    except Exception:
        _record_auto_update_failure("update_failed")


def _spawn_auto_update_worker(runtime_root: Path) -> None:
    env = os.environ.copy()
    env["HEPHAESTUS_AUTO_UPDATE_WORKER"] = "1"
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(runtime_root) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    with open(os.devnull, "rb") as stdin, open(os.devnull, "wb") as stdout, open(os.devnull, "wb") as stderr:
        subprocess.Popen(
            [sys.executable, "-m", "agentlas_cloud.update", "--auto-update-worker", str(runtime_root)],
            cwd=str(runtime_root),
            env=env,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
            start_new_session=True,
        )


def _installed_adapter_file_targets(source: Path, home: Path) -> list[tuple[Path, Path]]:
    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    targets: list[tuple[Path, Path]] = []
    # Derived from the release being installed: a new command reaches every
    # runtime adapter without editing this function.
    for command in _managed_command_names(source=source, home=home):
        targets.extend(
            [
                (Path(".claude") / "commands" / f"{command}.md", home / ".claude" / "commands" / f"{command}.md"),
                (Path("codex") / "prompts" / f"{command}.md", codex_home / "prompts" / f"{command}.md"),
                (Path("cursor") / "plugin" / "commands" / f"{command}.md", home / ".cursor" / "commands" / f"{command}.md"),
                (Path("opencode") / "commands" / f"{command}.md", home / ".config" / "opencode" / "commands" / f"{command}.md"),
                (Path("antigravity") / "workflows" / f"{command}.md", home / ".gemini" / "antigravity" / "global_workflows" / f"{command}.md"),
                (
                    Path("antigravity") / "workflows" / f"{command}.md",
                    home / ".gemini" / "antigravity-ide" / "global_workflows" / f"{command}.md",
                ),
                (
                    Path("gemini") / "extension" / "commands" / f"{command}.toml",
                    home / ".gemini" / "commands" / f"{command}.toml",
                ),
                (
                    Path("gemini") / "extension" / "commands" / f"{command}.toml",
                    home / ".gemini" / "hephaestus-extension-source" / "commands" / f"{command}.toml",
                ),
            ]
        )
    return [(src_rel, dest) for src_rel, dest in targets if (source / src_rel).exists()]


def _installed_adapter_dir_targets(source: Path, home: Path) -> list[tuple[Path, Path]]:
    targets: list[tuple[Path, Path]] = []
    if (source / "gemini" / "extension").is_dir():
        targets.append((Path("gemini") / "extension", home / ".gemini" / "hephaestus-extension-source"))
    for skill in _managed_skill_names(source):
        targets.extend(
            [
                (Path("skills") / skill, home / ".agents" / "skills" / skill),
                (Path("skills") / skill, home / ".cursor" / "skills" / skill),
                (Path("openclaw") / "skills" / skill, home / ".openclaw" / "skills" / skill),
                (Path("skills") / skill, home / ".hermes" / "skills" / skill),
                (
                    Path("skills") / skill,
                    home / ".gemini" / "config" / "plugins" / "agentlas-os" / "skills" / skill,
                ),
            ]
        )
    return [(src_rel, dest) for src_rel, dest in targets if (source / src_rel).is_dir()]


def _plugin_cache_roots(home: Path) -> list[tuple[str, Path, Path]]:
    """Return the host plugin-cache roots owned by the Agentlas updater.

    The source-relative path is kept beside the destination so one update pass
    can refresh Claude and Codex from their matching plugin payload without
    guessing which host a cache directory belongs to.
    """

    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    return [
        (
            "claude",
            Path("claude") / "plugins" / "agentlas-core-engine-meta-agent",
            home / ".claude" / "plugins" / "cache" / "agentlas-core-engine" / "hephaestus",
        ),
        (
            "codex",
            Path("codex") / "plugins" / "agentlas-core-engine-meta-agent",
            codex_home / "plugins" / "cache" / "agentlas-core-engine" / "hephaestus",
        ),
    ]


def _canonical_path(path: Path) -> Path:
    try:
        return path.expanduser().resolve()
    except OSError:
        return Path(os.path.abspath(os.path.expanduser(str(path))))


def _installed_plugin_cache_ledger_paths(home: Path) -> set[Path]:
    """Read host install ledgers and return cache paths that must not be replaced.

    Claude records the active plugin directory in ``installed_plugins.json``;
    Codex versions in the wild may use the same shape. The ledger is a stronger
    signal than a directory name because an active process can keep using an
    older version while the runtime updater is installing a new one.
    """

    codex_home = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    ledgers = (
        home / ".claude" / "plugins" / "installed_plugins.json",
        codex_home / "plugins" / "installed_plugins.json",
    )
    protected: set[Path] = set()
    for ledger_path in ledgers:
        data = _read_json(ledger_path)
        plugins = data.get("plugins") if isinstance(data, dict) else None
        if not isinstance(plugins, dict):
            continue
        for plugin_id, entries in plugins.items():
            if not str(plugin_id).startswith("hephaestus@"):
                continue
            if isinstance(entries, dict):
                entries = [entries]
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                install_path = entry.get("installPath")
                if isinstance(install_path, str) and install_path.strip():
                    protected.add(_canonical_path(Path(install_path)))
    return protected


def _existing_plugin_cache_children(home: Path) -> list[tuple[str, Path]]:
    """Find valid Agentlas cache version directories without following symlinks."""

    children: list[tuple[str, Path]] = []
    for host, _, cache_root in _plugin_cache_roots(home):
        if not cache_root.is_dir() or cache_root.is_symlink():
            continue
        try:
            entries = list(cache_root.iterdir())
        except OSError:
            continue
        for child in entries:
            if (
                child.is_dir()
                and not child.is_symlink()
                and (child / "bin" / "hephaestus").is_file()
            ):
                children.append((host, child))
    return children


def _active_plugin_cache_paths(home: Path) -> set[Path] | None:
    """Measure cache paths present in live host command lines.

    ``None`` means process inspection was unavailable. Callers must then defer
    destructive cache work rather than assuming that no process is using it.
    """

    if os.name == "nt":
        return None
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    cache_children = _existing_plugin_cache_children(home)
    if not cache_children:
        return set()
    active: set[Path] = set()
    for line in (result.stdout or "").splitlines():
        try:
            pid_text, command = line.strip().split(None, 1)
            if int(pid_text) == os.getpid():
                continue
        except (ValueError, IndexError):
            continue
        for _, child in cache_children:
            needle = str(_canonical_path(child))
            if any(
                marker in command
                for marker in (f"{needle}/", f"{needle} ", f"{needle}\t", f'{needle}"', f"{needle}'")
            ) or command.endswith(needle):
                active.add(_canonical_path(child))
    return active


def _installed_plugin_cache_targets(
    source: Path,
    home: Path,
    *,
    protected_paths: set[Path] | None = None,
) -> list[tuple[Path, Path]]:
    """Return only the exact release cache target for each installed host.

    Version-named cache directories are immutable, including copies that are
    not currently referenced by a ledger or process. Rewriting an old name with
    new bytes makes the filesystem disagree with the host registry and makes a
    later reload impossible to reason about. The exact target is created
    atomically; a referenced/live exact target is preserved until reload.
    """

    targets: list[tuple[Path, Path]] = []
    protected = {_canonical_path(path) for path in (protected_paths or set())}
    source_release = _source_release_tag(source)
    for _, src_rel, cache_root in _plugin_cache_roots(home):
        if (
            not (source / src_rel).is_dir()
            or not cache_root.is_dir()
            or cache_root.is_symlink()
        ):
            continue
        if source_release:
            target = cache_root / _runtime_version_dir_name(source_release)
            if (
                not target.is_symlink()
                and (not target.exists() or target.is_dir())
                and _canonical_path(target) not in protected
            ):
                targets.append((src_rel, target))
    return targets


def _plugin_cache_payload_matches(path: Path, release_tag: str) -> bool:
    """Verify that a cache target carries the release it is named for."""

    expected = str(release_tag).strip().lstrip("vV")
    if not expected:
        return False
    if not (path.is_dir() and not path.is_symlink() and (path / "bin" / "hephaestus").is_file()):
        return False
    try:
        marker = (path / "RELEASE").read_text(encoding="utf-8").strip().lstrip("vV")
    except OSError:
        marker = ""
    # RELEASE is the cache-level identity anchor. Host manifests may add
    # corroborating identities, but cannot make an unmarked cache exact.
    if marker != expected:
        return False
    manifest_versions: list[str] = []
    for manifest in (
        path / ".claude-plugin" / "plugin.json",
        path / ".codex-plugin" / "plugin.json",
    ):
        if not manifest.is_file():
            continue
        try:
            version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError, AttributeError):
            return False
        manifest_versions.append(str(version or "").strip().lstrip("vV"))
    # Every identity surface that exists must name the exact directory release.
    # A mixed Claude/Codex payload used to pass as soon as either manifest
    # matched. A host manifest also must not substitute for RELEASE.
    if manifest_versions:
        return all(version == expected for version in manifest_versions)
    # Older cache payloads did not carry a plugin manifest, so their RELEASE
    # marker is the only available identity. A present-but-mismatched manifest
    # is stronger evidence and must not be overridden by a stale marker.
    return True


def _compare_plugin_cache_paths(left: Path, right: Path) -> int:
    compared = _compare_semver(left.name, right.name)
    if compared is not None:
        return compared
    return (left.name > right.name) - (left.name < right.name)


def _prune_installed_plugin_caches(
    release_tag: str,
    *,
    home: Path | None = None,
    pending_hosts: list[str] | None = None,
) -> dict[str, Any]:
    """Prune only proven orphaned cache versions after a target is verified.

    The exact target and one rollback copy are retained. Ledger-referenced or
    live-process paths are always retained, and all work is deferred when the
    target is missing or process inspection is unavailable. Unrelated entries
    (for example a host's ``notes`` directory) are never considered.
    """

    home_dir = home or Path.home()
    target_name = _runtime_version_dir_name(release_tag)
    ledger_paths = _installed_plugin_cache_ledger_paths(home_dir)
    active_paths = _active_plugin_cache_paths(home_dir)
    pending = {str(host) for host in (pending_hosts or [])}
    result: dict[str, Any] = {
        "schemaVersion": "agentlas.plugin-cache-sync.v1",
        "status": "pass",
        "release": f"v{target_name}",
        "hosts": [],
        "removed": [],
        "preserved": [],
        "deferred": [],
        "failed": [],
    }
    for host, _, cache_root in _plugin_cache_roots(home_dir):
        row: dict[str, Any] = {"host": host, "root": str(cache_root)}
        if not cache_root.is_dir() or cache_root.is_symlink():
            row["status"] = "not_installed"
            result["hosts"].append(row)
            continue
        target = cache_root / target_name
        if not _plugin_cache_payload_matches(target, release_tag):
            reason = "verified_target_cache_missing"
            row.update({"status": "deferred", "reason": reason, "target": str(target)})
            result["deferred"].append(str(target))
            result["status"] = "partial"
            result["hosts"].append(row)
            continue
        try:
            children = [
                child
                for child in cache_root.iterdir()
                if child.is_dir()
                and not child.is_symlink()
                and (child / "bin" / "hephaestus").is_file()
                and child.name != target_name
            ]
        except OSError as exc:
            row.update({"status": "failed", "error": str(exc)})
            result["failed"].append({"path": str(cache_root), "error": str(exc)})
            result["status"] = "partial"
            result["hosts"].append(row)
            continue

        ordered = sorted(children, key=cmp_to_key(_compare_plugin_cache_paths))
        # A rollback cache is useful only when its immutable directory name and
        # payload identity agree. The v1.2.32 updater rewrote old directories in
        # place before target-release code could run; preserving the newest of
        # those mismatches as "rollback" made the corruption permanent.
        rollback_candidates = [
            child
            for child in ordered
            if _plugin_cache_payload_matches(child, f"v{child.name}")
        ]
        keep_rollback = rollback_candidates[-1] if rollback_candidates else None
        row.update({"status": "updated", "target": str(target), "rollback": str(keep_rollback) if keep_rollback else None})
        removed: list[str] = []
        preserved: list[str] = []
        deferred: list[str] = []
        # A host transition marked pending_reload is stronger evidence than a
        # command-line path scan: a live Codex/Claude process may retain plugin
        # bytes without spelling its cache path in argv. Preserve every prior
        # cache for that host until a later reconciliation proves reload.
        if host in pending:
            deferred.extend(str(child) for child in ordered)
            result["deferred"].extend(deferred)
            row.update(
                {
                    "status": "pending_reload",
                    "reason": "host_process_not_reloaded",
                    "deferred": deferred,
                }
            )
            if result["status"] == "pass":
                result["status"] = "pending_reload"
            result["hosts"].append(row)
            continue
        for child in ordered:
            canonical = _canonical_path(child)
            if canonical in ledger_paths or (active_paths is not None and canonical in active_paths):
                preserved.append(str(child))
                result["preserved"].append(str(child))
                continue
            if active_paths is None:
                deferred.append(str(child))
                result["deferred"].append(str(child))
                result["status"] = "partial"
                continue
            if keep_rollback is not None and child == keep_rollback:
                preserved.append(str(child))
                result["preserved"].append(str(child))
                continue
            try:
                _remove_path(child)
                removed.append(str(child))
                result["removed"].append(str(child))
            except OSError as exc:
                result["failed"].append({"path": str(child), "error": str(exc)})
                result["status"] = "partial"
        if preserved:
            row["preserved"] = preserved
        if removed:
            row["removed"] = removed
        if deferred:
            row["deferred"] = deferred
        result["hosts"].append(row)
    return result


# Grok Build has no background auto-refresh of its own: `grok marketplace add`
# git-clones this repo into a hash-named directory under
# ~/.grok/marketplace-cache/ and only re-reads it when the user runs
# `grok marketplace update`. Without this, new commands (including this one)
# only reach Grok after a manual update the user is unlikely to know to run.
def _grok_marketplace_cache_targets(home: Path) -> list[Path]:
    """Find Grok marketplace-cache clones of this repo by origin remote URL.

    Only directories whose ``origin`` remote points at this project are
    returned, so unrelated cached marketplaces (Firebase, Claude's official
    marketplace, xAI's own, ...) are never touched.
    """

    cache_root = home / ".grok" / "marketplace-cache"
    targets: list[Path] = []
    try:
        children = list(cache_root.iterdir())
    except OSError:
        return targets
    for child in children:
        if not child.is_dir() or child.is_symlink() or not (child / ".git").is_dir():
            continue
        try:
            result = subprocess.run(
                ["git", "-C", str(child), "remote", "get-url", "origin"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception:
            continue
        url = (result.stdout or "").strip().lower()
        if "agentlas-ai/agentlas-os" in url:
            targets.append(child)
    return targets


def _sync_grok_marketplace_cache(home: Path) -> dict[str, Any]:
    """Fast-forward any Grok marketplace-cache clone of this repo to latest.

    This stays git-native (fetch + hard reset) instead of replacing the
    directory wholesale, because Grok may rely on the clone's ``.git``
    metadata for its own integrity checks. It never invokes the ``grok``
    binary itself: the exact marketplace name Grok registers this repo under
    is not something this codebase controls, so guessing at a
    ``grok marketplace update <name>`` invocation would be a fragile
    assumption. Refreshing the git checkout directly is the conservative
    option — it is exactly what a marketplace update would do internally.
    """

    updated: list[str] = []
    failed: list[dict[str, str]] = []
    for cache_dir in _grok_marketplace_cache_targets(home):
        try:
            subprocess.run(
                ["git", "-C", str(cache_dir), "fetch", "--quiet", "origin", "main"],
                capture_output=True,
                timeout=20,
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(cache_dir), "reset", "--quiet", "--hard", "FETCH_HEAD"],
                capture_output=True,
                timeout=20,
                check=True,
            )
            updated.append(str(cache_dir))
        except Exception as exc:
            failed.append({"path": str(cache_dir), "error": str(exc)})
    return {"updated": updated, "failed": failed}


def _replace_directory(src: Path, dest: Path) -> None:
    tmp = dest.parent / f".{dest.name}.tmp-{os.getpid()}"
    if tmp.exists() or tmp.is_symlink():
        if tmp.is_dir() and not tmp.is_symlink():
            shutil.rmtree(tmp)
        else:
            tmp.unlink()
    shutil.copytree(src, tmp, ignore=PYTHON_CACHE_IGNORE)
    if dest.exists() or dest.is_symlink():
        if dest.is_dir() and not dest.is_symlink():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    tmp.rename(dest)


def _source_release_tag(source: Path) -> str | None:
    marker = source / "RELEASE"
    if marker.is_file():
        value = marker.read_text(encoding="utf-8").strip()
        if value:
            return value
    manifest = source / "manifest.json"
    try:
        version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
    except (FileNotFoundError, ValueError, OSError, AttributeError):
        return None
    if not version:
        return None
    value = str(version).strip()
    return value if value.startswith("v") else f"v{value}"


def _release_provenance_commit(source: Path) -> str | None:
    """Return the commit substituted by ``git archive`` for this runtime."""

    try:
        payload = json.loads(
            (source / RELEASE_PROVENANCE_FILE).read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return None
    commit = str(payload.get("commit") or "").strip().lower() if isinstance(payload, dict) else ""
    return commit if _COMMIT_SHA_RE.fullmatch(commit) else None


def _release_requires_provenance(source: Path) -> bool:
    release = _source_release_tag(source)
    comparison = _compare_semver(release, RELEASE_PROVENANCE_REQUIRED_SINCE)
    return comparison is not None and comparison >= 0


def _runtime_version_dir_name(tag: str) -> str:
    version = tag.lstrip("vV")
    alphanumeric = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    allowed = f"{alphanumeric}._+-"
    if (
        not version
        or version in {".", ".."}
        or version[0] not in alphanumeric
        or any(ch not in allowed for ch in version)
        or Path(version).name != version
    ):
        raise ValueError(f"unsafe release tag: {tag}")
    return version


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_sha256(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text.startswith("sha256:"):
        text = text.removeprefix("sha256:")
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError("release archive digest must be a SHA-256 value")
    return text


def _verified_runtime_archive_asset(release: dict[str, Any]) -> dict[str, Any]:
    """Select the tag-specific GitHub release asset and require its API digest.

    GitHub-generated ``tarball_url`` archives are mutable delivery responses and
    carry no publisher-visible digest in the releases API. Runtime updates must
    therefore use the explicitly uploaded ``hephaestus-runtime-vX.Y.Z.tar.gz``
    asset whose exact size and SHA-256 are part of the release metadata. Missing
    metadata fails closed before any network request.
    """

    tag = str(release.get("tag_name") or "").strip()
    if not tag:
        raise ValueError("release tag_name is required")
    expected_name = f"hephaestus-runtime-{tag}.tar.gz"
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise ValueError(f"release is missing verified runtime asset: {expected_name}")
    for asset in assets:
        if not isinstance(asset, dict) or str(asset.get("name") or "") != expected_name:
            continue
        url = str(asset.get("browser_download_url") or "").strip()
        if not url.startswith("https://github.com/"):
            raise ValueError("release runtime asset must use a GitHub HTTPS download URL")
        digest = asset.get("digest")
        if not digest:
            raise ValueError(f"release runtime asset is missing SHA-256 metadata: {expected_name}")
        size = asset.get("size")
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise ValueError(f"release runtime asset has invalid size metadata: {expected_name}")
        if size > MAX_RUNTIME_ARCHIVE_BYTES:
            raise ValueError(
                f"release runtime asset exceeds {MAX_RUNTIME_ARCHIVE_BYTES} bytes: {expected_name}"
            )
        return {
            "name": expected_name,
            "url": url,
            "sha256": _normalize_sha256(digest),
            "size": size,
        }
    raise ValueError(f"release is missing verified runtime asset: {expected_name}")


def _model_path(runtime_root: Path, *, release_source: bool) -> Path | None:
    base = runtime_root / ("assets" if release_source else "models") / "model2vec"
    for name in MODEL2VEC_ASSET_NAMES:
        candidate = base / name
        if candidate.is_dir():
            return candidate
    return None


def _validate_host_adapter_bundle(bundle_root: Path, release_tag: str) -> None:
    expected = release_tag.lstrip("vV")
    manifests = (
        bundle_root
        / "codex"
        / "plugins"
        / "agentlas-core-engine-meta-agent"
        / ".codex-plugin"
        / "plugin.json",
        bundle_root
        / "claude"
        / "plugins"
        / "agentlas-core-engine-meta-agent"
        / ".claude-plugin"
        / "plugin.json",
        bundle_root / "gemini" / "extension" / "gemini-extension.json",
    )
    missing: list[str] = []
    mismatched: list[str] = []
    for manifest in manifests:
        if not manifest.is_file():
            missing.append(str(manifest.relative_to(bundle_root)))
            continue
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(f"host adapter manifest is invalid: {manifest}") from exc
        actual = str(payload.get("version") or "").strip().lstrip("vV")
        if actual != expected:
            mismatched.append(f"{manifest.relative_to(bundle_root)}={actual or 'missing'}")
    if missing or mismatched:
        details = ", ".join([*(f"missing:{item}" for item in missing), *(f"version:{item}" for item in mismatched)])
        raise ValueError(f"host adapter bundle does not match {release_tag}: {details}")


def _validate_runtime_layout(runtime_root: Path, *, release_source: bool = False) -> Path:
    missing: list[str] = []
    for name in RUNTIME_DIRS:
        if not (runtime_root / name).is_dir():
            missing.append(f"{name}/")
    for relative in (
        Path("bin") / "hephaestus",
        Path("agentlas_cloud") / "__init__.py",
        Path("agentlas_cloud") / "__main__.py",
        Path("agentlas_cloud") / "cli.py",
        Path("agentlas_cloud") / "update.py",
        Path("agentlas_cloud") / "desktop_repair.py",
        Path("agentlas_cloud") / "desktop-update-bridge-v1.json",
        Path("agentlas_cloud") / "desktop_updater_cleanup.py",
        Path("agentlas_cloud") / "desktop-updater-cleanup-bridge-v1.json",
        Path("career_graph") / "__init__.py",
        Path("career_graph") / "runtime.py",
        Path("ontology") / "__init__.py",
        Path("ontology") / "model_assets.py",
        Path("templates") / "agentlas.json.tpl",
        Path("contracts") / "builder-interview-research-gate.md",
        Path("desktop-update-bridge-v1.json"),
        Path("scripts") / "install-memory-hooks.py",
    ):
        if not (runtime_root / relative).is_file():
            missing.append(str(relative))
    if release_source:
        for relative in (
            Path("antigravity") / "hooks" / "agentlas-memory.json",
            Path("grok") / "hooks" / "agentlas-memory.json",
            Path("grok") / "agentlas-memory-rule.md",
            Path("opencode") / "plugins" / "agentlas-memory.js",
        ):
            if not (runtime_root / relative).is_file():
                missing.append(str(relative))
    else:
        adapter_bundle = runtime_root / HOST_ADAPTER_BUNDLE_DIR
        if adapter_bundle.is_dir():
            release = current_release(runtime_root)
            if release:
                _validate_host_adapter_bundle(adapter_bundle, release)
    # Old signed releases predate the package-contract/schemas surface. Keep
    # them installable for rollback, but any runtime that ships the command
    # module must carry the complete root contract and Workforce schemas.
    if (runtime_root / "agentlas_cloud" / "package_contract.py").is_file():
        for relative in (
            Path("package-contract.json"),
            Path("contracts") / "builder-interview-research-gate.md",
            Path("schemas") / "package-contract.schema.json",
            Path("schemas") / "workforce-work-order.schema.json",
            Path("schemas") / "workforce-selection.schema.json",
        ):
            if not (runtime_root / relative).is_file():
                missing.append(str(relative))
    if _release_requires_provenance(runtime_root):
        if _release_provenance_commit(runtime_root) is None:
            raise ValueError(
                "release runtime provenance is missing or invalid: "
                f"{RELEASE_PROVENANCE_FILE} must contain the exact 40-hex release commit"
            )
    model_path = _model_path(runtime_root, release_source=release_source)
    if model_path is None:
        layout = "assets" if release_source else "models"
        missing.append(f"{layout}/model2vec/<verified-asset>/")
    if missing:
        raise ValueError(f"release runtime layout is incomplete: {', '.join(missing)}")

    from ontology.model_assets import ModelAssetError, verify_model_asset

    try:
        verify_model_asset(model_path)
    except (ModelAssetError, OSError, ValueError) as exc:
        layout = "release" if release_source else "installed runtime"
        raise ValueError(f"{layout} Model2Vec asset failed verification: {model_path}") from exc
    return model_path


def _healthcheck_runtime(runtime_root: Path) -> None:
    """Import the runnable surfaces from exactly the candidate runtime."""

    model_path = _validate_runtime_layout(runtime_root)
    try:
        resolved_root = runtime_root.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"runtime healthcheck could not resolve {runtime_root}") from exc

    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env["PYTHONPATH"] = str(resolved_root)
    env["PYTHONNOUSERSITE"] = "1"
    env["HEPHAESTUS_HEALTHCHECK_ROOT"] = str(resolved_root)
    env["HEPHAESTUS_HEALTHCHECK_MODEL"] = str(model_path.resolve(strict=True))
    check = (
        "import os\n"
        "from pathlib import Path\n"
        "import agentlas_cloud\n"
        "import agentlas_cloud.cli\n"
        "import agentlas_cloud.update\n"
        "import career_graph\n"
        "import ontology\n"
        "from ontology.model_assets import verify_model_asset\n"
        "root = Path(os.environ['HEPHAESTUS_HEALTHCHECK_ROOT']).resolve()\n"
        "modules = (agentlas_cloud, agentlas_cloud.cli, agentlas_cloud.update, career_graph, ontology)\n"
        "bad = [m.__name__ for m in modules if root not in Path(m.__file__).resolve().parents]\n"
        "verify_model_asset(Path(os.environ['HEPHAESTUS_HEALTHCHECK_MODEL']))\n"
        "raise SystemExit(8 if bad else 0)\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", check],
            cwd=str(resolved_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=HEALTHCHECK_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"runtime healthcheck timed out after {HEALTHCHECK_TIMEOUT_SECONDS}s") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-500:]
        suffix = f": {detail}" if detail else ""
        raise RuntimeError(f"runtime healthcheck failed with exit code {completed.returncode}{suffix}")


def _download(url: str, path: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "hephaestus-runtime-updater"})
    with urllib.request.urlopen(request, timeout=30) as response, path.open("wb") as out:
        shutil.copyfileobj(response, out)


def _safe_extract(tf: tarfile.TarFile, destination: Path) -> None:
    """Extract regular files/directories without trusting tar link semantics."""

    dest = destination.resolve()
    planned: list[tuple[tarfile.TarInfo, Path]] = []
    seen: set[Path] = set()
    for member in tf.getmembers():
        if member.issym() or member.islnk():
            raise ValueError(f"archive links are not allowed: {member.name}")
        if not member.isdir() and not member.isfile():
            raise ValueError(f"unsupported archive member type: {member.name}")
        if not member.name or "\x00" in member.name or "\\" in member.name:
            raise ValueError(f"unsafe path in release archive: {member.name}")
        archive_path = PurePosixPath(member.name)
        if archive_path.is_absolute() or any(part == ".." for part in archive_path.parts):
            raise ValueError(f"unsafe path in release archive: {member.name}")
        parts = [part for part in archive_path.parts if part not in {"", "."}]
        if not parts and not member.isdir():
            raise ValueError(f"unsafe path in release archive: {member.name}")
        target = dest.joinpath(*parts).resolve()
        try:
            inside_destination = Path(os.path.commonpath((str(dest), str(target)))) == dest
        except ValueError:
            inside_destination = False
        if not inside_destination:
            raise ValueError(f"unsafe path in release archive: {member.name}")
        if target in seen:
            raise ValueError(f"duplicate path in release archive: {member.name}")
        seen.add(target)
        planned.append((member, target))

    for member, target in planned:
        if member.isdir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        source = tf.extractfile(member)
        if source is None:
            raise ValueError(f"could not read archive member: {member.name}")
        try:
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
        except FileExistsError as exc:
            raise ValueError(f"archive member would overwrite an existing path: {member.name}") from exc
        target.chmod(0o755 if member.mode & 0o111 else 0o644)


def _path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _remove_path(path: Path) -> None:
    if not _path_present(path):
        return
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)


def _unique_sibling(path: Path, label: str) -> Path:
    return path.with_name(f".{path.name}.{label}.{os.getpid()}.{time.time_ns()}")


def _replace_runtime_target(staged: Path, target: Path) -> Path | None:
    backup: Path | None = None
    if _path_present(target):
        backup = _unique_sibling(target, "backup")
        target.rename(backup)
    try:
        staged.rename(target)
    except Exception:
        if backup is not None and _path_present(backup) and not _path_present(target):
            backup.rename(target)
        raise
    return backup


def _restore_runtime_target(target: Path, backup: Path | None) -> None:
    if backup is not None and not _path_present(backup):
        raise RuntimeError(f"runtime rollback backup is missing: {backup}")
    _remove_path(target)
    if backup is not None:
        backup.rename(target)


def _activate_runtime(staged: Path, target: Path) -> None:
    target_backup = _replace_runtime_target(staged, target)
    current_state: dict[str, str] | None = None
    try:
        current_state = _point_current_at(target)
        _healthcheck_runtime(target.parent / "current")
    except Exception as exc:
        rollback_errors: list[str] = []
        if current_state is not None:
            try:
                _restore_current(target.parent, current_state)
            except Exception as rollback_exc:
                rollback_errors.append(f"current: {rollback_exc}")
        try:
            _restore_runtime_target(target, target_backup)
        except Exception as rollback_exc:
            rollback_errors.append(f"target: {rollback_exc}")
        if rollback_errors:
            raise RuntimeError(f"runtime activation failed and rollback was incomplete: {'; '.join(rollback_errors)}") from exc
        raise

    _discard_current_state(current_state)
    if target_backup is not None and _path_present(target_backup):
        try:
            _remove_path(target_backup)
        except OSError:
            pass
    _prune_runtime_homes(target.parent)


RUNTIME_HOMES_KEPT = 3


def _prune_runtime_homes(runtime_root: Path) -> None:
    """옛 런타임 홈 버전을 거둔다 (PRD §4.22).

    버전별 디렉터리에 설치하고 링크만 바꾸는데 정리 코드가 없어 무한히 커졌다
    (실측 2026-08-23: 124개 9.1GB). 살아 있는 호스트 설정은 전부 `current` 를 보므로
    옛 버전에는 사용자 상태가 없다. 현재 것과 되돌리기용 몇 개만 남긴다.
    설치기(scripts/install-all-runtimes.sh prune_runtime_homes)와 **양쪽 모두** 있어야 한다 —
    한쪽에만 두면 다른 경로로 갱신한 머신은 계속 쌓인다.
    """
    try:
        current = runtime_root / "current"
        active = os.path.basename(os.readlink(current)) if current.is_symlink() else ""
        candidates = sorted(
            entry for entry in runtime_root.iterdir()
            if entry.is_dir()
            and not entry.name.startswith(".")
            and entry.name != "current"
            and entry.name != active
        )
    except OSError:
        return
    keep = max(0, RUNTIME_HOMES_KEPT - 1)  # current 를 포함해 RUNTIME_HOMES_KEPT 개
    for stale in candidates[:max(0, len(candidates) - keep)]:
        try:
            _remove_path(stale)
        except OSError:
            # 지우지 못한 것은 다음 갱신에서 다시 시도한다 — 실패가 업데이트를 막지 않는다.
            continue


def _point_current_at(target: Path) -> dict[str, str]:
    current = target.parent / "current"
    replacement = _unique_sibling(current, "next")
    try:
        replacement.symlink_to(target, target_is_directory=True)
    except OSError:
        _remove_path(replacement)
        shutil.copytree(target, replacement, ignore=PYTHON_CACHE_IGNORE)

    try:
        if current.is_symlink():
            previous_target = os.readlink(current)
            try:
                os.replace(replacement, current)
                return {"kind": "symlink", "target": previous_target}
            except OSError:
                backup = _unique_sibling(current, "backup")
                current.rename(backup)
                try:
                    replacement.rename(current)
                except Exception:
                    backup.rename(current)
                    raise
                return {"kind": "backup", "path": str(backup)}

        if _path_present(current):
            backup = _unique_sibling(current, "backup")
            current.rename(backup)
            try:
                replacement.rename(current)
            except Exception:
                backup.rename(current)
                raise
            return {"kind": "backup", "path": str(backup)}

        replacement.rename(current)
        return {"kind": "missing"}
    finally:
        if _path_present(replacement):
            _remove_path(replacement)


def _restore_current(runtime_base: Path, state: dict[str, str]) -> None:
    current = runtime_base / "current"
    kind = state.get("kind")
    if kind == "missing":
        _remove_path(current)
        return
    if kind == "backup":
        backup = Path(state["path"])
        _remove_path(current)
        backup.rename(current)
        return
    if kind == "symlink":
        replacement = _unique_sibling(current, "rollback")
        try:
            replacement.symlink_to(state["target"], target_is_directory=True)
            try:
                os.replace(replacement, current)
            except OSError:
                _remove_path(current)
                replacement.rename(current)
        finally:
            if _path_present(replacement):
                _remove_path(replacement)
        return
    raise ValueError(f"unknown current state: {kind}")


def _discard_current_state(state: dict[str, str]) -> None:
    if state.get("kind") != "backup":
        return
    backup = Path(state["path"])
    if _path_present(backup):
        try:
            _remove_path(backup)
        except OSError:
            pass


def _read_lock_metadata(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    try:
        payload = json.loads(raw)
    except ValueError:
        try:
            return {"pid": int(raw)}
        except (TypeError, ValueError):
            return {}
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, int):
        return {"pid": payload}
    return {}


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _lock_is_stale(path: Path, stale_seconds: int = LOCK_STALE_SECONDS) -> bool:
    if path.is_symlink():
        return True
    try:
        stat_result = os.lstat(path)
    except FileNotFoundError:
        return True
    metadata = _read_lock_metadata(path)
    created = metadata.get("created_epoch")
    try:
        created_epoch = float(created)
    except (TypeError, ValueError):
        created_epoch = float(stat_result.st_mtime)
    if max(0.0, time.time() - created_epoch) >= stale_seconds:
        return True
    try:
        pid = int(metadata.get("pid"))
    except (TypeError, ValueError):
        return False
    return not _pid_is_running(pid)


def _stat_fingerprint(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_mtime_ns, value.st_size)


def _remove_stale_lock(path: Path) -> bool:
    """Remove a stale lock if it did not change while being inspected."""

    try:
        before = os.lstat(path)
    except FileNotFoundError:
        return True
    if not _lock_is_stale(path):
        return False
    try:
        after = os.lstat(path)
    except FileNotFoundError:
        return True
    if _stat_fingerprint(before) != _stat_fingerprint(after):
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def _acquire_lock(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(16)
    for _ in range(3):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            if _remove_stale_lock(path):
                continue
            raise RuntimeError(f"update already running: {path}") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump({"pid": os.getpid(), "created_epoch": int(time.time()), "token": token}, fh, sort_keys=True)
            fh.write("\n")
        return token
    raise RuntimeError(f"could not acquire update lock: {path}")


def _release_lock(path: Path, token: str) -> None:
    if path.is_symlink():
        return
    try:
        before = os.lstat(path)
    except FileNotFoundError:
        return
    if _read_lock_metadata(path).get("token") != token:
        return
    try:
        after = os.lstat(path)
    except FileNotFoundError:
        return
    if _stat_fingerprint(before) != _stat_fingerprint(after):
        return
    try:
        path.unlink()
    except OSError:
        return


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as fh:
            data = json.load(fh)
    except (FileNotFoundError, ValueError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{time.time_ns()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) == 2 and args[0] == "--auto-update-worker":
        try:
            _run_auto_update_guarded(Path(args[1]))
        except Exception:
            # A read-only home must not break the caller either.
            return 0
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
