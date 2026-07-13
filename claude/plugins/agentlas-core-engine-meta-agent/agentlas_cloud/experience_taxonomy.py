"""Privacy-safe Experience task and environment taxonomy v1.

The portable v1 wire shape intentionally remains open to legacy public IDs.
This module is the stricter activation boundary: only the frozen canonical IDs
below may affect ranking or runtime selection. Unknown legacy values remain
storable but make that item ineligible; they never block the base agent.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .experience_contracts import ContractValidationError
from .portable_experience_bundle import canonical_json


TAXONOMY_SCHEMA = "agentlas.experience-taxonomy.v1"
TASK_SIGNATURE_PREFIX = "agentlas.task.v1/"
ENV_OS_PREFIX = "agentlas.env.v1/os/"
ENV_ARCH_PREFIX = "agentlas.env.v1/arch/"
ENV_RUNTIME_PREFIX = "agentlas.env.v1/runtime/"

TASK_SLUGS_V1 = (
    "research",
    "writing",
    "coding",
    "debugging",
    "design",
    "image-generation",
    "video-production",
    "presentation",
    "document",
    "data-analysis",
    "browser-automation",
    "social-publishing",
    "marketing",
    "sales",
    "customer-support",
    "ecommerce",
    "legal-review",
    "finance",
    "project-planning",
    "agent-building",
    "workflow-automation",
    "file-operations",
    "translation",
)
OS_VALUES_V1 = ("macos", "windows", "linux", "ios", "android", "unknown")
ARCH_VALUES_V1 = ("arm64", "x64", "unknown")
_RUNTIME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_CONTRACT_PATH = Path(__file__).with_name("experience_taxonomy_v1.json")


def _normalized_atom(value: Any) -> str:
    return unicodedata.normalize("NFKC", value).strip().lower() if isinstance(value, str) else ""


def validate_experience_taxonomy_contract(value: Any) -> dict[str, Any]:
    """Validate the frozen catalog itself, not a caller-supplied task label."""

    issues: list[str] = []
    if not isinstance(value, Mapping):
        raise ContractValidationError(["taxonomy contract must be an object"])
    if value.get("schema") != TAXONOMY_SCHEMA:
        issues.append(f"schema must be {TAXONOMY_SCHEMA}")
    if value.get("kind") != "agentlas-experience-taxonomy":
        issues.append("kind must be agentlas-experience-taxonomy")
    if value.get("taskSignaturePrefix") != TASK_SIGNATURE_PREFIX:
        issues.append(f"taskSignaturePrefix must be {TASK_SIGNATURE_PREFIX}")
    if tuple(value.get("taskSlugs") or ()) != TASK_SLUGS_V1:
        issues.append("taskSlugs must exactly match the frozen v1 catalog")
    if "general" in (value.get("taskSlugs") or ()):
        issues.append("general must never be an automatic task match")

    environment = value.get("environment")
    if not isinstance(environment, Mapping):
        issues.append("environment must be an object")
    else:
        expected_environment = {
            "osPrefix": ENV_OS_PREFIX,
            "archPrefix": ENV_ARCH_PREFIX,
            "runtimePrefix": ENV_RUNTIME_PREFIX,
            "osValues": list(OS_VALUES_V1),
            "archValues": list(ARCH_VALUES_V1),
            "runtimePattern": _RUNTIME_RE.pattern,
            "matching": "all-canonical-constraints-must-match",
            "unknownConstraint": "item-ineligible-base-unaffected",
        }
        if dict(environment) != expected_environment:
            issues.append("environment contract differs from frozen v1 semantics")

    normalization = value.get("normalization")
    expected_normalization = {
        "unicode": "NFKC",
        "trim": True,
        "case": "lower",
        "portableSource": "canonical-id-only",
        "runtimeProfile": "canonical-id-or-exact-bare-slug",
        "fuzzySimilarity": False,
        "generalAutoMatch": False,
    }
    if not isinstance(normalization, Mapping) or dict(normalization) != expected_normalization:
        issues.append("normalization contract differs from frozen v1 semantics")
    if issues:
        raise ContractValidationError(issues)
    return json.loads(canonical_json(value))


def load_experience_taxonomy_contract() -> dict[str, Any]:
    return validate_experience_taxonomy_contract(json.loads(_CONTRACT_PATH.read_text(encoding="utf-8")))


EXPERIENCE_TAXONOMY_V1 = load_experience_taxonomy_contract()
EXPERIENCE_TAXONOMY_CHECKSUM = "sha256:" + hashlib.sha256(
    canonical_json(EXPERIENCE_TAXONOMY_V1).encode("utf-8")
).hexdigest()


def canonical_source_task_signature(value: Any) -> str | None:
    """Accept only an explicit portable v1 task ID; bare slugs are legacy."""

    normalized = _normalized_atom(value)
    if not normalized.startswith(TASK_SIGNATURE_PREFIX):
        return None
    slug = normalized[len(TASK_SIGNATURE_PREFIX) :]
    return normalized if slug in TASK_SLUGS_V1 else None


def canonical_profile_task_signature(value: Any) -> str | None:
    """Map an exact runtime slug or canonical ID without fuzzy similarity."""

    normalized = _normalized_atom(value)
    source_id = canonical_source_task_signature(normalized)
    if source_id:
        return source_id
    return f"{TASK_SIGNATURE_PREFIX}{normalized}" if normalized in TASK_SLUGS_V1 else None


def canonical_profile_task_signatures(task_class: Any, capability_tags: Sequence[Any]) -> tuple[str, ...]:
    values = [canonical_profile_task_signature(task_class), *(
        canonical_profile_task_signature(value) for value in capability_tags
    )]
    return tuple(dict.fromkeys(value for value in values if value))


def parse_environment_constraint(value: Any) -> tuple[str, str] | None:
    normalized = _normalized_atom(value)
    if normalized.startswith(ENV_OS_PREFIX):
        os_value = normalized[len(ENV_OS_PREFIX) :]
        return ("os", os_value) if os_value in OS_VALUES_V1 else None
    if normalized.startswith(ENV_ARCH_PREFIX):
        arch_value = normalized[len(ENV_ARCH_PREFIX) :]
        return ("arch", arch_value) if arch_value in ARCH_VALUES_V1 else None
    if normalized.startswith(ENV_RUNTIME_PREFIX):
        runtime = normalized[len(ENV_RUNTIME_PREFIX) :]
        return ("runtime", runtime) if _RUNTIME_RE.fullmatch(runtime) else None
    return None


def environment_constraints_match(constraints: Sequence[Any], environment: Mapping[str, Any]) -> bool:
    actual = {
        "os": _normalized_atom(environment.get("os")),
        "arch": _normalized_atom(environment.get("arch")),
        "runtime": _normalized_atom(environment.get("runtime")),
    }
    if actual["os"] not in OS_VALUES_V1 or actual["arch"] not in ARCH_VALUES_V1 or not _RUNTIME_RE.fullmatch(actual["runtime"]):
        return False
    for raw in constraints:
        parsed = parse_environment_constraint(raw)
        if not parsed:
            return False
        dimension, expected = parsed
        if actual[dimension] != expected:
            return False
    return True


def select_applicable_portable_items(
    items: Sequence[Mapping[str, Any]],
    *,
    task_class: Any,
    capability_tags: Sequence[Any],
    environment: Mapping[str, Any],
) -> list[str]:
    """Reference selection used by Core/Web drift fixtures.

    Lifecycle and supersedes are applied only after exact task/environment
    eligibility. An ineligible superseder cannot hide an otherwise valid item.
    """

    profile_ids = set(canonical_profile_task_signatures(task_class, capability_tags))
    if not profile_ids:
        return []
    eligible: list[Mapping[str, Any]] = []
    for item in items:
        if item.get("status") in {"deprecated", "rejected"}:
            continue
        source_ids = {
            canonical
            for raw in item.get("taskSignatures") or ()
            if (canonical := canonical_source_task_signature(raw))
        }
        if not source_ids.intersection(profile_ids):
            continue
        if not environment_constraints_match(item.get("environmentConstraints") or (), environment):
            continue
        eligible.append(item)
    superseded = {
        item_id
        for item in eligible
        for item_id in (item.get("supersedesItemIds") or ())
        if isinstance(item_id, str)
    }
    return [
        str(item["experienceItemId"])
        for item in eligible
        if isinstance(item.get("experienceItemId"), str) and item["experienceItemId"] not in superseded
    ]


__all__ = [
    "ARCH_VALUES_V1",
    "ENV_ARCH_PREFIX",
    "ENV_OS_PREFIX",
    "ENV_RUNTIME_PREFIX",
    "EXPERIENCE_TAXONOMY_CHECKSUM",
    "EXPERIENCE_TAXONOMY_V1",
    "OS_VALUES_V1",
    "TASK_SIGNATURE_PREFIX",
    "TASK_SLUGS_V1",
    "canonical_profile_task_signature",
    "canonical_profile_task_signatures",
    "canonical_source_task_signature",
    "environment_constraints_match",
    "load_experience_taxonomy_contract",
    "parse_environment_constraint",
    "select_applicable_portable_items",
    "validate_experience_taxonomy_contract",
]
