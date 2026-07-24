"""Shared memory contract — the canonical Python mirror of the Desktop/Terminal
memory rework, so the three surfaces (Desktop TS, Terminal CJS, hep Python) do
not silently drift.

Background: the memory logic lives in three places (CLAUDE.md "3제품 싱크" pattern,
extended here to the memory contract). The hep plugin is a lighter, per-slug
implementation, but the *contracts* it produces on disk — the
``.agentlas/evolution-proposals.json`` shape, the ``context_source`` marker
names, and the member-cell key rule — must match what the Desktop produces so a
host reading either surface sees the same thing.

Canonical references this file mirrors (Desktop repo, separate checkout):
  - electron/agents/evolution-hep.ts   → evolution-proposals.json shape
  - electron/store/run-events.ts       → context_source marker names
  - electron/memory/import.ts          → member cell / orchestrator / shared layers

Nothing here is content — these are structural constants and validators only.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Iterable

# ── Evolution proposals (Phase 2 / 2+) ───────────────────────────────────────
# Mirror of electron/agents/evolution-hep.ts.
EVOLUTION_PROPOSALS_CONTRACT = "agentlas.evolution-proposals.v1"
EVOLUTION_PROPOSALS_RELATIVE = ".agentlas/evolution-proposals.json"
EVOLUTION_REVIEW_COMMAND = "agentlas evolve"

# The per-proposal entry shape written into both `pending` and `autoApplied`.
# Field names are load-bearing — they must equal the Desktop HepProposalEntry.
EVOLUTION_PROPOSAL_FIELDS: tuple[str, ...] = (
    "id",
    "agentId",
    "riskTier",
    "status",
    "learned",
    "change",
    "reversible",
)
# Trust tier: low → auto-applied (with undo); high → explicit approval.
EVOLUTION_RISK_TIERS: frozenset[str] = frozenset({"low", "high"})

# The top-level keys of the evolution-proposals.json payload.
EVOLUTION_PAYLOAD_KEYS: tuple[str, ...] = (
    "contract",
    "generatedAt",
    "reviewCommand",
    "pending",
    "autoApplied",
)

# ── Context-source markers (Phase 4+) ────────────────────────────────────────
# Mirror of electron/store/run-events.ts CONTEXT_SOURCE_NAMES. Content-free:
# a marker records ONLY which recall source entered the prompt and an approximate
# injected token count — never any value/content.
CONTEXT_SOURCE_NAMES: frozenset[str] = frozenset(
    {"pm_soul", "code_map", "sitemap", "experience", "memory"}
)

# ── Member cells (Phase 1) ───────────────────────────────────────────────────
# hep's store is natively per-slug: each agent/member already gets its own
# ``~/.agentlas/networking/hub-agents/<slug>/memory/experience.sqlite``. That IS
# the member cell. The one rule that must match the Desktop is key preservation:
# a member's slug is used verbatim as its cell id — no new id is minted — so a
# team member's experience keys the same on every surface (C1 key-preservation).
MEMBER_CELL_KEY_RULE = (
    "member cell id == member slug (verbatim, normalized); never mint a new id"
)

# Scope separation inside a cell (three-layer model, all on the existing
# privacy_scope axis so no schema change is needed):
#   - member domain (this member's own experience)  → private
#   - team coordination (orchestrator)               → private, keyed by team slug
#   - shared team_memory (glossary/handoff/safety)   → public / internal
MEMBER_DOMAIN_SCOPES: tuple[str, ...] = ("private",)
TEAM_MEMORY_SHARED_SCOPES: tuple[str, ...] = ("public", "internal")


def _agentlas_home() -> Path:
    return Path(os.environ.get("AGENTLAS_HOME", "~/.agentlas")).expanduser()


def normalize_slug(value: str) -> str:
    """Slug normalization identical to memory_hook._normalize_slug so a member
    slug resolves to the same cell id on every code path."""
    return re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")


def member_cell_db_path(slug: str) -> Path:
    """The per-slug experience store path for a member cell. Keying by the
    (normalized) slug preserves the member's identity across surfaces — the hep
    equivalent of the Desktop's slug==installed_agents.id preservation."""
    normalized = normalize_slug(slug)
    if not normalized:
        raise ValueError("slug is required for a member cell")
    return (
        _agentlas_home()
        / "networking"
        / "hub-agents"
        / normalized
        / "memory"
        / "experience.sqlite"
    )


def validate_proposal_entry(entry: Any) -> bool:
    """True iff `entry` matches the Desktop HepProposalEntry shape."""
    if not isinstance(entry, dict):
        return False
    if set(entry.keys()) != set(EVOLUTION_PROPOSAL_FIELDS):
        return False
    if entry.get("riskTier") not in EVOLUTION_RISK_TIERS:
        return False
    for field in ("id", "agentId", "status", "learned", "change", "reversible"):
        if not isinstance(entry.get(field), str):
            return False
    return bool(entry["id"] and entry["agentId"])


def validate_proposals_payload(payload: Any) -> bool:
    """True iff `payload` matches agentlas.evolution-proposals.v1 exactly."""
    if not isinstance(payload, dict):
        return False
    if set(payload.keys()) != set(EVOLUTION_PAYLOAD_KEYS):
        return False
    if payload.get("contract") != EVOLUTION_PROPOSALS_CONTRACT:
        return False
    if payload.get("reviewCommand") != EVOLUTION_REVIEW_COMMAND:
        return False
    if not isinstance(payload.get("generatedAt"), str) or not payload["generatedAt"]:
        return False
    for bucket in ("pending", "autoApplied"):
        items = payload.get(bucket)
        if not isinstance(items, list):
            return False
        if not all(validate_proposal_entry(item) for item in items):
            return False
    return True


def context_source_names() -> frozenset[str]:
    return CONTEXT_SOURCE_NAMES


def is_context_source(name: str) -> bool:
    return name in CONTEXT_SOURCE_NAMES


def iter_proposal_fields() -> Iterable[str]:
    return EVOLUTION_PROPOSAL_FIELDS
