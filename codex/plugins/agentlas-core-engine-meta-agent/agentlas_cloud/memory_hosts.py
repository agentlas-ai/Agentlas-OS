"""One table for every host the Agentlas memory hook speaks to.

The same host list used to live in four hand lists: the hook's argparse
choices, its empty-output set, and its output-format if-chain in
``agentlas_cloud/memory_hook.py``, plus the installer's ``SUPPORTED_HOSTS``,
detection if-chain, and installer dispatch in
``scripts/install-memory-hooks.py``. Adding a host meant finding all of them,
and missing one produced a host that could be selected but not answered, or
installed but never auto-detected. This table is now the only place a host is
described; both consumers derive their lists from it.

``contracts/runtime-registry.json`` (read by ``runtime_registry.py``) stays
the canonical registry for onboarding data — instruction file, hook file and
shape, ACP spawn. It does not carry the memory hook's *process contract*
(what the hook prints back to which host), and the hook must stay fail-open
and cheap on every prompt, so this stays a plain in-code table instead of a
JSON load. Host ids here are the hook's own ``--host`` tokens ("claude", not
the registry row id "claude-code"); ``raw`` is the debug/passthrough host and
exists only here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MemoryHookHost:
    id: str
    # What the hook process prints when it has nothing to inject. Hosts that
    # parse hook stdout as JSON need "{}"; the rest accept an empty string.
    empty_output: str
    # Which envelope carries a non-empty capsule back to the host:
    #   hook-specific-output  Claude/Codex settings-hook JSON
    #   inject-steps          Antigravity ephemeral-message JSON
    #   cache-file            written to the workspace cache; stdout stays empty
    #   plain                 capsule verbatim (OpenCode plugin, raw/debug)
    capsule_style: str
    # True when scripts/install-memory-hooks.py owns this host's hook assets.
    # Claude/Codex hooks arrive through the plugin channel, not that script.
    installable: bool = False
    # Detection inputs for the installer's `--hosts auto` mode. A host is
    # detected when ANY env var is set, ANY binary is on PATH, or ANY
    # home-relative directory exists.
    detect_env: tuple[str, ...] = ()
    detect_binaries: tuple[str, ...] = ()
    detect_dirs: tuple[str, ...] = ()


MEMORY_HOOK_HOSTS: tuple[MemoryHookHost, ...] = (
    MemoryHookHost("claude", "{}", "hook-specific-output"),
    MemoryHookHost("codex", "{}", "hook-specific-output"),
    MemoryHookHost(
        "antigravity",
        "{}",
        "inject-steps",
        installable=True,
        detect_env=("HEPHAESTUS_FORCE_ANTIGRAVITY",),
        detect_dirs=(
            ".gemini/antigravity",
            ".gemini/antigravity-ide",
            ".gemini/antigravity-cli",
        ),
    ),
    MemoryHookHost(
        "grok",
        "{}",
        "cache-file",
        installable=True,
        detect_binaries=("grok",),
        detect_dirs=(".grok",),
    ),
    MemoryHookHost(
        "opencode",
        "",
        "plain",
        installable=True,
        detect_binaries=("opencode",),
        detect_dirs=(".config/opencode",),
    ),
    MemoryHookHost("raw", "", "plain"),
)

# Order matters twice: argparse renders choices in this order, and the
# installer's auto-detection reports hosts in table order.
HOST_CHOICES: tuple[str, ...] = tuple(spec.id for spec in MEMORY_HOOK_HOSTS)
INSTALLABLE_HOSTS: tuple[str, ...] = tuple(spec.id for spec in MEMORY_HOOK_HOSTS if spec.installable)

_BY_ID: dict[str, MemoryHookHost] = {spec.id: spec for spec in MEMORY_HOOK_HOSTS}
_RAW = _BY_ID["raw"]


def host_spec(host: str) -> MemoryHookHost:
    """Spec for ``host``; unknown hosts get the fail-open raw contract."""

    return _BY_ID.get(host, _RAW)
