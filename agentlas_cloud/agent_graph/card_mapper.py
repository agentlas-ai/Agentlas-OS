"""Map global routing cards into the Agent Ontology (AO) graph.

The project AO graph (``.agentlas/agent-ontology/``) is built from a company
blueprint and only contains a company's internal agents. The GLOBAL routing-card
store (installed agents/teams/plugins) was never ingested, so the network
router's ``_filter_candidates_by_ao`` reported every global card as
``available_but_unmapped`` → ``graph_path: []`` → pure lexical fallback.

This module materializes the card store into a parallel, card-derived AO graph
(``<networking_home>/agent-ontology/``) with:
  - one ``ExternalAgent`` node per card,
  - ``Domain`` nodes + ``in_domain`` edges (the coarse semantic frame),
  - ``Capability`` nodes + ``has_capability`` edges.

It is intentionally separate from the project AO loader/validator, so existing
project-graph behavior is untouched. ``card_route_path`` produces a concrete,
non-empty ``graph_path`` for a routed card so the ontology is visible in the
routing receipt and A2A tooling.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _card_domains(card: dict[str, Any]) -> list[str]:
    explicit = card.get("domains")
    if isinstance(explicit, list) and explicit:
        return [str(d) for d in explicit if str(d)]
    # Lazy import keeps agent_graph free of a networking import at module load.
    try:
        from agentlas_cloud.networking.domains import classify_domains
    except Exception:  # pragma: no cover
        return []
    triggers = " ".join(
        str(entry.get("text") or "")
        for entry in (card.get("trigger_examples") or [])
        if isinstance(entry, dict)
    )
    return classify_domains(
        str(card.get("name") or ""),
        str(card.get("name_ko") or ""),
        str(card.get("summary") or ""),
        str(card.get("summary_ko") or ""),
        " ".join(str(c) for c in (card.get("capabilities") or [])),
        triggers,
    )


def build_card_ontology(cards: list[dict[str, Any]]) -> dict[str, Any]:
    """In-memory card-derived AO: nodes + typed edges + a domain index."""
    agents: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    capabilities: set[str] = set()
    domains: set[str] = set()
    domain_index: dict[str, list[str]] = {}
    node_index: dict[str, dict[str, Any]] = {}

    for card in cards:
        card_id = str(card.get("id") or "").strip()
        if not card_id:
            continue
        card_domains = _card_domains(card)
        caps = [str(c) for c in (card.get("capabilities") or []) if str(c).strip()]
        node = {
            "id": card_id,
            "type": "ExternalAgent",
            "name": card.get("name") or card_id,
            "domains": card_domains,
            "capabilities": caps,
            "source": "routing-card-store",
        }
        agents.append(node)
        node_index[card_id] = node
        for cap in caps:
            capabilities.add(cap)
            edges.append({"from": card_id, "to": f"capability:{cap}", "relation": "has_capability", "kind": "card_ontology"})
        for dom in card_domains:
            domains.add(dom)
            domain_index.setdefault(dom, []).append(card_id)
            edges.append({"from": f"domain:{dom}", "to": card_id, "relation": "in_domain", "kind": "card_ontology"})

    return {
        "agents": agents,
        "edges": edges,
        "capabilities": sorted(capabilities),
        "domains": sorted(domains),
        "domain_index": domain_index,
        "node_index": node_index,
    }


def card_route_path(
    card_id: str,
    card_domains: list[str] | set[str] | None,
    query_domains: list[str] | set[str] | None,
) -> list[dict[str, Any]]:
    """A concrete AO edge justifying a route: prefer the domain shared by query
    and card, else the card's own domain, else a plain routes_to edge."""
    card_set = set(card_domains or [])
    query_set = set(query_domains or [])
    shared = sorted(card_set & query_set)
    # Only claim a domain-derived edge when query and card actually SHARE a
    # domain; a card-only domain did not drive this route, so fall back to a
    # plain routes_to edge rather than fabricating an in_domain justification.
    chosen = shared[0] if shared else None
    if chosen:
        return [{"from": f"domain:{chosen}", "to": card_id, "relation": "in_domain", "kind": "card_ontology"}]
    return [{"from": "router", "to": card_id, "relation": "routes_to", "kind": "card_ontology"}]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def ingest_routing_cards(home: str | Path, cards: list[dict[str, Any]], *, write: bool = True) -> dict[str, Any]:
    """Materialize the card-derived AO graph under ``<home>/agent-ontology/``.

    Returns a summary. Idempotent — fully rewrites the card-derived graph each
    call so it always mirrors the current card store.
    """
    graph = build_card_ontology(cards)
    if write:
        ao_dir = Path(home) / "agent-ontology"
        ao_dir.mkdir(parents=True, exist_ok=True)
        _write_jsonl(ao_dir / "agents.jsonl", graph["agents"])
        _write_jsonl(ao_dir / "edges.jsonl", graph["edges"])
        _write_jsonl(
            ao_dir / "domains.jsonl",
            [{"id": f"domain:{d}", "type": "Domain", "name": d, "agents": graph["domain_index"].get(d, [])} for d in graph["domains"]],
        )
        (ao_dir / "capabilities.json").write_text(
            json.dumps({"capabilities": graph["capabilities"]}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    return {
        "status": "ok",
        "agents": len(graph["agents"]),
        "edges": len(graph["edges"]),
        "domains": len(graph["domains"]),
        "capabilities": len(graph["capabilities"]),
    }
