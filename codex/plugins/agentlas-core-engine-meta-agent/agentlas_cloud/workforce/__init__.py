"""Agent Workforce Ontology reference runtime.

The package deliberately separates content-derived candidate retrieval from the
host-LLM staffing decision.  It is dependency-free so the same contracts can be
used by the local Core runtime and mirrored by hosted surfaces.
"""

from .compiler import compile_workforce_profile
from .execution import (
    WORKFORCE_EXECUTION_PLAN_SCHEMA,
    WORKFORCE_RUNTIME_BUNDLE_DIGEST_SCHEMA,
    prepare_execution_plan,
    validate_execution_receipt,
    workforce_runtime_bundle_canonical_json,
    workforce_runtime_bundle_digest,
)
from .governance import apply_ontology_proposal, validate_ontology_proposal
from .contracts import (
    WORKFORCE_ONTOLOGY_SNAPSHOT_SHA256,
    WORKFORCE_ONTOLOGY_VERSION,
    canonical_digest,
    load_ontology,
)
from .index import WorkforceIndex
from .lifecycle import WorkforceProjection, replay_events
from .selection import validate_host_selection

__all__ = [
    "WorkforceIndex",
    "WorkforceProjection",
    "WORKFORCE_ONTOLOGY_SNAPSHOT_SHA256",
    "WORKFORCE_ONTOLOGY_VERSION",
    "WORKFORCE_EXECUTION_PLAN_SCHEMA",
    "WORKFORCE_RUNTIME_BUNDLE_DIGEST_SCHEMA",
    "canonical_digest",
    "compile_workforce_profile",
    "prepare_execution_plan",
    "validate_execution_receipt",
    "workforce_runtime_bundle_canonical_json",
    "workforce_runtime_bundle_digest",
    "apply_ontology_proposal",
    "validate_ontology_proposal",
    "load_ontology",
    "replay_events",
    "validate_host_selection",
]
