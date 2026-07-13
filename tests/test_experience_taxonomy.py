from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentlas_cloud.experience_contracts import ContractValidationError
from agentlas_cloud.experience_taxonomy import (
    EXPERIENCE_TAXONOMY_CHECKSUM,
    EXPERIENCE_TAXONOMY_V1,
    TASK_SLUGS_V1,
    canonical_profile_task_signature,
    canonical_profile_task_signatures,
    canonical_source_task_signature,
    environment_constraints_match,
    load_experience_taxonomy_contract,
    select_applicable_portable_items,
    validate_experience_taxonomy_contract,
)


FIXTURE = Path(__file__).parent / "fixtures" / "experience-taxonomy-v1-cross-surface.json"


def test_frozen_taxonomy_artifact_and_checksum() -> None:
    assert load_experience_taxonomy_contract() == EXPERIENCE_TAXONOMY_V1
    assert len(TASK_SLUGS_V1) == 23
    assert "general" not in TASK_SLUGS_V1
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["taxonomyChecksum"] == EXPERIENCE_TAXONOMY_CHECKSUM


def test_contract_validator_rejects_drift_and_general() -> None:
    drifted = json.loads(json.dumps(EXPERIENCE_TAXONOMY_V1))
    drifted["taskSlugs"].append("general")
    with pytest.raises(ContractValidationError):
        validate_experience_taxonomy_contract(drifted)


def test_source_is_strict_but_runtime_profile_accepts_exact_slug() -> None:
    assert canonical_source_task_signature("agentlas.task.v1/research") == "agentlas.task.v1/research"
    assert canonical_source_task_signature(" research ") is None
    assert canonical_source_task_signature("sha256:" + "a" * 64) is None
    assert canonical_profile_task_signature(" Research ") == "agentlas.task.v1/research"
    assert canonical_profile_task_signature("agentlas.task.v1/WRITING") == "agentlas.task.v1/writing"
    assert canonical_profile_task_signature("general") is None
    assert canonical_profile_task_signatures("research", ["writing", "research", "unknown-task"]) == (
        "agentlas.task.v1/research",
        "agentlas.task.v1/writing",
    )


def test_environment_constraints_are_exact_and_unknown_fails_closed() -> None:
    environment = {"os": "macos", "arch": "arm64", "runtime": "codex"}
    assert environment_constraints_match([], environment)
    assert environment_constraints_match([
        "agentlas.env.v1/os/macos",
        "agentlas.env.v1/arch/arm64",
        "agentlas.env.v1/runtime/codex",
    ], environment)
    assert not environment_constraints_match(["agentlas.env.v1/os/windows"], environment)
    assert not environment_constraints_match(["macos-arm64"], environment)
    assert not environment_constraints_match(["agentlas.env.v1/runtime/unknown runtime"], environment)


def test_cross_surface_selection_fixture() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    by_id = {item["experienceItemId"]: item for item in fixture["items"]}
    for case in fixture["cases"]:
        selected = select_applicable_portable_items(
            [by_id[item_id] for item_id in case["itemIds"]],
            task_class=case["taskClass"],
            capability_tags=case["capabilityTags"],
            environment=case["environment"],
        )
        assert selected == case["expectedSelectedItemIds"], case["id"]
