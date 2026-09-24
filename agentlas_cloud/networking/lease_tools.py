"""Retired Hub day-lease tool names, kept only to reject stale host calls.

Creator-priced Hub rentals and settlement were permanently closed when the
public Hub became a free agent community. Never dispatch a quote or purchase
request to a server that may still expose the legacy billing endpoint.
"""

from __future__ import annotations

from typing import Any

QUOTE = "hephaestus.quote_agent_lease"
PURCHASE = "hephaestus.purchase_agent_lease"
LEASE_TOOLS: list[dict[str, Any]] = []


def call_agent_lease_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "rejected",
        "error": "hub_commerce_closed" if name in {QUOTE, PURCHASE} else "unknown_lease_tool",
        "purchaseDispatched": False,
    }
