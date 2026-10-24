"""Read-only execution guidance for hosts consuming pinned Workforce plans.

This metadata describes authority boundaries; it neither grants authority nor
observes a host. Keep it outside preparations so existing signatures and cached
runtime envelopes remain authoritative and byte-for-byte reusable.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from .execution import deny_all_permission_policy, validate_permission_policy


HOST_EXECUTION_CONTRACT_SCHEMA = "agentlas.workforce-host-execution-contract.v1"


def _row_authority(
    row: Mapping[str, Any], index: int, *, projected: bool, plan_ref: list[str],
) -> dict[str, Any]:
    raw_policy = row.get("permissionPolicy")
    try:
        if not isinstance(raw_policy, Mapping):
            raise ValueError("permission_policy_missing")
        policy = validate_permission_policy(raw_policy)
        valid = True
    except (TypeError, ValueError, RecursionError):
        policy = deny_all_permission_policy()
        valid = False
    host_authority = (
        policy["network"] == "host"
        and policy["shell"] == "host"
        and policy["mcp"]["mode"] == "host"
        and policy["fileRead"]["mode"] in {"host", "manifest-allowlist"}
    )
    row_ref = [*plan_ref, "executionRoster", index]

    def content_ref(field: str) -> list[Any]:
        if projected and row.get("contentDigest") and row.get(field) is not None:
            return ["bundleContents", row["contentDigest"], field]
        return [*row_ref, field]
    return {
        **{
            key: deepcopy(row[key])
            for key in (
                "slotId", "agentDefinitionId", "agentReleaseId", "releaseVersion",
                "packageHash", "contentDigest", "bundleDigest", "permissionPolicyDigest",
                "executionGraphDigest", "entityKind",
            )
            if key in row
        },
        "authorityClass": "invalid" if not valid else "host" if host_authority else "restricted",
        "permissionPolicyStatus": "valid" if valid else "invalid",
        "packageRead": {"scope": "package-contents", **policy["fileRead"]},
        "workspaceFileRead": "deny" if policy["fileRead"]["mode"] == "deny" else "host",
        "runtimeAuthority": {
            "network": policy["network"],
            "shell": policy["shell"],
            "mcp": policy["mcp"],
            "unknownTools": policy["unknownTools"],
        },
        "directiveBundleRef": content_ref("directiveBundle"),
        "executionGraphRef": content_ref("executionGraph"),
    }


def host_execution_contract(
    plan: Mapping[str, Any], *, projected: bool = False, wrapped: bool = True,
) -> dict[str, Any]:
    """Return additive metadata without changing any pinned field in ``plan``."""
    roster = plan.get("executionRoster")
    plan_ref = ["executionPlan"] if wrapped else []
    return {
        "schemaVersion": HOST_EXECUTION_CONTRACT_SCHEMA,
        "referenceRoot": "prepare.v2-response" if projected else "preparation" if wrapped else "execution-plan",
        "routing": {
            "preferred": "current-host-native",
            "fallback": "external-host-adapter",
            "fallbackCondition": "current-host-native-unavailable",
            "hostAvailability": "not-observed",
            "automaticHostSwitch": False,
        },
        "authority": {
            "source": "current-host",
            "packageReadAllowlistScope": "package-contents",
            "grantsTools": False,
            "hostAuthorizationRequired": True,
            "explicitRowRestrictions": "preserved",
            "unsupportedRequiredEnforcement": "block-affected-action",
        },
        "invocation": {
            "identity": "exact-prepared-roster",
            "directives": "pinned-directive-bundle",
            "teamExpansion": "pinned-execution-graph",
            "distinctWorkers": True,
            "handoffs": "actual-upstream-artifacts",
            "dependencyOrder": "execution-context-edges",
            "synthesis": "distinct-invocation",
            "verifier": "independent-invocation",
            "substitutions": "forbidden",
            "executionContextRef": [*plan_ref, "executionContext"],
        },
        "evidence": {
            "validationStage": "post-execution",
            "missingTelemetryBlocksHostExecution": False,
            "completionClaimRequiresValidatedEvidence": True,
            "completionClaimScope": "workforce-execution-receipt",
            "fabricateReceipt": False,
            "validationTool": "workforce.validate_execution_receipt",
            "unvalidatedEvidenceStatus": "unvalidated",
        },
        "rosterAuthority": [
            _row_authority(row, index, projected=projected, plan_ref=plan_ref)
            for index, row in enumerate(roster if isinstance(roster, list) else [])
            if isinstance(row, Mapping)
        ],
    }


def goal_runtime_execution_contract(context: Mapping[str, Any]) -> dict[str, Any]:
    """Enrich outer runtime entries while retaining exact cached preparations."""
    goals = context.get("goals")
    if not isinstance(goals, list):
        return dict(context)
    projected_goals = []
    for goal in goals:
        if not isinstance(goal, Mapping) or not isinstance(goal.get("plans"), list):
            projected_goals.append(goal)
            continue
        entries = []
        for entry in goal["plans"]:
            if not isinstance(entry, Mapping) or entry.get("status") != "ready":
                entries.append(entry)
                continue
            preparation = entry.get("preparation")
            if not isinstance(preparation, Mapping):
                entries.append(entry)
                continue
            plan = preparation.get("executionPlan", preparation)
            if not isinstance(plan, Mapping):
                entries.append(entry)
                continue
            entries.append({
                **entry,
                "hostExecutionContract": host_execution_contract(
                    plan, wrapped="executionPlan" in preparation,
                ),
            })
        projected_goals.append({**goal, "plans": entries})
    return {**context, "goals": projected_goals}
