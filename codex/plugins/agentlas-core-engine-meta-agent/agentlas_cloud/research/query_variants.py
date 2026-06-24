"""Bounded search query variants for broader recall without new modules."""

from __future__ import annotations

from typing import Iterable


MAX_QUERY_VARIANTS = 8

QUERY_VARIANT_TEMPLATES: dict[str, str] = {
    "base": "{query}",
    "official": "{query} official",
    "docs": "{query} documentation docs",
    "github": "{query} GitHub",
    "reddit": "{query} reddit",
    "threads": "{query} Threads site:threads.com",
    "news": "{query} latest news",
}


def expand_query_variants(query: str, variants: Iterable[str] | None = None) -> list[str]:
    """Return deterministic, bounded query variants.

    Unknown variant names are treated as literal suffixes so API callers can
    supply small domain hints without changing engine code.
    """

    base = _compact(query)
    if not base:
        return []
    requested = [_compact(item) for item in variants or [] if _compact(item)]
    if not requested:
        requested = ["base"]
    if "base" not in requested:
        requested.insert(0, "base")

    expanded: list[str] = []
    for variant in requested[:MAX_QUERY_VARIANTS]:
        template = QUERY_VARIANT_TEMPLATES.get(variant)
        if template:
            candidate = template.format(query=base)
        else:
            candidate = f"{base} {variant}"
        candidate = _compact(candidate)
        if candidate and candidate not in expanded:
            expanded.append(candidate)
    return expanded


def query_variant_catalog() -> list[dict[str, str]]:
    return [
        {"name": name, "template": template}
        for name, template in QUERY_VARIANT_TEMPLATES.items()
    ]


def _compact(value: str) -> str:
    return " ".join(str(value or "").split())
