"""Explicit day-lease bridge; the authenticated web service owns every debit."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from ..auth import AgentlasAuthError
from .hub_client import HubToolError, call_hub_tool

QUOTE = "hephaestus.quote_agent_lease"
PURCHASE = "hephaestus.purchase_agent_lease"
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_RETRY_KEY = re.compile(r"[\x21-\x7e]{1,128}\Z")
_UNCERTAIN_BILLING = frozenset({
    "source_unavailable", "source_timeout", "lease_commit_unknown", "lease_recovery_incomplete",
})


def _refuse(code: str) -> dict[str, Any]:
    return {"status": "rejected", "error": code, "purchaseDispatched": False}


def _integer(value: Any, minimum: int, maximum: int) -> bool:
    return type(value) is int and minimum <= value <= maximum


def _remote_failure(code: str, confirmed: bool) -> dict[str, Any]:
    unknown = confirmed and code in _UNCERTAIN_BILLING
    return {"status": "blocked" if unknown else "rejected", "error": code,
            "purchaseDispatched": confirmed, "retryWithSameIdempotencyKey": unknown,
            **({"billingOutcome": "unknown"} if unknown else {})}


def call_agent_lease_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Validate explicit purchase intent before authentication or transport.

    No day count, price, approval, or retry identity is invented here. A lost
    response is retried by the caller with the same idempotency key; Core does
    not retry network errors or turn a purchase into an ordinary paid borrow.
    """
    if name not in {QUOTE, PURCHASE}:
        return _refuse("unknown_lease_tool")
    allowed = {"slug", "days"} if name == QUOTE else {
        "slug", "days", "confirm", "confirmationToken", "expectedPerDayCredits",
        "expectedTotalCredits", "idempotencyKey",
    }
    if not isinstance(arguments, dict) or set(arguments) - allowed:
        return _refuse("invalid_lease_arguments")
    slug = arguments.get("slug")
    if not isinstance(slug, str):
        return _refuse("invalid_slug")
    slug = unicodedata.normalize("NFKC", slug).strip().lower()
    if not slug:
        return _refuse("invalid_slug")
    days = arguments.get("days")
    if (name == PURCHASE or "days" in arguments) and not _integer(days, 1, 30):
        return _refuse("invalid_lease_days")
    if "confirm" in arguments and type(arguments["confirm"]) is not bool:
        return _refuse("invalid_lease_confirmation")
    for field, maximum in (("confirmationToken", 8192),):
        if field in arguments and (
            not isinstance(arguments[field], str)
            or not arguments[field].strip()
            or len(arguments[field]) > maximum
        ):
            return _refuse("invalid_lease_" + field)
    if "idempotencyKey" in arguments and (
        not isinstance(arguments["idempotencyKey"], str)
        or not _RETRY_KEY.fullmatch(arguments["idempotencyKey"].strip())
    ):
        return _refuse("invalid_idempotency_key")
    for field in ("expectedPerDayCredits", "expectedTotalCredits"):
        if field in arguments and not _integer(arguments[field], 0, _MAX_SAFE_INTEGER):
            return _refuse("invalid_lease_price")
    confirmed = name == PURCHASE and arguments.get("confirm") is True
    if confirmed:
        for field in ("confirmationToken", "expectedPerDayCredits", "expectedTotalCredits", "idempotencyKey"):
            if field not in arguments:
                return _refuse("lease_" + field + "_required")
        if arguments["expectedPerDayCredits"] * days != arguments["expectedTotalCredits"]:
            return _refuse("invalid_lease_total")
    payload = dict(arguments)
    payload["slug"] = slug
    if "idempotencyKey" in payload:
        payload["idempotencyKey"] = payload["idempotencyKey"].strip()
    if name == PURCHASE:
        payload["confirm"] = confirmed
    try:
        result = call_hub_tool(name, payload, endpoint_path="/api/mcp/hephaestus-network")
    except AgentlasAuthError:
        # OAuth error descriptions can contain private provider response text.
        return _refuse("source_unauthorized")
    except HubToolError as exc:
        # The remote purchase may have committed before a response was lost.
        # Do not claim that no debit happened or mint a new retry identity.
        return _remote_failure(exc.code, confirmed)
    if isinstance(result.get("error"), str):
        return {**result, **_remote_failure(result["error"], confirmed)}
    return result


LEASE_TOOLS: list[dict[str, Any]] = [
    {
        "name": QUOTE,
        "description": "Quote a public Hub agent's explicit 1-30 day lease without spending credits. Omit days to read the daily price. A lease is not offered when the creator has no daily price. The web service is the price and account authority.",
        "inputSchema": {"type": "object", "additionalProperties": False, "required": ["slug"],
                        "properties": {"slug": {"type": "string"}, "days": {"type": "integer", "minimum": 1, "maximum": 30}}},
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
    },
    {
        "name": PURCHASE,
        "description": "Buy a day-based Hub agent lease only after the user approves the displayed day count and total. Omitted or false confirm returns a quote only. For confirm:true, preserve its confirmationToken and exact expected prices, and provide a stable idempotencyKey reused after every uncertain response. Never choose days, infer approval, or silently borrow instead. This tool can spend credits.",
        "inputSchema": {"type": "object", "additionalProperties": False, "required": ["slug", "days"], "properties": {
            "slug": {"type": "string"}, "days": {"type": "integer", "minimum": 1, "maximum": 30},
            "confirm": {"type": "boolean"}, "confirmationToken": {"type": "string", "minLength": 1, "maxLength": 8192},
            "expectedPerDayCredits": {"type": "integer", "minimum": 0, "maximum": _MAX_SAFE_INTEGER},
            "expectedTotalCredits": {"type": "integer", "minimum": 0, "maximum": _MAX_SAFE_INTEGER},
            "idempotencyKey": {"type": "string", "minLength": 1, "maxLength": 128,
                               "pattern": "^[!-~]+$"},
        }},
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
    },
]
