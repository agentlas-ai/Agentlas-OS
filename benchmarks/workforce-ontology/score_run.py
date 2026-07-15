#!/usr/bin/env python3
"""Score one real Desktop/Terminal Agent Workforce Ontology benchmark run.

The scorer does not call a model and never chooses a worker.  It consumes the
artifacts emitted by a host runtime, revalidates the frozen Hub decision, and
checks that nested planner/worker/synthesis/verifier invocations really exist.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from agentlas_cloud.workforce.execution import (
    project_execution_context,
    validate_execution_receipt,
    workforce_execution_context_digest,
)
from agentlas_cloud.workforce.contracts import (
    WORKFORCE_ONTOLOGY_SNAPSHOT_SHA256,
    WORKFORCE_ONTOLOGY_VERSION,
)
from agentlas_cloud.workforce.selection import validate_host_selection


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _strings(value: Any) -> set[str]:
    return {str(item) for item in value or [] if isinstance(item, str) and item}


def _slot_matches(slot: Mapping[str, Any], family: Mapping[str, Any]) -> bool:
    for slot_keys, family_key in (
        (("requiredCommunities", "optionalCommunities"), "anyCommunities"),
        (("requiredRoles",), "anyRoles"),
        (("requiredSkills", "optionalSkills"), "anySkills"),
    ):
        expected = _strings(family.get(family_key))
        if any(_strings(slot.get(slot_key)) & expected for slot_key in slot_keys):
            return True
    return False


def _distinct_family_assignment(
    families: list[Mapping[str, Any]],
    slots: list[Mapping[str, Any]],
) -> dict[str, str] | None:
    options = {
        str(family.get("familyId")): [
            str(slot.get("slotId")) for slot in slots if _slot_matches(slot, family)
        ]
        for family in families
    }
    ordered = sorted(options, key=lambda family_id: (len(options[family_id]), family_id))

    def visit(index: int, used: set[str], result: dict[str, str]) -> dict[str, str] | None:
        if index == len(ordered):
            return dict(result)
        family_id = ordered[index]
        for slot_id in options[family_id]:
            if slot_id in used:
                continue
            used.add(slot_id)
            result[family_id] = slot_id
            found = visit(index + 1, used, result)
            if found is not None:
                return found
            used.remove(slot_id)
            result.pop(family_id, None)
        return None

    return visit(0, set(), {})


def score_run(spec: Mapping[str, Any], run: Mapping[str, Any]) -> dict[str, Any]:
    issues: list[str] = []
    work_order = _mapping(run.get("workOrder"))
    candidate_set = _mapping(run.get("candidateSet"))
    selection = _mapping(run.get("selection"))
    recorded_validation = _mapping(run.get("selectionValidation"))
    selection_receipt = _mapping(run.get("selectionReceipt"))
    prepared_execution = _mapping(run.get("preparedExecution"))
    tool_inventory_snapshot = _mapping(run.get("toolInventorySnapshot"))
    execution_receipt = _mapping(run.get("executionReceipt"))

    expected_ontology_version = str(spec.get("ontologyVersion") or "")
    expected_ontology_hash = str(spec.get("ontologySnapshotSha256") or "")
    if expected_ontology_version != WORKFORCE_ONTOLOGY_VERSION:
        issues.append("benchmark_spec_ontology_version_drift")
    if expected_ontology_hash != WORKFORCE_ONTOLOGY_SNAPSHOT_SHA256:
        issues.append("benchmark_spec_ontology_snapshot_drift")
    if str(work_order.get("ontologyVersion") or "") != expected_ontology_version:
        issues.append("work_order_ontology_version_drift")
    if str(candidate_set.get("ontologyVersion") or "") != expected_ontology_version:
        issues.append("candidate_set_ontology_version_drift")

    slots = [row for row in work_order.get("roleSlots") or [] if isinstance(row, Mapping)]
    families = [row for row in spec.get("expectedRoleFamilies") or [] if isinstance(row, Mapping)]
    family_assignment = _distinct_family_assignment(families, slots)
    if family_assignment is None:
        for family in families:
            if not any(_slot_matches(slot, family) for slot in slots):
                issues.append(f"missing_role_family:{family.get('familyId')}")
        if not any(issue.startswith("missing_role_family:") for issue in issues):
            issues.append("role_families_not_decomposed_into_distinct_slots")

    forbidden = _strings(spec.get("forbiddenCommunities"))
    for slot in slots:
        requested_communities = _strings(slot.get("requiredCommunities")) | _strings(
            slot.get("optionalCommunities")
        )
        for item in sorted(forbidden & requested_communities):
            issues.append(
                f"work_order_requests_forbidden_community:{slot.get('slotId')}:{item}"
            )
    for candidate_slot in candidate_set.get("slots") or []:
        if not isinstance(candidate_slot, Mapping):
            continue
        for candidate in candidate_slot.get("candidates") or []:
            if isinstance(candidate, Mapping) and forbidden & _strings(candidate.get("communities")):
                issues.append(f"forbidden_candidate_recalled:{candidate.get('agentReleaseId')}")

    try:
        validation = validate_host_selection(
            selection,
            candidate_set=candidate_set,
            work_order=work_order,
        )
    except Exception as exc:  # contract errors are a benchmark failure, not a scorer crash
        validation = {"status": "rejected", "issues": [f"selection_validation_exception:{type(exc).__name__}"]}
    if validation.get("status") != "accepted":
        issues.extend(str(item) for item in validation.get("issues") or ["host_selection_rejected"])
    if recorded_validation and recorded_validation.get("selectionReceiptId") != validation.get("selectionReceiptId"):
        issues.append("recorded_selection_receipt_drift")
    if recorded_validation.get("substitutions"):
        issues.append("selection_contains_substitutions")

    required_sequence = [str(item) for item in spec.get("requiredMcpSequence") or []]
    observed_sequence = [
        str(row.get("tool"))
        for row in selection_receipt.get("mcpCalls") or []
        if isinstance(row, Mapping)
    ]
    if observed_sequence != required_sequence:
        issues.append("mcp_sequence_missing_or_out_of_order")
    if selection_receipt.get("decisionOwner") != "host_llm":
        issues.append("selection_receipt_decision_owner_not_host_llm")
    if selection_receipt.get("historyInfluence") != "none":
        issues.append("selection_receipt_history_influence_detected")
    if selection_receipt.get("substitutions"):
        issues.append("selection_receipt_contains_substitutions")
    leader_phases = [
        str(row.get("phase"))
        for row in selection_receipt.get("leaderInvocations") or []
        if isinstance(row, Mapping) and row.get("status") == "completed"
    ]
    if leader_phases != ["work-order", "selection"]:
        issues.append("host_llm_leader_invocations_missing")

    if not prepared_execution:
        issues.append("prepared_execution_missing")
    else:
        try:
            expected_context = project_execution_context(
                work_order=work_order,
                selection=selection,
                validation_receipt=validation,
                candidate_set=candidate_set,
            )
            expected_context_digest = workforce_execution_context_digest(expected_context)
            if prepared_execution.get("executionContext") != expected_context:
                issues.append("prepared_execution_context_drift")
            if prepared_execution.get("executionContextDigest") != expected_context_digest:
                issues.append("prepared_execution_context_digest_drift")
        except Exception as exc:
            issues.append(f"prepared_execution_context_invalid:{type(exc).__name__}")
    execution_validation = validate_execution_receipt(
        execution_receipt,
        execution_plan=prepared_execution,
        tool_inventory=tool_inventory_snapshot,
        benchmark_mode=True,
    )
    if execution_validation.get("status") != "accepted":
        issues.extend(str(item) for item in execution_validation.get("issues") or [])
    workers = [row for row in execution_receipt.get("workers") or [] if isinstance(row, Mapping)]
    minimum_workers = int(spec.get("minimumDistinctWorkerInvocations") or 2)
    worker_invocations: set[str] = set()
    for row in workers:
        direct = _mapping(row.get("directInvocation"))
        if direct.get("invocationId"):
            worker_invocations.add(str(direct["invocationId"]))
    for nested_execution in execution_receipt.get("nestedExecutions") or []:
        if not isinstance(nested_execution, Mapping):
            continue
        for nested_worker in nested_execution.get("workers") or []:
            if isinstance(nested_worker, Mapping) and nested_worker.get("invocationId"):
                worker_invocations.add(str(nested_worker["invocationId"]))
    if len(worker_invocations) < minimum_workers:
        issues.append(f"insufficient_distinct_worker_invocations:{len(worker_invocations)}:{minimum_workers}")

    unique_issues = sorted(set(issues))
    return {
        "schemaVersion": "agentlas.workforce-benchmark-result.v1",
        "benchmarkId": spec.get("benchmarkId"),
        "status": "pass" if not unique_issues else "fail",
        "issues": unique_issues,
        "roleFamilySlots": family_assignment or {},
        "decisionModel": selection_receipt.get("decisionModel"),
        "decisionRuntime": selection_receipt.get("decisionRuntime"),
        "candidateSetDigest": candidate_set.get("candidateSetDigest"),
        "selectionReceiptId": validation.get("selectionReceiptId"),
        "executionId": execution_receipt.get("executionId"),
        "workerInvocationCount": len(worker_invocations),
        "mcpSequence": observed_sequence,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path, help="JSON object containing real runtime benchmark artifacts")
    parser.add_argument(
        "--spec",
        type=Path,
        default=Path(__file__).with_name("difficult-payment-platform.json"),
    )
    args = parser.parse_args()
    spec = json.loads(args.spec.read_text(encoding="utf-8"))
    run = json.loads(args.run.read_text(encoding="utf-8"))
    result = score_run(spec, run)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
