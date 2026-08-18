"""Setting what a published Hub agent charges.

WHY THIS IS A SEPARATE STEP FROM PUBLISHING
    The agent is already on the Hub by the time prices are set. Folding the
    price into ``register_package`` would let a wrong number or a network blip
    fail a publish that had already succeeded on the server, and send someone to
    re-publish something already published. So pricing runs after registration
    and its failure is reported, not raised: the listing stays live and free,
    which is exactly where every agent published before pricing existed lives.

WHY IT IS KEYED BY SLUG
    The registration response carries slug, packageHash, agentReleaseId,
    releaseVersion and contentDigest — it has never carried an
    ``agentDefinitionId``, which is what pricing is stored against on the
    server. The web endpoint therefore accepts a slug and resolves it against
    the caller's own listings, so this is one call instead of
    resolve-then-price. A two-call sequence is where the second call gets
    skipped.

BLANK IS NOT ZERO
    A kind with no price is not sold. Zero would mean "this is free", and an
    agent that does not sell forks is not giving copies away. So a kind is
    omitted from the patch rather than sent as 0.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .auth import AgentlasAuthError, ensure_access_token, same_origin_urlopen

PRICE_KINDS: tuple[str, ...] = ("RENT", "INGEST", "FORK")

#: Mirrors the server's PRICE_KIND_SPEC. The server checks again and wins; this
#: only avoids spending a round trip on an obviously bad number.
PRICE_KIND_BOUNDS: dict[str, dict[str, int | None]] = {
    # A work order is a 24-hour lease a buyer opens many of, so the ceiling is
    # deliberately low — the same job must not cost more for being split up.
    "RENT": {"min": 1, "max": 100},
    # A day of a whole project, not one task. Twenty times the rent ceiling.
    "INGEST": {"min": 1, "max": 2_000},
    # A copy sold once. No repeat, so nothing for a ceiling to protect against.
    "FORK": {"min": 1, "max": None},
}

KIND_LABEL: dict[str, tuple[str, str]] = {
    "RENT": ("빌리기 (워크오더 1건 · 24시간)", "Rent (per work order, 24h)"),
    "INGEST": ("장기대여 (에이전트 1일당)", "Long-term lease (per agent-day)"),
    "FORK": ("포크 (사본 1개)", "Fork (one copy)"),
}


class PriceError(Exception):
    """A price the server would refuse, caught before it is sent."""

    def __init__(self, message: str, *, code: str, kind: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.kind = kind


def bounds_text(kind: str) -> str:
    """``1-100`` / ``1+`` — what the field will accept, for a prompt or an error."""
    bounds = PRICE_KIND_BOUNDS[kind]
    maximum = bounds["max"]
    return f"{bounds['min']}+" if maximum is None else f"{bounds['min']}-{maximum}"


def check_price(kind: str, credits: Any) -> int:
    """Validate one price locally. Raises PriceError; returns the integer."""
    if kind not in PRICE_KIND_BOUNDS:
        raise PriceError(f"unknown price kind: {kind}", code="unknown_kind", kind=kind)
    if isinstance(credits, bool) or not isinstance(credits, int):
        raise PriceError(
            f"{kind} price must be a whole number of credits", code="not_an_integer", kind=kind
        )
    bounds = PRICE_KIND_BOUNDS[kind]
    minimum = int(bounds["min"] or 1)
    maximum = bounds["max"]
    if credits < minimum:
        # Zero is refused rather than read as "free": a row saying 0 cannot be
        # told apart from one nobody filled in, and the two settle differently.
        raise PriceError(
            f"{kind} price must be at least {minimum} credits ({bounds_text(kind)})",
            code="below_minimum",
            kind=kind,
        )
    if maximum is not None and credits > int(maximum):
        raise PriceError(
            f"{kind} price may not exceed {maximum} credits ({bounds_text(kind)})",
            code="above_maximum",
            kind=kind,
        )
    return credits


def build_patch(
    *,
    rent: int | None = None,
    ingest: int | None = None,
    fork: int | None = None,
) -> dict[str, int]:
    """Only the kinds actually given.

    A kind left out is untouched on the server, so this never deletes a price
    set from somewhere else. ``None`` means "not answered", which is different
    from "remove" — removal is deliberate and belongs on the web surface where
    the current value is visible.
    """
    patch: dict[str, int] = {}
    for kind, value in (("RENT", rent), ("INGEST", ingest), ("FORK", fork)):
        if value is None:
            continue
        patch[kind] = check_price(kind, value)
    return patch


def set_prices(
    slug: str,
    patch: dict[str, int],
    *,
    base_url: str,
    interactive: bool = True,
) -> dict[str, Any]:
    """POST the prices. Returns a result dict; never raises for a server refusal.

    The caller has already published. Reporting is the job here — raising would
    turn a successful publish into a failed command.
    """
    if not patch:
        return {"status": "skipped", "reason": "no_prices_given", "prices": {}}

    try:
        token = ensure_access_token(base_url, interactive=interactive)
    except AgentlasAuthError as exc:
        return {"status": "failed", "reason": "auth_unavailable", "detail": str(exc), "prices": {}}
    if not token:
        return {"status": "failed", "reason": "sign_in_required", "prices": {}}

    body = json.dumps({"slug": slug, "prices": patch}).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}/api/account/rates",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "hephaestus-upload",
            "Origin": base_url,
        },
        method="POST",
    )
    try:
        with same_origin_urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        parsed: dict[str, Any] = {}
        try:
            parsed = json.loads(detail)
        except Exception:  # noqa: BLE001 - the body may not be JSON at all
            parsed = {}
        return {
            "status": "failed",
            "reason": str(parsed.get("error") or f"http_{exc.code}"),
            # The bound comes back with the refusal so the caller can say what
            # the limit IS, not merely that the number was rejected.
            "rejection": parsed.get("rejection"),
            "kind": parsed.get("kind"),
            "detail": detail[:500],
            "prices": {},
        }
    except Exception as exc:  # noqa: BLE001 - network shapes vary by platform
        return {"status": "failed", "reason": "network", "detail": str(exc), "prices": {}}

    if payload.get("ok") is not True:
        return {"status": "failed", "reason": str(payload.get("error") or "unknown"), "prices": {}}
    # What the SERVER stored, not what was sent. They can differ, and the one
    # that matters is the server's.
    return {
        "status": "priced",
        "prices": payload.get("prices") or {},
        "changed": bool(payload.get("changed")),
    }
