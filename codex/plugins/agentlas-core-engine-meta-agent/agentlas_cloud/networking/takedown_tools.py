"""Taking a published agent back down; the authenticated web service owns the act.

WHY THIS EXISTS
    Publishing is one command from inside your AI (`/hep-upload`). Taking the
    same agent down was not reachable from there at all — `cargo.delete_agent`
    exists on the web service and handles the hub-public case correctly, but
    the local Core never exposed it, so the only way to unlist something you
    had just listed was to know that agentlas.cloud/cargo has a button.
    Measured 2026-09-13: zero `cargo` tools on the local MCP surface, and
    nothing in the upload command said where to go instead.

    A surface that can publish and cannot unpublish is not a symmetric one, and
    the asymmetry lands on the person who most needs it — someone who just
    published something they did not mean to.

WHAT IT DOES NOT DO
    It does not delete anything irreversibly. For a hub-public package the web
    service soft-unpublishes it from Hub routing and retains the package bytes
    for audit and recovery; for an owner-private package it removes the stored
    bytes. That distinction belongs to the service and is echoed back in the
    response rather than restated here, where it could drift.

    Confirmation is required. `confirm` defaults to false and the tool then
    returns what WOULD happen, so a host cannot unlist a listing on a guess.
"""

from __future__ import annotations

import unicodedata
from typing import Any

from ..auth import AgentlasAuthError
from .hub_client import HubToolError, call_hub_tool

TAKEDOWN = "hephaestus.unpublish_agent"


def _refuse(code: str, **extra: Any) -> dict[str, Any]:
    return {"status": "rejected", "error": code, "unpublishDispatched": False, **extra}


def call_agent_takedown_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate explicit intent before authentication or transport.

    Nothing is inferred here: no slug is guessed, no confirmation is implied,
    and a lost response is never retried as a second takedown.
    """
    if name != TAKEDOWN:
        return _refuse("unknown_takedown_tool")
    allowed = {"slug", "confirm"}
    if not isinstance(arguments, dict) or set(arguments) - allowed:
        return _refuse("invalid_takedown_arguments")

    slug = arguments.get("slug")
    if not isinstance(slug, str):
        return _refuse("invalid_slug")
    slug = unicodedata.normalize("NFKC", slug).strip().lower()
    if not slug:
        return _refuse("invalid_slug")

    confirm = arguments.get("confirm")
    if confirm is not None and not isinstance(confirm, bool):
        return _refuse("invalid_takedown_confirmation")

    if confirm is not True:
        return {
            "status": "needs_confirmation",
            "action": "confirm_agent_unpublish",
            "slug": slug,
            "unpublishDispatched": False,
            "question": (
                f"Take {slug} down from the public Hub? Nobody will be able to find or "
                "call it afterwards. Answer yes or no."
            ),
            "note": (
                "A hub-public package is soft-unpublished from Hub routing and its bytes "
                "are retained for audit and recovery; an owner-private package has its "
                "stored bytes removed. Local installs are untouched either way."
            ),
            "retryWith": {"slug": slug, "confirm": True},
        }

    try:
        result = call_hub_tool("cargo.delete_agent", {"slug": slug})
    except AgentlasAuthError:
        # OAuth error descriptions can carry private provider response text.
        return _refuse("source_unauthorized")
    except HubToolError as exc:
        return _refuse(exc.code)

    if isinstance(result.get("error"), str):
        return {**result, **_refuse(result["error"])}
    return {"status": "unpublished", "slug": slug, "unpublishDispatched": True, **result}


TAKEDOWN_TOOLS: list[dict[str, Any]] = [
    {
        "name": TAKEDOWN,
        "description": (
            "Take one of YOUR OWN published agents back down from the public Agentlas Hub. "
            "Requires Agentlas OAuth sign-in and workspace write access. Omitted or false "
            "confirm returns what would happen and asks the user; only confirm:true acts. "
            "A hub-public package is soft-unpublished from Hub routing with its bytes retained "
            "for audit and recovery; an owner-private package has its stored bytes removed. "
            "Local installs are never touched. Refusals are exact and must be repeated as-is: "
            "owner_only (not your agent), agent_not_found, source_unauthorized."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["slug"],
            "properties": {
                "slug": {"type": "string", "description": "The slug of your own published agent."},
                "confirm": {
                    "type": "boolean",
                    "description": "Set true only after the user explicitly says to take it down.",
                },
            },
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
    },
]
