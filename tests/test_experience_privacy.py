import copy
import json
from pathlib import Path

import pytest

from agentlas_cloud.experience_contracts import ContractValidationError, validate_experience_item
from agentlas_cloud.experience_privacy import (
    PRIVACY_CONTRACT_VERSION,
    scan_public_field,
    scan_public_text,
)
from agentlas_cloud.portable_experience_bundle import (
    experience_bundle_hash,
    experience_bundle_id,
    experience_pack_content_hash,
    normalize_experience_bundle,
    validate_experience_bundle,
)


ROOT = Path(__file__).resolve().parents[1]
PRIVACY_FIXTURE = ROOT / "tests" / "fixtures" / "experience-privacy-v1-cross-surface.json"
BUNDLE_FIXTURE = ROOT / "tests" / "fixtures" / "portable-experience-bundle-v1-golden.json"


def privacy_fixture() -> dict:
    return json.loads(PRIVACY_FIXTURE.read_text(encoding="utf-8"))


def bundle_fixture() -> dict:
    return json.loads(BUNDLE_FIXTURE.read_text(encoding="utf-8"))["bundle"]


def rehash(bundle: dict) -> dict:
    value = normalize_experience_bundle(copy.deepcopy(bundle))
    value["pack"]["contentHash"] = experience_pack_content_hash(value)
    value["bundleHash"] = experience_bundle_hash(value)
    value["bundleId"] = experience_bundle_id(value)
    return value


def direct_item(summary: str, privacy_scope: str = "public-safe") -> dict:
    return {
        "schemaVersion": "agentlas.experience-item.v1",
        "kind": "agentlas-experience-item",
        "experienceItemId": "experience-item:privacy:one",
        "experiencePackId": "experience-pack:privacy:one",
        "experiencePackReleaseId": "experience-release:privacy:one",
        "type": "warning",
        "summary": summary,
        "instructions": ["Keep only the compact public lesson."],
        "taskSignatures": ["task:privacy-review"],
        "environmentConstraints": [],
        "evidenceReceiptIds": ["receipt:privacy:one"],
        "supersedesItemIds": [],
        "confidence": 0.5,
        "status": "candidate",
        "privacyScope": privacy_scope,
    }


def test_cross_surface_privacy_fixture_is_exact():
    fixture = privacy_fixture()
    assert fixture["contractVersion"] == PRIVACY_CONTRACT_VERSION
    for case in fixture["freeTextCases"]:
        assert list(scan_public_text(case["value"])) == case["expected"], case["id"]
    for case in fixture["fieldCases"]:
        assert list(scan_public_field(case["path"], case["value"])) == case["expected"], case["id"]


def test_direct_item_allows_long_opaque_receipt_only_in_receipt_metadata_field():
    receipt = "evidence:" + "a" * 128
    item = direct_item("Use the independently recorded evidence receipt.")
    item["evidenceReceiptIds"] = [receipt]
    validate_experience_item(item)
    item["summary"] = receipt
    with pytest.raises(ContractValidationError, match="opaque"):
        validate_experience_item(item)


def test_portable_bundle_allows_long_opaque_receipt_only_in_receipt_metadata_field():
    receipt = "evidence:" + "a" * 128
    bundle = bundle_fixture()
    bundle["items"][0]["evidenceReceiptIds"] = [receipt]
    bundle["pack"]["evidenceReceiptIds"] = sorted([
        receipt,
        *bundle["items"][1]["evidenceReceiptIds"],
    ])
    validate_experience_bundle(rehash(bundle))
    bundle["items"][0]["summary"] = receipt
    with pytest.raises(ContractValidationError, match="opaque"):
        validate_experience_bundle(rehash(bundle))


@pytest.mark.parametrize(
    "case",
    [case for case in privacy_fixture()["freeTextCases"] if case["expected"]],
    ids=lambda case: case["id"],
)
def test_direct_public_safe_item_rejects_every_deterministic_privacy_case(case: dict):
    with pytest.raises(ContractValidationError, match="public-safe ExperienceItem"):
        validate_experience_item(direct_item(case["value"]))
    validate_experience_item(direct_item(case["value"], "private"))


@pytest.mark.parametrize(
    "case",
    [case for case in privacy_fixture()["freeTextCases"] if not case["expected"]],
    ids=lambda case: case["id"],
)
def test_direct_public_safe_item_allows_public_locations_and_normal_slash_prose(case: dict):
    validate_experience_item(direct_item(case["value"]))


@pytest.mark.parametrize(
    "case",
    [case for case in privacy_fixture()["freeTextCases"] if case["expected"]],
    ids=lambda case: case["id"],
)
def test_portable_bundle_rejects_every_deterministic_privacy_case_even_when_private(case: dict):
    bundle = bundle_fixture()
    bundle["items"][0]["summary"] = case["value"]
    bundle["items"][0]["privacyScope"] = "private"
    bundle["requestedVisibility"] = "private"
    bundle["pack"]["visibility"] = "private"
    bundle = rehash(bundle)
    with pytest.raises(ContractValidationError, match="ExperienceBundle contains"):
        validate_experience_bundle(bundle)


@pytest.mark.parametrize(
    "case",
    [case for case in privacy_fixture()["freeTextCases"] if not case["expected"]],
    ids=lambda case: case["id"],
)
def test_portable_bundle_allows_public_locations_and_normal_slash_prose(case: dict):
    bundle = bundle_fixture()
    bundle["items"][0]["summary"] = case["value"]
    validate_experience_bundle(rehash(bundle))
