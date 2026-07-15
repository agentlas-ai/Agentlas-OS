"""Deterministic, non-mutating privacy gate for Hub-bound WorkOrders."""

from __future__ import annotations

from typing import Any, Mapping

from ..experience_privacy import scan_public_text, secret_like_kinds
from .contracts import canonical_digest


WORKFORCE_HUB_BOUNDARY_SCHEMA = "agentlas.workforce-hub-boundary.v1"


class WorkOrderHubBoundaryError(ValueError):
    """Raised before transport when Hub-bound free text is not public-safe."""

    def __init__(self, validation: Mapping[str, Any]):
        self.validation = dict(validation)
        super().__init__("work_order_hub_boundary_rejected")


def validate_hub_work_order_boundary(work_order: Mapping[str, Any]) -> dict[str, Any]:
    """Validate only the free text that crosses the Hub trust boundary.

    This function never redacts, normalizes, copies values back into the input,
    or calls a transport.  A host may give the path/code-only issues back to the
    same model for one bounded repair; it must not send the rejected WorkOrder.
    """

    issues: list[dict[str, str]] = []

    def add(path: str, code: str) -> None:
        issue = {"path": path, "code": code}
        if issue not in issues:
            issues.append(issue)

    if work_order.get("redacted") is not True:
        add("redacted", "hub_redacted_flag_required")

    fields: list[tuple[str, Any]] = [("taskBrief", work_order.get("taskBrief"))]
    slots = work_order.get("roleSlots")
    if isinstance(slots, list):
        for index, slot in enumerate(slots):
            if not isinstance(slot, Mapping):
                add(f"roleSlots[{index}]", "hub_text_container_invalid")
                continue
            fields.extend(
                (
                    (f"roleSlots[{index}].title", slot.get("title")),
                    (f"roleSlots[{index}].task", slot.get("task")),
                )
            )
    else:
        add("roleSlots", "hub_text_container_invalid")

    for path, value in fields:
        if not isinstance(value, str) or not value.strip():
            add(path, "hub_text_invalid")
            continue
        for kind in scan_public_text(value):
            add(path, f"hub_private_{kind}")
        for kind in secret_like_kinds(value):
            add(path, f"hub_secret_{kind}")

    return {
        "schemaVersion": WORKFORCE_HUB_BOUNDARY_SCHEMA,
        "status": "rejected" if issues else "accepted",
        "repairable": bool(issues),
        "mutation": "none",
        "workOrderDigest": canonical_digest(work_order),
        "issues": issues,
    }


def assert_hub_work_order_boundary(work_order: Mapping[str, Any]) -> dict[str, Any]:
    validation = validate_hub_work_order_boundary(work_order)
    if validation["status"] != "accepted":
        raise WorkOrderHubBoundaryError(validation)
    return validation


__all__ = [
    "WORKFORCE_HUB_BOUNDARY_SCHEMA",
    "WorkOrderHubBoundaryError",
    "assert_hub_work_order_boundary",
    "validate_hub_work_order_boundary",
]
