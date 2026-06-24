"""Optional Playwright MCP snapshot hardpoint."""

from __future__ import annotations

from ..contracts import ResearchModuleManifest
from ..policy import DEFAULT_MAX_BYTES
from .command_snapshot import CommandSnapshotAdapter


class PlaywrightMcpAdapter(CommandSnapshotAdapter):
    module_id = "browser.playwright_mcp"
    capabilities = ("browser.snapshot", "browser.accessibility_tree", "read.url")
    weight = "browser_heavy"
    env_var = "AGENTLAS_PLAYWRIGHT_MCP_SNAPSHOT_CMD"
    command_label = "playwright_mcp_snapshot"
    output_fields = ("content_markdown", "snapshot", "text", "stdout")
    base_limits = ("browser_snapshot", "playwright_mcp_snapshot", "accessibility_snapshot")
    missing_reason = "AGENTLAS_PLAYWRIGHT_MCP_SNAPSHOT_CMD not configured"
    manifest = ResearchModuleManifest(
        module_id=module_id,
        capabilities=list(capabilities),
        weight=weight,
        slot="browser",
        activation="configured",
        requires=["command:playwright-mcp-snapshot"],
        permissions=["local_process:playwright_mcp_snapshot", "network:http", "network:https", "browser:isolated_session"],
        default_state="available_if_configured",
        privacy="snapshot_command_receives_requested_url; no_raw_token_to_model",
        failure_modes=["module_unavailable", "browser_error", "ssrf_blocked", "timeout", "empty_snapshot"],
        install_hint=(
            "Set AGENTLAS_PLAYWRIGHT_MCP_SNAPSHOT_CMD to a local snapshot command. "
            "Use {url} as a placeholder or the URL is appended as the final argument."
        ),
    )

    def __init__(self, *, timeout_seconds: int = 60, max_bytes: int = DEFAULT_MAX_BYTES):
        super().__init__(timeout_seconds=timeout_seconds, max_bytes=max_bytes)
