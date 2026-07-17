"""Local selection/preparation wrappers for federated candidate menus.

Federated menus are not Hub-owned sessions.  They are therefore validated by
Core and never replayed into remote ``workforce.validate/prepare`` tools.  The
wrappers below pin the selected source's original session/digest and require
runtime bundles to match the exact selected immutable release.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .contracts import canonical_digest
from .execution import prepare_execution_plan
from .federation_store import FederationSessionError, FederationSessionStore
from .federation import validate_federation_result
from .selection import validate_host_selection


WORKFORCE_FEDERATED_SELECTION_SCHEMA = "agentlas.workforce-federated-selection-validation.v1"
WORKFORCE_FEDERATED_PREPARATION_SCHEMA = "agentlas.workforce-federated-preparation.v1"


class FederatedProvenanceError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _require_work_order_binding(
    session_store: FederationSessionStore,
    selection_session_id: str,
    work_order: Mapping[str, Any],
    *,
    now: Any = None,
) -> str:
    try:
        return session_store.assert_work_order_binding(
            selection_session_id,
            work_order,
            now=now,
        )
    except FederationSessionError as exc:
        if exc.code in {
            "federation_session_expired",
            "federation_session_not_found",
            "source_candidate_set_expired",
            "source_candidate_set_not_found",
            "federated_selection_not_pinned",
        }:
            # Lifecycle errors are safe, finite protocol signals. Preserve them
            # so the host can start a fresh immutable transaction instead of
            # misreporting expiry as a tamper/binding failure.
            raise FederatedProvenanceError(exc.code) from exc
        raise FederatedProvenanceError("federated_work_order_binding_mismatch") from exc


def _bounded_wrapper_tree(value: Any, *, maximum: int = 4 * 1024 * 1024) -> None:
    total = 0
    stack: list[tuple[Any, int]] = [(value, 0)]
    active: set[int] = set()
    while stack:
        item, state = stack.pop()
        if isinstance(item, Mapping):
            identity = id(item)
            if state:
                active.discard(identity)
                continue
            if identity in active:
                raise FederatedProvenanceError("federated_selection_invalid")
            active.add(identity)
            total += 2 + len(item)
            stack.append((item, 1))
            for key, child in item.items():
                if not isinstance(key, str):
                    raise FederatedProvenanceError("federated_selection_invalid")
                total += len(key) * 4 + 3
                stack.append((child, 0))
        elif isinstance(item, list):
            identity = id(item)
            if state:
                active.discard(identity)
                continue
            if identity in active:
                raise FederatedProvenanceError("federated_selection_invalid")
            active.add(identity)
            total += 2 + len(item)
            stack.append((item, 1))
            stack.extend((child, 0) for child in item)
        elif isinstance(item, str):
            total += len(item) * 4 + 2
        elif item is None or isinstance(item, (bool, int, float)):
            total += 32
        else:
            raise FederatedProvenanceError("federated_selection_invalid")
        if total > maximum:
            raise FederatedProvenanceError("federated_selection_invalid")


def _wrapper_digest(value: Mapping[str, Any], field: str) -> str:
    return canonical_digest({key: item for key, item in value.items() if key != field})


def _source_pin_from_result(
    result: Mapping[str, Any],
    *,
    slot_id: str,
    definition_id: str,
    release_id: str,
) -> dict[str, Any]:
    provenance = next(
        (
            row
            for row in result.get("candidateProvenance") or []
            if isinstance(row, Mapping)
            and row.get("slotId") == slot_id
            and row.get("agentDefinitionId") == definition_id
            and row.get("selectedAgentReleaseId") == release_id
        ),
        None,
    )
    if not isinstance(provenance, Mapping):
        raise FederatedProvenanceError("selected_release_source_pin_missing")
    source = str(provenance.get("selectedSource") or "")
    appearance = next(
        (
            row
            for row in provenance.get("appearances") or []
            if isinstance(row, Mapping)
            and row.get("source") == source
            and row.get("agentReleaseId") == release_id
        ),
        None,
    )
    receipt = next(
        (
            row
            for row in result.get("sourceReceipts") or []
            if isinstance(row, Mapping) and row.get("source") == source and row.get("status") == "succeeded"
        ),
        None,
    )
    if not isinstance(appearance, Mapping) or not isinstance(receipt, Mapping):
        raise FederatedProvenanceError("selected_release_source_pin_missing")
    if appearance.get("candidateSetDigest") != receipt.get("candidateSetDigest"):
        raise FederatedProvenanceError("selected_release_source_pin_mismatch")
    pin = {
        "schemaVersion": "agentlas.workforce-source-pin.v1",
        "federationDigest": result["federationDigest"],
        "federatedSelectionSessionId": result["candidateSet"]["selectionSessionId"],
        "slotId": slot_id,
        "source": source,
        "sourceSelectionSessionId": receipt["selectionSessionId"],
        "sourceCandidateSetDigest": receipt["candidateSetDigest"],
        "agentDefinitionId": definition_id,
        "agentReleaseId": release_id,
        "releaseVersion": appearance["releaseVersion"],
        "packageHash": appearance["packageHash"],
        "contentDigest": appearance["contentDigest"],
        "entityKind": appearance["entityKind"],
        "lineageAttestation": appearance.get("lineageAttestation"),
    }
    pin["sourcePinDigest"] = canonical_digest(pin)
    return pin


def validate_federated_host_selection(
    selection: Mapping[str, Any],
    *,
    federation_result: Mapping[str, Any],
    work_order: Mapping[str, Any],
    session_store: FederationSessionStore,
    now: Any = None,
) -> dict[str, Any]:
    """Validate a host choice locally and bind every row to one source pin."""

    validate_federation_result(
        federation_result,
        lineage_verifier=session_store.lineage_verifier,
        now=now,
    )
    candidate_set = federation_result["candidateSet"]
    stored = session_store.get(candidate_set["selectionSessionId"], now=now)
    work_order_digest = _require_work_order_binding(
        session_store,
        str(candidate_set["selectionSessionId"]),
        work_order,
        now=now,
    )
    if canonical_digest(stored) != canonical_digest(federation_result):
        raise FederatedProvenanceError("federation_store_binding_mismatch")
    validation = validate_host_selection(
        selection,
        candidate_set=candidate_set,
        work_order=work_order,
        now=now,
    )
    validation_receipt = validation.get("receipt")
    try:
        exact_selection_digest = canonical_digest(selection)
    except (TypeError, ValueError) as exc:
        raise FederatedProvenanceError("federated_selection_exact_binding_mismatch") from exc
    if (
        not isinstance(validation_receipt, Mapping)
        or validation_receipt.get("selectionDigest") != exact_selection_digest
    ):
        raise FederatedProvenanceError("federated_selection_exact_binding_mismatch")
    pins: list[dict[str, Any]] = []
    if validation.get("status") == "accepted":
        for row in validation.get("idealTeam") or []:
            if not isinstance(row, Mapping):
                raise FederatedProvenanceError("selection_assignment_invalid")
            pins.append(
                _source_pin_from_result(
                    stored,
                    slot_id=str(row.get("slotId") or ""),
                    definition_id=str(row.get("agentDefinitionId") or ""),
                    release_id=str(row.get("agentReleaseId") or ""),
                )
            )
    wrapper = {
        "schemaVersion": WORKFORCE_FEDERATED_SELECTION_SCHEMA,
        "status": validation.get("status"),
        "federationDigest": federation_result["federationDigest"],
        "selectionSessionId": candidate_set["selectionSessionId"],
        "candidateSetDigest": candidate_set["candidateSetDigest"],
        "workOrderDigest": work_order_digest,
        "selectionDigest": exact_selection_digest,
        "selectionValidation": validation,
        "selectedSourcePins": pins,
    }
    wrapper["federatedSelectionDigest"] = _wrapper_digest(wrapper, "federatedSelectionDigest")
    if wrapper["status"] == "accepted":
        session_store.save_federated_selection(wrapper, now=now)
    return wrapper


def validate_federated_selection_wrapper(value: Mapping[str, Any]) -> None:
    _bounded_wrapper_tree(value)
    expected_keys = {
        "schemaVersion", "status", "federationDigest", "selectionSessionId",
        "candidateSetDigest", "workOrderDigest", "selectionDigest",
        "selectionValidation", "selectedSourcePins", "federatedSelectionDigest",
    }
    if set(value) != expected_keys or value.get("schemaVersion") != WORKFORCE_FEDERATED_SELECTION_SCHEMA:
        raise FederatedProvenanceError("federated_selection_schema_invalid")
    validation = value.get("selectionValidation")
    pins = value.get("selectedSourcePins")
    if not isinstance(validation, Mapping) or not isinstance(pins, list) or len(pins) > 128:
        raise FederatedProvenanceError("federated_selection_invalid")
    if value.get("federatedSelectionDigest") != _wrapper_digest(value, "federatedSelectionDigest"):
        raise FederatedProvenanceError("federated_selection_digest_mismatch")
    if validation.get("candidateSetDigest") != value.get("candidateSetDigest"):
        raise FederatedProvenanceError("federated_selection_candidate_mismatch")
    receipt = validation.get("receipt")
    if (
        not isinstance(receipt, Mapping)
        or not isinstance(value.get("workOrderDigest"), str)
        or not isinstance(value.get("selectionDigest"), str)
        or receipt.get("selectionDigest") != value.get("selectionDigest")
        or receipt.get("requestExpansionForSlots") != []
    ):
        raise FederatedProvenanceError("federated_selection_exact_binding_mismatch")
    if value.get("status") == "accepted" and len(pins) != len(validation.get("idealTeam") or []):
        raise FederatedProvenanceError("federated_selection_pin_count_mismatch")
    for pin in pins:
        if not isinstance(pin, Mapping):
            raise FederatedProvenanceError("federated_selection_source_pin_invalid")
        if pin.get("federationDigest") != value.get("federationDigest"):
            raise FederatedProvenanceError("federated_selection_source_pin_mismatch")
        if pin.get("sourcePinDigest") != canonical_digest(
            {key: item for key, item in pin.items() if key != "sourcePinDigest"}
        ):
            raise FederatedProvenanceError("federated_selection_source_pin_digest_mismatch")


def prepare_federated_execution_plan(
    *,
    work_order: Mapping[str, Any],
    selection: Mapping[str, Any],
    federated_selection: Mapping[str, Any],
    federation_result: Mapping[str, Any],
    source_runtime_bundles: Iterable[Mapping[str, Any]],
    session_store: FederationSessionStore,
    now: Any = None,
) -> dict[str, Any]:
    """Prepare locally after verifying exact-source bundle claims."""

    selection_session_id = str(federated_selection.get("selectionSessionId") or "")
    work_order_digest = _require_work_order_binding(
        session_store,
        selection_session_id,
        work_order,
        now=now,
    )
    validate_federated_selection_wrapper(federated_selection)
    validate_federation_result(
        federation_result,
        lineage_verifier=session_store.lineage_verifier,
        now=now,
    )
    stored = session_store.get(selection_session_id, now=now)
    pinned_selection = session_store.get_federated_selection(
        str(federated_selection.get("selectionSessionId") or ""),
        str(federated_selection.get("federatedSelectionDigest") or ""),
        now=now,
    )
    if canonical_digest(pinned_selection) != canonical_digest(federated_selection):
        raise FederatedProvenanceError("federated_selection_store_binding_mismatch")
    if canonical_digest(stored) != canonical_digest(federation_result):
        raise FederatedProvenanceError("federated_preparation_store_mismatch")
    if federated_selection.get("workOrderDigest") != work_order_digest:
        raise FederatedProvenanceError("federated_work_order_binding_mismatch")
    try:
        supplied_selection_digest = canonical_digest(selection)
    except (TypeError, ValueError) as exc:
        raise FederatedProvenanceError("federated_selection_exact_binding_mismatch") from exc
    if supplied_selection_digest != federated_selection.get("selectionDigest"):
        raise FederatedProvenanceError("federated_selection_exact_binding_mismatch")
    if federated_selection.get("federationDigest") != federation_result.get("federationDigest"):
        raise FederatedProvenanceError("federated_preparation_federation_mismatch")
    if federated_selection.get("status") != "accepted":
        raise FederatedProvenanceError("federated_selection_not_accepted")
    revalidated = validate_host_selection(
        selection,
        candidate_set=stored["candidateSet"],
        work_order=work_order,
        now=now,
    )
    if canonical_digest(revalidated) != canonical_digest(federated_selection.get("selectionValidation")):
        raise FederatedProvenanceError("federated_selection_validation_mismatch")
    if revalidated.get("status") != "accepted":
        raise FederatedProvenanceError("federated_selection_not_accepted")

    expected: dict[tuple[str, str], dict[str, Any]] = {}
    for row in federated_selection["selectionValidation"].get("idealTeam") or []:
        if not isinstance(row, Mapping):
            raise FederatedProvenanceError("federated_selection_invalid")
        pin = _source_pin_from_result(
            stored,
            slot_id=str(row.get("slotId") or ""),
            definition_id=str(row.get("agentDefinitionId") or ""),
            release_id=str(row.get("agentReleaseId") or ""),
        )
        expected[(pin["slotId"], pin["agentReleaseId"])] = pin
    wrapper_pins = {
        (pin.get("slotId"), pin.get("agentReleaseId")): dict(pin)
        for pin in federated_selection.get("selectedSourcePins") or []
        if isinstance(pin, Mapping)
    }
    if wrapper_pins != expected:
        raise FederatedProvenanceError("federated_selection_source_pin_mismatch")
    bundles_by_release: dict[str, dict[str, Any]] = {}
    runtime_pins: list[dict[str, Any]] = []
    observed: set[tuple[str, str]] = set()
    for row in source_runtime_bundles:
        if not isinstance(row, Mapping) or not isinstance(row.get("sourcePin"), Mapping) or not isinstance(
            row.get("runtimeBundle"), Mapping
        ):
            raise FederatedProvenanceError("source_runtime_bundle_invalid")
        pin = row["sourcePin"]
        key = (str(pin.get("slotId") or ""), str(pin.get("agentReleaseId") or ""))
        expected_pin = expected.get(key)
        if expected_pin is None or dict(pin) != dict(expected_pin) or key in observed:
            raise FederatedProvenanceError("source_runtime_bundle_pin_mismatch")
        bundle = dict(row["runtimeBundle"])
        for field in ("agentReleaseId", "packageHash", "contentDigest"):
            if bundle.get(field) != pin.get(field):
                raise FederatedProvenanceError("source_runtime_bundle_claim_mismatch")
        observed.add(key)
        release_id = str(pin["agentReleaseId"])
        existing_bundle = bundles_by_release.get(release_id)
        if existing_bundle is not None and canonical_digest(existing_bundle) != canonical_digest(bundle):
            raise FederatedProvenanceError("source_runtime_bundle_claim_mismatch")
        bundles_by_release[release_id] = bundle
        runtime_pins.append(dict(pin))
    if observed != set(expected):
        raise FederatedProvenanceError("source_runtime_bundle_missing")

    execution_plan = prepare_execution_plan(
        work_order=work_order,
        selection=selection,
        validation_receipt=federated_selection["selectionValidation"],
        candidate_set=stored["candidateSet"],
        # One immutable release bundle is reusable across multiple slot
        # assignments. execution.py maps bundles by release and emits one
        # roster row per assignment, so pass each exact release only once.
        runtime_bundles=list(bundles_by_release.values()),
    )
    wrapper = {
        "schemaVersion": WORKFORCE_FEDERATED_PREPARATION_SCHEMA,
        "status": execution_plan.get("status"),
        "federationDigest": stored["federationDigest"],
        "federatedSelectionDigest": federated_selection["federatedSelectionDigest"],
        "candidateSetDigest": stored["candidateSet"]["candidateSetDigest"],
        "runtimeSourcePins": runtime_pins,
        "executionPlan": execution_plan,
    }
    wrapper["federatedPreparationDigest"] = _wrapper_digest(wrapper, "federatedPreparationDigest")
    return wrapper


__all__ = [
    "FederatedProvenanceError",
    "WORKFORCE_FEDERATED_PREPARATION_SCHEMA",
    "WORKFORCE_FEDERATED_SELECTION_SCHEMA",
    "prepare_federated_execution_plan",
    "validate_federated_host_selection",
    "validate_federated_selection_wrapper",
]
