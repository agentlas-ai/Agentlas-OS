"""Agent Workforce Ontology reference runtime.

The package deliberately separates content-derived candidate retrieval from the
host-LLM staffing decision.  It is dependency-free so the same contracts can be
used by the local Core runtime and mirrored by hosted surfaces.
"""

from .compiler import compile_workforce_profile
from .execution import prepare_execution_plan, validate_execution_receipt
from .governance import apply_ontology_proposal, validate_ontology_proposal
from .contracts import canonical_digest, load_ontology
from .index import WorkforceIndex
from .lifecycle import WorkforceProjection, replay_events
from .selection import validate_host_selection

__all__ = [
    "WorkforceIndex",
    "WorkforceProjection",
    "canonical_digest",
    "compile_workforce_profile",
    "prepare_execution_plan",
    "validate_execution_receipt",
    "apply_ontology_proposal",
    "validate_ontology_proposal",
    "load_ontology",
    "replay_events",
    "validate_host_selection",
]
