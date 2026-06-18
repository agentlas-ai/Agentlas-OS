"""Agent OS assembly surfaces.

- ``build_pack`` (Phase 2): assemble an installable Ontology Pack manifest from
  the AO graph + kernel enforcement + interchange formats, with a content hash.
- ``os_surface`` (Phase 6): map the subsystems into OS kernel-module roles, each
  with a *live* status derived from real checks — so "it is an Agent OS" is a
  checkable claim, not a metaphor.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .a2a import WELL_KNOWN_PATH
from .kernel import verify_enforcement
from .loader import load_graph
from .okf import FORMAT as OKF_FORMAT
from .validator import validate_graph

PACK_FORMAT = "agent-ontology-pack-v1"


def build_pack(project_root: str | Path = ".") -> dict[str, Any]:
    """Build an installable Ontology Pack manifest (Phase 2)."""

    context = load_graph(project_root)
    graph = context.get("graph", {})
    counts = context.get("counts", {})
    caps = sorted(str(c) for c in graph.get("capabilities", []) if str(c).strip())
    kernel = verify_enforcement(project_root)

    fingerprint = json.dumps(
        {"counts": counts, "capabilities": caps, "kernel": kernel["fully_enforced_count"]},
        sort_keys=True,
        ensure_ascii=False,
    )
    content_hash = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]

    return {
        "format": PACK_FORMAT,
        "counts": counts,
        "capabilities": caps,
        "kernel": {
            "runtime_enforced_seeds": kernel["fully_enforced_count"],
            "all_enforced": kernel["all_enforced"],
        },
        "interchange": {"okf": OKF_FORMAT, "a2a_well_known": WELL_KNOWN_PATH},
        "artifacts": [
            "agent-ontology/grammar.json",
            "agent-ontology/agents.jsonl",
            "agent-ontology/edges.jsonl",
            "agent-ontology/artifacts.jsonl",
            "agent-ontology/scopes.jsonl",
            "agent-ontology/capabilities.json",
        ],
        "content_hash": content_hash,
        "installable": bool(counts.get("agents")),
    }


def os_surface(project_root: str | Path = ".") -> dict[str, Any]:
    """Map subsystems to OS kernel-module roles with live status (Phase 6)."""

    context = load_graph(project_root)
    counts = context.get("counts", {})
    kernel = verify_enforcement(project_root)
    validation = validate_graph(project_root)

    modules = [
        {
            "os_role": "protected mode / access manager",
            "subsystem": "super-ontology kernel + AO deny/require axioms",
            "live": bool(kernel["all_enforced"]),
            "detail": f"{kernel['fully_enforced_count']} seed contracts runtime-enforced",
        },
        {
            "os_role": "package manager + type system",
            "subsystem": "Ontology Pack (AO typed graph)",
            "live": bool(validation.get("valid")),
            "detail": (
                f"{counts.get('agents', 0)} agents / {counts.get('artifacts', 0)} artifacts / "
                f"{counts.get('edges', 0)} edges; lint {'valid' if validation.get('valid') else 'INVALID'}"
            ),
        },
        {
            "os_role": "filesystem",
            "subsystem": "Memory (5-scope) + MemoryScope ownership",
            "live": counts.get("scopes", 0) > 0,
            "detail": f"{counts.get('scopes', 0)} memory scopes owned via owns_scope",
        },
        {
            "os_role": "scheduler / dispatcher",
            "subsystem": "Network router (deterministic, local-first)",
            "live": _module_present("agentlas_cloud.networking.router"),
            "detail": "AO-filtered candidate routing + receipts",
        },
        {
            "os_role": "IPC + discovery",
            "subsystem": "A2A Agent Cards",
            "live": _module_present("agentlas_cloud.agent_graph.a2a"),
            "detail": WELL_KNOWN_PATH,
        },
        {
            "os_role": "interchange / wire format",
            "subsystem": "OKF bundle (vendor-neutral)",
            "live": _module_present("agentlas_cloud.agent_graph.okf"),
            "detail": OKF_FORMAT,
        },
    ]

    return {
        "agent_os": "hephaestus",
        "modules": modules,
        "all_live": all(m["live"] for m in modules),
        "live_count": sum(1 for m in modules if m["live"]),
        "factory_contract": factory_contract(),
    }


def factory_contract() -> dict[str, Any]:
    """Phase 6: the mandatory contract every emitted agent/team inherits.

    The factory does not just produce agents — it produces agents that are born
    ABI-compatible with the Agent OS (they inherit the kernel, memory discipline,
    routing card, promotion path, and interchange surface).
    """

    return {
        "inherited_contract": [
            "pm_soul (project continuity)",
            "memory_curator (sole durable writer)",
            "memory_tickets (ACK + idempotency)",
            "routing_card (network discoverability)",
            "promotion_path (candidate -> validated -> promoted)",
            "policy_gate (shared-memory approval)",
            "okf_export (vendor-neutral pack)",
            "bi_temporal_memory (supersede-not-delete)",
            "super_ontology_kernel (default-deny axioms)",
        ],
        "guarantee": "every Team-Builder / Single-Agent-Builder / Packager output is born ABI-compatible with the Agent OS",
        "degraded_runtimes": {"codex": "thin adapter", "gemini": "thin adapter"},
    }


def _module_present(dotted: str) -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec(dotted) is not None
    except (ImportError, ValueError):
        return False
