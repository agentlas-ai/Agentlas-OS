"""Canonical Portable Experience Bundle v1 validation.

This module is deliberately deterministic and model-free.  It owns only the
portable wire format: account ownership, Cloud release authority, persistence,
activation and reputation remain host responsibilities.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from decimal import Decimal
from datetime import datetime
from typing import Any

from .experience_contracts import (
    ContractValidationError,
    validate_experience_item,
    validate_experience_pack,
    validate_mcp_requirement,
)
from .experience_privacy import is_allowed_protocol_metadata, scan_public_field


EXPERIENCE_BUNDLE_SCHEMA_VERSION = "agentlas.experience-bundle.v1"
EXPERIENCE_UPLOAD_RECEIPT_SCHEMA_VERSION = "agentlas.experience-upload-receipt.v1"
MAX_BUNDLE_CANONICAL_BYTES = 3 * 1024 * 1024
MAX_STORED_ITEMS = 256
MAX_MCP_REQUIREMENTS = 64
MAX_EVIDENCE_REFS_PER_ITEM = 24
MAX_INSTRUCTIONS_PER_ITEM = 8
MAX_TASK_SIGNATURES_PER_ITEM = 32
MAX_SOURCE_ATTESTATIONS = MAX_STORED_ITEMS * MAX_EVIDENCE_REFS_PER_ITEM

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_PUBLIC_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{2,255}$")
_BUNDLE_ID_RE = re.compile(r"^exb_[0-9a-f]{48}$")
_UPLOAD_ID_RE = re.compile(r"^exu_[0-9a-f]{48}$")
_SEMVER_RE = re.compile(r"^v?[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?$")
_SECRET_PATTERNS = (
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b", re.I),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b", re.I),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.I),
    re.compile(
        r"\b(?:api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|"
        r"password|passwd|private[_-]?key|cookie)\b\s*[:=]\s*['\"]?[^\s'\"]{8,}",
        re.I,
    ),
    re.compile(r"\bauthorization\b\s*[:=]\s*['\"]?(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}", re.I),
)
_RAW_INTERACTION_PATTERNS = (
    re.compile(r"(?:^|\n)\s*(?:system|assistant|user|tool|customer|agent)\s*:\s+", re.I),
    re.compile(r"['\"]role['\"]\s*:\s*['\"](?:system|assistant|user|tool)['\"]", re.I),
    re.compile(r"<\|(?:system|assistant|user|im_start|im_end)[^>]*\|>", re.I),
    re.compile(r"BEGIN[ _-]?(?:SYSTEM[ _-]?PROMPT|BASE[ _-]?PROMPT|AGENT[ _-]?PACKAGE)", re.I),
    re.compile(r"\b(?:AGENTS|CLAUDE|GEMINI)\.md\b|\.agentlas[/\\]", re.I),
)
_PROMPT_INJECTION_PATTERNS = (
    re.compile(
        r"\b(?:ignore|disregard|override)[\s_-]+(?:all[\s_-]+)?"
        r"(?:previous|prior|system|developer|hidden)[\s_-]+(?:instructions?|prompts?|rules?)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:reveal|show|print|dump|expose|leak)[\s_-]+(?:(?:the|all)[\s_-]+)?"
        r"(?:(?:hidden|system|developer)[\s_-]+)?(?:prompts?|instructions?|credentials?|secrets?|tokens?|api[\s_-]?keys?)\b",
        re.I,
    ),
    re.compile(r"\b(?:exfiltrate|steal|upload|send)[^\n]{0,120}\b(?:secrets?|credentials?|tokens?|api[\s_-]?keys?|\.env)\b", re.I),
    re.compile(r"\b(?:disable|bypass|skip|remove|turn[\s_-]+off)[\s_-]+(?:safety|guardrails?|approval|permission|security)\b", re.I),
)
_BASE_PACKAGE_PATTERNS = (
    re.compile(r"\bcontentBase64\b|\bcloudPackage\b\s*[:=]", re.I),
    re.compile(r"\b(?:full|raw)\s+(?:system prompt|agent package|base package)\b", re.I),
    re.compile(r"\bBEGIN AGENTLAS (?:AGENT|PACKAGE)\b", re.I),
)
_OPAQUE_BLOB_RE = re.compile(r"(?:[A-Fa-f0-9]{128,}|[A-Za-z0-9+/]{124,}={0,2})")


def _nfc(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def _normalize_json(value: Any) -> Any:
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _nfc(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError(["canonical JSON forbids non-finite numbers"])
        return 0 if value == 0 else value
    if isinstance(value, Mapping):
        normalized: dict[str, Any] = {}
        for raw_key, child in value.items():
            if not isinstance(raw_key, str):
                raise ContractValidationError(["canonical JSON object keys must be strings"])
            key = _nfc(raw_key)
            if key in normalized:
                raise ContractValidationError([f"NFC-normalized object key collision: {key}"])
            normalized[key] = _normalize_json(child)
        return normalized
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, memoryview)):
        return [_normalize_json(child) for child in value]
    raise ContractValidationError([f"canonical JSON forbids {type(value).__name__}"])


def canonical_json(value: Any) -> str:
    """RFC-8259 JSON with NFC strings, code-point-sorted keys and no whitespace."""

    def encode(node: Any) -> str:
        if node is None:
            return "null"
        if node is True:
            return "true"
        if node is False:
            return "false"
        if isinstance(node, str):
            return json.dumps(node, ensure_ascii=False, allow_nan=False)
        if isinstance(node, int):
            return str(node)
        if isinstance(node, float):
            return _ecmascript_number(node)
        if isinstance(node, list):
            return "[" + ",".join(encode(child) for child in node) + "]"
        if isinstance(node, Mapping):
            return "{" + ",".join(
                f"{json.dumps(key, ensure_ascii=False)}:{encode(node[key])}" for key in sorted(node)
            ) + "}"
        raise ContractValidationError([f"canonical JSON forbids {type(node).__name__}"])

    return encode(_normalize_json(value))


def _ecmascript_number(value: float) -> str:
    """Match JSON.stringify for finite IEEE-754 numbers used by the contract."""

    if not math.isfinite(value):
        raise ContractValidationError(["canonical JSON forbids non-finite numbers"])
    if value == 0:
        return "0"
    if value.is_integer() and abs(value) < 1e21:
        return str(int(value))
    shortest = repr(value).lower()
    magnitude = abs(value)
    if 1e-6 <= magnitude < 1e21:
        fixed = format(Decimal(shortest), "f")
        if "." in fixed:
            fixed = fixed.rstrip("0").rstrip(".")
        return fixed
    if "e" not in shortest:
        shortest = format(value, ".15e")
    mantissa, exponent = shortest.split("e", 1)
    mantissa = mantissa.rstrip("0").rstrip(".")
    exponent_value = int(exponent)
    sign = "+" if exponent_value >= 0 else ""
    return f"{mantissa}e{sign}{exponent_value}"


def _hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _sorted_unique(values: Sequence[Any]) -> list[Any]:
    by_json = {canonical_json(value): value for value in values}
    return [by_json[key] for key in sorted(by_json)]


def _normalize_mcp_requirement(raw: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(_normalize_json(raw))
    for key in ("capabilities", "permissions", "alternatives"):
        if isinstance(value.get(key), list):
            value[key] = _sorted_unique(value[key])
    metadata = value.get("credentialMetadata")
    if isinstance(metadata, Mapping):
        metadata = dict(metadata)
        for key in ("env", "allowedHosts", "scopes"):
            if isinstance(metadata.get(key), list):
                metadata[key] = _sorted_unique(metadata[key])
        value["credentialMetadata"] = metadata
    return value


def _normalize_item(raw: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(_normalize_json(raw))
    for key in ("taskSignatures", "environmentConstraints", "evidenceReceiptIds", "supersedesItemIds"):
        if isinstance(value.get(key), list):
            value[key] = _sorted_unique(value[key])
    return value


def normalize_experience_bundle(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Return the canonical semantic envelope; set-like arrays are deduplicated."""

    if not isinstance(payload, Mapping):
        raise ContractValidationError(["ExperienceBundle must be an object"])
    value = dict(_normalize_json(payload))
    pack = value.get("pack")
    if isinstance(pack, Mapping):
        pack = dict(pack)
        compatibility = pack.get("baseCompatibility")
        if isinstance(compatibility, Mapping):
            compatibility = dict(compatibility)
            if isinstance(compatibility.get("compatibleBaseReleaseIds"), list):
                compatibility["compatibleBaseReleaseIds"] = _sorted_unique(compatibility["compatibleBaseReleaseIds"])
            pack["baseCompatibility"] = compatibility
        for key in ("itemIds", "evidenceReceiptIds"):
            if isinstance(pack.get(key), list):
                pack[key] = _sorted_unique(pack[key])
        if isinstance(pack.get("mcpRequirements"), list):
            pack["mcpRequirements"] = _sorted_unique([
                _normalize_mcp_requirement(item) if isinstance(item, Mapping) else item
                for item in pack["mcpRequirements"]
            ])
        value["pack"] = pack
    if isinstance(value.get("items"), list):
        value["items"] = _sorted_unique([
            _normalize_item(item) if isinstance(item, Mapping) else item
            for item in value["items"]
        ])
    if isinstance(value.get("sourceAttestations"), list):
        value["sourceAttestations"] = _sorted_unique(value["sourceAttestations"])
    return value


def experience_pack_content_payload(bundle: Mapping[str, Any]) -> dict[str, Any]:
    value = normalize_experience_bundle(bundle)
    pack = value.get("pack")
    items = value.get("items")
    if not isinstance(pack, Mapping) or not isinstance(items, list):
        raise ContractValidationError(["ExperienceBundle needs pack and items before hashing"])
    return {
        "schemaVersion": pack.get("schemaVersion"),
        "kind": pack.get("kind"),
        "experiencePackId": pack.get("experiencePackId"),
        "releaseId": pack.get("releaseId"),
        "version": pack.get("version"),
        "baseCompatibility": pack.get("baseCompatibility"),
        "itemIds": pack.get("itemIds"),
        "items": items,
        "evidenceReceiptIds": pack.get("evidenceReceiptIds"),
        "mcpRequirements": pack.get("mcpRequirements"),
        "containsBasePackageMaterial": pack.get("containsBasePackageMaterial"),
    }


def experience_pack_content_hash(bundle: Mapping[str, Any]) -> str:
    return _hash(experience_pack_content_payload(bundle))


def experience_bundle_hash_payload(bundle: Mapping[str, Any]) -> dict[str, Any]:
    value = normalize_experience_bundle(bundle)
    return {
        "content": experience_pack_content_payload(value),
        "sourceAttestations": value.get("sourceAttestations"),
        "privacy": value.get("privacy"),
    }


def experience_bundle_hash(bundle: Mapping[str, Any]) -> str:
    return _hash(experience_bundle_hash_payload(bundle))


def experience_bundle_id(bundle: Mapping[str, Any]) -> str:
    return "exb_" + experience_bundle_hash(bundle).removeprefix("sha256:")[:48]


def _strict_object(value: Any, required: set[str], allowed: set[str], label: str, issues: list[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        issues.append(f"{label} must be an object")
        return {}
    data = dict(value)
    missing = sorted(required - set(data))
    unknown = sorted(set(data) - allowed)
    if missing:
        issues.append(f"{label} missing required fields: {', '.join(missing)}")
    if unknown:
        issues.append(f"{label} contains unknown fields: {', '.join(unknown)}")
    return data


def _validate_bundle_security(value: Mapping[str, Any], issues: list[str]) -> None:
    text_values: list[tuple[str, str]] = []

    def walk(node: Any, path: str = "") -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
                next_path = f"{path}.{key}" if path else str(key)
                if normalized_key in {
                    "basepackage", "basepackagefiles", "baseprompt", "cloudpackage", "contentbase64",
                    "files", "fulltranscript", "rawsource", "systemprompt", "transcript", "messages",
                    "command", "args", "cwd", "endpoint", "executable", "headers", "serverurl",
                    "transportendpoint",
                }:
                    issues.append(f"ExperienceBundle forbids executable/raw field {next_path}")
                walk(child, next_path)
        elif isinstance(node, list):
            for index, child in enumerate(node):
                walk(child, f"{path}[{index}]")
        elif isinstance(node, str):
            text_values.append((path, node))

    walk(value)
    values = [item for _, item in text_values]
    privacy_findings = {
        finding
        for path, item in text_values
        for finding in scan_public_field(path, item)
    }
    if "local_path" in privacy_findings:
        issues.append("ExperienceBundle contains absolute local path, traversal, or file URL")
    if any(finding != "local_path" for finding in privacy_findings):
        issues.append("ExperienceBundle contains personal/customer identifier")
    checks = (
        (_SECRET_PATTERNS, values, "secret or credential value"),
        (_RAW_INTERACTION_PATTERNS, values, "raw prompt, transcript, or base package marker"),
        (_PROMPT_INJECTION_PATTERNS, values, "prompt-injection instruction"),
        (_BASE_PACKAGE_PATTERNS, values, "base package material"),
    )
    for patterns, candidates, label in checks:
        if any(pattern.search(candidate) for pattern in patterns for candidate in candidates):
            issues.append(f"ExperienceBundle contains {label}")
    if any(_OPAQUE_BLOB_RE.search(item) for path, item in text_values if not _metadata_string(path, item)):
        issues.append("ExperienceBundle contains a long opaque encoded blob")


def _metadata_string(path: str, value: str) -> bool:
    """Hashes, asset ids and ISO timestamps are protocol metadata, not PII blobs."""

    return bool(
        is_allowed_protocol_metadata(path, value)
        or (_UPLOAD_ID_RE.fullmatch(value) and path.rsplit(".", 1)[-1].lower().startswith("uploadid"))
    )


def validate_experience_bundle(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate cross-references, privacy, sizes and both canonical hashes."""

    value = normalize_experience_bundle(payload)
    issues: list[str] = []
    required = {"schemaVersion", "kind", "bundleId", "bundleHash", "requestedVisibility", "pack", "items", "sourceAttestations", "privacy"}
    _strict_object(value, required, required, "ExperienceBundle", issues)
    if value.get("schemaVersion") != EXPERIENCE_BUNDLE_SCHEMA_VERSION:
        issues.append(f"schemaVersion must equal {EXPERIENCE_BUNDLE_SCHEMA_VERSION!r}")
    if value.get("kind") != "agentlas-experience-bundle":
        issues.append("kind must equal 'agentlas-experience-bundle'")
    if value.get("requestedVisibility") not in {"private", "unlisted", "public"}:
        issues.append("requestedVisibility must be private, unlisted, or public")

    pack = value.get("pack")
    items = value.get("items")
    if isinstance(pack, Mapping):
        try:
            validate_experience_pack(pack)
        except ContractValidationError as exc:
            issues.extend(f"pack: {issue}" for issue in exc.issues)
        version = pack.get("version")
        if not isinstance(version, str) or not _SEMVER_RE.fullmatch(version):
            issues.append("pack.version must be a semantic version")
        requirements = pack.get("mcpRequirements")
        if not isinstance(requirements, list) or len(requirements) > MAX_MCP_REQUIREMENTS:
            issues.append(f"pack.mcpRequirements must contain at most {MAX_MCP_REQUIREMENTS} requirements")
        elif requirements:
            for index, requirement in enumerate(requirements):
                try:
                    validate_mcp_requirement(requirement)
                except ContractValidationError as exc:
                    issues.extend(f"pack.mcpRequirements[{index}]: {issue}" for issue in exc.issues)
    else:
        issues.append("pack must be an object")

    if not isinstance(items, list) or not 1 <= len(items) <= MAX_STORED_ITEMS:
        issues.append(f"items must contain 1..{MAX_STORED_ITEMS} items")
        items = []
    item_ids: list[str] = []
    evidence_ids: list[str] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            issues.append(f"items[{index}] must be an object")
            continue
        try:
            validate_experience_item(item)
        except ContractValidationError as exc:
            issues.extend(f"items[{index}]: {issue}" for issue in exc.issues)
        item_id = item.get("experienceItemId")
        if isinstance(item_id, str):
            item_ids.append(item_id)
        if isinstance(pack, Mapping):
            if item.get("experiencePackId") != pack.get("experiencePackId"):
                issues.append(f"items[{index}].experiencePackId does not match pack")
            if item.get("experiencePackReleaseId") != pack.get("releaseId"):
                issues.append(f"items[{index}].experiencePackReleaseId does not match pack release")
        bounds = (
            ("instructions", 1, MAX_INSTRUCTIONS_PER_ITEM),
            ("taskSignatures", 1, MAX_TASK_SIGNATURES_PER_ITEM),
            ("evidenceReceiptIds", 1, MAX_EVIDENCE_REFS_PER_ITEM),
        )
        for key, minimum, maximum in bounds:
            entries = item.get(key)
            if not isinstance(entries, list) or not minimum <= len(entries) <= maximum:
                issues.append(f"items[{index}].{key} must contain {minimum}..{maximum} values")
        if isinstance(item.get("evidenceReceiptIds"), list):
            evidence_ids.extend(entry for entry in item["evidenceReceiptIds"] if isinstance(entry, str))

    if len(item_ids) != len(set(item_ids)):
        issues.append("items must have unique experienceItemId values")
    if isinstance(pack, Mapping):
        if list(pack.get("itemIds") or []) != _sorted_unique(item_ids):
            issues.append("pack.itemIds must exactly equal the canonical submitted item ids")
        if list(pack.get("evidenceReceiptIds") or []) != _sorted_unique(evidence_ids):
            issues.append("pack.evidenceReceiptIds must exactly equal the items' evidence receipt ids")

    attestations = value.get("sourceAttestations")
    attestation_required = {"kind", "experienceItemId", "evidenceHash"}
    if not isinstance(attestations, list) or len(attestations) > MAX_SOURCE_ATTESTATIONS:
        issues.append(f"sourceAttestations must contain at most {MAX_SOURCE_ATTESTATIONS} entries")
        attestations = []
    for index, attestation in enumerate(attestations):
        row = _strict_object(attestation, attestation_required, attestation_required, f"sourceAttestations[{index}]", issues)
        if row.get("kind") != "user-attested":
            issues.append(f"sourceAttestations[{index}].kind must be user-attested")
        if row.get("experienceItemId") not in set(item_ids):
            issues.append(f"sourceAttestations[{index}] references a missing experience item")
        if not isinstance(row.get("evidenceHash"), str) or not _SHA256_RE.fullmatch(str(row.get("evidenceHash"))):
            issues.append(f"sourceAttestations[{index}].evidenceHash is invalid")

    privacy_required = {
        "basePackageMaterialIncluded", "rawPromptIncluded", "rawTranscriptIncluded",
        "rawLocalPathsIncluded", "credentialValuesIncluded",
    }
    privacy = _strict_object(value.get("privacy"), privacy_required, privacy_required, "privacy", issues)
    for flag in privacy_required:
        if privacy.get(flag) is not False:
            issues.append(f"privacy.{flag} must be false")

    _validate_bundle_security(value, issues)
    try:
        canonical_bytes = len(canonical_json(value).encode("utf-8"))
        if canonical_bytes > MAX_BUNDLE_CANONICAL_BYTES:
            issues.append(f"canonical ExperienceBundle exceeds {MAX_BUNDLE_CANONICAL_BYTES} bytes")
        expected_pack_hash = experience_pack_content_hash(value)
        if isinstance(pack, Mapping) and pack.get("contentHash") != expected_pack_hash:
            issues.append("pack.contentHash does not match canonical Experience content")
        expected_bundle_hash = experience_bundle_hash(value)
        if value.get("bundleHash") != expected_bundle_hash:
            issues.append("bundleHash does not match canonical bundle content")
        expected_bundle_id = "exb_" + expected_bundle_hash.removeprefix("sha256:")[:48]
        if value.get("bundleId") != expected_bundle_id or not _BUNDLE_ID_RE.fullmatch(str(value.get("bundleId", ""))):
            issues.append("bundleId must be derived from bundleHash")
    except ContractValidationError as exc:
        issues.extend(exc.issues)
    if issues:
        raise ContractValidationError(issues)
    return value


def validate_experience_upload_receipt(payload: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema", "uploadId", "bundleId", "bundleHash",
        "experiencePackId", "experienceReleaseId", "ownerWorkspaceRef", "status",
        "requestedVisibility", "revision", "createdAt", "updatedAt",
    }
    issues: list[str] = []
    normalized = _normalize_json(payload)
    if not isinstance(normalized, Mapping):
        raise ContractValidationError(["ExperienceUploadReceipt must be an object"])
    data = dict(normalized)
    missing = sorted(required - set(data))
    if missing:
        issues.append("ExperienceUploadReceipt missing required fields: " + ", ".join(missing))
    expected = {
        "schema": EXPERIENCE_UPLOAD_RECEIPT_SCHEMA_VERSION,
    }
    for key, value in expected.items():
        if data.get(key) != value:
            issues.append(f"{key} must equal {value!r}")
    if not _UPLOAD_ID_RE.fullmatch(str(data.get("uploadId", ""))):
        issues.append("uploadId must be exu_<48 lowercase hex>")
    if not _BUNDLE_ID_RE.fullmatch(str(data.get("bundleId", ""))):
        issues.append("bundleId must be exb_<48 lowercase hex>")
    for key in ("experiencePackId", "experienceReleaseId", "ownerWorkspaceRef"):
        if not _PUBLIC_ID_RE.fullmatch(str(data.get(key, ""))):
            issues.append(f"{key} must be an opaque public id")
    if not _SHA256_RE.fullmatch(str(data.get("bundleHash", ""))):
        issues.append("bundleHash must be sha256:<64 lowercase hex>")
    if data.get("status") not in {
        "draft-saved", "verification-requested", "verification-pending", "verified-private",
        "public-active", "conflict", "withdrawn", "rejected",
    }:
        issues.append("status is invalid")
    if not re.fullmatch(r"rev_[0-9a-f]{32}", str(data.get("revision", ""))):
        issues.append("revision must be rev_<32 lowercase hex>")
    if data.get("requestedVisibility") not in {"private", "unlisted", "public"}:
        issues.append("requestedVisibility is invalid")
    if "errorCode" in data and not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,95}", str(data.get("errorCode", ""))):
        issues.append("errorCode is invalid")
    for key in ("createdAt", "updatedAt"):
        raw = data.get(key)
        try:
            parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError("offset required")
        except ValueError:
            issues.append(f"{key} must be an ISO-8601 timestamp with offset")
    if issues:
        raise ContractValidationError(issues)
    return data
