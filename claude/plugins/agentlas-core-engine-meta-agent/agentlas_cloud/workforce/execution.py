"""Pinned BYOM preparation and truthful workforce execution validation."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .contracts import canonical_digest, normalized_strings


def _candidate_lookup(candidate_set: Mapping[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for slot in candidate_set.get("slots") or []:
        if not isinstance(slot, Mapping):
            continue
        slot_id = str(slot.get("slotId") or "")
        for candidate in slot.get("candidates") or []:
            if isinstance(candidate, Mapping) and candidate.get("agentReleaseId"):
                result[(slot_id, str(candidate["agentReleaseId"]))] = dict(candidate)
    return result


def prepare_execution_plan(
    *,
    validation_receipt: Mapping[str, Any],
    candidate_set: Mapping[str, Any],
    runtime_bundles: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Pin exact selected releases to exact BYOM bundles without selecting.

    Hub uses the same invariant after fetching the private directives.  The
    reference function is intentionally incapable of replacing an unavailable
    release with a different candidate.
    """

    issues: list[str] = []
    if validation_receipt.get("status") != "accepted":
        issues.append("selection_not_accepted")
    if validation_receipt.get("candidateSetDigest") != candidate_set.get("candidateSetDigest"):
        issues.append("candidate_set_digest_mismatch")
    if validation_receipt.get("unfilledPosts"):
        issues.append("selected_team_not_executable")
    candidates = _candidate_lookup(candidate_set)
    bundles = {
        str(bundle.get("agentReleaseId")): dict(bundle)
        for bundle in runtime_bundles
        if isinstance(bundle, Mapping) and bundle.get("agentReleaseId")
    }
    roster: list[dict[str, Any]] = []
    selected_release_ids: set[str] = set()
    for assignment in validation_receipt.get("executableTeam") or []:
        if not isinstance(assignment, Mapping):
            issues.append("invalid_executable_assignment")
            continue
        slot_id = str(assignment.get("slotId") or "")
        release_id = str(assignment.get("agentReleaseId") or "")
        selected_release_ids.add(release_id)
        candidate = candidates.get((slot_id, release_id))
        bundle = bundles.get(release_id)
        if candidate is None:
            issues.append(f"selected_release_missing_from_candidate_set:{slot_id}:{release_id}")
            continue
        if bundle is None:
            issues.append(f"runtime_bundle_missing:{release_id}")
            continue
        for field in ("packageHash", "contentDigest"):
            if bundle.get(field) != candidate.get(field):
                issues.append(f"runtime_bundle_{field}_mismatch:{release_id}")
        directive_bundle = bundle.get("directiveBundle") if isinstance(bundle.get("directiveBundle"), Mapping) else {}
        if not directive_bundle:
            directive_bundle = {
                key: bundle.get(key)
                for key in ("systemPrompt", "instructions", "agentMd")
                if isinstance(bundle.get(key), str) and str(bundle.get(key)).strip()
            }
        if not any(isinstance(value, str) and value.strip() for value in directive_bundle.values()):
            issues.append(f"runtime_bundle_directive_missing:{release_id}")
        if bundle.get("status") not in {None, "prepared", "ready"}:
            issues.append(f"runtime_bundle_not_ready:{release_id}")
        roster.append(
            {
                "slotId": slot_id,
                "agentDefinitionId": candidate.get("agentDefinitionId"),
                "agentReleaseId": release_id,
                "releaseVersion": candidate.get("releaseVersion"),
                "packageHash": candidate.get("packageHash"),
                "contentDigest": candidate.get("contentDigest"),
                "entityKind": candidate.get("entityKind"),
                "directiveBundle": dict(directive_bundle),
                "bundleDigest": str(bundle.get("bundleDigest") or canonical_digest(bundle)),
            }
        )
    extras = set(bundles) - selected_release_ids
    if extras:
        issues.extend(f"unselected_runtime_bundle:{release_id}" for release_id in sorted(extras))

    payload = {
        "selectionReceiptId": validation_receipt.get("selectionReceiptId"),
        "candidateSetDigest": candidate_set.get("candidateSetDigest"),
        "executionRoster": roster,
    }
    return {
        "schemaVersion": "agentlas.workforce-execution-plan.v1",
        "status": "rejected" if issues else "prepared",
        "issues": sorted(set(issues)),
        "preparationReceiptId": "workforce-preparation:" + canonical_digest(payload).split(":", 1)[1][:32],
        "selectionReceiptId": validation_receipt.get("selectionReceiptId"),
        "candidateSetDigest": candidate_set.get("candidateSetDigest"),
        "decisionOwner": "host_llm",
        "substitutions": [],
        "executionRoster": roster,
    }


def validate_execution_receipt(receipt: Mapping[str, Any], *, benchmark_mode: bool = False) -> dict[str, Any]:
    """Fail closed unless the nested team produced real child receipts."""

    issues: list[str] = []
    if receipt.get("schemaVersion") != "agentlas.workforce-execution-receipt.v1":
        issues.append("unsupported_execution_receipt")
    if not receipt.get("selectionReceiptId") or not receipt.get("preparationReceiptId"):
        issues.append("missing_selection_or_preparation_receipt")
    orchestrator = receipt.get("orchestrator") if isinstance(receipt.get("orchestrator"), Mapping) else {}
    if not orchestrator.get("modelId") or not orchestrator.get("invocationId"):
        issues.append("missing_orchestrator_model_invocation")
    planner = receipt.get("planner") if isinstance(receipt.get("planner"), Mapping) else {}
    if not planner.get("invocationId") or not planner.get("modelId"):
        issues.append("missing_planner_invocation")
    if planner.get("parseSuccess") is not True:
        issues.append("planner_structured_output_failed")
    if planner.get("fallbackUsed") is True:
        issues.append("planner_fallback_used")

    workers = receipt.get("workers") if isinstance(receipt.get("workers"), list) else []
    if not workers:
        issues.append("missing_worker_invocations")
    invocation_ids: set[str] = set()
    for worker in workers:
        if not isinstance(worker, Mapping):
            issues.append("invalid_worker_receipt")
            continue
        required = ("slotId", "agentReleaseId", "packageHash", "contentDigest", "modelId", "invocationId")
        if any(not worker.get(field) for field in required):
            issues.append("incomplete_worker_receipt")
        invocation_id = str(worker.get("invocationId") or "")
        if invocation_id in invocation_ids:
            issues.append("duplicate_child_invocation_id")
        if invocation_id:
            invocation_ids.add(invocation_id)
        if worker.get("status") != "completed":
            issues.append(f"worker_not_completed:{worker.get('slotId')}")
        if not normalized_strings(worker.get("handoffArtifactRefs")):
            issues.append(f"worker_handoff_missing:{worker.get('slotId')}")

    for phase in ("synthesis", "verifier"):
        phase_receipt = receipt.get(phase) if isinstance(receipt.get(phase), Mapping) else {}
        if not phase_receipt.get("invocationId") or not phase_receipt.get("modelId"):
            issues.append(f"missing_{phase}_invocation")
        if phase_receipt.get("status") != "completed":
            issues.append(f"{phase}_not_completed")
    verifier = receipt.get("verifier") if isinstance(receipt.get("verifier"), Mapping) else {}
    if verifier.get("verdict") != "pass":
        issues.append("verifier_did_not_pass")
    if benchmark_mode and len(workers) < 2:
        issues.append("benchmark_requires_multiple_workers")

    claimed = str(receipt.get("status") or "")
    if claimed == "passed" and issues:
        issues.append("false_pass_claim")
    return {
        "schemaVersion": "agentlas.workforce-execution-validation.v1",
        "status": "rejected" if issues else "accepted",
        "issues": sorted(set(issues)),
        "executionId": receipt.get("executionId"),
        "validatedDigest": canonical_digest(receipt),
    }


__all__ = ["prepare_execution_plan", "validate_execution_receipt"]
