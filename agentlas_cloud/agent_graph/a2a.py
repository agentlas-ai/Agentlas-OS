"""A2A Agent Card boundary for the Agent Ontology (AO).

This is the external-interoperability layer (Phase 4). It maps between the
internal AO and the A2A ``AgentCard`` interchange format:

- ``import_agent_card``: an external A2A ``AgentCard`` becomes an
  ``ExternalAgent`` node plus ``aligned_with`` edges into our controlled
  ``Capability`` vocabulary. It NEVER emits ``can_invoke``: the grammar
  require-rule ("ExternalAgent can_invoke => exists aligned_with") plus curator
  approval gate actual invocation. Unrecognized capabilities are reported, not
  silently invented into the vocabulary.
- ``export_agent_card``: an internal agent is projected into an A2A-style
  ``AgentCard`` built from a field whitelist, so private paths, local memory,
  raw routing-card text, and policy rationale can never leak. The canonical
  discovery path is ``/.well-known/agent-card.json``.

Capability alignment here is deterministic (normalization + token overlap).
LLM-assisted ontology matching is a future enhancement layered on top.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .loader import load_graph, load_grammar

# Fields that must never appear in an exported public Agent Card.
_PRIVATE_FIELDS = (
    "path",
    "entrypoints",
    "memory_behavior",
    "source",
    "risk_profile",
    "routing_overrides",
    "member_of",
)

# Canonical A2A discovery path (A2A v1.0 well-known URI).
WELL_KNOWN_PATH = "/.well-known/agent-card.json"

# Boundary-parser limits: an external card is untrusted input, so cap work
# before alignment to avoid a denial-of-service via a huge card.
_MAX_SKILLS = 1000
_MAX_TAGS_PER_SKILL = 64
_MAX_LABEL_LEN = 200


def _snake(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _vocabulary(project_root: str | Path = ".") -> set[str]:
    """The controlled capability vocabulary: grammar + materialized capabilities."""

    grammar = load_grammar(project_root)
    graph = load_graph(project_root)
    vocab = {str(c).strip() for c in grammar.get("capabilities", []) if str(c).strip()}
    vocab |= {
        str(c).strip()
        for c in graph.get("graph", {}).get("capabilities", [])
        if str(c).strip()
    }
    return vocab


def align_capability(raw: str, vocab: set[str]) -> str | None:
    """Map an external capability label to our vocabulary, or None.

    Deterministic: exact normalized match first, then best token-overlap match
    (requires at least one shared token). Never creates new vocabulary.
    """

    norm = _snake(raw)
    if not norm or not vocab:
        return None
    if norm in vocab:
        return norm
    tokens = set(norm.split("_"))
    best: str | None = None
    best_score = 0
    for cap in sorted(vocab):
        overlap = len(tokens & set(cap.split("_")))
        if overlap > best_score:
            best, best_score = cap, overlap
    return best if best_score >= 1 else None


def _capability_candidates(card: dict[str, Any]) -> list[str]:
    """Capability signals from an A2A card.

    In A2A, ``skills[].tags`` carry the semantic capability labels, so they are
    the primary signal. A skill ``name`` is only a fallback when a skill has no
    tags. The opaque ``skills[].id`` is never treated as a capability label
    (it would pollute the unaligned report with identifiers).
    """

    candidates: list[str] = []
    skills = card.get("skills") or []
    if not isinstance(skills, list):
        skills = []
    for skill in skills[:_MAX_SKILLS]:
        if not isinstance(skill, dict):
            continue
        raw_tags = skill.get("tags") or []
        if not isinstance(raw_tags, list):
            raw_tags = []
        tags = [str(tag)[:_MAX_LABEL_LEN] for tag in raw_tags[:_MAX_TAGS_PER_SKILL] if str(tag).strip()]
        if tags:
            candidates.extend(tags)
        elif skill.get("name"):
            candidates.append(str(skill["name"])[:_MAX_LABEL_LEN])
    # Top-level skill-less cards: fall back to the card name as a hint.
    if not candidates and card.get("name"):
        candidates.append(str(card["name"])[:_MAX_LABEL_LEN])
    return candidates


def import_agent_card(card: dict[str, Any], project_root: str | Path = ".") -> dict[str, Any]:
    """Project an external A2A AgentCard into AO ExternalAgent + aligned_with edges.

    Returns a proposal (not persisted). ``can_invoke`` is always False here:
    invocation requires a separate curator-approved step, enforced by the
    grammar require-rule.
    """

    if not isinstance(card, dict):
        return {"error": "agent card must be a JSON object", "edges": [], "can_invoke": False}

    vocab = _vocabulary(project_root)
    raw_name = card.get("name") or card.get("url") or "external-agent"
    external_id = f"external:{_snake(raw_name)}"
    node = {
        "id": external_id,
        "type": "ExternalAgent",
        "name": str(card.get("name") or raw_name),
        "url": card.get("url"),
        "protocol": "a2a",
        "source": "a2a-import",
        "alignment_status": "pending",
    }

    edges: list[dict[str, Any]] = []
    aligned: list[dict[str, str]] = []
    unaligned: list[str] = []
    seen_caps: set[str] = set()
    for candidate in _capability_candidates(card):
        capability = align_capability(candidate, vocab)
        if capability is None:
            unaligned.append(candidate)
            continue
        if capability in seen_caps:
            continue
        seen_caps.add(capability)
        edges.append(
            {
                "from": external_id,
                "to": f"capability:{capability}",
                "relation": "aligned_with",
                "kind": "a2a",
                "external_label": candidate,
            }
        )
        aligned.append({"external": candidate, "capability": capability})

    raw_skills = card.get("skills") if isinstance(card.get("skills"), list) else []
    warnings: list[str] = []
    if len(raw_skills) > _MAX_SKILLS:
        warnings.append(f"skills truncated to {_MAX_SKILLS} (received {len(raw_skills)})")

    return {
        "external_agent": node,
        "edges": edges,
        "aligned": aligned,
        "unaligned": sorted(set(unaligned)),
        "can_invoke": False,
        "warnings": warnings,
        "note": (
            "aligned_with edges proposed; can_invoke is withheld until a curator "
            "approves alignment (grammar require-rule: ExternalAgent can_invoke "
            "=> exists aligned_with)."
        ),
    }


def export_agent_card(project_root: str | Path = ".", agent_id: str | None = None) -> dict[str, Any]:
    """Project an internal AO agent into a public A2A-style AgentCard.

    Built from a field whitelist so private fields can never leak. If
    ``agent_id`` is omitted, the canonical local meta-agent (id starting with
    ``local/``) is used, else the first agent.
    """

    graph = load_graph(project_root).get("graph", {})
    agents = graph.get("agents", [])
    if not agents:
        return {"error": "no agents available to export"}

    target: dict[str, Any] | None = None
    if agent_id:
        target = next((a for a in agents if str(a.get("id")) == agent_id), None)
        if target is None:
            return {"error": f"agent not found: {agent_id}"}
    else:
        target = next((a for a in agents if str(a.get("id", "")).startswith("local/")), agents[0])

    target_id = str(target.get("id"))
    capabilities: list[str] = []
    for edge in graph.get("edges", []):
        if str(edge.get("relation") or edge.get("kind")) != "has_capability":
            continue
        if str(edge.get("from")) != target_id:
            continue
        capabilities.append(str(edge.get("to")).removeprefix("capability:"))
    # Fall back to any capabilities listed directly on the node.
    capabilities.extend(str(c) for c in (target.get("capabilities") or []))
    capabilities = sorted({c for c in capabilities if c})

    card = {
        "protocolVersion": "1.0",
        "name": str(target.get("name") or target_id),
        "description": f"Agentlas agent ({target_id})",
        "version": "1.1.3",
        "capabilities": {"streaming": False, "pushNotifications": False},
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [
            {
                "id": cap,
                "name": cap.replace("_", " "),
                "description": f"Capability: {cap}",
                "tags": cap.split("_"),
            }
            for cap in capabilities
        ],
        "wellKnownPath": WELL_KNOWN_PATH,
    }

    leaked = sorted(k for k in _PRIVATE_FIELDS if k in card)
    return {
        "agent_card": card,
        "source_agent": target_id,
        "redacted_fields": sorted(_PRIVATE_FIELDS),
        "leaked_private_fields": leaked,
        "well_known_path": WELL_KNOWN_PATH,
    }


def build_a2a_registry(project_root: str | Path = ".") -> dict[str, Any]:
    """Queryable A2A registry of internal agents (Phase 4 discovery surface).

    Each entry carries an identity block. ``verified`` is False until signed
    cards + per-agent identity hardening land — the non-negotiable prerequisite
    for external mesh exposure (redesign decision 3).
    """

    graph = load_graph(project_root).get("graph", {})
    caps_by_agent: dict[str, set[str]] = {}
    for edge in graph.get("edges", []):
        if str(edge.get("relation") or edge.get("kind")) != "has_capability":
            continue
        caps_by_agent.setdefault(str(edge.get("from")), set()).add(
            str(edge.get("to")).removeprefix("capability:")
        )

    entries: list[dict[str, Any]] = []
    for agent in graph.get("agents", []):
        if str(agent.get("type")) == "ExternalAgent":
            continue
        aid = str(agent.get("id"))
        entries.append(
            {
                "id": aid,
                "name": agent.get("name"),
                "type": agent.get("type"),
                "capabilities": sorted(caps_by_agent.get(aid, set())),
                "well_known": WELL_KNOWN_PATH,
                "identity": {"owner": "local", "sponsor": None, "expiry": None, "verified": False},
                "routing_status": agent.get("routing_status"),
            }
        )
    return {
        "format": "a2a-registry-v1",
        "count": len(entries),
        "agents": entries,
        "note": (
            "identity.verified=false until signed-card + per-agent identity hardening; "
            "external mesh exposure is gated on that (redesign decision 3)."
        ),
    }


def can_invoke_external(*, aligned: bool, identity_verified: bool) -> dict[str, Any]:
    """Phase 4 invoke gate: an external agent is callable only when its capability
    is curator-aligned AND its identity is verified (defense-in-depth)."""

    allowed = bool(aligned and identity_verified)
    reasons: list[str] = []
    if not aligned:
        reasons.append("capability not curator-aligned (aligned_with missing)")
    if not identity_verified:
        reasons.append("agent identity not verified (signed card required)")
    return {"can_invoke": allowed, "blocked_reasons": reasons}
