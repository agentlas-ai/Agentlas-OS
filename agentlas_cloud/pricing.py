"""Retired creator pricing compatibility surface.

The public Hub is a free agent community. Creator-set per-call, day-lease, and
fork prices were closed with the marketplace settlement model. Keep these
symbols for older host imports, but never dispatch a write to the account rate
endpoint, including when an older caller supplies a price patch.
"""

from __future__ import annotations

from typing import Any

PRICE_KINDS: tuple[str, ...] = ("RENT", "INGEST", "FORK")
PRICE_KIND_BOUNDS: dict[str, dict[str, int | None]] = {
    "RENT": {"min": 1, "max": 100},
    "INGEST": {"min": 1, "max": 2_000},
    "FORK": {"min": 1, "max": None},
}
KIND_LABEL: dict[str, tuple[str, str]] = {
    "RENT": ("종료된 원샷 가격", "Retired one-shot price"),
    "INGEST": ("종료된 장기대여 가격", "Retired day-lease price"),
    "FORK": ("종료된 포크 가격", "Retired fork price"),
}


class PriceError(Exception):
    def __init__(self, message: str, *, code: str, kind: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.kind = kind


def bounds_text(kind: str) -> str:
    bounds = PRICE_KIND_BOUNDS[kind]
    maximum = bounds["max"]
    return f"{bounds['min']}+" if maximum is None else f"{bounds['min']}-{maximum}"


def check_price(kind: str, credits: Any) -> int:
    raise PriceError("Agentlas Hub creator pricing is closed.", code="hub_pricing_closed", kind=kind)


def build_patch(*, rent: int | None = None, ingest: int | None = None, fork: int | None = None) -> dict[str, int]:
    if any(value is not None for value in (rent, ingest, fork)):
        raise PriceError("Agentlas Hub creator pricing is closed.", code="hub_pricing_closed")
    return {}


def set_prices(slug: str, patch: dict[str, int], *, base_url: str, interactive: bool = True) -> dict[str, Any]:
    return {"status": "rejected", "reason": "hub_pricing_closed", "prices": {}, "changed": False}
