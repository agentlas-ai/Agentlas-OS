"""Provider-neutral bridge from pinned Workforce plans to a host adapter.

Core owns preparation identities, execution order, receipt construction, and
validation.  An explicitly selected adapter owns native model/tool execution
and reports measured invocation evidence over one JSON request/response per
process.  The transport deliberately accepts argv, never a shell command.

Adapter v1 contract
-------------------
Each process reads exactly one JSON object from stdin and writes exactly one
JSON object to stdout.  Requests have the exact keys ``schemaVersion``,
``requestId``, ``executionId``, ``phase``, ``projectDir``, ``preparation``,
``pinnedRosterRow``, ``graphNode``, ``toolInventory``,
``capabilityBindingPlan``, and ``inputs``.  The preparation is the exact cached
Core envelope; its ``executionPlan`` member (or the envelope itself for a bare
v5 plan) is authoritative.

The ``observe`` response has the exact keys ``schemaVersion``, ``requestId``,
``phase``, and ``toolInventory``.  Every model phase returns ``invocation``,
``artifacts``, and a non-null JSON ``output`` in addition to the correlation
keys; ``planner`` also returns ``bindingInventory``.  An artifact descriptor is
exactly ``{artifactId, relativePath, sha256}``.  Core verifies and snapshots
declared project files, materializes text/JSON output in its private execution
directory, passes only those verified manifests to downstream calls, constructs
the pinned v2 receipt, and validates it with the existing strict validator.
Invocation objects must match the phase-specific definitions in
``schemas/workforce-execution-receipt.schema.json``.  A nonzero exit, timeout,
extra response key, correlation mismatch, invalid pin, changed artifact, or
validator refusal terminates the run without exposing an execution receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
from typing import Any, Callable, Mapping, Sequence
import uuid

from .contracts import canonical_digest
from .execution import (
    WORKFORCE_CAPABILITY_BINDING_PLAN_SCHEMA,
    WORKFORCE_EXECUTION_PLAN_SCHEMA,
    WORKFORCE_EXECUTION_RECEIPT_SCHEMA,
    WORKFORCE_RUNTIME_BUNDLE_DIGEST_SCHEMA,
    validate_capability_binding_plan,
    validate_execution_receipt,
    validate_tool_inventory,
    workforce_capability_binding_plan_digest,
    workforce_execution_context_digest,
    workforce_execution_graph_digest,
    workforce_permission_policy_digest,
    workforce_runtime_bundle_digest,
    workforce_tool_inventory_digest,
)
from .goal_binding import WorkforceGoalStore


HOST_EXECUTOR_REQUEST_SCHEMA = "agentlas.workforce-host-executor-request.v1"
HOST_EXECUTOR_RESPONSE_SCHEMA = "agentlas.workforce-host-executor-response.v1"
HOST_EXECUTION_RESULT_SCHEMA = "agentlas.workforce-host-execution-result.v1"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{1,255}$")
_INVOCATION_PHASES = frozenset({
    "orchestrator",
    "planner",
    "direct-worker",
    "team-manager-plan",
    "team-worker",
    "team-manager-synthesis",
    "synthesis",
    "verifier",
})
_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_PREPARATION_WRAPPER_SCHEMAS = frozenset({
    "agentlas.workforce-federated-preparation.v1",
    "agentlas.workforce-terminal-continuation.v1",
    "agentlas.workforce-desktop-continuation.v1",
})


class WorkforceHostExecutorError(ValueError):
    """Finite refusal raised before a receipt can truthfully be produced."""

    def __init__(self, code: str, *, detail: str | None = None):
        super().__init__(code)
        self.code = code
        self.detail = detail


def parse_adapter_argv(value: str) -> list[str]:
    """Parse an explicit JSON argv array without invoking a shell."""

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise WorkforceHostExecutorError("workforce_adapter_argv_json_invalid") from exc
    if not isinstance(parsed, list):
        raise WorkforceHostExecutorError("workforce_adapter_argv_invalid")
    return _validated_adapter_argv(parsed)


def _validated_adapter_argv(value: Sequence[str]) -> list[str]:
    if (
        isinstance(value, (str, bytes))
        or not (1 <= len(value) <= 32)
        or any(not isinstance(item, str) or not item or len(item) > 4096 for item in value)
    ):
        raise WorkforceHostExecutorError("workforce_adapter_argv_invalid")
    return list(value)


def _execution_plan(preparation: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = preparation.get("executionPlan")
    if nested is not None:
        if (
            preparation.get("schemaVersion") not in _PREPARATION_WRAPPER_SCHEMAS
            or preparation.get("status") != "prepared"
            or not isinstance(nested, Mapping)
        ):
            raise WorkforceHostExecutorError("workforce_execution_preparation_not_ready")
        if preparation.get("schemaVersion") == "agentlas.workforce-federated-preparation.v1":
            expected_wrapper_digest = canonical_digest({
                key: value
                for key, value in preparation.items()
                if key != "federatedPreparationDigest"
            })
            if preparation.get("federatedPreparationDigest") != expected_wrapper_digest:
                raise WorkforceHostExecutorError(
                    "workforce_execution_preparation_wrapper_pin_mismatch"
                )
        plan = nested
    else:
        plan = preparation
    if (
        not isinstance(plan, Mapping)
        or plan.get("schemaVersion") != WORKFORCE_EXECUTION_PLAN_SCHEMA
        or plan.get("status") != "prepared"
        or plan.get("issues") != []
        or not isinstance(plan.get("executionRoster"), list)
        or not plan.get("executionRoster")
    ):
        raise WorkforceHostExecutorError("workforce_execution_plan_not_ready")
    _assert_execution_plan_pins(plan)
    return plan


def _assert_execution_plan_pins(plan: Mapping[str, Any]) -> None:
    """Reject cached-plan drift before any adapter process is started."""

    context = plan.get("executionContext")
    if not isinstance(context, Mapping):
        raise WorkforceHostExecutorError("workforce_execution_context_invalid")
    try:
        expected_context_digest = workforce_execution_context_digest(context)
    except (TypeError, ValueError, RecursionError) as exc:
        raise WorkforceHostExecutorError("workforce_execution_context_invalid") from exc
    if plan.get("executionContextDigest") != expected_context_digest:
        raise WorkforceHostExecutorError("workforce_execution_context_pin_mismatch")
    if plan.get("decisionOwner") != "host_llm" or plan.get("substitutions") != []:
        raise WorkforceHostExecutorError("workforce_execution_plan_authority_invalid")

    seen_pairs: set[tuple[str, str]] = set()
    roster = plan["executionRoster"]
    for row in roster:
        if not isinstance(row, Mapping):
            raise WorkforceHostExecutorError("workforce_execution_roster_invalid")
        pair = (str(row.get("slotId") or ""), str(row.get("agentReleaseId") or ""))
        if not all(_ID_RE.fullmatch(value) for value in pair) or pair in seen_pairs:
            raise WorkforceHostExecutorError("workforce_execution_roster_identity_invalid")
        seen_pairs.add(pair)
        policy = row.get("permissionPolicy")
        graph = row.get("executionGraph")
        try:
            policy_digest = (
                workforce_permission_policy_digest(policy)
                if isinstance(policy, Mapping)
                else None
            )
            graph_digest = (
                workforce_execution_graph_digest(graph)
                if isinstance(graph, Mapping)
                else None
            )
            bundle_digest = workforce_runtime_bundle_digest(row)
        except (TypeError, ValueError, RecursionError) as exc:
            raise WorkforceHostExecutorError("workforce_execution_roster_pin_invalid") from exc
        if (
            row.get("permissionPolicyDigest") != policy_digest
            or row.get("executionGraphDigest") != graph_digest
            or row.get("bundleDigest") != bundle_digest
            or row.get("bundleDigestSchema") != WORKFORCE_RUNTIME_BUNDLE_DIGEST_SCHEMA
        ):
            raise WorkforceHostExecutorError("workforce_execution_roster_pin_mismatch")

    receipt_payload = {
        "selectionReceiptId": plan.get("selectionReceiptId"),
        "candidateSetDigest": plan.get("candidateSetDigest"),
        "executionContextDigest": plan.get("executionContextDigest"),
        "executionRoster": roster,
    }
    expected_receipt_id = (
        "workforce-preparation:"
        + canonical_digest(receipt_payload).split(":", 1)[1][:32]
    )
    if plan.get("preparationReceiptId") != expected_receipt_id:
        raise WorkforceHostExecutorError("workforce_execution_preparation_pin_mismatch")


def _select_ready_plan(
    runtime_context: Mapping[str, Any],
    *,
    requested_goal_id: str | None,
    requested_revision: int | None = None,
) -> tuple[str, int, Mapping[str, Any]]:
    goals = [goal for goal in (runtime_context.get("goals") or []) if isinstance(goal, Mapping)]
    if requested_goal_id is not None:
        goals = [goal for goal in goals if goal.get("goalId") == requested_goal_id]
    if not goals:
        raise WorkforceHostExecutorError("workforce_execution_goal_not_bound")
    if len(goals) != 1:
        raise WorkforceHostExecutorError("workforce_execution_goal_ambiguous")
    goal = goals[0]
    plans = [
        plan for plan in (goal.get("plans") or [])
        if isinstance(plan, Mapping)
        and isinstance(plan.get("revision"), int)
    ]
    if not plans:
        raise WorkforceHostExecutorError("workforce_execution_plan_refresh_required")
    selected = max(plans, key=lambda value: int(value["revision"]))
    if requested_revision is not None and selected.get("revision") != requested_revision:
        raise WorkforceHostExecutorError("workforce_execution_plan_changed_during_run")
    if selected.get("status") != "ready" or not isinstance(selected.get("preparation"), Mapping):
        raise WorkforceHostExecutorError("workforce_execution_plan_refresh_required")
    return str(goal["goalId"]), int(selected["revision"]), selected["preparation"]


def _json_size(value: Any) -> int:
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, RecursionError) as exc:
        raise WorkforceHostExecutorError("workforce_adapter_non_json_value") from exc


def _request_id(execution_id: str, phase: str, ordinal: int) -> str:
    return f"request:{execution_id.split(':', 1)[1]}:{phase}:{ordinal}"


def _call_adapter(
    adapter_argv: Sequence[str],
    request: Mapping[str, Any],
    *,
    project_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    if _json_size(request) > 32 * 1024 * 1024:
        raise WorkforceHostExecutorError("workforce_adapter_request_too_large")
    request_bytes = json.dumps(
        request, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    try:
        with tempfile.TemporaryFile() as stdout_file:
            process = subprocess.Popen(
                list(adapter_argv),
                stdin=subprocess.PIPE,
                stdout=stdout_file,
                stderr=subprocess.DEVNULL,
                cwd=project_dir,
                start_new_session=os.name == "posix",
            )
            try:
                process.communicate(input=request_bytes, timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                try:
                    if os.name == "posix":
                        os.killpg(process.pid, signal.SIGKILL)
                    else:
                        process.kill()
                except ProcessLookupError:
                    pass
                process.wait()
                raise WorkforceHostExecutorError("workforce_adapter_timeout") from exc
            if process.returncode != 0:
                raise WorkforceHostExecutorError(
                    "workforce_adapter_failed",
                    detail=f"adapter exited with status {process.returncode}",
                )
            stdout_file.seek(0)
            response_bytes = stdout_file.read(16 * 1024 * 1024 + 1)
    except WorkforceHostExecutorError:
        raise
    except OSError as exc:
        raise WorkforceHostExecutorError("workforce_adapter_unavailable") from exc
    if len(response_bytes) > 16 * 1024 * 1024:
        raise WorkforceHostExecutorError("workforce_adapter_response_too_large")
    try:
        response = json.loads(response_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkforceHostExecutorError("workforce_adapter_response_invalid_json") from exc
    if not isinstance(response, dict):
        raise WorkforceHostExecutorError("workforce_adapter_response_invalid")
    return response


def _validate_response(
    response: Mapping[str, Any],
    request: Mapping[str, Any],
) -> dict[str, Any]:
    phase = str(request["phase"])
    base = {"schemaVersion", "requestId", "phase"}
    expected = base | ({"toolInventory"} if phase == "observe" else {
        "invocation", "artifacts", "output",
    })
    if phase == "planner":
        expected.add("bindingInventory")
    if set(response) != expected:
        raise WorkforceHostExecutorError("workforce_adapter_response_keys_invalid")
    if (
        response.get("schemaVersion") != HOST_EXECUTOR_RESPONSE_SCHEMA
        or response.get("requestId") != request.get("requestId")
        or response.get("phase") != phase
    ):
        raise WorkforceHostExecutorError("workforce_adapter_response_correlation_mismatch")
    if phase == "observe":
        return dict(response)
    if phase not in _INVOCATION_PHASES or not isinstance(response.get("invocation"), Mapping):
        raise WorkforceHostExecutorError("workforce_adapter_invocation_missing")
    invocation = response["invocation"]
    if invocation.get("status") != "completed":
        raise WorkforceHostExecutorError("workforce_adapter_invocation_not_completed")
    output = response.get("output")
    if (
        output is None
        or (isinstance(output, str) and not output.strip())
        or (isinstance(output, (list, dict)) and not output)
        or _json_size(output) > 4 * 1024 * 1024
    ):
        raise WorkforceHostExecutorError("workforce_adapter_output_invalid")
    artifacts = response.get("artifacts")
    if (
        not isinstance(artifacts, list)
        or len(artifacts) > 256
        or any(
            not isinstance(artifact, Mapping)
            or set(artifact) != {"artifactId", "relativePath", "sha256"}
            or not isinstance(artifact.get("artifactId"), str)
            or not _ID_RE.fullmatch(artifact["artifactId"])
            or not isinstance(artifact.get("relativePath"), str)
            or not artifact["relativePath"]
            or len(artifact["relativePath"]) > 1024
            or not isinstance(artifact.get("sha256"), str)
            or not _SHA256_RE.fullmatch(artifact["sha256"])
            for artifact in artifacts
        )
    ):
        raise WorkforceHostExecutorError("workforce_adapter_artifacts_invalid")
    if phase == "planner" and not isinstance(response.get("bindingInventory"), list):
        raise WorkforceHostExecutorError("workforce_adapter_binding_inventory_invalid")
    return dict(response)


def _invoke(
    *,
    adapter_argv: Sequence[str],
    execution_id: str,
    phase: str,
    ordinal: int,
    project_dir: Path,
    preparation: Mapping[str, Any],
    row: Mapping[str, Any] | None,
    graph_node: Mapping[str, Any] | None,
    tool_inventory: Mapping[str, Any] | None,
    binding_plan: Mapping[str, Any] | None,
    inputs: list[Mapping[str, Any]],
    timeout_seconds: int,
) -> dict[str, Any]:
    request = {
        "schemaVersion": HOST_EXECUTOR_REQUEST_SCHEMA,
        "requestId": _request_id(execution_id, phase, ordinal),
        "executionId": execution_id,
        "phase": phase,
        "projectDir": str(project_dir),
        "preparation": preparation,
        "pinnedRosterRow": row,
        "graphNode": graph_node,
        "toolInventory": tool_inventory,
        "capabilityBindingPlan": binding_plan,
        "inputs": inputs,
    }
    return _validate_response(
        _call_adapter(
            adapter_argv,
            request,
            project_dir=project_dir,
            timeout_seconds=timeout_seconds,
        ),
        request,
    )


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    size = 0
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise WorkforceHostExecutorError("workforce_adapter_artifact_not_regular_file")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > 256 * 1024 * 1024:
                raise WorkforceHostExecutorError("workforce_adapter_artifact_too_large")
            digest.update(chunk)
    finally:
        os.close(descriptor)
    return "sha256:" + digest.hexdigest()


def _snapshot_verified_artifact(
    source: Path,
    target: Path,
    *,
    expected_digest: str,
) -> str:
    read_flags = os.O_RDONLY
    write_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        read_flags |= os.O_NOFOLLOW
        write_flags |= os.O_NOFOLLOW
    source_fd = os.open(source, read_flags)
    try:
        if not stat.S_ISREG(os.fstat(source_fd).st_mode):
            raise WorkforceHostExecutorError("workforce_adapter_artifact_not_regular_file")
        target_fd = os.open(target, write_flags, 0o600)
        try:
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > 256 * 1024 * 1024:
                    raise WorkforceHostExecutorError("workforce_adapter_artifact_too_large")
                digest.update(chunk)
                remaining = memoryview(chunk)
                while remaining:
                    written = os.write(target_fd, remaining)
                    if written <= 0:
                        raise WorkforceHostExecutorError(
                            "workforce_execution_output_write_failed"
                        )
                    remaining = remaining[written:]
            os.fsync(target_fd)
        finally:
            os.close(target_fd)
    finally:
        os.close(source_fd)
    observed = "sha256:" + digest.hexdigest()
    if observed != expected_digest:
        try:
            target.unlink()
        except OSError:
            pass
        raise WorkforceHostExecutorError("workforce_adapter_artifact_digest_mismatch")
    return observed


def _write_private_output(
    response: Mapping[str, Any],
    *,
    execution_id: str,
    ordinal: int,
    output_root: Path,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if output_root.is_symlink():
        raise WorkforceHostExecutorError("workforce_execution_output_root_unsafe")
    filename = f"{ordinal:04d}-{response['phase']}.json"
    target = output_root / filename
    if target.exists() or target.is_symlink():
        raise WorkforceHostExecutorError("workforce_execution_output_collision")
    temporary = output_root / f".{filename}.{os.getpid()}.tmp"
    data = json.dumps(response["output"], ensure_ascii=False, separators=(",", ":"))
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        remaining = memoryview(data.encode("utf-8"))
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise WorkforceHostExecutorError("workforce_execution_output_write_failed")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, target)
    if os.name == "posix":
        os.chmod(target, 0o600)
    return {
        "artifactId": (
            f"artifact:{execution_id.split(':', 1)[1]}:{response['phase']}:{ordinal}:output"
        ),
        "path": str(target),
        "sha256": _file_digest(target),
        "sizeBytes": target.stat().st_size,
        "source": "core-materialized-output",
    }


def _materialize_handoff(
    response: Mapping[str, Any],
    *,
    execution_id: str,
    ordinal: int,
    project_dir: Path,
    output_root: Path,
    seen_artifact_ids: set[str],
) -> dict[str, Any]:
    manifests = [
        _write_private_output(
            response,
            execution_id=execution_id,
            ordinal=ordinal,
            output_root=output_root,
        )
    ]
    for artifact_index, descriptor in enumerate(response.get("artifacts") or [], start=1):
        relative = Path(str(descriptor["relativePath"]))
        if relative.is_absolute() or ".." in relative.parts:
            raise WorkforceHostExecutorError("workforce_adapter_artifact_path_invalid")
        unresolved = project_dir / relative
        if unresolved.is_symlink():
            raise WorkforceHostExecutorError("workforce_adapter_artifact_symlink_forbidden")
        try:
            candidate = unresolved.resolve(strict=True)
        except OSError as exc:
            raise WorkforceHostExecutorError(
                "workforce_adapter_artifact_unavailable"
            ) from exc
        try:
            candidate.relative_to(project_dir)
        except ValueError as exc:
            raise WorkforceHostExecutorError("workforce_adapter_artifact_outside_project") from exc
        if not candidate.is_file():
            raise WorkforceHostExecutorError("workforce_adapter_artifact_not_regular_file")
        snapshot = output_root / f"{ordinal:04d}-{response['phase']}-file-{artifact_index}.bin"
        try:
            observed_digest = _snapshot_verified_artifact(
                candidate,
                snapshot,
                expected_digest=descriptor["sha256"],
            )
        except OSError as exc:
            raise WorkforceHostExecutorError(
                "workforce_adapter_artifact_unavailable"
            ) from exc
        manifests.append({
            "artifactId": descriptor["artifactId"],
            "path": str(snapshot),
            "sha256": observed_digest,
            "sizeBytes": snapshot.stat().st_size,
            "source": "core-snapshot-adapter-file",
        })
    for manifest in manifests:
        artifact_id = str(manifest["artifactId"])
        if artifact_id in seen_artifact_ids:
            raise WorkforceHostExecutorError("workforce_adapter_artifact_id_duplicate")
        seen_artifact_ids.add(artifact_id)
    return {
        "phase": response["phase"],
        "artifacts": manifests,
    }


def _assert_artifacts_unchanged(handoffs: Sequence[Mapping[str, Any]]) -> None:
    for handoff in handoffs:
        artifacts = handoff.get("artifacts")
        if not isinstance(artifacts, list):
            raise WorkforceHostExecutorError("workforce_execution_artifact_manifest_invalid")
        for artifact in artifacts:
            if not isinstance(artifact, Mapping):
                raise WorkforceHostExecutorError("workforce_execution_artifact_manifest_invalid")
            try:
                path = Path(str(artifact["path"]))
                if path.is_symlink() or not path.is_file():
                    raise WorkforceHostExecutorError("workforce_execution_artifact_changed")
                observed = _file_digest(path)
            except (KeyError, OSError) as exc:
                raise WorkforceHostExecutorError(
                    "workforce_execution_artifact_changed"
                ) from exc
            if observed != artifact.get("sha256"):
                raise WorkforceHostExecutorError("workforce_execution_artifact_changed")


def _worker_capability_bindings(
    binding_plan: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    context = plan.get("executionContext")
    if not isinstance(context, Mapping):
        raise WorkforceHostExecutorError("workforce_execution_context_invalid")
    required_by_slot = {
        str(slot.get("slotId")): list(slot.get("requiredToolCapabilities") or [])
        for slot in (context.get("slots") or [])
        if isinstance(slot, Mapping)
    }
    rows_by_pair: dict[tuple[str, str], dict[str, Mapping[str, Any]]] = {}
    for row in binding_plan.get("inventory") or []:
        pair = (str(row["slotId"]), str(row["agentReleaseId"]))
        for capability in row["capabilityIds"]:
            rows_by_pair.setdefault(pair, {})[capability] = row
    result: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in plan.get("executionRoster") or []:
        pair = (str(row["slotId"]), str(row["agentReleaseId"]))
        capability_rows = rows_by_pair.get(pair, {})
        result[pair] = [
            {
                "capabilityId": capability,
                "provider": capability_rows[capability]["provider"],
                "toolId": capability_rows[capability]["toolId"],
                "source": "host_inventory",
                "status": "bound",
            }
            for capability in required_by_slot.get(pair[0], [])
            if capability in capability_rows
        ]
    return result


def _ordered_roster(
    plan: Mapping[str, Any],
) -> tuple[list[Mapping[str, Any]], dict[str, set[str]]]:
    raw_roster = plan.get("executionRoster")
    if not isinstance(raw_roster, list) or not raw_roster:
        raise WorkforceHostExecutorError("workforce_execution_roster_invalid")
    roster = [row for row in raw_roster if isinstance(row, Mapping)]
    if len(roster) != len(raw_roster):
        raise WorkforceHostExecutorError("workforce_execution_roster_invalid")
    slots = list(dict.fromkeys(str(row.get("slotId")) for row in roster))
    slot_set = set(slots)
    predecessors: dict[str, set[str]] = {slot: set() for slot in slots}
    context = plan.get("executionContext")
    if not isinstance(context, Mapping):
        raise WorkforceHostExecutorError("workforce_execution_context_invalid")
    edges = list(context.get("workOrderEdges") or []) + list(context.get("selectionEdges") or [])
    for edge in edges:
        if not isinstance(edge, Mapping):
            raise WorkforceHostExecutorError("workforce_execution_context_edge_invalid")
        source = str(edge.get("from") or edge.get("fromSlot") or "")
        target = str(edge.get("to") or edge.get("toSlot") or "")
        relation = edge.get("relation")
        if source not in slot_set or target not in slot_set or relation == "coordinatesWith":
            continue
        if relation in {"handsOffTo", "reportsTo"}:
            predecessors[target].add(source)
        elif relation == "reviews":
            predecessors[source].add(target)
        else:
            raise WorkforceHostExecutorError("workforce_execution_context_edge_invalid")
    pending = list(slots)
    ordered_slots: list[str] = []
    while pending:
        ready = [slot for slot in pending if predecessors[slot].issubset(ordered_slots)]
        if not ready:
            raise WorkforceHostExecutorError("workforce_execution_context_cycle")
        for slot in ready:
            ordered_slots.append(slot)
            pending.remove(slot)
    ordinal = {slot: index for index, slot in enumerate(ordered_slots)}
    return sorted(roster, key=lambda row: ordinal[str(row.get("slotId"))]), predecessors


def _assert_inventory_pins(
    tool_inventory: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> None:
    roster = {
        (str(row.get("slotId")), str(row.get("agentReleaseId"))): row
        for row in plan.get("executionRoster") or []
        if isinstance(row, Mapping)
    }
    for entry in tool_inventory.get("entries") or []:
        pair = (str(entry.get("slotId")), str(entry.get("agentReleaseId")))
        row = roster.get(pair)
        if row is None or entry.get("permissionPolicyDigest") != row.get("permissionPolicyDigest"):
            raise WorkforceHostExecutorError("workforce_adapter_inventory_pin_mismatch")


def _assert_invocation_policy_pins(
    invocation: Mapping[str, Any],
    *,
    row: Mapping[str, Any],
    tool_inventory_digest: str,
) -> None:
    enforcement = invocation.get("permissionEnforcement")
    if not isinstance(enforcement, Mapping):
        raise WorkforceHostExecutorError("workforce_adapter_permission_evidence_missing")
    if enforcement.get("permissionPolicyDigest") != row.get("permissionPolicyDigest"):
        raise WorkforceHostExecutorError("workforce_adapter_permission_pin_mismatch")
    evidence = enforcement.get("enforcementEvidence")
    if not isinstance(evidence, Mapping) or evidence.get("toolInventoryDigest") != tool_inventory_digest:
        raise WorkforceHostExecutorError("workforce_adapter_tool_inventory_pin_mismatch")
    observation = evidence.get("hostObservation")
    if isinstance(observation, Mapping) and (
        observation.get("permissionPolicyDigest") != row.get("permissionPolicyDigest")
        or observation.get("toolInventoryDigest") != tool_inventory_digest
    ):
        raise WorkforceHostExecutorError("workforce_adapter_host_observation_pin_mismatch")
    broker_observation = evidence.get("brokerObservation")
    if isinstance(broker_observation, Mapping) and (
        broker_observation.get("permissionPolicyDigest") != row.get("permissionPolicyDigest")
        or broker_observation.get("toolInventoryDigest") != tool_inventory_digest
    ):
        raise WorkforceHostExecutorError("workforce_adapter_broker_observation_pin_mismatch")


def execute_preparation(
    *,
    preparation: Mapping[str, Any],
    adapter_argv: Sequence[str],
    project_dir: str | Path,
    timeout_seconds: int = 900,
    output_root: str | Path | None = None,
    before_finalize: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """Run every pinned plan node and validate the constructed receipt."""

    adapter_command = _validated_adapter_argv(adapter_argv)
    if not isinstance(timeout_seconds, int) or not (1 <= timeout_seconds <= 3600):
        raise WorkforceHostExecutorError("workforce_adapter_timeout_invalid")
    project = Path(project_dir).expanduser().resolve(strict=True)
    if not project.is_dir():
        raise WorkforceHostExecutorError("workforce_execution_project_unavailable")
    plan = _execution_plan(preparation)
    execution_id = "execution:" + uuid.uuid4().hex
    private_root = (
        Path(output_root).expanduser().resolve()
        if output_root is not None
        else (
            Path(os.environ.get("AGENTLAS_HOME") or (Path.home() / ".agentlas"))
            / "networking" / "workforce-executions" / execution_id.split(":", 1)[1]
        ).resolve()
    )
    ordinal = 0
    results: list[dict[str, Any]] = []
    handoffs_by_slot: dict[str, list[dict[str, Any]]] = {}
    seen_artifact_ids: set[str] = set()
    materialized_bytes = 0

    def handoff(response: Mapping[str, Any]) -> dict[str, Any]:
        nonlocal materialized_bytes
        value = _materialize_handoff(
            response,
            execution_id=execution_id,
            ordinal=ordinal,
            project_dir=project,
            output_root=private_root,
            seen_artifact_ids=seen_artifact_ids,
        )
        materialized_bytes += sum(
            int(artifact.get("sizeBytes") or 0) for artifact in value["artifacts"]
        )
        if materialized_bytes > 512 * 1024 * 1024:
            raise WorkforceHostExecutorError("workforce_execution_artifacts_too_large")
        return value

    def call(
        phase: str,
        *,
        row: Mapping[str, Any] | None = None,
        graph_node: Mapping[str, Any] | None = None,
        inventory: Mapping[str, Any] | None = None,
        bindings: Mapping[str, Any] | None = None,
        inputs: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        nonlocal ordinal
        _assert_artifacts_unchanged(list(inputs or []))
        ordinal += 1
        return _invoke(
            adapter_argv=adapter_command,
            execution_id=execution_id,
            phase=phase,
            ordinal=ordinal,
            project_dir=project,
            preparation=preparation,
            row=row,
            graph_node=graph_node,
            tool_inventory=inventory,
            binding_plan=bindings,
            inputs=list(inputs or []),
            timeout_seconds=timeout_seconds,
        )

    observed = call("observe")
    tool_inventory = validate_tool_inventory(observed["toolInventory"])
    if tool_inventory.get("executionContextDigest") != plan.get("executionContextDigest"):
        raise WorkforceHostExecutorError("workforce_adapter_inventory_context_mismatch")
    _assert_inventory_pins(tool_inventory, plan)
    tool_inventory_digest = workforce_tool_inventory_digest(tool_inventory)

    orchestrator = call("orchestrator", inventory=tool_inventory)
    results.append(handoff(orchestrator))
    planner = call("planner", inventory=tool_inventory, inputs=list(results))
    planner_invocation = dict(planner["invocation"])
    forbidden_planner_pins = {"toolInventoryDigest", "capabilityBindingPlanDigest"}.intersection(
        planner_invocation
    )
    if forbidden_planner_pins:
        raise WorkforceHostExecutorError("workforce_adapter_supplied_core_pin")
    if planner_invocation.get("parseSuccess") is not True or planner_invocation.get("fallbackUsed") is not False:
        raise WorkforceHostExecutorError("workforce_adapter_planner_invalid")
    binding_plan = {
        "schemaVersion": WORKFORCE_CAPABILITY_BINDING_PLAN_SCHEMA,
        "decisionOwner": "host_llm",
        "plannerInvocationId": planner_invocation.get("invocationId"),
        "executionContextDigest": plan.get("executionContextDigest"),
        "toolInventoryDigest": tool_inventory_digest,
        "inventory": planner["bindingInventory"],
    }
    binding_plan["bindingPlanDigest"] = workforce_capability_binding_plan_digest(binding_plan)
    binding_plan = validate_capability_binding_plan(binding_plan)
    planner_invocation["toolInventoryDigest"] = tool_inventory_digest
    planner_invocation["capabilityBindingPlanDigest"] = binding_plan["bindingPlanDigest"]
    results.append(handoff(planner))
    worker_bindings = _worker_capability_bindings(binding_plan, plan)
    base_inputs = list(results)
    ordered_roster, predecessors = _ordered_roster(plan)

    workers: list[dict[str, Any]] = []
    nested_executions: list[dict[str, Any]] = []
    for row_index, row in enumerate(ordered_roster):
        if not isinstance(row, Mapping):
            raise WorkforceHostExecutorError("workforce_execution_roster_invalid")
        pair = (str(row.get("slotId")), str(row.get("agentReleaseId")))
        roster_inputs = list(base_inputs)
        for predecessor in sorted(predecessors.get(pair[0], set())):
            roster_inputs.extend(handoffs_by_slot.get(predecessor, []))
        graph = row.get("executionGraph")
        if graph is None:
            worker_response = call(
                "direct-worker",
                row=row,
                inventory=tool_inventory,
                bindings=binding_plan,
                inputs=roster_inputs,
            )
            _assert_invocation_policy_pins(
                worker_response["invocation"],
                row=row,
                tool_inventory_digest=tool_inventory_digest,
            )
            worker_handoff = handoff(worker_response)
            results.append(worker_handoff)
            handoffs_by_slot.setdefault(pair[0], []).append(worker_handoff)
            workers.append({
                "slotId": row["slotId"],
                "agentReleaseId": row["agentReleaseId"],
                "entityKind": row["entityKind"],
                "packageHash": row["packageHash"],
                "contentDigest": row["contentDigest"],
                "bundleDigest": row["bundleDigest"],
                "permissionPolicyDigest": row["permissionPolicyDigest"],
                "executionGraphDigest": None,
                "status": "completed",
                "handoffArtifactRefs": [item["artifactId"] for item in worker_handoff["artifacts"]],
                "capabilityBindingPlanDigest": binding_plan["bindingPlanDigest"],
                "capabilityBindings": worker_bindings.get(pair, []),
                "executionMode": "direct",
                "directInvocation": worker_response["invocation"],
                "nestedExecutionId": None,
            })
            continue
        if not isinstance(graph, Mapping):
            raise WorkforceHostExecutorError("workforce_execution_graph_invalid")
        nested_id = f"nested:{execution_id.split(':', 1)[1]}:{row_index}"
        graph_workers = graph.get("workers")
        if not isinstance(graph_workers, list) or not graph_workers:
            raise WorkforceHostExecutorError("workforce_execution_graph_invalid")
        manager_plan_response = call(
            "team-manager-plan",
            row=row,
            graph_node=graph.get("manager"),
            inventory=tool_inventory,
            bindings=binding_plan,
            inputs=roster_inputs,
        )
        expected_worker_ids = [item.get("id") for item in graph_workers if isinstance(item, Mapping)]
        manager_plan_invocation = manager_plan_response["invocation"]
        if (
            manager_plan_invocation.get("parseSuccess") is not True
            or manager_plan_invocation.get("fallbackUsed") is not False
            or manager_plan_invocation.get("plannedWorkerIds") != expected_worker_ids
        ):
            raise WorkforceHostExecutorError("workforce_adapter_team_plan_invalid")
        _assert_invocation_policy_pins(
            manager_plan_invocation,
            row=row,
            tool_inventory_digest=tool_inventory_digest,
        )
        manager_plan_handoff = handoff(manager_plan_response)
        results.append(manager_plan_handoff)
        nested_inputs = list(results)
        nested_workers: list[Mapping[str, Any]] = []
        for graph_worker in graph_workers:
            if not isinstance(graph_worker, Mapping):
                raise WorkforceHostExecutorError("workforce_execution_graph_invalid")
            response = call(
                "team-worker",
                row=row,
                graph_node=graph_worker,
                inventory=tool_inventory,
                bindings=binding_plan,
                inputs=list(nested_inputs),
            )
            invocation = dict(response["invocation"])
            if "id" in invocation and invocation["id"] != graph_worker.get("id"):
                raise WorkforceHostExecutorError("workforce_adapter_supplied_core_pin")
            invocation["id"] = graph_worker["id"]
            _assert_invocation_policy_pins(
                invocation,
                row=row,
                tool_inventory_digest=tool_inventory_digest,
            )
            nested_workers.append(invocation)
            worker_handoff = handoff(response)
            nested_inputs.append(worker_handoff)
            results.append(worker_handoff)
        manager_synthesis = call(
            "team-manager-synthesis",
            row=row,
            graph_node=graph.get("manager"),
            inventory=tool_inventory,
            bindings=binding_plan,
            inputs=nested_inputs,
        )
        _assert_invocation_policy_pins(
            manager_synthesis["invocation"],
            row=row,
            tool_inventory_digest=tool_inventory_digest,
        )
        manager_synthesis_handoff = handoff(manager_synthesis)
        results.append(manager_synthesis_handoff)
        handoffs_by_slot.setdefault(pair[0], []).append(manager_synthesis_handoff)
        nested_executions.append({
            "nestedExecutionId": nested_id,
            "slotId": row["slotId"],
            "agentReleaseId": row["agentReleaseId"],
            "bundleDigest": row["bundleDigest"],
            "permissionPolicyDigest": row["permissionPolicyDigest"],
            "executionGraphDigest": row["executionGraphDigest"],
            "managerPlan": manager_plan_invocation,
            "workers": nested_workers,
            "managerSynthesis": manager_synthesis["invocation"],
            "status": "completed",
        })
        workers.append({
            "slotId": row["slotId"],
            "agentReleaseId": row["agentReleaseId"],
            "entityKind": row["entityKind"],
            "packageHash": row["packageHash"],
            "contentDigest": row["contentDigest"],
            "bundleDigest": row["bundleDigest"],
            "permissionPolicyDigest": row["permissionPolicyDigest"],
            "executionGraphDigest": row["executionGraphDigest"],
            "status": "completed",
            "handoffArtifactRefs": [
                item["artifactId"] for item in manager_synthesis_handoff["artifacts"]
            ],
            "capabilityBindingPlanDigest": binding_plan["bindingPlanDigest"],
            "capabilityBindings": worker_bindings.get(pair, []),
            "executionMode": "nested",
            "directInvocation": None,
            "nestedExecutionId": nested_id,
        })

    synthesis = call(
        "synthesis",
        inventory=tool_inventory,
        bindings=binding_plan,
        inputs=list(results),
    )
    results.append(handoff(synthesis))
    verifier = call(
        "verifier",
        inventory=tool_inventory,
        bindings=binding_plan,
        inputs=list(results),
    )
    if verifier["invocation"].get("verdict") != "pass":
        raise WorkforceHostExecutorError("workforce_adapter_verifier_failed")
    results.append(handoff(verifier))

    _assert_artifacts_unchanged(results)

    if before_finalize is not None:
        before_finalize()

    receipt = {
        "schemaVersion": WORKFORCE_EXECUTION_RECEIPT_SCHEMA,
        "executionId": execution_id,
        "workOrderId": plan.get("executionContext", {}).get("workOrderId"),
        "selectionReceiptId": plan.get("selectionReceiptId"),
        "preparationReceiptId": plan.get("preparationReceiptId"),
        "executionContextDigest": plan.get("executionContextDigest"),
        "orchestrator": orchestrator["invocation"],
        "planner": planner_invocation,
        "capabilityBindingPlan": binding_plan,
        "workers": workers,
        "nestedExecutions": nested_executions,
        "synthesis": synthesis["invocation"],
        "verifier": verifier["invocation"],
        "status": "passed",
    }
    validation = validate_execution_receipt(
        receipt,
        execution_plan=plan,
        tool_inventory=tool_inventory,
    )
    result = {
        "schemaVersion": HOST_EXECUTION_RESULT_SCHEMA,
        "status": "accepted" if validation.get("status") == "accepted" else "rejected",
        "toolInventory": tool_inventory,
        "validation": validation,
        "artifactManifest": results,
        "outputRoot": str(private_root),
    }
    if validation.get("status") == "accepted":
        result["executionReceipt"] = receipt
    else:
        result["error"] = "workforce_execution_receipt_rejected"
    return result


def execute_cached_goal(
    *,
    store: WorkforceGoalStore,
    adapter_argv: Sequence[str],
    project_dir: str | Path,
    goal_id: str | None = None,
    timeout_seconds: int = 900,
) -> dict[str, Any]:
    """Execute one unambiguous cached goal plan while it remains current."""

    before = store.runtime_context(project_dir=project_dir, goal_id=goal_id)
    selected_goal, revision, preparation = _select_ready_plan(
        before,
        requested_goal_id=goal_id,
    )
    preparation_digest = canonical_digest(preparation)

    def assert_still_current() -> None:
        current_context = store.runtime_context(project_dir=project_dir, goal_id=selected_goal)
        _, _, current_preparation = _select_ready_plan(
            current_context,
            requested_goal_id=selected_goal,
            requested_revision=revision,
        )
        if canonical_digest(current_preparation) != preparation_digest:
            raise WorkforceHostExecutorError("workforce_execution_plan_changed_during_run")

    result = execute_preparation(
        preparation=preparation,
        adapter_argv=adapter_argv,
        project_dir=project_dir,
        timeout_seconds=timeout_seconds,
        before_finalize=assert_still_current,
    )
    result["goalId"] = selected_goal
    result["revision"] = revision
    return result


def execute_cached_goal_refusal(**kwargs: Any) -> dict[str, Any]:
    """Return a stable CLI-safe refusal without manufacturing a receipt."""

    try:
        return execute_cached_goal(**kwargs)
    except WorkforceHostExecutorError as exc:
        result: dict[str, Any] = {
            "schemaVersion": HOST_EXECUTION_RESULT_SCHEMA,
            "status": "rejected",
            "error": exc.code,
            "executionAllowed": False,
        }
        if exc.detail:
            result["detail"] = exc.detail
        return result
    except (OSError, TypeError, ValueError) as exc:
        return {
            "schemaVersion": HOST_EXECUTION_RESULT_SCHEMA,
            "status": "rejected",
            "error": "workforce_execution_contract_rejected",
            "issues": [str(exc)[:256]],
            "executionAllowed": False,
        }


__all__ = [
    "HOST_EXECUTOR_REQUEST_SCHEMA",
    "HOST_EXECUTOR_RESPONSE_SCHEMA",
    "HOST_EXECUTION_RESULT_SCHEMA",
    "WorkforceHostExecutorError",
    "execute_cached_goal",
    "execute_cached_goal_refusal",
    "execute_preparation",
    "parse_adapter_argv",
]
