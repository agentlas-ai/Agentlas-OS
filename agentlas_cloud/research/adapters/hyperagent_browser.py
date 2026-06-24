"""Optional Hyperbrowser/HyperAgent snapshot hardpoint."""

from __future__ import annotations

from ..contracts import ResearchModuleManifest
from ..policy import DEFAULT_MAX_BYTES
from .command_snapshot import CommandSnapshotAdapter


class HyperAgentBrowserAdapter(CommandSnapshotAdapter):
    module_id = "browser.hyperagent"
    capabilities = ("browser.agent_task", "browser.snapshot", "browser.extract", "read.url")
    weight = "browser_heavy"
    env_var = "AGENTLAS_HYPERAGENT_SNAPSHOT_CMD"
    command_label = "hyperagent_snapshot"
    output_fields = ("content_markdown", "result", "extraction", "snapshot", "text", "stdout")
    base_limits = ("browser_snapshot", "hyperagent_snapshot", "agent_browser_task")
    missing_reason = "AGENTLAS_HYPERAGENT_SNAPSHOT_CMD not configured"
    manifest = ResearchModuleManifest(
        module_id=module_id,
        capabilities=list(capabilities),
        weight=weight,
        slot="browser",
        activation="configured",
        requires=["command:hyperagent-snapshot"],
        permissions=["local_process:hyperagent_snapshot", "network:http", "network:https", "browser:local_or_cloud_session"],
        default_state="available_if_configured",
        privacy="snapshot_command_receives_requested_url; provider_tokens_stay_outside_engine",
        failure_modes=["module_unavailable", "browser_error", "ssrf_blocked", "timeout", "empty_snapshot"],
        install_hint=(
            "Set AGENTLAS_HYPERAGENT_SNAPSHOT_CMD to a local HyperAgent or Hyperbrowser-backed snapshot command. "
            "Use {url} as a placeholder or the URL is appended as the final argument."
        ),
    )

    def __init__(self, *, timeout_seconds: int = 120, max_bytes: int = DEFAULT_MAX_BYTES):
        super().__init__(timeout_seconds=timeout_seconds, max_bytes=max_bytes)
