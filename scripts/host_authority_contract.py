"""Proves the `host` permission mode contract end to end with real functions.

Desktop (2026-09-05, commit 26d5025a) started emitting, for a roster row whose
package declares no tool ceiling, a `host` permission policy plus a
`native-sandbox` enforcement receipt (sandboxMode "host-native", toolInventory
"policy-filtered", ephemeral=false, ignoredUserConfig=false, ignoredRules=false,
grantedToolIds from the grant). This check calls the real workforce functions
that own that contract instead of matching source strings, so a future edit
that quietly breaks the shape fails here first.

Five things are proven:
 1. host_permission_policy() validates and is host/host/host on network,
    shell, mcp; declared read patterns keep manifest-allowlist.
 2. deny_all_permission_policy() still validates (legacy rows keep working).
 3. _capability_assignment_policy_issue returns None for the three builtin
    tools and for an mcp tool under a host policy, and "outside_mcp_policy"
    for an mcp tool under a deny policy.
 4. A minimal synthetic invocation shaped like Desktop's native-sandbox
    enforcement receipt passes `_invocation`'s permission-enforcement checks
    with no issues, and a no-authority-sandbox enforcement carrying approvals
    is rejected (the gate can go red).
 5. A plan row's permissionPolicy validates against
    schemas/workforce-execution-plan.schema.json with the same
    Draft202012Validator approach execution.py uses.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from agentlas_cloud.workforce.execution import (  # noqa: E402
    _capability_assignment_policy_issue,
    _invocation,
    deny_all_permission_policy,
    host_permission_policy,
    validate_permission_policy,
    workforce_permission_policy_digest,
    workforce_tool_inventory_digest,
)


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def check_host_permission_policy() -> dict:
    policy = host_permission_policy()
    validated = validate_permission_policy(policy)
    if validated.get("network") != "host":
        fail("host_permission_policy: network is not host")
    if validated.get("shell") != "host":
        fail("host_permission_policy: shell is not host")
    if validated.get("mcp", {}).get("mode") != "host":
        fail("host_permission_policy: mcp.mode is not host")
    if validated.get("fileRead", {}).get("mode") != "host":
        fail("host_permission_policy (no read patterns): fileRead.mode is not host")

    scoped = host_permission_policy(
        allow_read=["AGENTS.md", "skills/**"],
        deny_read=["signing/**", "credentials/**"],
    )
    validated_scoped = validate_permission_policy(scoped)
    if validated_scoped.get("fileRead", {}).get("mode") != "manifest-allowlist":
        fail("host_permission_policy (with read patterns): fileRead.mode did not stay manifest-allowlist")
    print("PASS: host_permission_policy() validates and is host/host/host, "
          "and keeps manifest-allowlist with declared read patterns")
    return policy


def check_deny_all_permission_policy() -> dict:
    policy = deny_all_permission_policy()
    validated = validate_permission_policy(policy)
    if validated.get("network") != "deny" or validated.get("shell") != "deny":
        fail("deny_all_permission_policy: no longer deny/deny")
    print("PASS: deny_all_permission_policy() still validates (legacy rows keep working)")
    return policy


def check_capability_assignment_policy_issue(host_policy: dict, deny_policy: dict) -> None:
    for tool_id in ("builtin:shell", "builtin:network", "builtin:file-read"):
        issue = _capability_assignment_policy_issue(
            {"provider": "builtin", "toolId": tool_id}, host_policy
        )
        if issue is not None:
            fail(f"_capability_assignment_policy_issue: {tool_id} under host policy raised {issue!r}")

    mcp_assignment = {"provider": "mcp", "toolId": "some.mcp.tool"}
    issue = _capability_assignment_policy_issue(mcp_assignment, host_policy)
    if issue is not None:
        fail(f"_capability_assignment_policy_issue: mcp tool under host policy raised {issue!r}")

    issue = _capability_assignment_policy_issue(mcp_assignment, deny_policy)
    if issue != "outside_mcp_policy":
        fail(
            "_capability_assignment_policy_issue: mcp tool under deny policy "
            f"expected 'outside_mcp_policy', got {issue!r}"
        )
    print(
        "PASS: _capability_assignment_policy_issue is None for builtin:shell/network/"
        "file-read and mcp under host, and 'outside_mcp_policy' for mcp under deny"
    )


def _fake_sha256(seed: str) -> str:
    return "sha256:" + hashlib.sha256(seed.encode("utf-8")).hexdigest()


def check_enforcement_receipt(host_policy: dict) -> None:
    policy_digest = workforce_permission_policy_digest(host_policy)
    tool_inventory = {
        "schemaVersion": "agentlas.workforce-tool-inventory.v1",
        "executionContextDigest": _fake_sha256("execution-context"),
        "observedAt": "2026-09-05T00:00:00Z",
        "entries": [
            {
                "slotId": "slot-1",
                "agentReleaseId": "release-1",
                "permissionPolicyDigest": policy_digest,
                "provider": "builtin",
                "toolId": "builtin:shell",
                "serverId": None,
                "description": "host-authority contract gate fixture entry",
                "inputSchemaDigest": None,
                "runtimeIds": ["runtime-desktop-1"],
                "selectiveEnforcement": "exact-tool-allowlist",
                "capabilityIds": ["capability-1"],
                "status": "ready",
            }
        ],
    }
    tool_inventory_digest = workforce_tool_inventory_digest(tool_inventory)
    granted_tool_ids = ["mcp:example.tool"]

    def make_invocation(**enforcement_overrides) -> dict:
        evidence = {
            "runtimeKind": "desktop",
            "runtimeVersion": "1.2.44",
            "sandboxMode": "host-native",
            "toolInventory": "policy-filtered",
            "disabledCapabilities": [],
            "ephemeral": False,
            "ignoredUserConfig": False,
            "ignoredRules": False,
            "toolInventoryDigest": tool_inventory_digest,
            "grantedToolIds": granted_tool_ids,
        }
        evidence.update(enforcement_overrides.pop("evidence_overrides", {}))
        enforcement = {
            "permissionPolicyDigest": policy_digest,
            "enforcementMode": "native-sandbox",
            "status": "enforced",
            "approvalReceiptIds": [],
            "enforcementEvidence": evidence,
        }
        enforcement.update(enforcement_overrides)
        return {
            "invocationId": "inv-1",
            "modelId": "model-1",
            "runtimeId": "runtime-desktop-1",
            "provider": "anthropic",
            "status": "completed",
            "requestedEffort": None,
            "appliedEffort": None,
            "effortEvidence": "not-observable",
            "permissionEnforcement": enforcement,
        }

    positive = make_invocation()
    issues: list[str] = []
    _invocation(
        positive,
        label="worker",
        issues=issues,
        invocation_ids=set(),
        permission_policy_digest=policy_digest,
        expected_tool_inventory_digest=tool_inventory_digest,
        expected_granted_tool_ids=granted_tool_ids,
        eligible_runtime_ids={"runtime-desktop-1"},
    )
    if issues:
        fail(f"native-sandbox host-authority invocation raised issues: {issues}")
    print("PASS: Desktop's synthetic native-sandbox host-authority enforcement receipt "
          "passes _invocation with no issues")

    negative = make_invocation(
        enforcementMode="no-authority-sandbox",
        approvalReceiptIds=["approval-1"],
        evidence_overrides={
            "sandboxMode": "read-only",
            "toolInventory": "empty",
            "disabledCapabilities": ["builtin:shell"],
            "ephemeral": True,
            "ignoredUserConfig": True,
            "ignoredRules": True,
            "grantedToolIds": [],
        },
    )
    negative_issues: list[str] = []
    _invocation(
        negative,
        label="worker",
        issues=negative_issues,
        invocation_ids=set(),
        permission_policy_digest=policy_digest,
        expected_tool_inventory_digest=tool_inventory_digest,
        expected_granted_tool_ids=[],
        eligible_runtime_ids={"runtime-desktop-1"},
    )
    if "worker_no_authority_has_approvals" not in negative_issues:
        fail(
            "negative case: a no-authority-sandbox enforcement carrying approvals "
            f"was NOT rejected; issues={negative_issues}"
        )
    print(
        "PASS (negative case shown red): no-authority-sandbox enforcement with "
        f"approvals is rejected -> {negative_issues}"
    )


def check_plan_schema(host_policy: dict) -> None:
    from agentlas_cloud._vendor import load_jsonschema

    Draft202012Validator = load_jsonschema().Draft202012Validator
    schema_path = REPO_ROOT / "schemas" / "workforce-execution-plan.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    permission_policy_schema = {
        "$schema": schema["$schema"],
        "$id": schema["$id"] + "#permission-policy-check",
        "$ref": "#/$defs/permissionPolicy",
        "$defs": schema["$defs"],
    }
    validator = Draft202012Validator(permission_policy_schema)
    errors = list(validator.iter_errors(host_policy))
    if errors:
        fail(f"host permission policy failed schema validation: {errors[0]}")
    print(
        "PASS: a plan row's host permissionPolicy validates against "
        "schemas/workforce-execution-plan.schema.json (Draft202012Validator)"
    )


def main() -> int:
    host_policy = check_host_permission_policy()
    deny_policy = check_deny_all_permission_policy()
    check_capability_assignment_policy_issue(host_policy, deny_policy)
    check_enforcement_receipt(host_policy)
    check_plan_schema(host_policy)
    print("ALL PASS: host authority contract holds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
