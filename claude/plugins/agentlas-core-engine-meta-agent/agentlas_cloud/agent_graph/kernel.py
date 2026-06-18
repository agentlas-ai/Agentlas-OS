"""Super-Ontology kernel loader (Phase 1).

The super-ontology is the governance/quality KERNEL: 1 master contract +
24 theme contracts under ``.agentlas/super-ontology-*.json``. Most stay
``export_only`` (spec, not yet a live enforcer). Phase 1 *promotes* a small,
calibrated set of seed contracts to ``runtime_enforced`` and links them to the
live AO grammar axioms that actually enforce them at lint + routing time.

This module loads the kernel, reports which contracts are runtime-enforced, and
maps each enforced contract to the concrete grammar axiom that realizes it — so
"the kernel enforces X" is a checkable claim, not a spec promise.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .loader import load_grammar

_PREFIX = "super-ontology-"
_MASTER = "super-ontology-contract.json"

# Phase 1 calibrated seeds: contracts promoted from spec to live enforcement,
# each linked to the AO grammar axiom that realizes it at runtime.
ENFORCED_SEEDS: dict[str, dict[str, str]] = {
    "capability-delegation-authority": {
        "axiom_kind": "require",
        "realized_by": 'to.type == "ExternalAgent" and relation == "can_invoke" => exists aligned_with(to)',
        "summary": "any agent may invoke an external agent only when that external agent's capability is curator-aligned",
    },
    "consensus-coordination": {
        "axiom_kind": "require",
        "realized_by": 'edge.kind == "shared_memory_write" => requires_approval_from(PolicyGate)',
        "summary": "a shared-memory write requires Policy Gate approval (no peer-pressure / last-writer-wins write)",
    },
}


def _contract_id(filename: str) -> str:
    return filename[len(_PREFIX):].removesuffix(".json")


def load_kernel(project_root: str | Path = ".") -> dict[str, Any]:
    """Load the super-ontology kernel: master + theme contracts + enforcement map."""

    base = Path(project_root) / ".agentlas"
    master: dict[str, Any] | None = None
    contracts: dict[str, dict[str, Any]] = {}
    for path in sorted(base.glob(f"{_PREFIX}*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if path.name == _MASTER:
            master = payload
            continue
        contracts[_contract_id(path.name)] = payload

    enforced: list[dict[str, Any]] = []
    for cid, link in ENFORCED_SEEDS.items():
        contract = contracts.get(cid)
        enforced.append(
            {
                "contract": cid,
                "present": contract is not None,
                "state": (contract or {}).get("state"),
                "runtime_enforced": (contract or {}).get("state") == "runtime_enforced",
                "realized_by": link["realized_by"],
                "summary": link["summary"],
                "hard_stops": (contract or {}).get("hardStops", []),
            }
        )

    return {
        "master_present": master is not None,
        "contract_count": len(contracts) + (1 if master else 0),
        "theme_count": len(contracts),
        "enforced": enforced,
        "enforced_count": sum(1 for e in enforced if e["runtime_enforced"] and e["present"]),
    }


def verify_enforcement(project_root: str | Path = ".") -> dict[str, Any]:
    """Confirm each promoted seed is actually realized by a live grammar axiom.

    A seed is only honestly "enforced" when (a) its contract state is
    ``runtime_enforced`` AND (b) the linked axiom exists in the live grammar.
    """

    kernel = load_kernel(project_root)
    grammar = load_grammar(project_root)
    require_rules = [str(r.get("if", "")) + " => " + str(r.get("then", "")) for r in grammar.get("require", [])]
    deny_rules = [
        f'{r.get("from")} -{r.get("relation")}-> {r.get("to")}' for r in grammar.get("deny", [])
    ]

    results: list[dict[str, Any]] = []
    for entry in kernel["enforced"]:
        realized = entry["realized_by"]
        # Match the require axiom by its if/then shape (whitespace-insensitive).
        norm = lambda s: " ".join(str(s).split())
        axiom_present = any(norm(realized) == norm(rule) for rule in require_rules) or any(
            norm(realized) == norm(rule) for rule in deny_rules
        )
        results.append(
            {
                "contract": entry["contract"],
                "state_ok": entry["runtime_enforced"] and entry["present"],
                "axiom_present": axiom_present,
                "enforced": bool(entry["runtime_enforced"] and entry["present"] and axiom_present),
                "realized_by": realized,
            }
        )

    return {
        "enforced_seeds": results,
        "all_enforced": all(r["enforced"] for r in results) if results else False,
        "fully_enforced_count": sum(1 for r in results if r["enforced"]),
    }
