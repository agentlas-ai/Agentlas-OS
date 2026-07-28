"""Build the catalogue graph and the embedding texts from compiled briefs.

The graph is not decoration. Two packages that produce the same kind of thing, or
that need the same thing to start, are neighbours whether or not they share a
single word - and word-sharing is exactly what failed: a Korean request and an
English resume overlap on nothing, and 1186 of 1189 trigger sentences in the live
catalogue were unique strings. Structure is what survives translation.

Nodes:
  agent      one published package
  artifact   a thing produced or required, keyed by its own words
  effect     what happens in the requester's world

Edges:
  agent -produces-> artifact
  agent -requires-> artifact
  agent -performs-> effect

The embedding text is assembled here too, so the graph and the vectors are built
from the same sentences and can never drift into describing different things.
Nothing is tokenised: each text stays a sentence, because cutting sentences into
bare terms is what moved a correct agent from rank 2 to rank 24.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Any, Iterable, Mapping

__all__ = ["build_graph", "embedding_text"]


def _key(text: str) -> str:
    """A stable id for an artifact phrase.

    Folded and space-collapsed so "Contract alignment log" and
    "contract  alignment log" are one node, but never stemmed or translated: two
    genuinely different phrasings stay two nodes rather than being merged by a
    guess.
    """
    folded = unicodedata.normalize("NFKC", str(text)).casefold().strip()
    folded = re.sub(r"\s+", " ", folded)
    return hashlib.sha256(folded.encode("utf-8")).hexdigest()[:16]


def _produced(brief: Mapping[str, Any], limit: int = 24) -> list[str]:
    """The things a package hands back, as the things themselves.

    NOT the deliverable label. A label is the output schema's title, which is
    almost always the package's own name again — measured across the catalogue,
    produced nodes came out as "Brand Introduction — output" while required nodes
    came out as "Which brand should be introduced?", so producers and consumers
    described different kinds of object and the maximum similarity between any
    producer and any consumer was 0.511. A title can never match a question.

    What a package actually hands back is inside the schema: `contains` holds its
    property names and descriptions, so "contract alignment log with a
    provision-level verdict" becomes a node another package can require.
    """
    value = brief.get("deliverables")
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        contains = item.get("contains")
        if isinstance(contains, list) and contains:
            out.extend(str(entry).strip() for entry in contains if str(entry).strip())
        else:
            # No contract yet: the label is all there is. Kept so the package is
            # still on the graph rather than absent from it.
            label = str(item.get("label") or "").strip()
            if label:
                out.append(label)
        if len(out) >= limit:
            break
    return out[:limit]


def _required(brief: Mapping[str, Any]) -> list[str]:
    value = brief.get("obligations")
    if not isinstance(value, list):
        return []
    return [
        str(item.get("about")).strip()
        for item in value
        if isinstance(item, Mapping) and str(item.get("about") or "").strip()
    ]


def build_graph(briefs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """`briefs` maps slug -> compiled offer brief."""
    agents: list[dict[str, Any]] = []
    artifacts: dict[str, dict[str, Any]] = {}
    effects: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []

    for slug, brief in briefs.items():
        agents.append({
            "id": f"agent:{slug}",
            "type": "agent",
            "slug": slug,
            "statement": str(brief.get("statement") or ""),
            "locale": list(brief.get("locale") or []),
        })

        for label in _produced(brief):
            node_id = f"artifact:{_key(label)}"
            artifacts.setdefault(node_id, {"id": node_id, "type": "artifact", "phrase": label, "producers": 0, "consumers": 0})
            artifacts[node_id]["producers"] += 1
            edges.append({"from": f"agent:{slug}", "rel": "produces", "to": node_id})

        for about in _required(brief):
            node_id = f"artifact:{_key(about)}"
            artifacts.setdefault(node_id, {"id": node_id, "type": "artifact", "phrase": about, "producers": 0, "consumers": 0})
            artifacts[node_id]["consumers"] += 1
            edges.append({"from": f"agent:{slug}", "rel": "requires", "to": node_id})

        authority = brief.get("authority")
        performs = authority.get("performs") if isinstance(authority, Mapping) else None
        for effect in performs or []:
            node_id = f"effect:{effect}"
            effects.setdefault(node_id, {"id": node_id, "type": "effect", "effect": str(effect), "agents": 0})
            effects[node_id]["agents"] += 1
            edges.append({"from": f"agent:{slug}", "rel": "performs", "to": node_id})

    # A handoff edge: one package produces what another requires. This is the
    # relation a team builder needs and no free-text field can express.
    by_phrase: dict[str, dict[str, list[str]]] = {}
    for edge in edges:
        if edge["rel"] not in ("produces", "requires"):
            continue
        slot = by_phrase.setdefault(edge["to"], {"produces": [], "requires": []})
        slot[edge["rel"]].append(edge["from"])
    handoffs = [
        {"from": producer, "rel": "hands-off-to", "to": consumer, "via": node_id}
        for node_id, slot in by_phrase.items()
        for producer in slot["produces"]
        for consumer in slot["requires"]
        if producer != consumer
    ]

    return {
        "agents": agents,
        "artifacts": list(artifacts.values()),
        "effects": list(effects.values()),
        "edges": edges + handoffs,
        "counts": {
            "agents": len(agents),
            "artifacts": len(artifacts),
            "effects": len(effects),
            "edges": len(edges),
            "handoffs": len(handoffs),
        },
    }


def embedding_text(brief: Mapping[str, Any], limit: int = 4000) -> str:
    """The text a vector is built from: whole sentences, in writing order.

    Deliverable contents are included because they are what discriminates - a
    schema title is usually the package's own name again, while the property
    names inside it are the words a requester actually uses. Measured: adding
    them moved the correct package from 4th at 0.63 to 1st at 16.32.
    """
    parts: list[str] = [str(brief.get("statement") or "")]
    for item in brief.get("deliverables") or []:
        if not isinstance(item, Mapping):
            continue
        label = str(item.get("label") or "").strip()
        if label:
            parts.append(f"produces: {label}")
        contains = item.get("contains")
        if isinstance(contains, list):
            parts.extend(f"including {str(entry)}" for entry in contains[:12])
    for item in brief.get("obligations") or []:
        if isinstance(item, Mapping) and str(item.get("about") or "").strip():
            parts.append(f"needs: {str(item['about']).strip()}")
    text = "\n".join(part for part in parts if part.strip())
    return text[:limit]
