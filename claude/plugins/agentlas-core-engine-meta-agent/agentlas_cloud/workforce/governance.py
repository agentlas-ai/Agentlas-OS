"""Versioned community governance for workforce concepts and crosswalks."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .contracts import canonical_digest, normalized_strings


ENTITY_COLLECTIONS = {"community": "communities", "role": "roles"}
MAP_COLLECTIONS = {
    "skill_alias": "skillAliases",
    "tool_alias": "toolCapabilityAliases",
    "capability_role_hint": "capabilityRoleHints",
}
OPERATIONS = {"add", "update", "deprecate", "merge", "crosswalk"}


def validate_ontology_proposal(proposal: Mapping[str, Any], ontology: Mapping[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    if proposal.get("schemaVersion") != "agentlas.workforce-ontology-proposal.v1":
        issues.append("unsupported_proposal_schema")
    if proposal.get("baseOntologyVersion") != ontology.get("ontologyVersion"):
        issues.append("base_ontology_version_mismatch")
    operation = str(proposal.get("operation") or "")
    entity_type = str(proposal.get("entityType") or "")
    if operation not in OPERATIONS:
        issues.append("unsupported_operation")
    if entity_type not in (set(ENTITY_COLLECTIONS) | set(MAP_COLLECTIONS)):
        issues.append("unsupported_entity_type")
    if not proposal.get("proposalId") or not proposal.get("proposerId"):
        issues.append("missing_proposal_identity")
    if not normalized_strings(proposal.get("evidenceRefs")):
        issues.append("missing_evidence_refs")
    reviews = [row for row in proposal.get("reviews") or [] if isinstance(row, Mapping)]
    accepting = {
        str(row.get("reviewerId"))
        for row in reviews
        if row.get("decision") == "accept" and row.get("reviewerId") != proposal.get("proposerId")
    }
    required_reviews = 2 if operation in {"update", "deprecate", "merge"} else 1
    if len(accepting) < required_reviews:
        issues.append(f"insufficient_independent_reviews:{len(accepting)}:{required_reviews}")
    if any(row.get("decision") == "reject" for row in reviews):
        issues.append("proposal_has_rejecting_review")
    patch = proposal.get("patch") if isinstance(proposal.get("patch"), Mapping) else {}
    if not patch:
        issues.append("missing_patch")

    collection_name = ENTITY_COLLECTIONS.get(entity_type)
    if collection_name:
        entity_id = str(patch.get("id") or proposal.get("entityId") or "")
        current = {
            str(item.get("id")): item
            for item in ontology.get(collection_name) or []
            if isinstance(item, Mapping) and item.get("id")
        }
        if operation == "add" and entity_id in current:
            issues.append("entity_already_exists")
        if operation in {"update", "deprecate", "merge"} and entity_id not in current:
            issues.append("entity_not_found")
    return {
        "schemaVersion": "agentlas.workforce-ontology-proposal-validation.v1",
        "status": "rejected" if issues else "accepted",
        "issues": sorted(set(issues)),
        "proposalDigest": canonical_digest(proposal),
        "popularityInfluence": "none",
    }


def apply_ontology_proposal(proposal: Mapping[str, Any], ontology: Mapping[str, Any]) -> dict[str, Any]:
    validation = validate_ontology_proposal(proposal, ontology)
    if validation["status"] != "accepted":
        raise ValueError("ontology proposal rejected: " + ",".join(validation["issues"]))
    result = deepcopy(dict(ontology))
    operation = str(proposal["operation"])
    entity_type = str(proposal["entityType"])
    patch = deepcopy(dict(proposal["patch"]))
    if entity_type in ENTITY_COLLECTIONS:
        collection_name = ENTITY_COLLECTIONS[entity_type]
        rows = [deepcopy(dict(item)) for item in result.get(collection_name) or []]
        entity_id = str(patch.get("id") or proposal.get("entityId"))
        if operation == "add":
            rows.append(patch)
        else:
            for index, row in enumerate(rows):
                if str(row.get("id")) != entity_id:
                    continue
                if operation == "deprecate":
                    row["deprecated"] = True
                    row["replacedBy"] = patch.get("replacedBy")
                    row["deprecationReason"] = patch.get("deprecationReason")
                elif operation == "merge":
                    row["deprecated"] = True
                    row["replacedBy"] = patch.get("replacedBy")
                else:
                    row.update(patch)
                rows[index] = row
                break
        result[collection_name] = sorted(rows, key=lambda item: str(item.get("id")))
    else:
        collection_name = MAP_COLLECTIONS[entity_type]
        mapping = dict(result.get(collection_name) or {})
        key = str(proposal.get("entityId") or patch.get("key") or "")
        if operation == "deprecate":
            mapping.pop(key, None)
        else:
            mapping[key] = patch.get("value")
        result[collection_name] = dict(sorted(mapping.items()))

    previous_version = str(result.get("ontologyVersion"))
    version_payload = {
        "previous": previous_version,
        "proposalDigest": validation["proposalDigest"],
        "content": {key: value for key, value in result.items() if key not in {"ontologyVersion", "contributions"}},
    }
    result["ontologyVersion"] = "awo:" + canonical_digest(version_payload).split(":", 1)[1][:20]
    contributions = [dict(row) for row in result.get("contributions") or [] if isinstance(row, Mapping)]
    contributions.append(
        {
            "proposalId": proposal["proposalId"],
            "proposalDigest": validation["proposalDigest"],
            "baseOntologyVersion": previous_version,
            "ontologyVersion": result["ontologyVersion"],
            "proposerId": proposal["proposerId"],
            "reviewerIds": sorted(
                {
                    str(row.get("reviewerId"))
                    for row in proposal.get("reviews") or []
                    if isinstance(row, Mapping) and row.get("decision") == "accept"
                }
            ),
            "evidenceRefs": normalized_strings(proposal.get("evidenceRefs")),
        }
    )
    result["contributions"] = contributions
    return result


__all__ = ["apply_ontology_proposal", "validate_ontology_proposal"]
