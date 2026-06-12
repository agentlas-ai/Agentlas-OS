"""Small JSON-RPC client for the public Agentlas Hub MCP endpoint."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .bootstrap import networking_home, read_json

_HUB_TIMEOUT_SECONDS = 15


class HubToolError(RuntimeError):
    """Raised when the Hub MCP endpoint returns a protocol or tool error."""


def hub_url(home: Path | str | None = None) -> str:
    base = Path(home) if home else networking_home()
    config = read_json(base / "config.json", default={}) or {}
    return str(config.get("hub_url") or "https://agentlas.cloud").rstrip("/")


def call_hub_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    home: Path | str | None = None,
    timeout: int = _HUB_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Call an Agentlas Hub MCP tool and return its parsed JSON payload."""

    url = hub_url(home) + "/api/mcp/v1"
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "hephaestus-network-hub-invoke",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise HubToolError(f"hub tool {name} failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise HubToolError(f"hub tool {name} returned a non-object response")
    if payload.get("error"):
        raise HubToolError(f"hub tool {name} error: {payload['error']}")

    result = payload.get("result")
    if not isinstance(result, dict):
        raise HubToolError(f"hub tool {name} returned no result object")
    if result.get("isError"):
        text = _first_text(result)
        raise HubToolError(f"hub tool {name} error: {text or result}")

    text = _first_text(result)
    if text is not None:
        try:
            parsed = json.loads(text)
        except ValueError as exc:
            raise HubToolError(f"hub tool {name} returned non-JSON text") from exc
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    return result


def _first_text(result: dict[str, Any]) -> str | None:
    content = result.get("content")
    if not isinstance(content, list):
        return None
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            return str(item.get("text") or "")
    return None
