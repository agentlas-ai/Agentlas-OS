"""Runtime update checks for the Hephaestus CLI.

The explicit ``hephaestus hep-update`` command can install the latest runtime into
``~/.agentlas/runtime/<version>`` and atomically point ``current`` at it. Normal
command paths start a detached, fail-silent auto-update worker at most once per
metadata-check window so the user's command does not wait on network or install work.
"""

from __future__ import annotations

import ast
import base64
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
from typing import Any, Mapping
from .windows_console import no_console_window

_O_BINARY = getattr(os, "O_BINARY", 0)  # Windows: os.open() fds are text mode without it

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
# runtime-support/ contains mode-map skills without exposing host commands.
# Older immutable release archives predate this directory; current releases
# require its exact mapped paths in the official asset builder.
RUNTIME_OPTIONAL_DIRS = ("schemas", "system-agents", "goose", "openclaw", "skills", "runtime-support")
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
    ".zcode",
    "antigravity",
    "claude",
    "codex",
    "copilot-cli",
    "cursor",
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
    "agentlas-hub",
    "agentlas-local",
    "agentlas-login",
    "agentlas-network",
    "agentlas-one",
    "agentlas-goal",
    "agentlas-orch",
    "agentlas-search",
    "agentlas-storm",
    "agentlas-update",
    "agentlas-upload",
    "hep-browser",
    "hep-build",
    "hep-call",
    "hep-cloud",
    "hep-goal",
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
    retired = {"agentlas-connect", "agentlas-graph", "hep-connect", "hep-graph"}
    return tuple(sorted(names - retired))
# Every AgentSkills surface installed by the one-touch installer. Keep graph and
# upload in the same updater-owned set as network/cloud/storm so an update can
# never leave a first-install copy frozen indefinitely.
HEP_SKILLS = (
    "agentlas",
    "agentlas-one",
    "hephaestus-network",
    "hephaestus-cloud",
    "hephaestus-storm",
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
            return tuple(name for name in dict.fromkeys(skills) if name != "hephaestus-graph")
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
        "desktop_npm_repair",
        "archive_digest",
        "digest_verified",
        "archive_asset",
        "adapter_sync",
        "memory_hook_sync",
        "global_router_sync",
        "activation",
    ):
        if key in {"desktop_repair", "desktop_updater_cleanup", "desktop_npm_repair"} and key in previous:
            # Historical receipts are evidence, not a request to repeat recovery.
            canonical[key] = previous[key]
        elif key in result:
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
                "runtime_root": str(resolved_root),
                "current_link": str(current_link),
            }
        )
        model_root = result.get("model_root") or resolved_root / RUNTIME_MODEL2VEC_PATH
        canonical["model_root"] = str(model_root)
        receipt = result if (result.get("status") == "updated" and result.get("appliedReceiptVersion") == "agentlas.runtime-applied.v1") else previous
        if (receipt.get("appliedReceiptVersion") == "agentlas.runtime-applied.v1"
                and receipt.get("last_applied_tag") == observed_release
                and isinstance(receipt.get("last_applied_epoch"), (int, float))):
            canonical["appliedReceiptVersion"] = receipt["appliedReceiptVersion"]
            canonical["last_applied_tag"] = observed_release
            canonical["last_applied_epoch"] = receipt["last_applied_epoch"]
        if result.get("status") == "updated" and result.get("updated_to") == observed_release:
            canonical["updated_to"] = observed_release
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
    # Only a successful standalone lookup produces a notice receipt.  The
    # receipt and its timestamp are replaced together with the atomic marker.
    channel_tag = result.get("channelTag")
    if (result.get("status") in {"current", "updated"}
            and isinstance(channel_tag, str)
            and _channel_engine_tag(channel_tag) is not None
            and result.get("latest") == _channel_engine_tag(channel_tag)):
        canonical["noticeSchema"] = "agentlas.standalone-notice.v1"
        canonical["noticeTag"] = channel_tag
    return canonical


def _persist_update_marker(previous: dict[str, Any], result: dict[str, Any], runtime_root: Path) -> None:
    _write_json(
        _runtime_base() / AUTO_UPDATE_MARKER,
        _canonical_update_marker(previous, result, runtime_root),
    )


def _standalone_json(url: str) -> tuple[Any, str]:
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "agentlas-os-standalone"})
    with urllib.request.urlopen(request, timeout=2) as response:
        if response.geturl() != url:
            raise ValueError("standalone_metadata_origin_mismatch")
        link = response.headers.get("Link", "")
        raw = response.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("standalone_metadata_too_large")
    return json.loads(raw.decode("utf-8")), link


def _channel_engine_tag(tag: str) -> str | None:
    if not re.fullmatch(r"(?:os-)?v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag):
        return None
    return tag[3:] if tag.startswith("os-") else tag


def _standalone_tag_metadata(tag: str, release: dict[str, Any]) -> dict[str, Any]:
    if _channel_engine_tag(tag) is None:
        raise ValueError("standalone_channel_tag_invalid")
    if release.get("tag_name") != tag or release.get("draft") is not False or release.get("prerelease") is not False:
        raise ValueError("standalone_release_mismatch")
    lines = [line for line in str(release.get("body") or "").splitlines() if line.startswith("agentlas-os-channel:")]
    if lines != ["agentlas-os-channel: stable"]:
        raise ValueError("standalone_channel_marker_invalid")
    asset = _verified_runtime_archive_asset(release)
    if asset["url"] != "https://github.com/agentlas-ai/Agentlas-OS/releases/download/" + tag + "/" + asset["name"]:
        raise ValueError("standalone_asset_origin_mismatch")
    url = "https://api.github.com/repos/agentlas-ai/Agentlas-OS/git/ref/tags/" + tag
    ref, _ = _standalone_json(url)
    obj = ref.get("object") if isinstance(ref, dict) else None
    if not isinstance(ref, dict) or ref.get("ref") != "refs/tags/" + tag:
        raise ValueError("standalone_tag_ref_mismatch")
    if not isinstance(obj, dict) or obj.get("type") != "commit":
        raise ValueError("standalone_tag_not_lightweight_commit")
    commit = str(obj.get("sha") or "").lower()
    if not _COMMIT_SHA_RE.fullmatch(commit):
        raise ValueError("standalone_tag_commit_invalid")
    return {**release, "standalone_source_commit": commit}


def _standalone_next_page(link: str, page: int) -> bool:
    """Validate pagination; only its page number is used, never its URL."""
    if not link:
        return False
    relations: set[str] = set()
    for entry in link.split(","):
        match = re.fullmatch(r'\s*<([^<>]+)>\s*;\s*rel="(next|prev|first|last)"\s*', entry)
        if match is None or match.group(2) in relations:
            raise ValueError("standalone_channel_pagination_invalid")
        relation = match.group(2)
        relations.add(relation)
        target = urllib.parse.urlsplit(match.group(1))
        # GitHub emits the repository's numeric canonical URL in Link headers.
        # This immutable repository ID was verified for agentlas-ai/Agentlas-OS.
        if (target.scheme != "https" or target.netloc != "api.github.com"
                or target.path not in {"/repos/agentlas-ai/Agentlas-OS/releases", "/repositories/1258962324/releases"}
                or target.fragment):
            raise ValueError("standalone_channel_pagination_origin_mismatch")
        query = urllib.parse.parse_qs(target.query, keep_blank_values=True)
        values = query.get("page", [])
        if (set(query) != {"per_page", "page"} or query.get("per_page") != ["100"]
                or len(values) != 1 or not re.fullmatch(r"[1-9][0-9]*", values[0])):
            raise ValueError("standalone_channel_pagination_invalid")
        number = int(values[0])
        if relation == "next" and number != page + 1:
            raise ValueError("standalone_channel_pagination_cycle")
    return "next" in relations


def fetch_standalone_latest() -> dict[str, Any]:
    base_url = "https://api.github.com/repos/agentlas-ai/Agentlas-OS/releases?per_page=100"
    releases: list[dict[str, Any]] = []
    page_fingerprints: set[str] = set()
    for page in range(1, 21):
        url = base_url if page == 1 else f"{base_url}&page={page}"
        rows, link = _standalone_json(url)
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError("standalone_channel_invalid")
        fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True).encode("utf-8")).hexdigest()
        if fingerprint in page_fingerprints:
            raise ValueError("standalone_channel_pagination_cycle")
        page_fingerprints.add(fingerprint)
        releases.extend(rows)
        if not _standalone_next_page(link, page):
            break
    else:
        raise ValueError("standalone_channel_incomplete")
    candidates: dict[tuple[int, int, int], dict[str, Any]] = {}
    for item in releases:
        if not isinstance(item, dict) or item.get("draft") is not False or item.get("prerelease") is not False:
            continue
        tag = str(item.get("tag_name") or "")
        match = re.fullmatch(r"(os-)v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag)
        if not match:
            continue  # a legacy-channel tag (v1.2.x) is never chosen as the newest release
        lines = [line for line in str(item.get("body") or "").splitlines() if line.startswith("agentlas-os-channel:")]
        if not lines or lines == ["agentlas-os-channel: preview"]:
            continue  # preview or unclassified release; never automatically use it
        if lines != ["agentlas-os-channel: stable"]:
            raise ValueError("standalone_channel_marker_invalid")
        key = tuple(int(v) for v in match.groups()[1:])
        if key in candidates:
            raise ValueError("standalone_channel_duplicate")
        candidates[key] = item
    if not candidates:
        raise ValueError("standalone_channel_empty")
    chosen = candidates[max(candidates)]
    return _standalone_tag_metadata(chosen["tag_name"], chosen)


def _desktop_host_requested() -> bool:
    return str(os.environ.get("AGENTLAS_HOST_RUNTIME") or "").strip().lower() in {"desktop", "agentlas-desktop", "agentlas_desktop", "runtime:desktop"}


def _allowed_update_root(runtime_root: Path, base: Path) -> bool:
    try:
        resolved = runtime_root.resolve()
        if resolved.is_relative_to(base.resolve()):
            return True
        # A Desktop-bundled engine may seed the isolated generation. The host
        # remains responsible for authenticating the bundled engine itself.
        return (_desktop_host_requested()
                and resolved == Path(__file__).resolve().parent.parent
                and _is_comparable_release(current_release(resolved)))
    except (OSError, ValueError, TypeError):
        return False


def run_update(check_only: bool = False, root: Path | None = None) -> dict[str, Any]:
    if root is None:
        try:
            active = _active_runtime_for_cached_updater()
            if active is not None:
                return _run_update_in_active_runtime(active, check_only)
        except ValueError as exc:
            return {"status": "blocked", "error": str(exc), "writeAttempted": False}
    try:
        base = _runtime_base()
    except ValueError as exc:
        return {"status": "blocked", "error": str(exc), "writeAttempted": False}
    runtime_root = root or base / "current"
    if not _allowed_update_root(runtime_root, base):
        return {"status": "blocked", "error": "standalone_runtime_outside_base", "writeAttempted": False}
    # Host-adapter housekeeping left over from an older update is retried on every run, but a
    # step that keeps failing (a read-only host file, a surface that vanished) is reported and
    # must never stop the runtime from receiving a newer release: that would be a dead end the
    # owner cannot repair. The newer generation repeats the same work with its own checks.
    reconciliation_notes: dict[str, Any] = {}
    if not check_only:
        bridge = reconcile_legacy_bridge()
        if bridge.get("status") == "blocked":
            reconciliation_notes["bridge"] = bridge
        retry = _retry_legacy_host_reconciliation(base)
        if retry.get("status") == "blocked":
            reconciliation_notes["hostRetry"] = retry
    current = current_release(runtime_root)
    selected = base / "current"
    if _path_present(selected):
        try:
            if not selected.resolve().is_relative_to(base.resolve()):
                return {"status": "blocked", "error": "standalone_current_outside_base", "writeAttempted": False}
            selected_release = current_release(selected)
            if not _is_comparable_release(selected_release):
                return {"status": "blocked", "error": "standalone_current_unverified", "writeAttempted": False}
            if not _is_comparable_release(current) or _release_status(current, selected_release) == "update_available":
                current = selected_release
        except (OSError, ValueError):
            return {"status": "blocked", "error": "standalone_current_unverified", "writeAttempted": False}
    write_attempted = False
    try:
        release = fetch_standalone_latest()
        engine_tag = _channel_engine_tag(release["tag_name"])
        if engine_tag is None:
            raise ValueError("standalone_channel_tag_invalid")
        state = _release_status(current, engine_tag)
        result = {"status": state, "current": current, "latest": engine_tag, "channelTag": release["tag_name"], "writeAttempted": False}
        if reconciliation_notes:
            result["reconciliation"] = reconciliation_notes
        if check_only or state != "update_available":
            return result
        write_attempted = True
        installed = install_latest_runtime(release)
        adapter_result = installed.get("adapter_sync") or {}
        activation = installed.get("activation") or {}
        hook_result = installed.get("memory_hook_sync") or {}
        router_result = installed.get("global_router_sync") or {}
        host_result = installed.get("host_plugin_sync") or {}
        incomplete = (activation.get("status") == "blocked" or bool(adapter_result.get("failed"))
                      or hook_result.get("status") in {"fail", "failed", "blocked"}
                      or router_result.get("status") in {"fail", "failed", "blocked"}
                      or host_result.get("status") in {"partial", "fail", "failed", "blocked"})
        return {**result, **installed, "status": "blocked" if incomplete else "updated",
                **({"reason": "post_activation_incomplete"} if incomplete else {}), "writeAttempted": True}
    except (OSError, ValueError, RuntimeError, tarfile.TarError, urllib.error.URLError) as exc:
        unreachable = isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError)
        message = ("Could not reach api.github.com; check the network and retry. " if unreachable else "") + \
            "Standalone update unavailable; the existing runtime was preserved."
        raise UpdateUnavailableError({"status": "check_failed", "error": "standalone_update_unavailable", "current": current, "detail": str(exc)[:300], "writeAttempted": write_attempted}, message) from exc


def maybe_auto_update(root: Path | None = None, *, background: bool = True) -> None:
    """Start a fail-silent runtime auto-update check.

    This function intentionally returns ``None`` for every outcome. It never
    raises, never prints, and by default never performs network or install work
    in the caller process.
    """

    try:
        if _auto_update_disabled():
            return
        runtime_root = root or Path(__file__).resolve().parent.parent
        base = _runtime_base_for_root(runtime_root)
        if not _allowed_update_root(runtime_root, base):
            return
        current = current_release(runtime_root)
        if current is not None and not _is_comparable_release(current):
            return
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
            if not _desktop_host_requested() or runtime_root.resolve() != Path(__file__).resolve().parent.parent:
                return
            _prepare_update_base(base)
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
                    _record_auto_update_failure("spawn_failed", base=base)
            else:
                try:
                    if Path(__file__).resolve().parent.parent != runtime_root.resolve():
                        _run_external_auto_update_worker(runtime_root, base)
                    else:
                        _run_auto_update_guarded(runtime_root)
                except Exception:
                    _record_auto_update_failure("worker_failed", base=base)
        finally:
            _release_lock(check_lock, check_token)
    except Exception:
        return


def maybe_print_update_notice(root: Path | None = None) -> None:
    if _auto_update_disabled():
        return
    runtime_root = root or Path(__file__).resolve().parent.parent
    try:
        base = _runtime_base_for_root(runtime_root)
        # Keep the pre-existing notice scope: a bundled Desktop engine is not
        # itself the active standalone installation. Never follow current out
        # of the standalone base or compare an inactive generation when an
        # active one exists.
        if not runtime_root.resolve().is_relative_to(base.resolve()):
            return
        active = base / "current"
        if _path_present(active):
            if not active.resolve().is_relative_to(base.resolve()):
                return
            runtime_root = active
        current = current_release(runtime_root)
        marker = _read_json(base / AUTO_UPDATE_MARKER)
        tag = marker.get("noticeTag")
        if (marker.get("markerSchemaVersion") != "agentlas.auto-update.v2"
                or marker.get("noticeSchema") != "agentlas.standalone-notice.v1"
                or marker.get("status") not in {"current", "updated"}
                or not isinstance(tag, str)
                or _channel_engine_tag(tag) is None
                or marker.get("latest") != _channel_engine_tag(tag)
                or not _marker_recent(marker.get("last_checked_epoch"), METADATA_TTL_SECONDS)):
            return
        engine_tag = _channel_engine_tag(tag)
    except Exception:
        return
    if current and _release_status(current, engine_tag) == "update_available":
        print(f"Standalone update available: {engine_tag} (current {current}). Run: hephaestus hep-update", file=sys.stderr)


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
    same_generation = _canonical_path(current_target) == _canonical_path(target)
    if not same_generation and current_path.is_dir() and not _is_link(current_path):
        # Symlink/junction creation can fail even on POSIX. In that case
        # _point_current_at copies the generation; prove contents match before
        # acknowledging activation rather than treating every copy as broken.
        same_generation = _managed_content_matches(current_path, target)
    runtime_current = (
        current_release(current_path) == release_tag
        and current_release(target) == release_tag
        and same_generation
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
    channel_tag = str(release.get("tag_name") or "").strip()
    tag = _channel_engine_tag(channel_tag)
    if tag is None:
        raise ValueError("standalone_channel_tag_invalid")
    source_commit = str(release.get("standalone_source_commit") or "").strip().lower()
    if not _COMMIT_SHA_RE.fullmatch(source_commit):
        raise ValueError("standalone_tag_commit_missing")
    archive_asset = _verified_runtime_archive_asset(release)
    expected_url = "https://github.com/agentlas-ai/Agentlas-OS/releases/download/" + channel_tag + "/" + archive_asset["name"]
    if archive_asset["url"] != expected_url:
        raise ValueError("standalone_asset_origin_mismatch")
    tarball_url = archive_asset["url"]
    expected_sha256 = archive_asset["sha256"]
    expected_size = archive_asset["size"]

    base = _runtime_base()
    legacy_install = _legacy_runtime_base() == base
    previous_release = current_release(base / "current") if legacy_install else None
    previous_adapter_bundle = base / "current" / HOST_ADAPTER_BUNDLE_DIR if legacy_install else None
    target = base / _runtime_version_dir_name(tag)
    if target.exists() or target.is_symlink():
        raise ValueError("standalone_target_already_exists")
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
    _prepare_update_base(base)
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
            if legacy_install and previous_adapter_bundle is not None:
                if (not previous_release or _is_link(previous_adapter_bundle)
                        or not previous_adapter_bundle.is_dir()):
                    raise ValueError("legacy_adapter_baseline_unverified")
                # Snapshot the active generation, including copy-based current,
                # then verify official bytes before using it as an ownership baseline.
                snapshot = tmp_path / "previous-adapter-bundle"
                shutil.copytree(previous_adapter_bundle, snapshot, ignore=PYTHON_CACHE_IGNORE, symlinks=True)
                if not _official_legacy_baseline_matches(
                        previous_release, snapshot, base / "current" / ".runtime-adapter-verified-v1.json"):
                    raise ValueError("legacy_adapter_baseline_unverified")
                previous_adapter_bundle = snapshot
            if source.name != "Agentlas-OS-" + tag[1:]:
                raise ValueError("standalone_archive_root_mismatch")
            if _source_release_tag(source) != tag:
                raise ValueError("standalone_engine_version_mismatch")
            try:
                manifest_version = str(json.loads((source / "manifest.json").read_text(encoding="utf-8"))["version"])
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise ValueError("standalone_manifest_invalid") from exc
            if manifest_version != tag[1:]:
                raise ValueError("standalone_manifest_version_mismatch")
            provenance_commit = _release_provenance_commit(source)
            if not provenance_commit:
                raise ValueError("standalone_provenance_missing")
            if provenance_commit != source_commit:
                raise ValueError("standalone_provenance_tag_mismatch")
            if not channel_tag.startswith("os-") and not (source / _LEGACY_ADAPTER_PAYLOAD).is_dir():
                raise ValueError("legacy_adapter_payload_missing")
            _restore_relocated_release_payload(source)
            source_baseline_manifest = _validate_source_adapter_manifest(source, tag)
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
                # Preserve an older archive's optional host bridge when supplied.
                if relative_name == "desktop-update-bridge-v1.json" and not src.is_file():
                    continue
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
            if source_baseline_manifest is not None:
                if _legacy_baseline_digest(adapter_bundle) != source_baseline_manifest["digest"]:
                    raise ValueError("legacy_baseline_bundle_mismatch")
                _write_json(staged_target / ".runtime-adapter-verified-v1.json", {
                    "schemaVersion": "agentlas.runtime-adapter-verification.v1",
                    "release": tag, "commit": source_commit, "assetSha256": expected_sha256,
                    "digest": source_baseline_manifest["digest"],
                })
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
            if legacy_install:
                _write_json(base / ".legacy-host-reconcile.json", {
                    "schemaVersion": "agentlas.legacy-host-reconcile.v1",
                    "target": tag, "previous": previous_release,
                })
            _activate_runtime(staged_target, target)
            applied_epoch = int(time.time())
            staged_target = None
            if legacy_install:
                adapter_sync = sync_installed_runtime_adapters(source, previous_source=previous_adapter_bundle)
                from .host_update import reconcile_host_plugins
                host_plugin_sync = reconcile_host_plugins(target / HOST_ADAPTER_BUNDLE_DIR, tag)
                plugin_cache_sync = {"status": "not_run", "reason": "preserve_existing_caches"}
                memory_hook_sync = sync_installed_memory_hooks(source)
                global_router_sync = _sync_installed_global_router(target)
            else:
                # Standalone must not alter existing host registrations or One.
                adapter_sync = {"status": "not_run", "reason": "isolated_namespace"}
                host_plugin_sync = {"status": "not_run", "hosts": []}
                plugin_cache_sync = {"status": "not_run", "preserved": []}
                memory_hook_sync = {"status": "not_run", "reason": "isolated_namespace"}
                global_router_sync = {"status": "not_run", "reason": "isolated_namespace"}
    finally:
        if staged_target is not None and _path_present(staged_target):
            _remove_path(staged_target)
        _release_lock(lock, lock_token)

    # 활성화가 끝나고 잠금을 놓은 뒤에만 옛 세대를 거둔다. 정리는 어떤 이유로든
    # 업데이트 결과를 바꾸지 못한다(항목별 OSError 는 안에서 삼키고, 나머지도 여기서 막는다).
    try:
        if not (legacy_install and _path_present(base / ".legacy-host-reconcile.json")):
            _prune_runtime_homes(base)
    except Exception:
        pass

    model_path = installed_model_path or target / RUNTIME_MODEL2VEC_PATH
    activation = _post_activation_state(
        target,
        tag,
        model_path,
        host_plugin_sync,
        plugin_cache_sync,
    )
    if legacy_install and not (
        activation.get("status") == "blocked" or adapter_sync.get("failed")
        or host_plugin_sync.get("status") in {"partial", "fail", "failed", "blocked"}
        or memory_hook_sync.get("status") in {"fail", "failed", "blocked"}
        or global_router_sync.get("status") in {"fail", "failed", "blocked"}
    ):
        marker = base / ".legacy-host-reconcile.json"
        if not marker.is_symlink() and _read_json(marker).get("target") == tag:
            marker.unlink(missing_ok=True)
            try:
                _prune_runtime_homes(base)
            except Exception:
                pass
    return {
        "runtime_root": str(target),
        "current_link": str(base / "current"),
        "updated_to": tag,
        "last_applied_tag": tag,
        "last_applied_epoch": applied_epoch,
        "appliedReceiptVersion": "agentlas.runtime-applied.v1",
        "archive_digest": f"sha256:{archive_sha256}",
        "digest_verified": True,
        "archive_asset": archive_asset["name"],
        "model_root": str(model_path),
        "model_verified": bool(activation["modelCurrent"]),
        "adapter_sync": adapter_sync,
        "host_plugin_sync": host_plugin_sync,
        "plugin_cache_sync": plugin_cache_sync,
        "memory_hook_sync": memory_hook_sync,
        "desktop_npm_repair": memory_hook_sync.get("desktop_npm_repair") or {
            "status": "not_applicable", "reason": "not_reported",
        },
        "global_router_sync": global_router_sync,
        "activation": activation,
        "reloadRequired": bool(activation["reloadRequired"]),
        "pendingHosts": activation["pendingHosts"],
    }


_LEGACY_ADAPTER_PAYLOAD = Path("agentlas_cloud") / "legacy-adapters"
_LEGACY_CONTRACT_PAYLOAD = Path("agentlas_cloud") / "legacy-contracts"
_LEGACY_RUNTIME_PAYLOAD = Path("agentlas_cloud") / "legacy-runtime"
_LEGACY_RUNTIME_ROOTS = ("system-agents", "goose", "openclaw", "runtime-support")
_LEGACY_ADAPTER_PATHS = (
    Path("codex/prompts"), Path(".claude/commands"), Path("cursor/plugin/commands"),
    Path("opencode/commands"), Path("antigravity/workflows"), Path("skills"),
    Path("openclaw/skills"),
)

# Adapter tree fingerprints checked against the exact verified release asset.
# Unknown historical assets are never inferred from a source tag alone.
_LEGACY_BASELINE_SHA256 = {
    "v1.2.0": "068f314e234d1e6fb07bfd5e39f1d8bf5c16d465d22ec04a12baef330dc8d776",
    "v1.2.1": "12bf33f8dc565a7208a2ba1efe96abf2b0e400ddd67bb394344e2e6527b611a4",
    "v1.2.2": "12bf33f8dc565a7208a2ba1efe96abf2b0e400ddd67bb394344e2e6527b611a4",
    "v1.2.3": "d7893771432aae593c90d24620cdccbe6009f1c978c79b8b19b7a9c8ddcb3438",
    "v1.2.4": "de67782772faca1bfab2348544e115de013ba6066c6a6d1d0cc3037f5c8f895a",
    "v1.2.5": "38dd92be57cad3656c73a44f940603b668c6041f6751e74f0180d466e3f908be",
    "v1.2.6": "c26c614a731ff25981e87a2a6ebc556ca545cb2e9bb3d7447673865ab9b30cd6",
    "v1.2.7": "c26c614a731ff25981e87a2a6ebc556ca545cb2e9bb3d7447673865ab9b30cd6",
    "v1.2.9": "c8234567294a611d0017f532d873e5e07b1f31790f2322b173e3b27ceb345771",
    "v1.2.10": "24d92533ad423b7fd19285525d3fc5319637cb9c9a39fc81374882beae677459",
    "v1.2.11": "24d92533ad423b7fd19285525d3fc5319637cb9c9a39fc81374882beae677459",
    "v1.2.12": "5ad3982273909990d7911af959ef4712a6b65db17f1a71a3f72e1bf5a5939dfe",
    "v1.2.14": "971d26ea547e4b47807f79ab07dce542ca06f0f57911fd343fb915fe76655db8",
    "v1.2.16": "4c0249a2a80e618e63926673b08dc8734dccb3755974acc939d1820c31879382",
    "v1.2.17": "46707077b81024cdf65b19f0ad6da92c3178119667988df93908a94db56c3aae",
    "v1.2.18": "46707077b81024cdf65b19f0ad6da92c3178119667988df93908a94db56c3aae",
    "v1.2.19": "46707077b81024cdf65b19f0ad6da92c3178119667988df93908a94db56c3aae",
    "v1.2.20": "46707077b81024cdf65b19f0ad6da92c3178119667988df93908a94db56c3aae",
    "v1.2.21": "46707077b81024cdf65b19f0ad6da92c3178119667988df93908a94db56c3aae",
    "v1.2.22": "46707077b81024cdf65b19f0ad6da92c3178119667988df93908a94db56c3aae",
    "v1.2.23": "09ecf5ca9bfa2428c766c7bba9d93d08c2d3d87d9ce8b8cea0b333d3ee9fb299",
    "v1.2.24": "ab11c9552f55deafa4c19556dd32518f59271703f0e544393ed34aec3497e91c",
    "v1.2.25": "ab11c9552f55deafa4c19556dd32518f59271703f0e544393ed34aec3497e91c",
    "v1.2.26": "ab11c9552f55deafa4c19556dd32518f59271703f0e544393ed34aec3497e91c",
    "v1.2.27": "ab11c9552f55deafa4c19556dd32518f59271703f0e544393ed34aec3497e91c",
    "v1.2.28": "96908b3c3b2608090f2c779d3e2f5efe9aeb5fdbf4d248502cdbc24cc192dbf5",
    "v1.2.29": "96908b3c3b2608090f2c779d3e2f5efe9aeb5fdbf4d248502cdbc24cc192dbf5",
    "v1.2.30": "96908b3c3b2608090f2c779d3e2f5efe9aeb5fdbf4d248502cdbc24cc192dbf5",
    "v1.2.31": "7618434115dcbfdbd3731c628254c04fe811b67858c7532fcd07674fc2b81093",
    "v1.2.32": "7618434115dcbfdbd3731c628254c04fe811b67858c7532fcd07674fc2b81093",
    "v1.2.33": "74779d82746f95a64c9f54898bdead28adfe273e2677b2fab3645761383aac8e",
    "v1.2.34": "7d8945f6e4f0d95b07cd3315b384dd129a6f739a6e744ce35816015615729d47",
    "v1.2.35": "26bbf9ba551d3d46a3bda219b67df33e308ccfc69788a8bc3d6f02ad4a41813a",
    "v1.2.36": "26bbf9ba551d3d46a3bda219b67df33e308ccfc69788a8bc3d6f02ad4a41813a",
    "v1.2.37": "26bbf9ba551d3d46a3bda219b67df33e308ccfc69788a8bc3d6f02ad4a41813a",
    "v1.2.38": "26bbf9ba551d3d46a3bda219b67df33e308ccfc69788a8bc3d6f02ad4a41813a",
    "v1.2.39": "26bbf9ba551d3d46a3bda219b67df33e308ccfc69788a8bc3d6f02ad4a41813a",
    "v1.2.40": "26bbf9ba551d3d46a3bda219b67df33e308ccfc69788a8bc3d6f02ad4a41813a",
    "v1.2.42": "26bbf9ba551d3d46a3bda219b67df33e308ccfc69788a8bc3d6f02ad4a41813a",
    "v1.2.43": "26bbf9ba551d3d46a3bda219b67df33e308ccfc69788a8bc3d6f02ad4a41813a",
    "v1.2.44": "26bbf9ba551d3d46a3bda219b67df33e308ccfc69788a8bc3d6f02ad4a41813a",
    "v1.2.45": "4e7130ccabbfed0b217cb806597faa1cb3315b2eaead2d57d649f01d19607b09",
    "v1.2.46": "6bc6941a22ba4680095b73ed47764c0780ed4347679d0a04c05481d0dd93ae69",
    "v1.2.47": "6bc6941a22ba4680095b73ed47764c0780ed4347679d0a04c05481d0dd93ae69",
    "v1.2.48": "6bc6941a22ba4680095b73ed47764c0780ed4347679d0a04c05481d0dd93ae69",
    "v1.2.49": "6bc6941a22ba4680095b73ed47764c0780ed4347679d0a04c05481d0dd93ae69",
    "v1.2.50": "fae3e304d5bd05b216de29086f6b98684d2249e3bc8b715c84b578b707e671b5",
    "v1.2.51": "fae3e304d5bd05b216de29086f6b98684d2249e3bc8b715c84b578b707e671b5",
    "v1.2.54": "c9dca33c4678fae5e76d1c14fad095f32d6b657e21321a35fd3866108b7718ba",
    "v1.2.55": "c9dca33c4678fae5e76d1c14fad095f32d6b657e21321a35fd3866108b7718ba",
    "v1.2.56": "506d5c4e7bb99947e5e2b665833359ea0f8a5740d2f8110618620901f4338ba9",
    "v1.2.57": "df7bad0ff40d29cf0efe84b140687a5b3e103b1d056e0589fe5221c4e8860a6a",
    "v1.2.58": "9ea55d2c75031d15f5d2f8a979d822d35974741589ee5707a66101b9fe3bcdfd",
    "v1.2.59": "9ea55d2c75031d15f5d2f8a979d822d35974741589ee5707a66101b9fe3bcdfd",
    "v1.2.60": "9ea55d2c75031d15f5d2f8a979d822d35974741589ee5707a66101b9fe3bcdfd",
    "v1.2.61": "9ea55d2c75031d15f5d2f8a979d822d35974741589ee5707a66101b9fe3bcdfd",
    "v1.2.62": "9ea55d2c75031d15f5d2f8a979d822d35974741589ee5707a66101b9fe3bcdfd",
    "v1.2.63": "9ea55d2c75031d15f5d2f8a979d822d35974741589ee5707a66101b9fe3bcdfd",
    "v1.2.64": "dd4de82021f07a52bc0f8cd491c2594aa32b40f91ddc73493fd6cbc6688cf67b",
    "v1.2.65": "ca758dab5201928fe037802535ed9b8014b41a3dd688a7f83c2921e0a54bbfde",
    "v1.2.66": "ca758dab5201928fe037802535ed9b8014b41a3dd688a7f83c2921e0a54bbfde",
    "v1.2.67": "ca758dab5201928fe037802535ed9b8014b41a3dd688a7f83c2921e0a54bbfde",
    "v1.2.68": "ca758dab5201928fe037802535ed9b8014b41a3dd688a7f83c2921e0a54bbfde",
    "v1.2.69": "ca758dab5201928fe037802535ed9b8014b41a3dd688a7f83c2921e0a54bbfde",
    "v1.2.70": "33503e7aab139cecaed3c79537b1d0cecf58a1127afd7a6b9f081bfeb40863df",
    "v1.2.71": "33503e7aab139cecaed3c79537b1d0cecf58a1127afd7a6b9f081bfeb40863df",
    "v1.2.72": "33503e7aab139cecaed3c79537b1d0cecf58a1127afd7a6b9f081bfeb40863df",
    "v1.2.90": "01dbf7ccfd9360de450579fd1430d69e87ea7594a894b76bed3f4e089ccf0716",
    "v1.2.91": "01dbf7ccfd9360de450579fd1430d69e87ea7594a894b76bed3f4e089ccf0716",
}
_LEGACY_BASELINE_PATHS = (
    Path(".claude/commands"), Path("codex/prompts"), Path("cursor/plugin/commands"),
    Path("opencode/commands"), Path("antigravity/workflows"), Path("skills"),
    Path("openclaw/skills"),
)


def _legacy_baseline_digest(root: Path) -> str:
    """Hash all managed trees, including names and empty directories."""
    digest = hashlib.sha256()
    for relative in _LEGACY_BASELINE_PATHS:
        tree = root / relative
        if _has_symlink_in_path(tree, root) or not tree.is_dir():
            raise ValueError("legacy_baseline_tree_invalid")
        digest.update(f"D {relative.as_posix()}\n".encode())
        for entry in sorted(tree.rglob("*"), key=lambda p: p.relative_to(root).as_posix()):
            if "__pycache__" in entry.parts or entry.suffix in {".pyc", ".pyo"}:
                continue
            name = entry.relative_to(root).as_posix()
            if _is_link(entry):
                raise ValueError("legacy_baseline_symlink")
            if entry.is_dir():
                digest.update(f"D {name}\n".encode())
            elif entry.is_file():
                digest.update(f"F {name} {_sha256_file(entry)}\n".encode())
            else:
                raise ValueError("legacy_baseline_entry_invalid")
    return digest.hexdigest()


def _validate_source_adapter_manifest(source: Path, release: str, *, tree: Path | None = None) -> dict[str, Any] | None:
    """Reject a present release contract that disagrees with its artifact."""
    path = source / "contracts" / "runtime-adapter-baseline.json"
    if not _path_present(path):
        return None
    if path.is_symlink() or not path.is_file():
        raise ValueError("legacy_baseline_manifest_invalid")
    manifest = _read_json(path)
    if (manifest.get("schemaVersion") != "agentlas.runtime-adapter-baseline.v1"
            or manifest.get("release") != release
            or manifest.get("algorithm") != "sha256-tree-v1"
            or manifest.get("paths") != [p.as_posix() for p in _LEGACY_BASELINE_PATHS]
            or not re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("digest") or ""))
            or _legacy_baseline_digest(tree or source) != manifest["digest"]):
        raise ValueError("legacy_baseline_manifest_invalid")
    return manifest


def _official_legacy_baseline_matches(release: str, baseline: Path, attestation: Path | None = None) -> bool:
    """Check official defaults against the verified release archive."""
    known = _LEGACY_BASELINE_SHA256.get(release)
    if known:
        return _legacy_baseline_digest(baseline) == known
    if not re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", release):
        raise ValueError("legacy_baseline_release_invalid")
    url = "https://api.github.com/repos/agentlas-ai/Agentlas-OS/releases/tags/" + release
    raw, _ = _standalone_json(url)
    if not isinstance(raw, dict):
        raise ValueError("legacy_baseline_release_invalid")
    previous = _standalone_tag_metadata(release, raw)
    asset = _verified_runtime_archive_asset(previous)
    commit = previous["standalone_source_commit"]
    # The tag's contract is trusted only for releases whose publisher checks
    # the contract against the final archive before publishing.
    manifest_path = "contracts/runtime-adapter-baseline.json"
    manifest_url = ("https://api.github.com/repos/agentlas-ai/Agentlas-OS/contents/"
                    + manifest_path + "?ref=" + commit)
    receipt = _read_json(attestation) if attestation is not None and not attestation.is_symlink() else {}
    attested = (receipt.get("schemaVersion") == "agentlas.runtime-adapter-verification.v1"
                and receipt.get("release") == release and receipt.get("commit") == commit
                and receipt.get("assetSha256") == asset["sha256"])
    manifest_ref = None
    if attested:
        try:
            manifest_ref, _ = _standalone_json(manifest_url)
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
    if attested and isinstance(manifest_ref, dict) and manifest_ref.get("type") == "file" and manifest_ref.get("path") == manifest_path:
        encoded = manifest_ref.get("content")
        blob_sha = manifest_ref.get("sha")
        if (manifest_ref.get("encoding") == "base64" and isinstance(encoded, str)
                and len(encoded) <= 32768 and isinstance(blob_sha, str)
                and re.fullmatch(r"[0-9a-f]{40}", blob_sha)):
            try:
                raw_manifest = base64.b64decode("".join(encoded.split()), validate=True)
                blob = hashlib.sha1(b"blob " + str(len(raw_manifest)).encode() + b"\0" + raw_manifest).hexdigest()
                manifest = json.loads(raw_manifest.decode("utf-8"))
            except (ValueError, UnicodeError):
                manifest = None
                blob = ""
            if (blob == blob_sha and isinstance(manifest, dict)
                    and manifest.get("schemaVersion") == "agentlas.runtime-adapter-baseline.v1"
                    and manifest.get("release") == release and manifest.get("algorithm") == "sha256-tree-v1"
                    and manifest.get("paths") == [p.as_posix() for p in _LEGACY_BASELINE_PATHS]
                    and re.fullmatch(r"[0-9a-f]{64}", str(manifest.get("digest") or ""))
                    and receipt.get("digest") == manifest["digest"]
                    and _legacy_baseline_digest(baseline) == manifest["digest"]):
                return True
    with tempfile.TemporaryDirectory(prefix="agentlas-official-baseline-") as temporary:
        temp = Path(temporary)
        archive = temp / "previous.tar.gz"
        _download(asset["url"], archive)
        if archive.stat().st_size != asset["size"] or _sha256_file(archive) != asset["sha256"]:
            raise ValueError("legacy_baseline_archive_mismatch")
        extraction = temp / "extract"
        extraction.mkdir()
        with tarfile.open(archive, "r:gz") as source:
            _safe_extract(source, extraction)
        source = extraction / ("Agentlas-OS-" + release[1:])
        if not source.is_dir() or _source_release_tag(source) != release:
            raise ValueError("legacy_baseline_archive_root_mismatch")
        entries = list(extraction.iterdir())
        if len(entries) != 1 or entries[0] != source:
            raise ValueError("legacy_baseline_archive_root_mismatch")
        manifest = _read_json(source / "manifest.json")
        if (manifest.get("version") != release[1:]
                or _release_provenance_commit(source) != previous["standalone_source_commit"]):
            raise ValueError("legacy_baseline_provenance_mismatch")
        _restore_relocated_release_payload(source)
        _validate_source_adapter_manifest(source, release)
        return _legacy_baseline_digest(source) == _legacy_baseline_digest(baseline)


def _legacy_staged_baseline() -> None:
    """Capture the actual old generation while the legacy installer holds its lock.

    The pre-activation healthcheck is a child of the old installer.  Limit this
    side effect to its exact staging directory; ordinary imports and the
    post-activation healthcheck must never write a snapshot.
    """
    requested = os.environ.get("HEPHAESTUS_HEALTHCHECK_ROOT")
    if not requested:
        return
    root = Path(requested).resolve()
    if root != Path(__file__).resolve().parent.parent:
        return
    match = re.fullmatch(r"\.(\d+\.\d+\.\d+)\.staged\.(\d+)\.(\d+)", root.name)
    if not match or int(match.group(2)) != os.getppid():
        return
    payload = root / _LEGACY_ADAPTER_PAYLOAD
    if not payload.is_dir() or _is_link(payload):
        return
    base = root.parent
    lock = base / ".update.lock"
    if lock.is_symlink() or not lock.is_file():
        raise RuntimeError("legacy_baseline_update_lock_unverified")
    lock_data = _read_json(lock)
    token = lock_data.get("token")
    if lock_data.get("pid") != os.getppid() or not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        raise RuntimeError("legacy_baseline_update_lock_unverified")
    # The oldest supported updaters do not stage contracts/.  The release
    # archive carries a duplicate inside the mandatory agentlas_cloud tree.
    contract_payload = root / _LEGACY_CONTRACT_PAYLOAD
    contracts = root / "contracts"
    if _path_present(contract_payload):
        if _has_symlink_in_path(contract_payload, root) or not contract_payload.is_dir():
            raise RuntimeError("legacy_contract_payload_unsafe")
        if not _path_present(contracts):
            shutil.copytree(contract_payload, contracts, symlinks=True)
        elif _is_link(contracts) or not _managed_content_matches(contracts, contract_payload):
            raise RuntimeError("legacy_contract_payload_mismatch")
        shutil.rmtree(contract_payload)
    if _is_link(contracts) or not contracts.is_dir():
        raise RuntimeError("legacy_contract_payload_missing")
    runtime_payload = root / _LEGACY_RUNTIME_PAYLOAD
    if _path_present(runtime_payload):
        if _has_symlink_in_path(runtime_payload, root) or not runtime_payload.is_dir():
            raise RuntimeError("legacy_runtime_payload_unsafe")
        for name in _LEGACY_RUNTIME_ROOTS:
            source = runtime_payload / name
            if _is_link(source) or not source.is_dir():
                raise RuntimeError("legacy_runtime_payload_missing")
            _copy_missing_payload(source, root / name, strict=True,
                                  source_boundary=runtime_payload, dest_boundary=root)
        provenance = runtime_payload / "release-provenance.json"
        destination = root / "release-provenance.json"
        if _is_link(provenance) or not provenance.is_file():
            raise RuntimeError("legacy_provenance_payload_missing")
        if not _path_present(destination):
            shutil.copy2(provenance, destination)
        elif not _managed_content_matches(destination, provenance):
            raise RuntimeError("legacy_provenance_payload_mismatch")
        shutil.rmtree(runtime_payload)
    # Early v1.2 updaters did not copy these roots at all.
    if any(not (root / name).is_dir() or _is_link(root / name) for name in _LEGACY_RUNTIME_ROOTS):
        raise RuntimeError("legacy_runtime_payload_missing")
    if _is_link(root / "release-provenance.json") or not (root / "release-provenance.json").is_file():
        raise RuntimeError("legacy_provenance_payload_missing")
    _copy_missing_payload(payload / "skills", root / "skills", strict=True,
                          source_boundary=payload, dest_boundary=root)
    _validate_source_adapter_manifest(root, "v" + match.group(1), tree=payload)
    current = base / "current"
    active = current.resolve()
    if not current.is_dir() or not _is_generation_dir(active, base.resolve()):
        raise RuntimeError("legacy_baseline_active_generation_unverified")
    release = current_release(current)
    expected = _LEGACY_BASELINE_SHA256.get(release or "")
    previous = current / HOST_ADAPTER_BUNDLE_DIR
    if not expected or _is_link(previous) or not previous.is_dir():
        raise RuntimeError("legacy_adapter_baseline_unverified")
    snapshot = root / ".legacy-pre-activation-v1"
    if _path_present(snapshot):
        raise RuntimeError("legacy_baseline_snapshot_conflict")
    with tempfile.TemporaryDirectory(prefix=".legacy-baseline-", dir=root) as temporary:
        pending = Path(temporary) / "snapshot"
        pending.mkdir()
        for relative in _LEGACY_BASELINE_PATHS:
            if _has_symlink_in_path(previous / relative, previous):
                raise RuntimeError("legacy_baseline_symlink")
            target = pending / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(previous / relative, target, symlinks=True)
        if _legacy_baseline_digest(pending) != expected or current.resolve() != active:
            raise RuntimeError("legacy_adapter_baseline_unverified")
        if _read_json(lock).get("token") != token:
            raise RuntimeError("legacy_baseline_update_lock_changed")
        _write_json(pending / "receipt.json", {
            "schemaVersion": "agentlas.legacy-pre-activation.v1",
            "release": release, "digest": expected, "lockToken": token,
            "parentPid": os.getppid(), "targetRelease": "v" + match.group(1),
        })
        pending.rename(snapshot)


def _has_symlink_in_path(path: Path, boundary: Path) -> bool:
    if not path.is_relative_to(boundary):
        return True
    for part in (path, *path.parents):
        if _is_link(part):
            return True
        if part == boundary:
            return False
    return True


def _copy_missing_payload(source: Path, dest: Path, *, strict: bool, source_boundary: Path, dest_boundary: Path) -> list[str]:
    """Merge verified payload into an owned tree without replacing existing files."""
    preserved: list[str] = []
    if not source.exists():
        return preserved
    if not source.is_dir() or _has_symlink_in_path(source, source_boundary):
        raise ValueError("legacy_adapter_payload_unsafe")
    for entry in sorted(source.rglob("*")):
        relative = entry.relative_to(source)
        target = dest / relative
        if entry.is_symlink():
            raise ValueError("legacy_adapter_payload_unsafe")
        if _has_symlink_in_path(target, dest_boundary):
            raise ValueError("legacy_adapter_destination_unsafe")
        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif entry.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if not target.is_file() or target.read_bytes() != entry.read_bytes():
                    if strict:
                        raise ValueError("legacy_adapter_payload_conflict")
                    preserved.append(str(target))
                continue
            try:
                with target.open("xb") as output, entry.open("rb") as input_file:
                    shutil.copyfileobj(input_file, output)
                shutil.copymode(entry, target, follow_symlinks=False)
            except FileExistsError:
                if strict:
                    raise ValueError("legacy_adapter_payload_conflict")
                preserved.append(str(target))
    return preserved


def _restore_relocated_release_payload(source: Path) -> None:
    """Normalize a legacy-safe archive only after its digest is verified."""
    source = source.resolve()
    payload = source / _LEGACY_ADAPTER_PAYLOAD
    if not payload.exists():
        return
    if payload.is_symlink() or not payload.is_dir():
        raise ValueError("legacy_adapter_payload_unsafe")
    if any(not (payload / relative).is_dir() for relative in _LEGACY_ADAPTER_PATHS):
        raise ValueError("legacy_adapter_payload_incomplete")
    for relative in _LEGACY_ADAPTER_PATHS:
        _copy_missing_payload(payload / relative, source / relative, strict=True, source_boundary=payload, dest_boundary=source)
    # This is the updater-owned temporary extraction, not an installed tree.
    shutil.rmtree(payload)
    contract_payload = source / _LEGACY_CONTRACT_PAYLOAD
    if _path_present(contract_payload):
        if (_has_symlink_in_path(contract_payload, source) or not contract_payload.is_dir()
                or not _managed_content_matches(source / "contracts", contract_payload)):
            raise ValueError("legacy_contract_payload_mismatch")
        shutil.rmtree(contract_payload)
    runtime_payload = source / _LEGACY_RUNTIME_PAYLOAD
    if _path_present(runtime_payload):
        if _has_symlink_in_path(runtime_payload, source) or not runtime_payload.is_dir():
            raise ValueError("legacy_runtime_payload_unsafe")
        for name in _LEGACY_RUNTIME_ROOTS:
            if not _managed_content_matches(source / name, runtime_payload / name):
                raise ValueError("legacy_runtime_payload_mismatch")
        if not _managed_content_matches(source / "release-provenance.json", runtime_payload / "release-provenance.json"):
            raise ValueError("legacy_provenance_payload_mismatch")
        shutil.rmtree(runtime_payload)


def reconcile_legacy_bridge() -> dict[str, Any]:
    """Complete a legacy-safe archive installed by an older updater.

    The old updater runs the hook installer after activation.  Only that
    active, self-owned generation is eligible; no foreign checkout is touched.
    """
    try:
        base = _legacy_runtime_base()
        if base is None:
            return {"status": "not_applicable"}
        root = (base / "current").resolve()
        if root != Path(__file__).resolve().parent.parent:
            return {"status": "blocked", "reason": "legacy_bridge_not_active_generation"}
        payload = root / _LEGACY_ADAPTER_PAYLOAD
        if not payload.exists():
            return {"status": "not_applicable"}
        if (not payload.is_dir() or _is_link(payload) or _is_link(payload.parent)
                or payload.resolve().parent != (root / "agentlas_cloud").resolve()):
            return {"status": "blocked", "reason": "legacy_adapter_payload_unsafe"}
        if any(not (payload / relative).is_dir() for relative in _LEGACY_ADAPTER_PATHS):
            return {"status": "blocked", "reason": "legacy_adapter_payload_incomplete"}
        marker = root / ".legacy-adapters-reconciled-v1.json"
        if _read_json(marker).get("status") == "pass":
            return {"status": "pass", "alreadyReconciled": True}
        lock = base / ".legacy-adapter-reconcile.lock"
        token = _acquire_lock(lock)
        try:
            current = current_release(root)
            previous = root / ".legacy-pre-activation-v1"
            receipt_path = previous / "receipt.json"
            if _is_link(previous) or not previous.is_dir() or _is_link(receipt_path) or not receipt_path.is_file():
                return {"status": "blocked", "reason": "legacy_adapter_baseline_unverified"}
            receipt = _read_json(receipt_path)
            previous_release = receipt.get("release")
            expected = _LEGACY_BASELINE_SHA256.get(previous_release) if isinstance(previous_release, str) else None
            update_lock = base / ".update.lock"
            lock_data = _read_json(update_lock) if not update_lock.is_symlink() else {}
            old_lock_present = _path_present(update_lock)
            receipt_token = receipt.get("lockToken")
            if (receipt.get("schemaVersion") != "agentlas.legacy-pre-activation.v1"
                    or not expected or receipt.get("digest") != expected
                    or receipt.get("targetRelease") != current
                    or not isinstance(receipt_token, str) or not re.fullmatch(r"[0-9a-f]{32}", receipt_token)
                    or not isinstance(receipt.get("parentPid"), int) or receipt["parentPid"] <= 0
                    or (old_lock_present and (receipt_token != lock_data.get("token")
                                              or receipt["parentPid"] != lock_data.get("pid")))
                    or _compare_semver(previous_release, current) is None
                    or _compare_semver(previous_release, current) >= 0):
                return {"status": "blocked", "reason": "legacy_adapter_baseline_unverified"}
            bundle = root / HOST_ADAPTER_BUNDLE_DIR
            if bundle.is_symlink() or not bundle.is_dir():
                raise ValueError("legacy_bridge_bundle_unavailable")
            # Keep the verified tree stable while comparing installed files.
            with tempfile.TemporaryDirectory(prefix="agentlas-legacy-baseline-") as temporary:
                baseline = Path(temporary) / "baseline"
                baseline.mkdir()
                for relative in _LEGACY_BASELINE_PATHS:
                    target = baseline / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(previous / relative, target, symlinks=True)
                if _legacy_baseline_digest(baseline) != expected:
                    return {"status": "blocked", "reason": "legacy_adapter_baseline_changed"}
                preserved: list[str] = []
                for relative in _LEGACY_ADAPTER_PATHS:
                    src = payload / relative
                    preserved.extend(_copy_missing_payload(src, bundle / relative, strict=False, source_boundary=payload, dest_boundary=bundle))
                    if relative in (Path("skills"), Path("openclaw/skills")):
                        preserved.extend(_copy_missing_payload(src, root / relative, strict=False, source_boundary=payload, dest_boundary=root))
                sync = sync_installed_runtime_adapters(bundle, previous_source=baseline, skip_grok=True)
                if sync.get("failed"):
                    return {"status": "blocked", "reason": "legacy_adapter_sync_failed", "failedCount": len(sync["failed"])}
                if preserved:
                    # The generation's own adapter bundle disagrees with the verified payload.
                    return {"status": "blocked", "reason": "legacy_adapter_bundle_conflict",
                            "preservedCount": len(preserved)}
            # Installed files the owner edited are left exactly as they are. That is the
            # intended result of the sync, not a failure: blocking here would stop every
            # later update on a machine whose owner customized one command.
            kept = len(sync.get("preserved_modified") or [])
            _write_json(marker, {"schemaVersion": "agentlas.legacy-adapters.v1", "status": "pass", "release": current,
                                 "preservedModifiedCount": kept})
            return {"status": "pass", "preservedCount": kept}
        finally:
            _release_lock(lock, token)
    except (OSError, ValueError, RuntimeError) as exc:
        return {"status": "blocked", "reason": str(exc)[:200]}


_LEGACY_HOST_RETRY_LIMIT = 3


def _retry_legacy_host_reconciliation(base: Path) -> dict[str, Any]:
    """Retry post-activation host work after an interrupted legacy update."""
    if _legacy_runtime_base() != base:
        return {"status": "not_applicable"}
    marker = base / ".legacy-host-reconcile.json"
    if not _path_present(marker):
        return {"status": "not_applicable"}
    if marker.is_symlink() or not marker.is_file():
        return {"status": "blocked", "reason": "legacy_host_marker_unsafe"}
    record = _read_json(marker)
    if record.get("schemaVersion") != "agentlas.legacy-host-reconcile.v1":
        return {"status": "blocked", "reason": "legacy_host_marker_invalid"}
    current = base / "current"
    release = current_release(current)
    if record.get("target") != release:
        # An activation that rolled back leaves the previous generation live.
        return {"status": "not_applicable", "reason": "legacy_host_marker_stale"}
    try:
        token = _acquire_lock(base / ".update.lock")
    except RuntimeError:
        return {"status": "blocked", "reason": "legacy_host_update_in_progress"}
    try:
        # Retry a bounded number of times. A step that keeps failing would otherwise rewrite the
        # host files on every update check forever and hold back the cleanup of old generations.
        attempts = record.get("attempts")
        attempts = attempts if isinstance(attempts, int) and not isinstance(attempts, bool) and attempts >= 0 else 0
        if attempts >= _LEGACY_HOST_RETRY_LIMIT:
            if not marker.is_symlink() and _read_json(marker) == record:
                marker.unlink(missing_ok=True)
            return {"status": "gave_up", "reason": "legacy_host_reconcile_incomplete", "attempts": attempts}
        record = {**record, "attempts": attempts + 1}
        _write_json(marker, record)
        bundle = current / HOST_ADAPTER_BUNDLE_DIR
        _validate_host_adapter_bundle(bundle, release)
        previous = record.get("previous")
        if not isinstance(previous, str) or not _is_comparable_release(previous):
            return {"status": "blocked", "reason": "legacy_adapter_baseline_unverified"}
        candidate = base / _runtime_version_dir_name(previous)
        old_bundle = candidate / HOST_ADAPTER_BUNDLE_DIR
        if (_is_link(candidate) or not candidate.is_dir() or current_release(candidate) != previous
                or _is_link(old_bundle) or not old_bundle.is_dir()):
            return {"status": "blocked", "reason": "legacy_adapter_baseline_unverified"}
        with tempfile.TemporaryDirectory(prefix="agentlas-legacy-retry-") as temporary:
            baseline = Path(temporary) / "baseline"
            shutil.copytree(old_bundle, baseline, ignore=PYTHON_CACHE_IGNORE, symlinks=True)
            if not _official_legacy_baseline_matches(
                    previous, baseline, candidate / ".runtime-adapter-verified-v1.json"):
                return {"status": "blocked", "reason": "legacy_adapter_baseline_unverified"}
            adapters = sync_installed_runtime_adapters(bundle, previous_source=baseline)
        from .host_update import reconcile_host_plugins
        plugins = reconcile_host_plugins(bundle, release)
        hooks = sync_installed_memory_hooks(bundle)
        router = _sync_installed_global_router(current)
        if (adapters.get("failed")
                or plugins.get("status") in {"partial", "fail", "failed", "blocked"}
                or hooks.get("status") in {"fail", "failed", "blocked"}
                or router.get("status") in {"fail", "failed", "blocked"}):
            return {"status": "blocked", "reason": "legacy_host_reconcile_incomplete"}
        if marker.is_symlink() or _read_json(marker) != record:
            return {"status": "blocked", "reason": "legacy_host_marker_changed"}
        marker.unlink()
        return {"status": "pass"}
    except (OSError, ValueError, RuntimeError) as exc:
        return {"status": "blocked", "reason": str(exc)[:200]}
    finally:
        _release_lock(base / ".update.lock", token)


def _managed_content_matches(left: Path, right: Path) -> bool:
    """Only replace an installed adapter if it still matches its old bundle."""
    try:
        if left.is_symlink() or right.is_symlink():
            return False
        if left.is_file() and right.is_file():
            return left.read_bytes() == right.read_bytes()
        if not left.is_dir() or not right.is_dir():
            return False
        left_paths = {p.relative_to(left) for p in left.rglob("*") if "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}}
        right_paths = {p.relative_to(right) for p in right.rglob("*") if "__pycache__" not in p.parts and p.suffix not in {".pyc", ".pyo"}}
        if left_paths != right_paths:
            return False
        for relative in left_paths:
            a, b = left / relative, right / relative
            if a.is_symlink() or b.is_symlink() or a.is_dir() != b.is_dir():
                return False
            if a.is_file() and (not b.is_file() or a.read_bytes() != b.read_bytes()):
                return False
        return True
    except OSError:
        return False


def sync_installed_runtime_adapters(source: Path, home: Path | None = None, *, previous_source: Path | None = None, skip_grok: bool = False) -> dict[str, Any]:
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
    preserved_modified: list[str] = []

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
        if existed and previous_source is not None and not _managed_content_matches(dest, previous_source / src_rel):
            # A previous retry may already have installed this exact content.
            if not _managed_content_matches(dest, src):
                preserved_modified.append(str(dest))
            continue
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
        if previous_source is not None and not _managed_content_matches(dest, previous_source / src_rel):
            if not _managed_content_matches(dest, src):
                preserved_modified.append(str(dest))
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
        if previous_source is not None and dest.exists():
            # A versioned cache may have been populated by a host or user;
            # never replace it while migrating an existing installation.
            cache_preserved.append(str(dest))
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

    grok_result = {"updated": [], "failed": []} if skip_grok else _sync_grok_marketplace_cache(home_dir)
    updated.extend(grok_result["updated"])
    # A Grok marketplace clone that is dirty, offline or not fast-forwardable is a cache of
    # this repository. Report it, but never let it fail (and so block) a runtime update.
    grok_cache_skipped = list(grok_result["failed"])

    return {
        "updated": updated,
        # Named separately from `updated` so a receipt can show that a surface
        # gained a command it did not have, rather than burying it in a refresh
        # count that looks identical whether or not anything arrived.
        "added": added,
        "skipped_missing": skipped_missing,
        "failed": failed,
        "preserved_modified": preserved_modified,
        "grok_cache_skipped": grok_cache_skipped,
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
            **no_console_window(),
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

    from .feature_preferences import feature_enabled

    if not feature_enabled("memory-hooks", home=home):
        return {"status": "skipped", "reason": "feature_disabled", "installed": {}, "errors": {}}

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
            **no_console_window(),
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
    desktop_npm_repair = payload.get("desktop_npm_repair")
    if not isinstance(desktop_npm_repair, dict):
        desktop_npm_repair = installed.get("desktop_npm_repair")
    if not isinstance(desktop_npm_repair, dict):
        desktop_npm_repair = {"status": "not_applicable", "reason": "not_reported"}
    return {
        "status": status,
        "installed": installed,
        "errors": errors,
        "desktop_repair": desktop_repair,
        "desktop_updater_cleanup": desktop_updater_cleanup,
        "desktop_npm_repair": desktop_npm_repair,
    }


def retry_installed_desktop_npm_repair(source: Path, home: Path | None = None) -> dict[str, Any]:
    """Retain the legacy receipt without operating on another product."""
    return {"status": "not_applicable", "reason": "engine_independent"}


def retry_installed_desktop_repair(source: Path, home: Path | None = None) -> dict[str, Any]:
    return {"status": "not_applicable", "reason": "engine_independent"}


def retry_installed_desktop_updater_cleanup(source: Path, home: Path | None = None) -> dict[str, Any]:
    return {"status": "not_applicable", "reason": "engine_independent"}


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


_CMD_PATH_BASES = ("USERPROFILE", "LOCALAPPDATA", "APPDATA")


def windows_cmd_path(absolute: str, env: Mapping[str, str] | None = None) -> tuple[str, bool]:
    """(text to write inside a .cmd file, whether the file must switch cmd.exe to UTF-8).

    cmd.exe reads a batch file in the console's OEM code page (949 on Korean Windows), not
    UTF-8. An absolute path written as UTF-8 for a user named 홍길동 reads back as mojibake and
    the shim fails with "The system cannot find the path specified" every time. A path under
    %USERPROFILE% / %LOCALAPPDATA% / %APPDATA% is written relative to that variable (ASCII;
    cmd.exe expands it to the real Unicode path at run time). Anything else that is still not
    ASCII is written as-is and the caller puts `chcp 65001 >nul` first. Same rule as Agentlas
    Desktop's windowsCmdPath (electron/runtime/install-cli.ts). ASCII paths are unchanged.
    """
    def ascii(value: str) -> bool:
        return all(" " <= character <= "~" for character in value)

    if ascii(absolute):
        return absolute.replace("%", "%%"), False
    variables = os.environ if env is None else env
    for name in _CMD_PATH_BASES:
        base = str(variables.get(name) or "").rstrip("\\/")
        if not base:
            continue
        head, rest = absolute[: len(base)], absolute[len(base):]
        if head.lower() != base.lower() or rest[:1] not in ("\\", "/"):
            continue
        relative = rest.lstrip("\\/")
        if relative and ascii(relative) and ".." not in relative.replace("/", "\\").split("\\"):
            return f"%{name}%\\" + relative.replace("/", "\\").replace("%", "%%"), False
    return absolute.replace("%", "%%"), True


def _cmd_utf8_prologue(needs_utf8: bool) -> str:
    return "chcp 65001 >nul\r\n" if needs_utf8 else ""


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
    cmd_executable, executable_utf8 = windows_cmd_path(executable_text)
    cache_utf8 = False
    if os.name == "nt":
        cmd_cache_path, cache_utf8 = windows_cmd_path(str(cache_prefix))
        cmd_cache = f'set "PYTHONPYCACHEPREFIX={cmd_cache_path}"\r\n'
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
        f"{_cmd_utf8_prologue(executable_utf8 or cache_utf8)}"
        'setlocal\r\n'
        'set "PYTHONDONTWRITEBYTECODE=1"\r\n'
        f"{cmd_cache}"
        f'"{cmd_executable}" %*\r\n'
        'exit /b %ERRORLEVEL%\r\n',
    )
    _write_cmd_runner(cmd_runner, cache_prefix)
    _write_cmd_text(
        env_cmd,
        '@echo off\r\n'
        f"{_cmd_utf8_prologue(cache_utf8)}"
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
    # A per-user Git install lives under %LOCALAPPDATA%\Programs\Git — a Korean user name would
    # put a non-ASCII absolute path into every wrapper (see windows_cmd_path).
    bash, bash_utf8 = windows_cmd_path(bash)
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
        # %~dp0, not the absolute script path: bin_dir is the staged directory,
        # which _activate_runtime renames right after, so an absolute path here
        # points every wrapper at a directory that no longer exists.
        _write_cmd_text(
        target,
            "@echo off\r\n"
            f"{_cmd_utf8_prologue(bash_utf8)}"
            "setlocal\r\n"
            f'"{bash}" "%~dp0{script.name}" %*\r\n'
            "exit /b %ERRORLEVEL%\r\n",
        )
        written.append(target.name)
    return written


def _write_cmd_runner(path: Path, cache_prefix: Path | None = None) -> None:
    cache_utf8 = False
    if cache_prefix is not None and os.name == "nt":
        cmd_cache_path, cache_utf8 = windows_cmd_path(str(cache_prefix))
        cmd_cache = f'set "PYTHONPYCACHEPREFIX={cmd_cache_path}"\r\n'
    else:
        cmd_cache = (
            'if defined LOCALAPPDATA (set "PYTHONPYCACHEPREFIX=%LOCALAPPDATA%\\Agentlas\\PythonCache") '
            'else (set "PYTHONPYCACHEPREFIX=%TEMP%\\Agentlas-PythonCache")\r\n'
        )
    _write_cmd_text(
        path,
        '@echo off\r\n'
        f"{_cmd_utf8_prologue(cache_utf8)}"
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


def _is_default_standalone_namespace(candidate: Path, home: Path) -> bool:
    if candidate.resolve() != (home / ".agentlas" / "os-runtime").resolve():
        return False
    marker = candidate / ".agentlas-os-namespace-v1"
    if not _path_present(marker):
        # A legacy user was allowed to choose this very path before namespaces.
        return False
    if marker.is_symlink() or not marker.is_file() or marker.read_bytes() != b"agentlas-os-namespace-v1\n":
        raise ValueError("standalone_namespace_ownership_unverified")
    return True


def _legacy_runtime_base() -> Path | None:
    """Recognize an updater loaded from an existing legacy generation.

    The environment override named the legacy base itself in older versions;
    standalone uses the same setting as the parent of its isolated namespace.
    The executable's actual path determines which contract it belongs to.
    """
    home = Path.home().resolve()
    override = os.environ.get("HEPHAESTUS_RUNTIME_BASE")
    candidate = Path(override) if override else home / ".agentlas" / "runtime"
    if override and _is_default_standalone_namespace(candidate, home):
        return None
    try:
        base = candidate.resolve()
        module = Path(__file__).resolve()
        relative = module.relative_to(base)
        if len(relative.parts) != 3 or relative.parts[1:] != ("agentlas_cloud", "update.py"):
            return None
        generation = base / relative.parts[0]
        current = base / "current"
        selected = current.resolve()
        if not _path_present(current) or not current.is_dir() or not _is_generation_dir(selected, base):
            raise RuntimeError("legacy_runtime_current_unsafe")
        if not _is_comparable_release(current_release(generation)):
            raise RuntimeError("legacy_runtime_generation_unverified")
        if not _is_comparable_release(current_release(current)):
            raise RuntimeError("legacy_runtime_current_unverified")
        return base
    except (OSError, ValueError):
        return None


def _runtime_base() -> Path:
    try:
        legacy = _legacy_runtime_base()
    except RuntimeError as exc:
        raise ValueError(str(exc)) from exc
    if legacy is not None:
        return legacy
    home = Path.home().resolve()
    state = home / ".agentlas"
    override = os.environ.get("HEPHAESTUS_RUNTIME_BASE")
    if override and not Path(override).is_absolute():
        raise ValueError("standalone_runtime_base_not_absolute")
    custom = Path(override) if override else None
    if state.is_symlink() or (custom is not None and custom.is_symlink()):
        raise ValueError("standalone_runtime_base_unsafe")
    if custom is not None and custom.resolve() == (state / "os-runtime").resolve():
        custom = None
    parent = custom.resolve() if custom is not None else state
    legacy = (state / "runtime").resolve()
    if custom is not None and (parent == legacy or parent.is_relative_to(legacy) or legacy.is_relative_to(parent)):
        raise ValueError("standalone_runtime_base_shared")
    base = parent / "os-runtime"
    if base.is_symlink():
        raise ValueError("standalone_runtime_base_unsafe")
    if custom is not None:
        old_current = parent / "current"
        if (old_current.exists() or old_current.is_symlink()) and old_current.resolve().is_relative_to(base.resolve()):
            raise ValueError("standalone_custom_current_shared")
    if base.exists():
        marker = base / ".agentlas-os-namespace-v1"
        if marker.is_symlink() or not marker.is_file() or marker.read_bytes() != b"agentlas-os-namespace-v1\n":
            raise ValueError("standalone_namespace_ownership_unverified")
        current = base / "current"
        if current.exists() or current.is_symlink():
            if (not current.is_dir() or not _is_generation_dir(current.resolve(), base.resolve())
                    or not _is_comparable_release(current_release(current))):
                raise ValueError("standalone_namespace_current_unsafe")
    return base


def _legacy_base_for_root(runtime_root: Path) -> Path | None:
    """Resolve an explicit active legacy root passed by an installed hook."""
    override = os.environ.get("HEPHAESTUS_RUNTIME_BASE")
    candidate = Path(override) if override else Path.home().resolve() / ".agentlas" / "runtime"
    if override and _is_default_standalone_namespace(candidate, Path.home().resolve()):
        return None
    base = candidate.resolve()
    current = base / "current"
    try:
        selected = current.resolve()
        requested = runtime_root.resolve()
        if requested != selected:
            return None
        if (not current.is_dir() or not _is_generation_dir(selected, base)
                or not _is_comparable_release(current_release(current))):
            raise ValueError("legacy_runtime_current_unsafe")
        return base
    except OSError as exc:
        raise ValueError("legacy_runtime_current_unsafe") from exc


def _runtime_base_for_root(runtime_root: Path) -> Path:
    return _legacy_base_for_root(runtime_root) or _runtime_base()


def _active_runtime_for_cached_updater() -> Path | None:
    """A host plugin's cached CLI must update its installed runtime, not itself."""
    module = Path(__file__).resolve()
    home = Path.home().resolve()
    from_cache = False
    for _, _, cache in _plugin_cache_roots(home):
        try:
            relative = module.relative_to(cache.resolve())
        except ValueError:
            continue
        if len(relative.parts) == 3 and relative.parts[1:] == ("agentlas_cloud", "update.py"):
            from_cache = True
            break
    if not from_cache:
        return None
    override = os.environ.get("HEPHAESTUS_RUNTIME_BASE")
    legacy = Path(override) if override else home / ".agentlas" / "runtime"
    current = legacy / "current"
    if _path_present(current) and not _is_default_standalone_namespace(legacy, home):
        if _legacy_base_for_root(current) is None:
            raise ValueError("legacy_runtime_current_unsafe")
        return current.resolve()
    base = _runtime_base()
    current = base / "current"
    if _path_present(current):
        if not _allowed_update_root(current, base) or not _is_comparable_release(current_release(current)):
            raise ValueError("standalone_current_unverified")
        return current.resolve()
    return None


def _run_update_in_active_runtime(runtime_root: Path, check_only: bool) -> dict[str, Any]:
    base = _runtime_base_for_root(runtime_root)
    env = os.environ.copy()
    if env.get("HEPHAESTUS_RUNTIME_BASE") and _legacy_base_for_root(runtime_root) is not None:
        env["HEPHAESTUS_RUNTIME_BASE"] = str(base)
    code = (
        "import json,sys\n"
        "sys.path.insert(0,sys.argv[1])\n"
        "from agentlas_cloud.update import run_update,UpdateUnavailableError\n"
        "try:\n result=run_update(check_only=sys.argv[2]=='1')\n"
        "except UpdateUnavailableError as exc:\n print(json.dumps({'errorPayload':exc.payload})); raise SystemExit(3)\n"
        "print(json.dumps({'result':result},ensure_ascii=False))\n"
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-c", code, str(runtime_root), "1" if check_only else "0"],
            cwd=str(base), env=env, stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=1800, check=False, **no_console_window(),
        )
        payload = json.loads(completed.stdout)
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise UpdateUnavailableError({"status": "check_failed", "error": "runtime_worker_failed", "writeAttempted": not check_only},
                                     "Runtime update result unavailable; inspect runtime status.") from exc
    if completed.returncode == 3 and isinstance(payload, dict) and isinstance(payload.get("errorPayload"), dict):
        raise UpdateUnavailableError(payload["errorPayload"], "Runtime update unavailable; inspect runtime status.")
    if completed.returncode != 0 or not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
        raise UpdateUnavailableError({"status": "check_failed", "error": "runtime_worker_failed", "writeAttempted": not check_only},
                                     "Runtime update unavailable; inspect runtime status before retrying.")
    return payload["result"]


def _prepare_update_base(base: Path) -> None:
    if _legacy_runtime_base() == base:
        return
    override = os.environ.get("HEPHAESTUS_RUNTIME_BASE")
    default_base = Path.home().resolve() / ".agentlas" / "os-runtime"
    use_default = not override or Path(override).expanduser().resolve() == default_base.resolve()
    if not use_default:
        parent = Path(override).expanduser()
        if not parent.is_dir() or parent.is_symlink():
            raise ValueError("standalone_custom_base_unavailable")
    created = False
    try:
        base.mkdir(parents=use_default)
        created = True
    except FileExistsError:
        pass
    marker = base / ".agentlas-os-namespace-v1"
    if created:
        with marker.open("x", encoding="utf-8") as handle:
            handle.write("agentlas-os-namespace-v1\n")
    if (marker.is_symlink() or not marker.is_file()
            or marker.read_bytes() != b"agentlas-os-namespace-v1\n"
            or _runtime_base() != base):
        raise ValueError("standalone_namespace_ownership_unverified")




def _auto_update_disabled() -> bool:
    from .feature_preferences import feature_enabled
    return not feature_enabled("auto-update")


def _marker_recent(epoch: Any, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> bool:
    return isinstance(epoch, (int, float)) and 0 <= time.time() - float(epoch) < ttl_seconds


def _run_auto_update_once(root: Path | None = None) -> dict[str, Any]:
    if _auto_update_disabled():
        return {"status": "skipped", "reason": "feature_disabled", "writeAttempted": False}
    try:
        return run_update(check_only=False, root=root)
    except UpdateUnavailableError as exc:
        return exc.payload


def _record_auto_update_failure(code: str, *, base: Path | None = None) -> None:
    # Never persist exception text: it can contain URLs, paths or credentials.
    base = base or _runtime_base()
    marker_path = base / AUTO_UPDATE_MARKER
    marker = _read_json(marker_path)
    marker.pop("updated_to", None)
    try:
        marker["current"] = current_release(base / "current")
    except (OSError, ValueError):
        marker["current"] = None
    previous = marker.get("failure_count", 0)
    count = min(previous + 1, len(UPDATE_RETRY_SECONDS)) if isinstance(previous, int) and previous >= 0 else 1
    _write_json(marker_path, {**marker, "status": "failed", "errorCode": code,
                              "failure_count": count, "last_failed_epoch": int(time.time())})


def _run_auto_update_guarded(runtime_root: Path) -> None:
    try:
        # The preference may have changed while this detached worker started.
        if _auto_update_disabled():
            return
        result = _run_auto_update_once(runtime_root)
        previous = _read_json(_runtime_base() / AUTO_UPDATE_MARKER)
        _persist_update_marker(previous, result, runtime_root)
        if result.get("status") in {"check_failed", "blocked", "failed"}:
            _record_auto_update_failure("update_failed")
    except (urllib.error.URLError, TimeoutError):
        _record_auto_update_failure("network_unavailable")
    except Exception:
        _record_auto_update_failure("update_failed")


def _auto_update_worker_settings(runtime_root: Path) -> tuple[dict[str, str], Path]:
    env = os.environ.copy()
    env["HEPHAESTUS_AUTO_UPDATE_WORKER"] = "1"
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(runtime_root) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    worker_cwd = _runtime_base_for_root(runtime_root)
    # In legacy versions the override names the base itself. A relative value
    # must be frozen before changing cwd or the child selects base/base.
    if env.get("HEPHAESTUS_RUNTIME_BASE") and _legacy_base_for_root(runtime_root) is not None:
        env["HEPHAESTUS_RUNTIME_BASE"] = str(worker_cwd)
    return env, worker_cwd


def _spawn_auto_update_worker(runtime_root: Path) -> None:
    env, worker_cwd = _auto_update_worker_settings(runtime_root)
    # The worker is what replaces `current`, so its cwd must not be inside a
    # generation: Windows refuses to rename a directory that is any process's
    # cwd (current is a plain copy there without symlink privilege), and the
    # worker would block its own activation. PYTHONPATH still finds the code.
    try:
        worker_cwd.mkdir(parents=True, exist_ok=True)
    except OSError:
        worker_cwd = Path.home()
    with open(os.devnull, "rb") as stdin, open(os.devnull, "wb") as stdout, open(os.devnull, "wb") as stderr:
        subprocess.Popen(
            [sys.executable, "-m", "agentlas_cloud.update", "--auto-update-worker", str(runtime_root)],
            cwd=str(worker_cwd),
            env=env,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            close_fds=True,
            start_new_session=True,
            **no_console_window(),
        )


def _run_external_auto_update_worker(runtime_root: Path, base: Path) -> None:
    """Run a foreign-cache request with the active runtime's own updater."""
    env, worker_cwd = _auto_update_worker_settings(runtime_root)
    if worker_cwd != base:
        raise ValueError("runtime_worker_namespace_mismatch")
    completed = subprocess.run(
        [sys.executable, "-m", "agentlas_cloud.update", "--auto-update-worker", str(runtime_root)],
        cwd=str(worker_cwd), env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1800,
        check=False, **no_console_window(),
    )
    if completed.returncode:
        raise RuntimeError("runtime_worker_failed")


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
            ]
        )
    return [(src_rel, dest) for src_rel, dest in targets if (source / src_rel).exists()]


def _installed_adapter_dir_targets(source: Path, home: Path) -> list[tuple[Path, Path]]:
    targets: list[tuple[Path, Path]] = []
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
            **no_console_window(),
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
                **no_console_window(),
            )
        except Exception:
            continue
        url = (result.stdout or "").strip().lower()
        if "agentlas-ai/agentlas-os" in url:
            targets.append(child)
    return targets


def _sync_grok_marketplace_cache(home: Path) -> dict[str, Any]:
    """Fast-forward any Grok marketplace-cache clone of this repo to latest.

    This stays git-native (fetch + fast-forward) instead of replacing the
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
            status = subprocess.run(
                ["git", "-C", str(cache_dir), "status", "--porcelain"],
                capture_output=True, timeout=20, check=True, **no_console_window(),
            )
            if status.stdout:
                failed.append({"path": str(cache_dir), "error": "local_changes_preserved"})
                continue
            subprocess.run(
                ["git", "-C", str(cache_dir), "fetch", "--quiet", "origin", "main"],
                capture_output=True,
                timeout=20,
                check=True,
                **no_console_window(),
            )
            subprocess.run(
                ["git", "-C", str(cache_dir), "merge", "--quiet", "--ff-only", "FETCH_HEAD"],
                capture_output=True,
                timeout=20,
                check=True,
                **no_console_window(),
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
    if os.name == "nt" and dest.is_dir() and not _is_link(dest):
        _swap_directory_into_place(tmp, dest)
        return
    if dest.exists() or dest.is_symlink():
        if dest.is_dir() and not dest.is_symlink():
            shutil.rmtree(dest)
        else:
            dest.unlink()
    tmp.rename(dest)


def _swap_directory_into_place(staged: Path, destination: Path) -> None:
    """Windows: move the old directory aside first, then the new one in, then delete the old.

    rmtree(destination) followed by a rename half-deleted a plugin/adapter cache whenever a
    file in it was loaded (.pyd/.node/.exe cannot be deleted while mapped): the tree was left
    partly gone and the rename then failed. Renaming the whole directory away fails cleanly
    instead and leaves the old copy intact; a leftover aside copy is only disk space.
    """
    aside = destination.parent / f".{destination.name}.old-{os.getpid()}-{time.time_ns()}"
    os.rename(destination, aside)
    try:
        os.rename(staged, destination)
    except BaseException:
        os.rename(aside, destination)
        raise
    shutil.rmtree(aside, ignore_errors=True)


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
    engine_tag = _channel_engine_tag(tag)
    if engine_tag is None:
        raise ValueError("standalone_channel_tag_invalid")
    expected_name = (f"agentlas-os-runtime-{engine_tag}.tar.gz" if tag.startswith("os-")
                     else f"hephaestus-runtime-{engine_tag}.tar.gz")
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


def _requires_feature_preferences(runtime_root: Path) -> bool:
    """Detect a source dependency without inferring it from a release version."""
    package_root = runtime_root / "agentlas_cloud"
    for path in package_root.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError("cannot inspect runtime feature dependencies") from exc
        if "feature_preferences" not in text:
            continue
        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as exc:
            raise ValueError("cannot inspect runtime feature dependencies") from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(alias.name == "agentlas_cloud.feature_preferences" for alias in node.names):
                    return True
            elif isinstance(node, ast.ImportFrom):
                if node.module in {"feature_preferences", "agentlas_cloud.feature_preferences"}:
                    return True
                if node.module == "agentlas_cloud" and any(alias.name == "feature_preferences" for alias in node.names):
                    return True
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if node.value in {"feature_preferences", "agentlas_cloud.feature_preferences"}:
                    return True
    # The source installer may embed a Python import inside a shell command.
    installer = runtime_root / "scripts" / "install-all-runtimes.sh"
    if installer.is_file():
        try:
            text = installer.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ValueError("cannot inspect runtime feature dependencies") from exc
        if re.search(r"\b(?:from|import)\s+agentlas_cloud\.feature_preferences\b", text):
            return True
    return False


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
        Path("career_graph") / "__init__.py",
        Path("career_graph") / "runtime.py",
        Path("ontology") / "__init__.py",
        Path("ontology") / "model_assets.py",
        Path("templates") / "agentlas.json.tpl",
        Path("contracts") / "builder-interview-research-gate.md",
        Path("scripts") / "install-memory-hooks.py",
    ):
        if not (runtime_root / relative).is_file():
            missing.append(str(relative))
    feature_module = runtime_root / "agentlas_cloud" / "feature_preferences.py"
    if not feature_module.is_file() and _requires_feature_preferences(runtime_root):
        missing.append("agentlas_cloud/feature_preferences.py")
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
            **no_console_window(),
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


_IO_REPARSE_TAG_MOUNT_POINT = 0xA0000003


def _is_junction(path: Path) -> bool:
    """A Windows directory junction (always False elsewhere).

    Path.is_symlink() is False for a junction and shutil.rmtree() refuses one, so every
    place that handles `runtime/current` as a link must also ask this.
    """
    if os.name != "nt":
        return False
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None:
        return bool(isjunction(path))
    try:
        metadata = os.lstat(path)
    except (OSError, ValueError):
        return False
    return getattr(metadata, "st_reparse_tag", 0) == _IO_REPARSE_TAG_MOUNT_POINT


def _is_generation_dir(selected: Path, base: Path) -> bool:
    """A runtime generation is a direct child of the base, or of its `.generations` folder.

    The shell installer promotes every runtime into `<base>/.generations/<version>.<random>`
    and points `current` there; the updaters create `<base>/<version>`. Both are owned layouts.
    """
    parent = selected.parent
    return parent == base or (parent.name == ".generations" and parent.parent == base)


def _is_link(path: Path) -> bool:
    return path.is_symlink() or _is_junction(path)


def _create_junction(target: Path, link: Path) -> None:
    import _winapi  # noqa: PLC0415 - Windows only

    _winapi.CreateJunction(os.path.abspath(str(target)), os.path.abspath(str(link)))


def _path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink() or _is_junction(path)


def _remove_path(path: Path) -> None:
    if not _path_present(path):
        return
    if _is_junction(path):
        # Removes the junction itself; the generation it points at is untouched.
        os.rmdir(path)
    elif path.is_symlink() or not path.is_dir():
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
    # 옛 세대는 여기서 지우지 않는다 — install_latest_runtime 이 잠금을 놓은 뒤
    # _prune_runtime_homes 로 거둔다(호스트 설정·실행 중 프로세스가 쓰는 세대는 그쪽이 지킨다).


def _runtime_homes_kept() -> int:
    raw = os.environ.get("AGENTLAS_RUNTIME_KEEP", "").strip()
    return int(raw) if raw.isdigit() and int(raw) >= 1 else 2


# 런타임 경로를 `current` 를 거치지 않고 직접 적을 수 있는 호스트 설정 파일.
# 여기에 적힌 세대는 아직 살아 있다(예: Claude 마켓플레이스 원본 경로).
RUNTIME_REFERENCE_FILES = (
    ".claude.json",
    ".claude/settings.json",
    ".claude/plugins/known_marketplaces.json",
    ".codex/config.toml",
    ".gemini/settings.json",
    ".gemini/antigravity/mcp_config.json",
    ".cursor/mcp.json",
    ".config/opencode/opencode.json",
)


def _runtime_reference_text() -> str:
    home = Path.home()
    chunks = []
    for name in RUNTIME_REFERENCE_FILES:
        try:
            with open(home / name, encoding="utf-8", errors="replace") as handle:
                chunks.append(handle.read(4 * 1024 * 1024))
        except OSError:
            continue
    return "\n".join(chunks)


_holder_skip_reason = ""


def _runtime_holder_text() -> str | None:
    """실행 중인 프로세스의 명령줄·작업 폴더·열린 파일 경로. 알 수 없으면 None.

    파이썬 서버는 모듈을 읽고 파일을 닫으므로 열린 파일만으로는 부족하다 — 명령줄과
    환경 인자에 세대 경로가 남는다(실측 2026-10-16: 옛 세대 1.2.59 를 명령줄 10개가 가리킴).
    """
    global _holder_skip_reason
    _holder_skip_reason = ""
    if os.name == "nt":
        return None
    texts = []
    try:
        texts.append(subprocess.run(["ps", "-axww", "-o", "command="], capture_output=True, text=True,
                                    errors="replace", timeout=20, check=True, **no_console_window()).stdout)
    except subprocess.CalledProcessError as exc:
        _holder_skip_reason = f"ps exit {exc.returncode}"
        return None
    except (OSError, subprocess.SubprocessError):
        _holder_skip_reason = "ps failed"
        return None
    # lsof 가 없거나 비정상 종료하면 열린 파일·작업 폴더를 알 수 없다 — ps 의 명령줄만으로는
    # 작업 폴더로만 세대를 쓰는 프로세스를 못 본다(재현: 그런 세대가 지워짐). 모르면 None.
    lsof = shutil.which("lsof")
    if not lsof:
        _holder_skip_reason = "lsof missing"
        return None
    try:
        done = subprocess.run([lsof, "-w", "-u", str(os.getuid()), "-Fn"], capture_output=True,
                              text=True, errors="replace", timeout=60, **no_console_window())
    except (OSError, subprocess.SubprocessError):
        _holder_skip_reason = "lsof failed"
        return None
    if done.returncode != 0:
        _holder_skip_reason = f"lsof exit {done.returncode}"
        return None
    texts.append(done.stdout)
    return "\n".join(texts)


def _mentions(text: str, path: Path) -> bool:
    # 호스트 설정은 경로를 이스케이프해 적는다 — JSON·TOML 기본 문자열은 `C:\\Users\\…`(비ASCII는
    # \uXXXX 일 수도 있다), 일부는 `C:/Users/…`. Windows 에서는 이것만이 세대를 지키므로(holders 가
    # 늘 None) 원형만 찾으면 아직 쓰는 세대를 지운다. Windows 경로는 대소문자를 가리지 않는다.
    # 상위 폴더가 심볼릭 링크일 때(macOS /var → /private/var 등) ps·lsof 는 실경로를 적을 수 있다.
    forms: set[str] = set()
    for raw in {str(path), os.path.realpath(path)}:
        forms |= {raw, raw.replace("\\", "/"), json.dumps(raw)[1:-1], json.dumps(raw, ensure_ascii=False)[1:-1]}
    needle = "|".join(re.escape(form) for form in sorted(forms, key=len, reverse=True))
    flags = re.MULTILINE | (re.IGNORECASE if os.name == "nt" else 0)
    return re.search(f"(?:{needle})" + r"(?=[/\\\s\"',;:)]|$)", text, flags) is not None


def _runtime_release(entry: Path) -> str:
    try:
        release = (entry / "RELEASE").read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        release = ""
    name = entry.name.rsplit(".", 1)[0] if entry.parent.name == ".generations" else entry.name
    return release.lstrip("v") or name


# 방금 만들어졌거나 만들어지는 중인 세대를 건드리지 않는 시간. 셸 설치기는 .update.lock 을
# 잡지 않으므로(같은 버전 재설치는 .generations 에 새 세대를 놓고 current 를 나중에 바꾼다)
# 정리가 그 사이에 끼어들면 새 세대를 지우고 current 가 사라진 폴더를 가리킨다.
_PRUNE_RECENT_SECONDS = 15 * 60
# 한 번에 지우는 세대 수 상한. 세대가 많이 쌓인 머신의 첫 실행이 업데이트를 오래 붙잡지 않게
# 하고, 나머지는 다음 갱신에서 거둔다.
_PRUNE_MAX_PER_RUN = 5
_PRUNE_TRASH_RE = re.compile(r"^\..+\.prune\.\d+\.\d+$")


def _release_key(release: str) -> tuple[int, ...]:
    """`v1.2.85`·`1.2.85-rc1` → (1, 2, 85). 읽을 수 없으면 ()(가장 낮음)."""
    head = re.split(r"[-+]", release.lstrip("v"), maxsplit=1)[0]
    return tuple(int(part) for part in re.findall(r"\d+", head))


def _entry_is_recent(entry: Path, now: float) -> bool:
    """세대가 최근 15분 안에 만들어졌거나 바뀌었는가. 시각을 읽지 못하면 최근으로 본다."""
    stamps = []
    try:
        stamps.append(entry.lstat().st_mtime)
        try:  # 설치기가 포인터를 바꾸기 직전에 만드는 `<세대>.current` 링크
            stamps.append(entry.with_name(entry.name + ".current").lstat().st_mtime)
        except FileNotFoundError:
            pass
    except OSError:
        return True
    return any(abs(now - stamp) < _PRUNE_RECENT_SECONDS for stamp in stamps)


def _discard_generation(entry: Path) -> None:
    """이름을 점으로 시작하는 형제로 먼저 바꾼 뒤 지운다.

    지우는 도중 끊겨도 반쯤 지워진 폴더가 RELEASE 를 가진 채 유효한 세대로 보이지 않는다.
    Windows 는 열린 파일이 있으면 이름을 바꿀 수 없다 — 바뀌면 아무도 쓰지 않는 것이다.
    """
    moved = _unique_sibling(entry, "prune")
    os.rename(entry, moved)
    _remove_path(moved)


def _prune_runtime_homes(runtime_root: Path) -> None:
    """옛 런타임 홈 버전을 거둔다 (PRD §4.22).

    버전별 디렉터리에 설치하고 링크만 바꾸는데 정리 코드가 없어 무한히 커졌다
    (실측 2026-08-23: 124개 9.1GB). 설치기가 `.generations/<버전>.<임의>` 에 설치하게 바뀐 뒤로는
    이 함수가 숨김 폴더를 건너뛰어 세대가 다시 쌓였다(실측 2026-10-16: 10세대 1.6GB).
    남기는 것: `current` 가 가리키는 것, 호스트 설정이 경로로 직접 적은 것, 실행 중인 프로세스가
    쓰는 것, 그리고 현재와 다른 릴리스 중 최신 `AGENTLAS_RUNTIME_KEEP - 1`(기본 1)개(되돌리기용).
    같은 릴리스를 다시 설치해 생긴 세대는 되돌리기 가치가 없어 남기지 않는다.
    사용 여부를 확인할 수 없는 POSIX 머신에서는 지우지 않는다.
    설치기(scripts/install-all-runtimes.sh prune_runtime_homes)는 이 함수를 그대로 부른다 —
    한쪽에만 두면 다른 경로로 갱신한 머신은 계속 쌓인다.
    """
    try:
        if (runtime_root / ".update.lock").exists():
            return  # 다른 업데이트가 설치 중이다 — 다음 갱신에서 거둔다.
        current = runtime_root / "current"
        active = Path(os.path.realpath(current)) if _is_link(current) else None
        generations = runtime_root / ".generations"

        def real_dirs(parent: Path) -> list[Path]:
            return [entry for entry in parent.iterdir() if entry.is_dir() and not entry.is_symlink()]

        top = real_dirs(runtime_root)
        gens = real_dirs(generations) if generations.is_dir() and not generations.is_symlink() else []
        # 지우다 끊긴 찌꺼기(`.이름.prune.PID.NS`). 유효한 세대가 아니므로 슬롯 없이 지운다.
        trash = [entry for entry in top + gens if _PRUNE_TRASH_RE.match(entry.name)]
        candidates = [entry for entry in top + gens if not entry.name.startswith(".") and entry.name != "current"]
        candidates = [entry for entry in candidates if active is None or Path(os.path.realpath(entry)) != active]
        mtimes = {entry: entry.stat().st_mtime for entry in candidates}
    except OSError:
        return
    if not candidates and not trash:
        return
    references = _runtime_reference_text()
    holders = _runtime_holder_text()
    if os.name != "nt" and holders is None:
        # 실행 중인 프로세스를 확인할 수 없다(ps·lsof 없음/실패) — 이번에는 아무것도 지우지 않는다.
        print(f"agentlas: runtime prune skipped: {_holder_skip_reason or 'process list unavailable'}", file=sys.stderr)
        return
    current_release = _runtime_release(active) if active is not None else ""
    current_key = _release_key(current_release) if active is not None else None
    # 되돌리기 후보는 디렉터리 mtime 이 아니라 릴리스 번호 순이다(파일 하나 만진 옛 세대가 이기면 안 된다).
    candidates.sort(key=lambda entry: (_release_key(_runtime_release(entry)), mtimes[entry]), reverse=True)
    kept_releases = {current_release} if active is not None else set()
    rollbacks = max(0, _runtime_homes_kept() - 1)  # current 를 포함해 AGENTLAS_RUNTIME_KEEP 개
    # 수동 롤백으로 current 가 최고 릴리스가 아닐 때, 방금 되돌아온 원본(current 보다 높은 것 중 최고)은 남긴다.
    keep_newer = active is not None
    removed = 0

    def safe_to_delete(entry: Path, check_recent: bool) -> bool:
        # current 가 링크인지 여부는 처음 읽었을 때와 같아야 한다(다르면 누가 바꾸는 중이다).
        # 삭제 직전에 다시 읽는다: 그 사이 current 가 이 세대로 바뀌었거나(셸 설치기는 잠금이 없다)
        # 방금 만들어진 세대일 수 있다.
        if (active is None) == _is_link(current):
            return False
        if active is not None and Path(os.path.realpath(entry)) == Path(os.path.realpath(current)):
            return False
        return not (check_recent and _entry_is_recent(entry, time.time()))

    for entry in [*trash, *candidates]:
        is_trash = entry in trash
        if removed >= _PRUNE_MAX_PER_RUN:
            continue
        if _mentions(references, entry) or (holders is not None and _mentions(holders, entry)):
            continue
        if not is_trash:
            release = _runtime_release(entry)
            # RELEASE 가 없는 세대는 설치가 끝나지 않은 것이다 — 되돌릴 수 없으니 슬롯을 차지하지 못한다.
            complete = (entry / "RELEASE").is_file()
            key = _release_key(release)
            if complete and keep_newer and current_key is not None and key > current_key and release not in kept_releases:
                keep_newer = False  # 후보는 릴리스 번호 내림차순이라 첫 번째가 가장 높다
                kept_releases.add(release)
                continue
            below_current = current_key is None or key < current_key
            if complete and below_current and rollbacks > 0 and release not in kept_releases:
                kept_releases.add(release)
                rollbacks -= 1
                continue
        if not safe_to_delete(entry, check_recent=not is_trash):
            continue
        try:
            _discard_generation(entry)
        except OSError:
            # 지우지 못한 것은 다음 갱신에서 다시 시도한다 — 실패가 업데이트를 막지 않는다.
            continue
        removed += 1
        sibling = entry.with_name(entry.name + ".current")
        if sibling.is_symlink() and not sibling.exists():
            try:
                sibling.unlink()  # 지운 세대를 가리키던 설치기의 포인터 링크
            except OSError:
                pass
    if removed:
        print(f"agentlas: pruned {removed} old runtime generation(s) from {runtime_root}", file=sys.stderr)


def _point_current_at(target: Path) -> dict[str, str]:
    current = target.parent / "current"
    replacement = _unique_sibling(current, "next")
    try:
        replacement.symlink_to(target, target_is_directory=True)
    except OSError:
        _remove_path(replacement)
        linked = False
        if os.name == "nt":
            # Ordinary Windows (no Developer Mode, not elevated) refuses symlinks with
            # WinError 1314. A copy made `current` a second tree: Desktop's realpath pin then
            # pinned the copy, the next update replaced it wholesale, and an engine server
            # already running from it imported new-version files lazily into old-version
            # modules. A junction needs no privilege and resolves to the generation itself
            # (the same choice as Desktop's config-home-mirror).
            try:
                _create_junction(target, replacement)
                linked = True
            except (ImportError, AttributeError, OSError):
                _remove_path(replacement)
        if not linked:
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
    if os.name == "nt":
        # os.kill(pid, 0) is not a probe on Windows (it sends CTRL_C_EVENT and raises
        # WinError 87 for a live pid, which read as "alive" here, so a crashed update kept
        # the lock for LOCK_STALE_SECONDS). Ask the kernel; unknown stays "running".
        from .process_liveness import pid_alive

        return pid_alive(pid) is not False
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
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | _O_BINARY, 0o600)
        except FileExistsError as exc:
            if _remove_stale_lock(path):
                continue
            raise RuntimeError(f"update already running: {path}") from exc
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
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


_LOCAL_DIAGNOSTIC_SHA256 = "5e3076ccfcac7bfd927e7af38bfe1832ef5d7776f447381eeca7a164e4add2b3"
_LOCAL_DIAGNOSTIC_PATH = Path("agentlas_cloud") / "networking" / "bench.py"
_LOCAL_DIAGNOSTIC_RECEIPT = ".local-diagnostic-preservation-v1.json"


def _local_diagnostic_failure(runtime_root: Path) -> str | None:
    """Return a bounded preservation failure recorded by the updater."""
    root = runtime_root.resolve()
    path = root / _LOCAL_DIAGNOSTIC_RECEIPT
    if _is_link(path):
        return None
    receipt = _read_json(path)
    if (receipt.get("schemaVersion") != "agentlas.local-diagnostic-preservation.v1"
            or receipt.get("release") != current_release(root)
            or receipt.get("status") != "not_preserved"):
        return None
    reason = receipt.get("reason")
    return reason if reason in {"source_unverified", "copy_failed"} else None


def _verified_local_diagnostic(runtime_root: Path) -> bytes | None:
    """Read an unchanged, already-installed diagnostic without shipping it."""
    try:
        root = runtime_root.resolve(strict=True)
        path = root / _LOCAL_DIAGNOSTIC_PATH
        if _has_symlink_in_path(path, root) or not path.is_file():
            return None
        release = current_release(root)
        if release not in _LEGACY_BASELINE_SHA256 and release != "v1.2.89":
            receipt_path = root / _LOCAL_DIAGNOSTIC_RECEIPT
            if (_is_link(receipt_path) or _read_json(receipt_path) != {
                    "schemaVersion": "agentlas.local-diagnostic-preservation.v1",
                    "release": release, "sha256": _LOCAL_DIAGNOSTIC_SHA256,
                    "status": "preserved"}):
                return None
        with path.open("rb") as source:
            data = source.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024 or hashlib.sha256(data).hexdigest() != _LOCAL_DIAGNOSTIC_SHA256:
            return None
        return data
    except (OSError, ValueError):
        return None


def _preserve_local_diagnostic() -> None:
    """Preserve a verified installed file inside an updater-owned staging root."""
    requested = os.environ.get("HEPHAESTUS_HEALTHCHECK_ROOT")
    if not requested:
        return
    root = Path(requested).resolve()
    if root != Path(__file__).resolve().parent.parent:
        return
    match = re.fullmatch(r"\.(\d+\.\d+\.\d+)\.staged\.(\d+)\.(\d+)", root.name)
    if not match or int(match.group(2)) != os.getppid():
        return
    base = root.parent
    lock = base / ".update.lock"
    if lock.is_symlink() or not lock.is_file():
        return
    lock_data = _read_json(lock)
    token = lock_data.get("token")
    if lock_data.get("pid") != os.getppid() or not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token):
        return
    if _path_present(root / _LOCAL_DIAGNOSTIC_RECEIPT):
        return
    current = base / "current"
    if not current.is_dir():
        return
    active = current.resolve()
    if not _is_generation_dir(active, base.resolve()) or not _is_comparable_release(current_release(current)):
        return
    data = _verified_local_diagnostic(active)
    if data is None:
        # Preserve modified or linked source files in place and explain why
        # the optional command cannot be carried into the new generation.
        previous_failure = _local_diagnostic_failure(active)
        if _path_present(active / _LOCAL_DIAGNOSTIC_PATH) or previous_failure:
            try:
                _write_json(root / _LOCAL_DIAGNOSTIC_RECEIPT, {
                    "schemaVersion": "agentlas.local-diagnostic-preservation.v1",
                    "release": "v" + match.group(1), "status": "not_preserved",
                    "reason": previous_failure or "source_unverified",
                })
            except OSError:
                pass
        return
    target = root / _LOCAL_DIAGNOSTIC_PATH
    if _has_symlink_in_path(target.parent, root) or not target.parent.is_dir() or _path_present(target):
        return
    # The staged directory is owned by this updater.  Exclusive creation avoids
    # replacing a pre-existing or concurrently created file.
    identity: tuple[int, int] | None = None
    written = False
    try:
        with target.open("xb") as output:
            stat = os.fstat(output.fileno())
            identity = (stat.st_dev, stat.st_ino)
            if output.write(data) != len(data):
                raise OSError("local_diagnostic_short_write")
        written = True
        _write_json(root / _LOCAL_DIAGNOSTIC_RECEIPT, {
            "schemaVersion": "agentlas.local-diagnostic-preservation.v1",
            "release": "v" + match.group(1), "sha256": _LOCAL_DIAGNOSTIC_SHA256,
            "status": "preserved",
        })
    except OSError:
        # This locally preserved optional file must not prevent a core update.
        # Remove only an incomplete file created by this invocation, and only
        # if it is still the same inode (never replace or delete user files).
        if not written and identity is not None:
            try:
                stat = target.lstat()
                if (stat.st_dev, stat.st_ino) == identity and not _is_link(target):
                    target.unlink()
            except OSError:
                pass
        try:
            _write_json(root / _LOCAL_DIAGNOSTIC_RECEIPT, {
                "schemaVersion": "agentlas.local-diagnostic-preservation.v1",
                "release": "v" + match.group(1), "status": "not_preserved",
                "reason": "copy_failed",
            })
        except OSError:
            pass
        return
    if current.resolve() != active or _read_json(lock).get("token") != token:
        raise RuntimeError("local_diagnostic_update_context_changed")


_legacy_staged_baseline()
_preserve_local_diagnostic()


def _main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) == 2 and args[0] == "--standalone-install":
        tag = args[1]
        if not re.fullmatch(r"os-v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag):
            print(json.dumps({"status": "blocked", "error": "standalone_channel_tag_invalid"}))
            return 2
        try:
            url = "https://api.github.com/repos/agentlas-ai/Agentlas-OS/releases/tags/" + tag
            release, _ = _standalone_json(url)
            if not isinstance(release, dict):
                raise ValueError("standalone_release_mismatch")
            release = _standalone_tag_metadata(tag, release)
            print(json.dumps(install_latest_runtime(release), ensure_ascii=False))
            return 0
        except (OSError, ValueError, RuntimeError, tarfile.TarError) as exc:
            print(json.dumps({"status": "blocked", "error": str(exc)[:300]}, ensure_ascii=False))
            return 2
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
