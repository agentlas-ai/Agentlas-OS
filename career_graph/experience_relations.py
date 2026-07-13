from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


SCHEMA_VERSION = "agentlas.experience-relation-lineage.v1"
KIND = "agentlas-experience-relation-lineage"

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{2,255}$")
_TAG_RE = re.compile(r"^[a-z0-9\uac00-\ud7a3][a-z0-9\uac00-\ud7a3._-]{1,63}$")
_HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_UNSAFE_IDENTIFIER_RE = re.compile(
    r"(?:^[/\\]|://|\\|/Users/|/home/|file:|(?:api[_-]?key|token|secret|password|authorization|cookie))",
    re.IGNORECASE,
)

_TOP_LEVEL_KEYS = {
    "schemaVersion",
    "kind",
    "eventId",
    "eventType",
    "packId",
    "releaseId",
    "baseReleaseHash",
    "projectScopeKey",
    "environmentKey",
    "itemIds",
    "taskBindings",
    "mcpRequirements",
    "evidenceBindings",
    "supersedesReleaseId",
    "sourceFingerprint",
    "createdAt",
}


@dataclass(frozen=True)
class LineageValidation:
    event: dict[str, Any] | None
    issues: tuple[str, ...]


def _safe_id(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(_ID_RE.fullmatch(value))
        and not _UNSAFE_IDENTIFIER_RE.search(value)
    )


def _safe_tag(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(_TAG_RE.fullmatch(value))
        and not _UNSAFE_IDENTIFIER_RE.search(value)
        and not (value.isdigit() and len(value) >= 8)
        and not bool(re.fullmatch(r"[0-9a-fA-F]{24,}", value))
    )


def _unique(values: list[Any]) -> bool:
    return len(values) == len({str(value) for value in values})


def validate_lineage_event(value: Any) -> LineageValidation:
    """Validate the value-free Experience lineage contract.

    The accepted event intentionally has no free-form summary, instruction,
    prompt, transcript, path, URL, account identifier, or package bytes. It is
    safe lineage metadata for rebuilding a local relation index, not the owned
    Experience asset itself.
    """

    issues: list[str] = []
    if not isinstance(value, dict):
        return LineageValidation(None, ("event-not-object",))
    if set(value) != _TOP_LEVEL_KEYS:
        issues.append("unexpected-or-missing-fields")
    if value.get("schemaVersion") != SCHEMA_VERSION:
        issues.append("schema-version")
    if value.get("kind") != KIND:
        issues.append("kind")
    if value.get("eventType") not in {"promotion", "export-intent"}:
        issues.append("event-type")

    for key in ("eventId", "packId", "releaseId"):
        if not _safe_id(value.get(key)):
            issues.append(f"unsafe-{key}")
    for key in ("baseReleaseHash", "projectScopeKey", "environmentKey", "sourceFingerprint"):
        if not isinstance(value.get(key), str) or not _HASH_RE.fullmatch(value[key]):
            issues.append(f"invalid-{key}")
    if not isinstance(value.get("createdAt"), str) or not _DATETIME_RE.fullmatch(value["createdAt"]):
        issues.append("created-at")

    supersedes = value.get("supersedesReleaseId")
    if supersedes is not None and not _safe_id(supersedes):
        issues.append("unsafe-supersedes-release")
    if supersedes is not None and supersedes == value.get("releaseId"):
        issues.append("self-supersedes")

    item_ids = value.get("itemIds")
    if not isinstance(item_ids, list) or len(item_ids) > 256 or not all(_safe_id(item) for item in item_ids):
        issues.append("item-ids")
        item_ids = []
    elif not _unique(item_ids):
        issues.append("duplicate-item-ids")
    item_set = set(item_ids)

    task_bindings = value.get("taskBindings")
    if not isinstance(task_bindings, list) or len(task_bindings) > 256:
        issues.append("task-bindings")
        task_bindings = []
    else:
        seen_items: set[str] = set()
        for binding in task_bindings:
            if not isinstance(binding, dict) or set(binding) != {"itemId", "tags"}:
                issues.append("task-binding-shape")
                continue
            item_id = binding.get("itemId")
            tags = binding.get("tags")
            if item_id not in item_set or item_id in seen_items:
                issues.append("task-binding-item")
            if not isinstance(tags, list) or len(tags) > 32 or not all(_safe_tag(tag) for tag in tags):
                issues.append("task-binding-tags")
            elif not _unique(tags):
                issues.append("duplicate-task-tags")
            if isinstance(item_id, str):
                seen_items.add(item_id)

    requirements = value.get("mcpRequirements")
    if not isinstance(requirements, list) or len(requirements) > 32:
        issues.append("mcp-requirements")
        requirements = []
    else:
        seen_catalogs: set[str] = set()
        for requirement in requirements:
            if not isinstance(requirement, dict) or set(requirement) != {"catalogId", "required", "alternatives"}:
                issues.append("mcp-requirement-shape")
                continue
            catalog_id = requirement.get("catalogId")
            alternatives = requirement.get("alternatives")
            if not _safe_id(catalog_id) or catalog_id in seen_catalogs:
                issues.append("mcp-catalog-id")
            if not isinstance(requirement.get("required"), bool):
                issues.append("mcp-required")
            if (
                not isinstance(alternatives, list)
                or len(alternatives) > 8
                or not all(_safe_id(item) for item in alternatives)
                or not _unique(alternatives)
                or catalog_id in alternatives
            ):
                issues.append("mcp-alternatives")
            if isinstance(catalog_id, str):
                seen_catalogs.add(catalog_id)

    evidence_bindings = value.get("evidenceBindings")
    if not isinstance(evidence_bindings, list) or len(evidence_bindings) > 256:
        issues.append("evidence-bindings")
        evidence_bindings = []
    else:
        seen_items = set()
        for binding in evidence_bindings:
            if not isinstance(binding, dict) or set(binding) != {"itemId", "receiptIds"}:
                issues.append("evidence-binding-shape")
                continue
            item_id = binding.get("itemId")
            receipt_ids = binding.get("receiptIds")
            if item_id not in item_set or item_id in seen_items:
                issues.append("evidence-binding-item")
            if (
                not isinstance(receipt_ids, list)
                or len(receipt_ids) > 16
                or not all(_safe_id(receipt_id) for receipt_id in receipt_ids)
                or not _unique(receipt_ids)
            ):
                issues.append("evidence-receipt-ids")
            if isinstance(item_id, str):
                seen_items.add(item_id)

    if issues:
        return LineageValidation(None, tuple(sorted(set(issues))))
    return LineageValidation(value, ())
