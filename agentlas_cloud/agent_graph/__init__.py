"""Agent Ontology (AO) runtime package.

Loads canonical AO JSONL views, validates grammar/axioms, runs lightweight
graph queries, and migrates legacy .agentlas files into AO materialized views.
"""

from __future__ import annotations

from .card_mapper import build_card_ontology, card_route_path, ingest_routing_cards
from .loader import AGENT_ONTOLOGY_DIR, load_grammar, load_graph
from .migrate import migrate_ontology, diff_ontology
from .query import (
    describe_graph,
    execute_query,
    is_blocked,
    plan_path,
    plan_pipeline_ao,
    reachable,
    who_consumes,
    who_produces,
)
from .validator import validate_graph
from .validator import evaluate_requirements, explain_edge_gate, edge_is_blocked
from .a2a import (
    WELL_KNOWN_PATH,
    align_capability,
    build_a2a_registry,
    can_invoke_external,
    export_agent_card,
    import_agent_card,
)
from .okf import FORMAT as OKF_FORMAT
from .okf import from_okf_bundle, to_okf_bundle
from .kernel import ENFORCED_SEEDS, load_kernel, verify_enforcement
from .agentos import PACK_FORMAT, build_pack, factory_contract, os_surface
from .catalog import knowledge_catalog_descriptor
from .memory import BiTemporalStore, MemoryEntry

__all__ = [
    "AGENT_ONTOLOGY_DIR",
    "build_card_ontology",
    "card_route_path",
    "ingest_routing_cards",
    "BiTemporalStore",
    "MemoryEntry",
    "WELL_KNOWN_PATH",
    "OKF_FORMAT",
    "PACK_FORMAT",
    "build_pack",
    "os_surface",
    "factory_contract",
    "plan_pipeline_ao",
    "knowledge_catalog_descriptor",
    "ENFORCED_SEEDS",
    "load_kernel",
    "verify_enforcement",
    "to_okf_bundle",
    "from_okf_bundle",
    "align_capability",
    "build_a2a_registry",
    "can_invoke_external",
    "export_agent_card",
    "import_agent_card",
    "diff_ontology",
    "describe_graph",
    "execute_query",
    "is_blocked",
    "load_grammar",
    "load_graph",
    "migrate_ontology",
    "plan_path",
    "reachable",
    "validate_graph",
    "evaluate_requirements",
    "explain_edge_gate",
    "edge_is_blocked",
    "who_consumes",
    "who_produces",
]
