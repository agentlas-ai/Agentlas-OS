"""A way out for a Cloud or Hub agent that cannot be called.

A remote source refuses with a closed code (``source_unauthorized``,
``no_cloud_package`` …). The host used to receive that token and nothing to do
about it. This table gives each code the same machine-readable shape the local
repair plan has (``release_health``): what is wrong, and the ordered actions a
host can take. It decides nothing and never substitutes an agent; the host
chooses, and another agent always needs a new selection.

Actions:

- ``login``: the account is not signed in or the token expired.
- ``retry``: a transient failure; try the same selection again after the delay.
- ``wait``: the source is rate limiting or its circuit is open; do not hammer it.
- ``reselect``: this listing cannot serve the request; choose another candidate
  (``alternates`` carries some when the Hub call returned them) or another source.
- ``republish``: only for the owner of the agent: the stored package is missing
  or unusable, upload it again with ``/hep-upload``.
- ``report``: the listing is inconsistent (hash or claim mismatch). Never run
  it; tell the user the Hub copy failed its own integrity check.
"""

from __future__ import annotations

from typing import Any

_LOGIN = {
    "action": "login",
    "available": True,
    "command": "hephaestus auth login",
    "effect": "opens the browser sign-in window; the same selection can be prepared again afterwards",
}
_RETRY = {
    "action": "retry",
    "available": True,
    "effect": "prepare the same selection again; nothing was executed",
}
_WAIT = {
    "action": "wait",
    "available": True,
    "effect": "the source is limiting or protecting itself; retry after the delay it names, or use another source",
}
_RESELECT = {
    "action": "reselect",
    "available": True,
    "effect": "choose another candidate or another source; a different agent always needs a new selection",
}
_REPUBLISH = {
    "action": "republish",
    "available": True,
    "command": "hep-upload <agent-folder> --visibility private-link",
    "effect": "owners only: upload the package again so the stored copy is complete",
}
_REPORT = {
    "action": "report",
    "available": True,
    "effect": "do not run this listing; say its copy failed an integrity check and offer another candidate",
}

_UPDATE = {
    "action": "update",
    "available": True,
    "command": "hephaestus update",
    "effect": "update the local runtime; an older runtime may not speak this source's current protocol",
}
_DOCTOR = {
    "action": "doctor",
    "available": True,
    "command": "hephaestus doctor",
    "effect": "diagnose and self-heal the local runtime and its source configuration",
}

# code -> (meaning, ordered actions)
_PLANS: dict[str, tuple[str, tuple[dict[str, Any], ...]]] = {
    "source_unauthorized": ("this machine is not signed in to Agentlas, or its sign-in expired", (_LOGIN, _RESELECT)),
    "source_forbidden": ("the signed-in account may not use this agent", (_RESELECT,)),
    "owner_only": ("this agent is private to another account", (_RESELECT,)),
    "insufficient_credits": ("the account cannot pay for this call", (_RESELECT,)),
    "agent_not_found": ("the listing no longer exists or was unpublished", (_RESELECT,)),
    "no_cloud_package": ("the listing has no stored package to run", (_REPUBLISH, _RESELECT)),
    "release_artifact_unavailable": ("the stored release is missing on the server", (_REPUBLISH, _RESELECT)),
    "source_bundle_fetch_failed": ("the package could not be downloaded", (_RETRY, _RESELECT)),
    "source_unavailable": ("the source could not be reached", (_RETRY, _RESELECT)),
    "source_timeout": ("the source took too long to answer", (_RETRY, _RESELECT)),
    "source_circuit_open": ("the source was failing and is paused to protect it", (_WAIT, _RESELECT)),
    "source_rate_limited": ("too many requests to this source", (_WAIT, _RESELECT)),
    "source_bundle_verification_failed": ("the downloaded package failed its integrity check", (_RETRY, _REPORT)),
    "source_bundle_claim_mismatch": ("the package differs from what the listing claimed", (_REPORT, _RESELECT)),
    "prepare_receipt_cache_busy": ("another preparation of the same selection is still running", (_RETRY,)),
    "source_not_supported": ("this source does not support the requested operation", (_UPDATE, _RESELECT)),
    "source_bundle_fetch_not_supported": ("this source cannot hand out packages for this request", (_UPDATE, _RESELECT)),
    "source_not_configured": ("this source is not configured on this machine", (_DOCTOR, _RESELECT)),
}


def plan_for(code: str) -> dict[str, Any] | None:
    """The repair plan for a remote refusal code, or ``None`` for codes it does not cover."""

    entry = _PLANS.get(code)
    if entry is None:
        return None
    meaning, actions = entry
    return {
        "brokenReason": code,
        "meaning": meaning,
        "repair": [dict(action) for action in actions],
        "reselectionRequired": any(action["action"] in {"reselect", "republish"} for action in actions),
    }


def covered_codes() -> frozenset[str]:
    return frozenset(_PLANS)
