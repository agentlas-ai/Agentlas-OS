"""Portable Agentlas experience-asset and MCP policy validation.

This module deliberately contains no account store, billing logic, keychain
access, MCP executable definitions, or model calls.  It is the executable,
public-safe companion to the JSON Schemas under ``schemas/``.

The contracts follow four rules:

* an AgentVariant binds one exact agent release to one exact experience release;
* experience is candidate-first and never contains a base package copy;
* MCP packages name catalog capabilities only -- the host registry owns commands;
* success metrics count only independently verifiable, replay-safe RunReceipts.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping
from urllib.parse import urlsplit

from .experience_privacy import is_allowed_protocol_metadata, scan_public_field


CORE_MEMORY_MAX_TOKENS = 150
EXPERIENCE_RETRIEVAL_MAX_TOKENS = 800
EXPERIENCE_RETRIEVAL_MAX_ITEMS = 8

SCHEMA_VERSIONS = {
    "agent-definition": "agentlas.agent-definition.v1",
    "experience-pack": "agentlas.experience-pack.v1",
    "experience-item": "agentlas.experience-item.v1",
    "taste-style-release": "agentlas.taste-style-release.v1",
    "pairwise-preference-receipt": "agentlas.pairwise-preference-receipt.v1",
    "agent-loadout": "agentlas.agent-loadout.v1",
    "agent-variant": "agentlas.agent-variant.v1",
    "run-receipt": "agentlas.run-receipt.v1",
    "mcp-requirement": "agentlas.mcp-requirement.v1",
    "mcp-policy": "agentlas.mcp-policy.v1",
    "rental-resolution-receipt": "agentlas.rental-resolution-receipt.v1",
}

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{2,255}$")
_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----", re.I),
    re.compile(
        r"\b(?:api[_-]?key|secret|token|password|cookie)\s*[:=]\s*['\"]?[A-Za-z0-9+/=_-]{16,}",
        re.I,
    ),
)
_MCP_EXECUTION_KEYS = {
    "args",
    "command",
    "cwd",
    "endpoint",
    "executable",
    "headers",
    "serverurl",
    "transportendpoint",
}
_RAW_EXPERIENCE_KEYS = {
    "basepackagefiles",
    "baseprompt",
    "files",
    "fulltranscript",
    "rawlocalpath",
    "rawprompt",
    "rawsource",
    "rawtranscript",
    "systemprompt",
}
_PUBLIC_TRANSCRIPT_RE = re.compile(
    r"(?:^|\n)\s*(?:system|assistant|user|tool)\s*:\s+"
    r"|<\|(?:system|assistant|user|im_start|im_end)[^>]*\|>"
    r"|BEGIN[ _-]?(?:SYSTEM[ _-]?PROMPT|BASE[ _-]?PROMPT|AGENT[ _-]?PACKAGE)"
    r"|\b(?:AGENTS|CLAUDE|GEMINI)\.md\b|\.agentlas[/\\]",
    re.I,
)
_PUBLIC_OPAQUE_BLOB_RE = re.compile(r"(?:[A-Fa-f0-9]{128,}|[A-Za-z0-9+/]{124,}={0,2})")
_MCP_HOST_RE = re.compile(
    r"^(?:\*\.)?"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$"
)
_MCP_SCOPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,127}$")
_MCP_SETUP_URL_RE = re.compile(
    r"^https://"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*"
    r"(?:/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*)?$"
)
_MCP_PROMPT_INJECTION_PATTERNS = (
    re.compile(
        r"\b(?:ignore|disregard|override)[\s_-]+(?:all[\s_-]+)?"
        r"(?:previous|prior|system|developer|hidden)[\s_-]+"
        r"(?:instructions?|prompts?|rules?|directives?)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:reveal|show|print|dump|expose|leak)[\s_-]+"
        r"(?:(?:the|all)[\s_-]+)?(?:(?:hidden|system|developer)[\s_-]+)?"
        r"(?:prompts?|instructions?|credentials?|secrets?|tokens?|api[\s_-]?keys?|passwords?)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:exfiltrate|steal|leak|upload|send)[\s_-]+(?:(?:all|the)[\s_-]+)?"
        r"(?:secrets?|credentials?|tokens?|api[\s_-]?keys?|passwords?)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:disable|bypass|skip|remove|turn[\s_-]+off)[\s_-]+(?:(?:the|all)[\s_-]+)?"
        r"(?:safety|guardrails?|approval|consent|permission[\s_-]?checks?|security[\s_-]?checks?)\b",
        re.I,
    ),
)


class ContractValidationError(ValueError):
    """Raised when a portable asset contract violates a public invariant."""

    def __init__(self, issues: Iterable[str]):
        self.issues = tuple(dict.fromkeys(str(issue) for issue in issues if str(issue)))
        super().__init__("; ".join(self.issues) or "invalid Agentlas contract")


def default_mcp_policy() -> dict[str, Any]:
    """Return the value-free, failure-isolated policy seeded into new packages."""

    return {
        "schemaVersion": SCHEMA_VERSIONS["mcp-policy"],
        "kind": "agentlas-mcp-policy",
        "registryResolutionOrder": ["system-global", "project-local", "catalog-recommendation"],
        "consentMode": "one-pass",
        "serverDefinitionsFromPackage": False,
        "credentialValuesAllowed": False,
        "failureIsolation": "per-requirement",
        "permissionWidening": "ask",
        "toolSchemaLoading": "selected-tools-only",
        "skillLoading": "triggered-only",
        "contextBudget": {
            "coreMemoryMaxTokens": CORE_MEMORY_MAX_TOKENS,
            "experienceRetrievalMaxTokens": EXPERIENCE_RETRIEVAL_MAX_TOKENS,
            "experienceRetrievalMaxItems": EXPERIENCE_RETRIEVAL_MAX_ITEMS,
        },
        "requirements": [],
    }


def canonical_hash(payload: Mapping[str, Any], *, exclude: Iterable[str] = ()) -> str:
    """Hash normalized JSON while excluding envelope fields such as receiptHash."""

    blocked = set(exclude)
    normalized = {key: value for key, value in payload.items() if key not in blocked}
    encoded = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def validate_contract(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one known public contract and return a detached plain dict."""

    data = _mapping(payload, "contract")
    version = data.get("schemaVersion")
    validators = {
        SCHEMA_VERSIONS["agent-definition"]: validate_agent_definition,
        SCHEMA_VERSIONS["experience-pack"]: validate_experience_pack,
        SCHEMA_VERSIONS["experience-item"]: validate_experience_item,
        SCHEMA_VERSIONS["taste-style-release"]: validate_taste_style_release,
        SCHEMA_VERSIONS["pairwise-preference-receipt"]: validate_pairwise_preference_receipt,
        SCHEMA_VERSIONS["agent-loadout"]: validate_agent_loadout,
        SCHEMA_VERSIONS["agent-variant"]: validate_agent_variant,
        SCHEMA_VERSIONS["run-receipt"]: validate_run_receipt,
        SCHEMA_VERSIONS["mcp-requirement"]: validate_mcp_requirement,
        SCHEMA_VERSIONS["mcp-policy"]: validate_mcp_policy,
        SCHEMA_VERSIONS["rental-resolution-receipt"]: validate_rental_resolution_receipt,
    }
    validator = validators.get(version)
    if validator is None:
        raise ContractValidationError([f"unsupported schemaVersion: {version!r}"])
    validator(data)
    return json.loads(json.dumps(data, ensure_ascii=False))


def validate_agent_definition(payload: Mapping[str, Any]) -> None:
    data = _mapping(payload, "AgentDefinition")
    issues: list[str] = []
    required = {
        "schemaVersion", "kind", "agentDefinitionId", "releaseId", "authorRef", "version",
        "packageHash", "entrypoint", "capabilities", "mcpPolicyRef",
        "thirdPartyExperiencePolicy", "visibility", "status", "contextBudget",
    }
    allowed = required | {"createdAt", "releasedAt", "supersedesReleaseId"}
    _require_keys(data, required, issues, "AgentDefinition")
    _reject_unknown(data, allowed, issues, "AgentDefinition")
    _identity(data, issues, "agentDefinitionId", "releaseId", "authorRef")
    _expect(data, issues, "schemaVersion", SCHEMA_VERSIONS["agent-definition"])
    _expect(data, issues, "kind", "agentlas-agent-definition")
    version = data.get("version")
    if (
        not isinstance(version, str)
        or len(version) > 64
        or not re.fullmatch(r"v?[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", version)
    ):
        issues.append("version must be a semantic version")
    _hash(data, issues, "packageHash")
    _relative_path(data, issues, "entrypoint")
    _string_list(data, issues, "capabilities", min_items=1)
    _relative_path(data, issues, "mcpPolicyRef")
    _enum(data, issues, "thirdPartyExperiencePolicy", {"denied", "private-only", "public-allowed", "approval-required"})
    _enum(data, issues, "visibility", {"private", "unlisted", "public"})
    _enum(data, issues, "status", {"draft", "active", "suspended", "deprecated", "deleted"})
    _validate_context_budget(data.get("contextBudget"), issues, "contextBudget")
    _forbid_secrets(data, issues, "AgentDefinition")
    _raise(issues)


def validate_experience_pack(payload: Mapping[str, Any]) -> None:
    data = _mapping(payload, "ExperiencePack")
    issues: list[str] = []
    required = {
        "schemaVersion", "kind", "experiencePackId", "releaseId", "ownerRef", "version",
        "baseCompatibility", "itemIds", "evidenceReceiptIds", "mcpRequirements",
        "containsBasePackageMaterial", "contentHash", "visibility", "status",
    }
    allowed = required | {"createdAt", "releasedAt", "withdrawnAt"}
    _require_keys(data, required, issues, "ExperiencePack")
    _reject_unknown(data, allowed, issues, "ExperiencePack")
    _identity(data, issues, "experiencePackId", "releaseId", "ownerRef")
    _expect(data, issues, "schemaVersion", SCHEMA_VERSIONS["experience-pack"])
    _expect(data, issues, "kind", "agentlas-experience-pack")
    _id(data, issues, "version")
    _hash(data, issues, "contentHash")
    compatibility = _child(data, issues, "baseCompatibility")
    if compatibility:
        _require_keys(compatibility, {"agentDefinitionId", "compatibleBaseReleaseIds"}, issues, "baseCompatibility")
        _reject_unknown(compatibility, {"agentDefinitionId", "compatibleBaseReleaseIds"}, issues, "baseCompatibility")
        _id(compatibility, issues, "agentDefinitionId", prefix="baseCompatibility.")
        _string_list(
            compatibility,
            issues,
            "compatibleBaseReleaseIds",
            min_items=1,
            max_items=64,
            prefix="baseCompatibility.",
        )
        _forbid_keys(
            compatibility,
            {"latest", "latestcompatible", "samemajor", "semverrange", "versionrange"},
            issues,
            "baseCompatibility",
        )
    _string_list(data, issues, "itemIds", min_items=0, max_items=256)
    _string_list(data, issues, "evidenceReceiptIds", min_items=0, max_items=6144)
    if data.get("status") == "active" and not data.get("itemIds"):
        issues.append("active ExperiencePack requires at least one itemId")
    _false(data, issues, "containsBasePackageMaterial")
    _enum(data, issues, "visibility", {"private", "unlisted", "public"})
    _enum(data, issues, "status", {"draft", "active", "suspended", "withdrawn", "deleted"})
    requirements = data.get("mcpRequirements", [])
    if not isinstance(requirements, list):
        issues.append("mcpRequirements must be an array")
    elif len(requirements) > 64:
        issues.append("mcpRequirements must contain at most 64 requirements")
    else:
        for index, requirement in enumerate(requirements):
            try:
                validate_mcp_requirement(_mapping(requirement, f"mcpRequirements[{index}]"))
            except ContractValidationError as exc:
                issues.extend(f"mcpRequirements[{index}]: {issue}" for issue in exc.issues)
    _forbid_keys(data, _RAW_EXPERIENCE_KEYS, issues, "ExperiencePack")
    _forbid_secrets(data, issues, "ExperiencePack")
    _raise(issues)


def validate_experience_item(payload: Mapping[str, Any]) -> None:
    data = _mapping(payload, "ExperienceItem")
    issues: list[str] = []
    required = {
        "schemaVersion", "kind", "experienceItemId", "experiencePackId", "experiencePackReleaseId",
        "type", "summary", "instructions", "taskSignatures", "environmentConstraints",
        "evidenceReceiptIds", "supersedesItemIds", "confidence", "status", "privacyScope",
    }
    allowed = required | {"createdAt"}
    _require_keys(data, required, issues, "ExperienceItem")
    _reject_unknown(data, allowed, issues, "ExperienceItem")
    _expect(data, issues, "schemaVersion", SCHEMA_VERSIONS["experience-item"])
    _expect(data, issues, "kind", "agentlas-experience-item")
    for key in ("experienceItemId", "experiencePackId", "experiencePackReleaseId"):
        _id(data, issues, key)
    _enum(
        data,
        issues,
        "type",
        {"procedure", "failure-recovery", "environment-gotcha", "tool-affordance", "warning", "supersedes"},
    )
    _bounded_string(data, issues, "summary", 1, 320)
    instructions = data.get("instructions")
    if not isinstance(instructions, list) or not 1 <= len(instructions) <= 8:
        issues.append("instructions must contain 1..8 compact steps")
    else:
        for index, instruction in enumerate(instructions):
            if not isinstance(instruction, str) or not 1 <= len(instruction) <= 600:
                issues.append(f"instructions[{index}] must be a 1..600 character string")
    _string_list(data, issues, "taskSignatures", min_items=1, max_items=32)
    _string_list(data, issues, "environmentConstraints", min_items=0, max_items=32)
    _string_list(data, issues, "evidenceReceiptIds", min_items=1, max_items=24)
    _string_list(data, issues, "supersedesItemIds", min_items=0, max_items=256)
    confidence = data.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        issues.append("confidence must be a number from 0 to 1")
    _enum(data, issues, "status", {"candidate", "promoted", "deprecated", "rejected"})
    privacy_scope = _enum(data, issues, "privacyScope", {"private", "public-safe"})
    if privacy_scope == "public-safe":
        _validate_public_safe_experience_text(
            [
                ("experienceItemId", str(data.get("experienceItemId") or "")),
                ("experiencePackId", str(data.get("experiencePackId") or "")),
                ("experiencePackReleaseId", str(data.get("experiencePackReleaseId") or "")),
                ("summary", str(data.get("summary") or "")),
                *((f"instructions[{index}]", str(item)) for index, item in enumerate(data.get("instructions", []))),
                *((f"taskSignatures[{index}]", str(item)) for index, item in enumerate(data.get("taskSignatures", []))),
                *((f"environmentConstraints[{index}]", str(item)) for index, item in enumerate(data.get("environmentConstraints", []))),
                *((f"evidenceReceiptIds[{index}]", str(item)) for index, item in enumerate(data.get("evidenceReceiptIds", []))),
                *((f"supersedesItemIds[{index}]", str(item)) for index, item in enumerate(data.get("supersedesItemIds", []))),
                ("createdAt", str(data.get("createdAt") or "")),
            ],
            issues,
        )
    _forbid_keys(data, _RAW_EXPERIENCE_KEYS, issues, "ExperienceItem")
    _forbid_secrets(data, issues, "ExperienceItem")
    _raise(issues)


def validate_taste_style_release(payload: Mapping[str, Any]) -> None:
    """Validate an immutable, generalized human-preference chip release.

    This contract intentionally has no success rate.  Execution receipts prove
    that a workflow ran; only explicit randomized human A/B receipts may support
    an aesthetic preference claim.
    """

    data = _mapping(payload, "TasteStyleRelease")
    issues: list[str] = []
    required = {
        "schemaVersion", "kind", "tasteStyleId", "releaseId", "ownerRef", "version",
        "title", "summary", "baseCompatibility", "taskSignatures", "preferenceAxes",
        "rules", "pairwiseEvidenceReceiptIds", "previewAssetRefs", "audienceTags",
        "aggregate", "privacy", "contentHash", "visibility", "status",
    }
    allowed = required | {"createdAt", "releasedAt", "withdrawnAt"}
    _require_keys(data, required, issues, "TasteStyleRelease")
    _reject_unknown(data, allowed, issues, "TasteStyleRelease")
    _expect(data, issues, "schemaVersion", SCHEMA_VERSIONS["taste-style-release"])
    _expect(data, issues, "kind", "agentlas-taste-style-release")
    for key in ("tasteStyleId", "releaseId", "ownerRef"):
        _id(data, issues, key)
    version = data.get("version")
    if (
        not isinstance(version, str)
        or len(version) > 64
        or not re.fullmatch(r"v?[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", version)
    ):
        issues.append("version must be a semantic version")
    _bounded_string(data, issues, "title", 1, 120)
    _bounded_string(data, issues, "summary", 1, 600)
    compatibility = _child(data, issues, "baseCompatibility")
    if compatibility:
        keys = {"agentDefinitionId", "compatibleBaseReleaseIds"}
        _require_keys(compatibility, keys, issues, "baseCompatibility")
        _reject_unknown(compatibility, keys, issues, "baseCompatibility")
        _id(compatibility, issues, "agentDefinitionId", prefix="baseCompatibility.")
        _id_list(
            compatibility,
            issues,
            "compatibleBaseReleaseIds",
            min_items=1,
            max_items=64,
            prefix="baseCompatibility.",
        )
        _forbid_keys(
            compatibility,
            {"latest", "latestcompatible", "samemajor", "semverrange", "versionrange"},
            issues,
            "baseCompatibility",
        )
    task_signatures = _id_list(data, issues, "taskSignatures", min_items=1, max_items=32)
    allowed_axes = {
        "composition", "color", "typography", "motion", "pacing", "density",
        "imagery", "editing", "spatial-rhythm",
    }
    axes = _string_list(data, issues, "preferenceAxes", min_items=1, max_items=len(allowed_axes))
    for index, axis in enumerate(axes):
        if axis not in allowed_axes:
            issues.append(f"preferenceAxes[{index}] is not a supported aesthetic axis")
    rules = data.get("rules")
    safe_text: list[tuple[str, str]] = [
        ("title", str(data.get("title") or "")),
        ("summary", str(data.get("summary") or "")),
        *((f"taskSignatures[{index}]", value) for index, value in enumerate(task_signatures)),
        *((f"preferenceAxes[{index}]", value) for index, value in enumerate(axes)),
    ]
    if not isinstance(rules, list) or not 1 <= len(rules) <= 32:
        issues.append("rules must contain 1..32 generalized preference rules")
    else:
        rule_ids: set[str] = set()
        for index, rule in enumerate(rules):
            label = f"rules[{index}]"
            if not isinstance(rule, Mapping):
                issues.append(f"{label} must be an object")
                continue
            rule = dict(rule)
            keys = {"ruleId", "axis", "polarity", "statement", "contexts", "confidence"}
            _require_keys(rule, keys, issues, label)
            _reject_unknown(rule, keys, issues, label)
            rule_id = _id(rule, issues, "ruleId", prefix=f"{label}.")
            if isinstance(rule_id, str):
                if rule_id in rule_ids:
                    issues.append(f"duplicate Taste/Style ruleId: {rule_id}")
                rule_ids.add(rule_id)
            axis = rule.get("axis")
            if axis not in allowed_axes or axis not in axes:
                issues.append(f"{label}.axis must be declared in preferenceAxes")
            _enum(rule, issues, "polarity", {"prefer", "avoid"}, prefix=f"{label}.")
            statement = rule.get("statement")
            if not isinstance(statement, str) or not 1 <= len(statement) <= 320:
                issues.append(f"{label}.statement must be a 1..320 character generalized rule")
            contexts = _id_list(rule, issues, "contexts", min_items=1, max_items=12, prefix=f"{label}.")
            confidence = rule.get("confidence")
            if (
                not isinstance(confidence, (int, float))
                or isinstance(confidence, bool)
                or not 0 <= confidence <= 1
            ):
                issues.append(f"{label}.confidence must be 0..1")
            safe_text.extend([
                (f"{label}.ruleId", str(rule_id or "")),
                (f"{label}.statement", str(statement or "")),
                *((f"{label}.contexts[{item_index}]", value) for item_index, value in enumerate(contexts)),
            ])
    evidence_ids = _id_list(
        data,
        issues,
        "pairwiseEvidenceReceiptIds",
        min_items=0,
        max_items=6144,
    )
    previews = data.get("previewAssetRefs")
    preview_ids: set[str] = set()
    preview_treatments: list[dict[str, Any]] = []
    if not isinstance(previews, list) or len(previews) > 24:
        issues.append("previewAssetRefs must be an array with at most 24 public-safe asset references")
    else:
        for index, preview in enumerate(previews):
            label = f"previewAssetRefs[{index}]"
            if not isinstance(preview, Mapping):
                issues.append(f"{label} must be an object")
                continue
            preview = dict(preview)
            keys = {"assetId", "contentHash", "rightsStatus", "safetyStatus", "mimeType"}
            _require_keys(preview, keys, issues, label)
            _reject_unknown(preview, keys | {"treatment"}, issues, label)
            asset_id = _id(preview, issues, "assetId", prefix=f"{label}.")
            if isinstance(asset_id, str):
                if asset_id in preview_ids:
                    issues.append(f"duplicate preview asset: {asset_id}")
                preview_ids.add(asset_id)
            _hash(preview, issues, "contentHash", prefix=f"{label}.")
            _enum(
                preview,
                issues,
                "rightsStatus",
                {"owner-authorized", "licensed-for-public-preview", "public-domain"},
                prefix=f"{label}.",
            )
            _expect(preview, issues, "safetyStatus", "passed", prefix=f"{label}.")
            _enum(
                preview,
                issues,
                "mimeType",
                {"image/jpeg", "image/png", "image/webp", "video/mp4"},
                prefix=f"{label}.",
            )
            if "treatment" in preview:
                treatment = preview.get("treatment")
                treatment_label = f"{label}.treatment"
                if not isinstance(treatment, Mapping):
                    issues.append(f"{treatment_label} must be an object")
                else:
                    treatment = dict(treatment)
                    treatment_keys = {
                        "role", "canonicalTaskInputHash", "baseAgentDefinitionId",
                        "baseAgentReleaseId", "generationCohortHash", "evidenceLevel",
                        "generationReceiptId", "tasteStyleReleaseId", "tasteMaterialHash",
                        "noTasteOverlay", "ownerAttested",
                    }
                    _require_keys(treatment, treatment_keys, issues, treatment_label)
                    _reject_unknown(treatment, treatment_keys, issues, treatment_label)
                    role = _enum(
                        treatment,
                        issues,
                        "role",
                        {"chip-on", "control"},
                        prefix=f"{treatment_label}.",
                    )
                    for hash_key in ("canonicalTaskInputHash", "generationCohortHash"):
                        _hash(treatment, issues, hash_key, prefix=f"{treatment_label}.")
                    for id_key in (
                        "baseAgentDefinitionId", "baseAgentReleaseId", "tasteStyleReleaseId",
                    ):
                        _id(treatment, issues, id_key, prefix=f"{treatment_label}.")
                    evidence_level = _enum(
                        treatment,
                        issues,
                        "evidenceLevel",
                        {"owner-attested-external", "trusted-evaluator"},
                        prefix=f"{treatment_label}.",
                    )
                    generation_receipt_id = treatment.get("generationReceiptId")
                    if generation_receipt_id is not None:
                        _id(treatment, issues, "generationReceiptId", prefix=f"{treatment_label}.")
                    taste_material_hash = treatment.get("tasteMaterialHash")
                    if taste_material_hash is not None:
                        _hash(treatment, issues, "tasteMaterialHash", prefix=f"{treatment_label}.")
                    if treatment.get("ownerAttested") is not True:
                        issues.append(f"{treatment_label}.ownerAttested must be true")
                    no_taste_overlay = treatment.get("noTasteOverlay")
                    if not isinstance(no_taste_overlay, bool):
                        issues.append(f"{treatment_label}.noTasteOverlay must be a boolean")
                    if role == "chip-on" and (taste_material_hash is None or no_taste_overlay is not False):
                        issues.append(f"{treatment_label} chip-on must bind Taste material and apply the overlay")
                    if role == "control" and (taste_material_hash is not None or no_taste_overlay is not True):
                        issues.append(f"{treatment_label} control must assert no Taste overlay")
                    if evidence_level == "trusted-evaluator" and generation_receipt_id is None:
                        issues.append(f"{treatment_label} trusted evaluator provenance requires generationReceiptId")
                    if evidence_level == "owner-attested-external" and generation_receipt_id is not None:
                        issues.append(f"{treatment_label} owner attestation cannot claim generationReceiptId")
                    preview_treatments.append(treatment)
            safe_text.append((f"{label}.assetId", str(asset_id or "")))
    if preview_treatments:
        if not isinstance(previews, list) or len(previews) != 2 or len(preview_treatments) != 2:
            issues.append("a treatment comparison requires exactly two fully-provenanced previews")
        else:
            by_role = {str(item.get("role")): item for item in preview_treatments}
            if set(by_role) != {"chip-on", "control"}:
                issues.append("a treatment comparison requires one chip-on preview and one control")
            else:
                chip_on = by_role["chip-on"]
                control = by_role["control"]
                shared_keys = {
                    "canonicalTaskInputHash", "baseAgentDefinitionId",
                    "baseAgentReleaseId", "generationCohortHash",
                }
                if any(chip_on.get(key) != control.get(key) for key in shared_keys):
                    issues.append("chip-on and control must share the exact task input, base, and generation cohort")
                compatible_release_ids = (
                    compatibility.get("compatibleBaseReleaseIds", [])
                    if isinstance(compatibility, Mapping)
                    else []
                )
                for treatment in preview_treatments:
                    if (
                        treatment.get("baseAgentDefinitionId") != (
                            compatibility.get("agentDefinitionId")
                            if isinstance(compatibility, Mapping)
                            else None
                        )
                        or treatment.get("baseAgentReleaseId") not in compatible_release_ids
                        or treatment.get("tasteStyleReleaseId") != data.get("releaseId")
                    ):
                        issues.append("treatment provenance must bind the exact Taste release and compatible base")
                taste_material = {
                    key: data.get(key)
                    for key in (
                        "schemaVersion", "kind", "tasteStyleId", "releaseId", "version",
                        "title", "summary", "baseCompatibility", "taskSignatures",
                        "preferenceAxes", "rules", "audienceTags",
                    )
                }
                if chip_on.get("tasteMaterialHash") != canonical_hash(taste_material):
                    issues.append("chip-on provenance does not bind this exact Taste material")
    audience_tags = _id_list(data, issues, "audienceTags", min_items=0, max_items=16)
    safe_text.extend((f"audienceTags[{index}]", value) for index, value in enumerate(audience_tags))
    aggregate = _child(data, issues, "aggregate")
    sample_count = 0
    if aggregate:
        keys = {
            "sampleCount", "distinctRaterCount", "ruleAlignedCount", "alternativeCount",
            "tieCount", "skipCount", "disagreement",
        }
        _require_keys(aggregate, keys, issues, "aggregate")
        _reject_unknown(aggregate, keys, issues, "aggregate")
        counts: dict[str, int] = {}
        for key in (
            "sampleCount", "distinctRaterCount", "ruleAlignedCount", "alternativeCount",
            "tieCount", "skipCount",
        ):
            value = aggregate.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                issues.append(f"aggregate.{key} must be a non-negative integer")
            else:
                counts[key] = value
        sample_count = counts.get("sampleCount", 0)
        if counts.get("distinctRaterCount", 0) > sample_count:
            issues.append("aggregate.distinctRaterCount cannot exceed sampleCount")
        if all(key in counts for key in ("ruleAlignedCount", "alternativeCount", "tieCount", "skipCount")):
            if sum(counts[key] for key in ("ruleAlignedCount", "alternativeCount", "tieCount", "skipCount")) != sample_count:
                issues.append("aggregate choice counts must sum to sampleCount")
        disagreement = aggregate.get("disagreement")
        if (
            not isinstance(disagreement, (int, float))
            or isinstance(disagreement, bool)
            or not 0 <= disagreement <= 1
        ):
            issues.append("aggregate.disagreement must be 0..1")
    if sample_count != len(evidence_ids):
        issues.append("aggregate.sampleCount must equal the number of pairwise evidence receipts")
    privacy = _child(data, issues, "privacy")
    if privacy:
        privacy_keys = {
            "rawRaterIdentityIncluded", "rawLocalPathsIncluded", "rawOutputsIncluded",
            "credentialValuesIncluded", "privateAssetBytesIncluded",
        }
        _require_keys(privacy, privacy_keys, issues, "privacy")
        _reject_unknown(privacy, privacy_keys, issues, "privacy")
        for key in privacy_keys:
            _false(privacy, issues, key, prefix="privacy.")
    visibility = _enum(data, issues, "visibility", {"private", "unlisted", "public"})
    status = _enum(data, issues, "status", {"draft", "active", "suspended", "withdrawn", "deleted"})
    if visibility == "public" and status == "active":
        if not evidence_ids:
            issues.append("an active public Taste/Style release requires human pairwise evidence")
        if len(preview_ids) < 2:
            issues.append("an active public Taste/Style release requires at least two safe public previews")
    _hash(data, issues, "contentHash")
    if _SHA256_RE.fullmatch(str(data.get("contentHash", ""))):
        expected = canonical_hash(data, exclude={"contentHash"})
        if data["contentHash"] != expected:
            issues.append("contentHash does not match the immutable Taste/Style release payload")
    _validate_public_safe_asset_text(safe_text, issues, "TasteStyleRelease")
    _forbid_keys(
        data,
        _RAW_EXPERIENCE_KEYS
        | {
            "credentialvalue", "successrate", "universalscore", "llmaestheticverdict",
            "previewurl", "privateassetembedding", "rawpreviewbytes",
        },
        issues,
        "TasteStyleRelease",
    )
    _forbid_secrets(data, issues, "TasteStyleRelease")
    _raise(issues)


def validate_pairwise_preference_receipt(payload: Mapping[str, Any]) -> None:
    """Validate a replay-safe, human-only A/B preference receipt."""

    data = _mapping(payload, "PairwisePreferenceReceipt")
    issues: list[str] = []
    required = {
        "schemaVersion", "kind", "receiptId", "idempotencyKey", "receiptHash",
        "tasteStyleReleaseId", "baseAgentReleaseId", "taskSignature", "pair",
        "rater", "choice", "contextTags", "privacy", "createdAt",
    }
    allowed = required | {"signature", "treatmentChoice"}
    _require_keys(data, required, issues, "PairwisePreferenceReceipt")
    _reject_unknown(data, allowed, issues, "PairwisePreferenceReceipt")
    _expect(data, issues, "schemaVersion", SCHEMA_VERSIONS["pairwise-preference-receipt"])
    _expect(data, issues, "kind", "agentlas-pairwise-preference-receipt")
    for key in ("receiptId", "idempotencyKey", "tasteStyleReleaseId", "baseAgentReleaseId"):
        _id(data, issues, key)
    _hash(data, issues, "receiptHash")
    if "signature" in data and data.get("signature") is not None:
        issues.append("signature must be null in the portable PairwisePreferenceReceipt v1 contract")
    task = _child(data, issues, "taskSignature")
    safe_text: list[tuple[str, str]] = []
    if task:
        _require_keys(task, {"kind", "hash"}, issues, "taskSignature")
        _reject_unknown(task, {"kind", "hash", "locale"}, issues, "taskSignature")
        task_kind = _id(task, issues, "kind", prefix="taskSignature.")
        _hash(task, issues, "hash", prefix="taskSignature.")
        safe_text.append(("taskSignature.kind", str(task_kind or "")))
    pair = _child(data, issues, "pair")
    if pair:
        keys = {"leftPreviewAssetRef", "rightPreviewAssetRef", "orderRandomized"}
        _require_keys(pair, keys, issues, "pair")
        _reject_unknown(pair, keys, issues, "pair")
        left = _id(pair, issues, "leftPreviewAssetRef", prefix="pair.")
        right = _id(pair, issues, "rightPreviewAssetRef", prefix="pair.")
        if left == right and isinstance(left, str):
            issues.append("pair must compare two distinct preview assets")
        if pair.get("orderRandomized") is not True:
            issues.append("pair.orderRandomized must be true to limit position bias")
        safe_text.extend([
            ("pair.leftPreviewAssetRef", str(left or "")),
            ("pair.rightPreviewAssetRef", str(right or "")),
        ])
    rater = _child(data, issues, "rater")
    if rater:
        keys = {"antiSybilPrincipalHash", "source", "consent"}
        _require_keys(rater, keys, issues, "rater")
        _reject_unknown(rater, keys, issues, "rater")
        _hash(rater, issues, "antiSybilPrincipalHash", prefix="rater.")
        _expect(rater, issues, "source", "human", prefix="rater.")
        _expect(rater, issues, "consent", "explicit", prefix="rater.")
    _enum(data, issues, "choice", {"left", "right", "tie", "skip"})
    if "treatmentChoice" in data:
        _enum(data, issues, "treatmentChoice", {"chip-on", "control", "tie", "skip"})
    contexts = _id_list(data, issues, "contextTags", min_items=0, max_items=16)
    safe_text.extend((f"contextTags[{index}]", value) for index, value in enumerate(contexts))
    privacy = _child(data, issues, "privacy")
    if privacy:
        privacy_keys = {
            "rawRaterIdentityIncluded", "rawLocalPathsIncluded", "rawOutputsIncluded",
            "credentialValuesIncluded", "privateAssetBytesIncluded",
        }
        _require_keys(privacy, privacy_keys, issues, "privacy")
        _reject_unknown(privacy, privacy_keys, issues, "privacy")
        for key in privacy_keys:
            _false(privacy, issues, key, prefix="privacy.")
    if _SHA256_RE.fullmatch(str(data.get("receiptHash", ""))):
        expected = canonical_hash(data, exclude={"receiptHash", "signature"})
        if data["receiptHash"] != expected:
            issues.append("receiptHash does not match the canonical pairwise preference payload")
    _validate_public_safe_asset_text(safe_text, issues, "PairwisePreferenceReceipt")
    _forbid_keys(
        data,
        _RAW_EXPERIENCE_KEYS
        | {
            "credentialvalue", "successrate", "universalscore", "aestheticscore",
            "rawleftoutput", "rawrightoutput", "rateridentity", "email", "phone",
        },
        issues,
        "PairwisePreferenceReceipt",
    )
    _forbid_secrets(data, issues, "PairwisePreferenceReceipt")
    _raise(issues)


def validate_agent_loadout(payload: Mapping[str, Any]) -> None:
    """Validate an explicit references-only attachment of up to one chip of each kind."""

    data = _mapping(payload, "AgentLoadout")
    issues: list[str] = []
    required = {
        "schemaVersion", "kind", "loadoutId", "ownerRef", "baseAgentReleaseId",
        "experiencePackReleaseId", "tasteStyleReleaseId", "compositionMode",
        "updatePolicy", "consentMode", "consentReceiptId", "activationMode",
        "permissionWidening", "bindingHash", "status", "createdAt",
    }
    _require_keys(data, required, issues, "AgentLoadout")
    _reject_unknown(data, required, issues, "AgentLoadout")
    _expect(data, issues, "schemaVersion", SCHEMA_VERSIONS["agent-loadout"])
    _expect(data, issues, "kind", "agentlas-agent-loadout")
    for key in ("loadoutId", "ownerRef", "baseAgentReleaseId", "consentReceiptId"):
        _id(data, issues, key)
    _nullable_id(data, issues, "experiencePackReleaseId")
    _nullable_id(data, issues, "tasteStyleReleaseId")
    if data.get("experiencePackReleaseId") is None and data.get("tasteStyleReleaseId") is None:
        issues.append("AgentLoadout must attach an Experience or Taste/Style release")
    _expect(data, issues, "compositionMode", "references-only")
    policy = _child(data, issues, "updatePolicy")
    if policy:
        keys = {"experience", "tasteStyle"}
        _require_keys(policy, keys, issues, "updatePolicy")
        _reject_unknown(policy, keys, issues, "updatePolicy")
        for key in keys:
            _enum(
                policy,
                issues,
                key,
                {"pinned", "verified-compatible", "manual"},
                prefix="updatePolicy.",
            )
    _expect(data, issues, "consentMode", "explicit-user")
    _expect(data, issues, "activationMode", "next-session-only")
    _expect(data, issues, "permissionWidening", "ask")
    _hash(data, issues, "bindingHash")
    _enum(data, issues, "status", {"pending", "active", "dormant", "rollback-required", "revoked"})
    binding = {
        "baseAgentReleaseId": data.get("baseAgentReleaseId"),
        "experiencePackReleaseId": data.get("experiencePackReleaseId"),
        "tasteStyleReleaseId": data.get("tasteStyleReleaseId"),
    }
    if _SHA256_RE.fullmatch(str(data.get("bindingHash", ""))) and data.get("bindingHash") != canonical_hash(binding):
        issues.append("bindingHash must hash the exact base, Experience, and Taste/Style release ids")
    _forbid_keys(
        data,
        _RAW_EXPERIENCE_KEYS | {"credentialvalue", "autoattach", "prompt", "rules", "files"},
        issues,
        "AgentLoadout",
    )
    _forbid_secrets(data, issues, "AgentLoadout")
    _raise(issues)


def validate_agent_variant(payload: Mapping[str, Any]) -> None:
    data = _mapping(payload, "AgentVariant")
    issues: list[str] = []
    required = {
        "schemaVersion", "kind", "variantId", "variantOwnerRef", "baseAgentReleaseId",
        "experiencePackReleaseId", "compositionMode", "bindingHash", "compatibilityStatus",
        "visibility", "status",
    }
    allowed = required | {"verificationReceiptIds", "createdAt"}
    _require_keys(data, required, issues, "AgentVariant")
    _reject_unknown(data, allowed, issues, "AgentVariant")
    _expect(data, issues, "schemaVersion", SCHEMA_VERSIONS["agent-variant"])
    _expect(data, issues, "kind", "agentlas-agent-variant")
    for key in ("variantId", "variantOwnerRef", "baseAgentReleaseId", "experiencePackReleaseId"):
        _id(data, issues, key)
    _expect(data, issues, "compositionMode", "references-only")
    _hash(data, issues, "bindingHash")
    _enum(data, issues, "compatibilityStatus", {"unverified", "verified", "incompatible", "stale"})
    verification_receipts = _id_list(data, issues, "verificationReceiptIds", min_items=0, max_items=24) \
        if "verificationReceiptIds" in data else []
    if data.get("compatibilityStatus") == "verified" and not verification_receipts:
        issues.append("compatibilityStatus=verified requires at least one verificationReceiptId")
    _enum(data, issues, "visibility", {"private", "unlisted", "public"})
    _enum(data, issues, "status", {"draft", "active", "dormant", "suspended", "withdrawn", "deleted"})
    _forbid_keys(data, _RAW_EXPERIENCE_KEYS, issues, "AgentVariant")
    expected = canonical_hash(
        {
            "baseAgentReleaseId": data.get("baseAgentReleaseId"),
            "experiencePackReleaseId": data.get("experiencePackReleaseId"),
        }
    )
    if _SHA256_RE.fullmatch(str(data.get("bindingHash", ""))) and data.get("bindingHash") != expected:
        issues.append("bindingHash must hash the exact base and experience release ids")
    _raise(issues)


def validate_mcp_requirement(payload: Mapping[str, Any]) -> None:
    data = _mapping(payload, "MCPRequirement")
    issues: list[str] = []
    required_fields = {
        "schemaVersion", "kind", "requirementId", "catalogId", "reason", "capabilities",
        "required", "requiresKey", "priority", "permissions", "alternatives", "unavailablePolicy",
    }
    allowed_fields = required_fields | {"credentialMetadata"}
    _require_keys(data, required_fields, issues, "MCPRequirement")
    _reject_unknown(data, allowed_fields, issues, "MCPRequirement")
    _expect(data, issues, "schemaVersion", SCHEMA_VERSIONS["mcp-requirement"])
    _expect(data, issues, "kind", "agentlas-mcp-requirement")
    for key in ("requirementId", "catalogId"):
        _id(data, issues, key)
    _bounded_string(data, issues, "reason", 1, 300)
    capabilities = _id_list(data, issues, "capabilities", min_items=1, max_items=32)
    required = _bool(data, issues, "required")
    requires_key = _bool(data, issues, "requiresKey")
    priority = data.get("priority")
    if not isinstance(priority, int) or isinstance(priority, bool) or not 1 <= priority <= 1000:
        issues.append("priority must be an integer from 1 to 1000")
    permissions = _id_list(data, issues, "permissions", min_items=0, max_items=64)
    alternatives = _id_list(data, issues, "alternatives", min_items=0, max_items=32)
    if data.get("catalogId") in alternatives:
        issues.append("alternatives must not include the primary catalogId")
    credentials = data.get("credentialMetadata")
    credential_text: list[tuple[str, str]] = []
    if credentials is None:
        if requires_key is True:
            issues.append("requiresKey=true requires value-free credentialMetadata")
    elif not isinstance(credentials, Mapping):
        issues.append("credentialMetadata must be an object")
    else:
        credentials = dict(credentials)
        credential_allowed = {"provider", "env", "allowedHosts", "scopes", "setupUrl", "brokerMode"}
        _require_keys(credentials, {"provider", "env"}, issues, "credentialMetadata")
        _reject_unknown(credentials, credential_allowed, issues, "credentialMetadata")
        provider = _id(credentials, issues, "provider", prefix="credentialMetadata.")
        env = _env_list(credentials, issues, "env", prefix="credentialMetadata.")
        allowed_hosts = _optional_hostname_list(credentials, issues, "allowedHosts", prefix="credentialMetadata.")
        scopes = _optional_scope_list(credentials, issues, "scopes", prefix="credentialMetadata.")
        setup_url = credentials.get("setupUrl")
        if setup_url is not None:
            _validate_https_setup_url(setup_url, issues)
        broker_mode = credentials.get("brokerMode")
        if broker_mode is not None and broker_mode not in {
            "host-bound-broker",
            "runtime-env-injection",
            "provider-managed-oauth",
            "manual-provider-page",
        }:
            issues.append("credentialMetadata.brokerMode is invalid")
        credential_text.extend([
            ("credentialMetadata.provider", str(provider or "")),
            *((f"credentialMetadata.env[{index}]", value) for index, value in enumerate(env)),
            *((f"credentialMetadata.allowedHosts[{index}]", value) for index, value in enumerate(allowed_hosts)),
            *((f"credentialMetadata.scopes[{index}]", value) for index, value in enumerate(scopes)),
            ("credentialMetadata.setupUrl", str(setup_url or "")),
            ("credentialMetadata.brokerMode", str(broker_mode or "")),
        ])
    policy = _child(data, issues, "unavailablePolicy")
    if policy:
        _require_keys(policy, {"build", "rental", "execution"}, issues, "unavailablePolicy")
        _reject_unknown(policy, {"build", "rental", "execution"}, issues, "unavailablePolicy")
        _expect(policy, issues, "build", "degrade", prefix="unavailablePolicy.")
        rental = _enum(
            policy,
            issues,
            "rental",
            {"exclude-variant", "continue-degraded"},
            prefix="unavailablePolicy.",
        )
        _enum(
            policy,
            issues,
            "execution",
            {"use-alternative", "disable-capability", "continue-degraded"},
            prefix="unavailablePolicy.",
        )
        if required is True and rental != "exclude-variant":
            issues.append("required MCP absence must exclude only that variant during rental")
        if required is False and rental != "continue-degraded":
            issues.append("optional MCP absence must continue degraded during rental")
    _validate_mcp_safe_text([
        ("requirementId", str(data.get("requirementId") or "")),
        ("catalogId", str(data.get("catalogId") or "")),
        ("reason", str(data.get("reason") or "")),
        *((f"capabilities[{index}]", value) for index, value in enumerate(capabilities)),
        *((f"permissions[{index}]", value) for index, value in enumerate(permissions)),
        *((f"alternatives[{index}]", value) for index, value in enumerate(alternatives)),
        *credential_text,
    ], issues)
    _forbid_keys(data, _MCP_EXECUTION_KEYS, issues, "MCPRequirement")
    _forbid_secrets(data, issues, "MCPRequirement")
    _raise(issues)


def validate_mcp_policy(payload: Mapping[str, Any]) -> None:
    data = _mapping(payload, "MCPPolicy")
    issues: list[str] = []
    required = {
        "schemaVersion", "kind", "registryResolutionOrder", "consentMode",
        "serverDefinitionsFromPackage", "credentialValuesAllowed", "failureIsolation",
        "permissionWidening", "toolSchemaLoading", "skillLoading", "contextBudget", "requirements",
    }
    _require_keys(data, required, issues, "MCPPolicy")
    _reject_unknown(data, required, issues, "MCPPolicy")
    _expect(data, issues, "schemaVersion", SCHEMA_VERSIONS["mcp-policy"])
    _expect(data, issues, "kind", "agentlas-mcp-policy")
    order = data.get("registryResolutionOrder")
    allowed_registry_scopes = {"system-global", "project-local", "catalog-recommendation"}
    if not isinstance(order, list) or order[:1] != ["system-global"]:
        issues.append("registryResolutionOrder must start with system-global")
    else:
        if order != list(dict.fromkeys(order)):
            issues.append("registryResolutionOrder must not contain duplicates")
        for index, scope in enumerate(order):
            if scope not in allowed_registry_scopes:
                issues.append(f"registryResolutionOrder[{index}] is not a supported registry scope")
    _expect(data, issues, "consentMode", "one-pass")
    _false(data, issues, "serverDefinitionsFromPackage")
    _false(data, issues, "credentialValuesAllowed")
    _expect(data, issues, "failureIsolation", "per-requirement")
    _expect(data, issues, "permissionWidening", "ask")
    _expect(data, issues, "toolSchemaLoading", "selected-tools-only")
    _expect(data, issues, "skillLoading", "triggered-only")
    _validate_context_budget(data.get("contextBudget"), issues, "contextBudget")
    requirements = data.get("requirements")
    if not isinstance(requirements, list):
        issues.append("requirements must be an array")
    elif len(requirements) > 64:
        issues.append("requirements must contain at most 64 MCP entries")
    else:
        ids: set[str] = set()
        catalogs: set[str] = set()
        for index, requirement in enumerate(requirements):
            try:
                item = _mapping(requirement, f"requirements[{index}]")
                validate_mcp_requirement(item)
                requirement_id = str(item.get("requirementId"))
                catalog_id = str(item.get("catalogId"))
                if requirement_id in ids:
                    issues.append(f"duplicate MCP requirementId: {requirement_id}")
                if catalog_id in catalogs:
                    issues.append(f"duplicate MCP catalogId: {catalog_id}")
                ids.add(requirement_id)
                catalogs.add(catalog_id)
            except ContractValidationError as exc:
                issues.extend(f"requirements[{index}]: {issue}" for issue in exc.issues)
    _forbid_keys(data, _MCP_EXECUTION_KEYS, issues, "MCPPolicy")
    _forbid_secrets(data, issues, "MCPPolicy")
    _raise(issues)


def validate_run_receipt(payload: Mapping[str, Any]) -> None:
    data = _mapping(payload, "RunReceipt")
    issues: list[str] = []
    required = {
        "schemaVersion", "kind", "receiptId", "idempotencyKey", "receiptHash", "runId",
        "agentDefinitionReleaseId", "experiencePackReleaseId", "variantId", "taskSignature",
        "environment", "resources", "outcome", "verification", "metricsEligible", "metrics",
        "sideEffects", "privacy", "createdAt",
    }
    allowed = required | {"signature"}
    _require_keys(data, required, issues, "RunReceipt")
    _reject_unknown(data, allowed, issues, "RunReceipt")
    _expect(data, issues, "schemaVersion", SCHEMA_VERSIONS["run-receipt"])
    _expect(data, issues, "kind", "agentlas-run-receipt")
    for key in ("receiptId", "idempotencyKey", "runId", "agentDefinitionReleaseId"):
        _id(data, issues, key)
    _nullable_id(data, issues, "experiencePackReleaseId")
    _nullable_id(data, issues, "variantId")
    _hash(data, issues, "receiptHash")
    if "signature" in data and data.get("signature") is not None:
        issues.append("signature must be null in the portable RunReceipt v1 contract")
    task = _child(data, issues, "taskSignature")
    if task:
        _require_keys(task, {"kind", "hash"}, issues, "taskSignature")
        _reject_unknown(task, {"kind", "hash", "locale"}, issues, "taskSignature")
        _id(task, issues, "kind", prefix="taskSignature.")
        _hash(task, issues, "hash", prefix="taskSignature.")
    environment = _child(data, issues, "environment")
    if environment:
        _require_keys(environment, {"runtime", "os", "arch", "fingerprintHash"}, issues, "environment")
        _reject_unknown(environment, {"runtime", "os", "arch", "fingerprintHash"}, issues, "environment")
        for key in ("runtime", "os", "arch"):
            _id(environment, issues, key, prefix="environment.")
        _hash(environment, issues, "fingerprintHash", prefix="environment.")
    resources = _child(data, issues, "resources")
    if resources:
        _require_keys(resources, {"mcp", "skills", "model"}, issues, "resources")
        _reject_unknown(resources, {"mcp", "skills", "model"}, issues, "resources")
        mcp = resources.get("mcp")
        if not isinstance(mcp, list):
            issues.append("resources.mcp must be an array")
        else:
            for index, item in enumerate(mcp):
                if not isinstance(item, Mapping) or not item.get("catalogId"):
                    issues.append(f"resources.mcp[{index}] requires catalogId")
                    continue
                _require_keys(item, {"catalogId", "status"}, issues, f"resources.mcp[{index}]")
                _reject_unknown(
                    item,
                    {"catalogId", "status", "resolvedVersion", "fallbackFor"},
                    issues,
                    f"resources.mcp[{index}]",
                )
                if item.get("status") not in {
                    "recommended",
                    "approved",
                    "connected",
                    "skipped",
                    "missing-key",
                    "failed",
                    "degraded",
                }:
                    issues.append(f"resources.mcp[{index}].status is invalid")
        if not isinstance(resources.get("skills"), list):
            issues.append("resources.skills must be an array")
        else:
            for index, skill in enumerate(resources["skills"]):
                if not isinstance(skill, Mapping):
                    issues.append(f"resources.skills[{index}] must be an object")
                    continue
                _require_keys(skill, {"id"}, issues, f"resources.skills[{index}]")
                _reject_unknown(skill, {"id", "version"}, issues, f"resources.skills[{index}]")
        model = resources.get("model")
        if not isinstance(model, Mapping) or not model.get("provider") or not model.get("modelId"):
            issues.append("resources.model requires provider and modelId")
        elif isinstance(model, Mapping):
            _reject_unknown(model, {"provider", "modelId"}, issues, "resources.model")
    outcome = _child(data, issues, "outcome")
    if outcome:
        _require_keys(outcome, {"status"}, issues, "outcome")
        _reject_unknown(outcome, {"status", "failureCode"}, issues, "outcome")
        _enum(outcome, issues, "status", {"succeeded", "partial", "failed", "cancelled"}, prefix="outcome.")
    verification = _child(data, issues, "verification")
    verdict = method = verifier = None
    if verification:
        _require_keys(verification, {"verdict", "method", "verifierRef", "evidenceRefs"}, issues, "verification")
        _reject_unknown(verification, {"verdict", "method", "verifierRef", "evidenceRefs"}, issues, "verification")
        verdict = _enum(verification, issues, "verdict", {"pass", "fail", "unverified"}, prefix="verification.")
        method = _enum(
            verification,
            issues,
            "method",
            {"automated", "human", "third-party", "self-report", "none"},
            prefix="verification.",
        )
        verifier = verification.get("verifierRef")
        if method in {"automated", "human", "third-party"} and not isinstance(verifier, str):
            issues.append("independent verification requires verification.verifierRef")
        _string_list(verification, issues, "evidenceRefs", min_items=0, prefix="verification.")
    eligible = _bool(data, issues, "metricsEligible")
    if eligible is True and not (
        data.get("outcome", {}).get("status") == "succeeded"
        and verdict == "pass"
        and method in {"automated", "human", "third-party"}
        and verifier
    ):
        issues.append("metricsEligible=true requires successful independently verified execution")
    metrics = _child(data, issues, "metrics")
    if metrics:
        metric_keys = {"promptTokens", "completionTokens", "totalTokens", "durationMs", "retryCount"}
        _require_keys(metrics, metric_keys, issues, "metrics")
        _reject_unknown(metrics, metric_keys, issues, "metrics")
        for key in ("promptTokens", "completionTokens", "totalTokens", "durationMs", "retryCount"):
            value = metrics.get(key)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                issues.append(f"metrics.{key} must be a non-negative integer")
        if all(isinstance(metrics.get(key), int) for key in ("promptTokens", "completionTokens", "totalTokens")):
            if metrics["totalTokens"] < metrics["promptTokens"] + metrics["completionTokens"]:
                issues.append("metrics.totalTokens cannot be less than promptTokens + completionTokens")
    privacy = _child(data, issues, "privacy")
    if privacy:
        privacy_keys = {"rawPromptIncluded", "rawTranscriptIncluded", "rawLocalPathsIncluded", "credentialValuesIncluded"}
        _require_keys(privacy, privacy_keys, issues, "privacy")
        _reject_unknown(privacy, privacy_keys, issues, "privacy")
        for key in ("rawPromptIncluded", "rawTranscriptIncluded", "rawLocalPathsIncluded", "credentialValuesIncluded"):
            _false(privacy, issues, key, prefix="privacy.")
    side_effects = _child(data, issues, "sideEffects")
    if side_effects:
        side_effect_keys = {"occurred", "adverse", "evidenceRefs"}
        _require_keys(side_effects, side_effect_keys, issues, "sideEffects")
        _reject_unknown(side_effects, side_effect_keys, issues, "sideEffects")
        _bool(side_effects, issues, "occurred")
        _bool(side_effects, issues, "adverse")
        _string_list(side_effects, issues, "evidenceRefs", min_items=0, prefix="sideEffects.")
    if _SHA256_RE.fullmatch(str(data.get("receiptHash", ""))):
        expected = canonical_hash(data, exclude={"receiptHash", "signature"})
        if data["receiptHash"] != expected:
            issues.append("receiptHash does not match the canonical receipt payload")
    _forbid_keys(data, _RAW_EXPERIENCE_KEYS | {"credentialvalue"}, issues, "RunReceipt")
    _forbid_secrets(data, issues, "RunReceipt")
    _raise(issues)


def validate_rental_resolution_receipt(payload: Mapping[str, Any]) -> None:
    data = _mapping(payload, "RentalResolutionReceipt")
    issues: list[str] = []
    required = {
        "schemaVersion", "kind", "resolutionReceiptId", "requestId", "taskSignature",
        "environment", "scoringPolicyVersion", "confidenceMethod", "candidates", "result",
        "selectedVariantId", "fallbackOrder", "createdAt",
    }
    _require_keys(data, required, issues, "RentalResolutionReceipt")
    _reject_unknown(data, required, issues, "RentalResolutionReceipt")
    _expect(data, issues, "schemaVersion", SCHEMA_VERSIONS["rental-resolution-receipt"])
    _expect(data, issues, "kind", "agentlas-rental-resolution-receipt")
    for key in ("resolutionReceiptId", "requestId", "scoringPolicyVersion"):
        _id(data, issues, key)
    task = _child(data, issues, "taskSignature")
    if task:
        _require_keys(task, {"kind", "hash"}, issues, "taskSignature")
        _reject_unknown(task, {"kind", "hash"}, issues, "taskSignature")
        _id(task, issues, "kind", prefix="taskSignature.")
        _hash(task, issues, "hash", prefix="taskSignature.")
    environment = _child(data, issues, "environment")
    if environment:
        _require_keys(environment, {"fingerprintHash"}, issues, "environment")
        _reject_unknown(environment, {"fingerprintHash", "runtime"}, issues, "environment")
        _hash(environment, issues, "fingerprintHash", prefix="environment.")
    _enum(data, issues, "confidenceMethod", {"wilson-lower-bound", "beta-posterior-lower-bound"})
    candidates = data.get("candidates")
    selected_candidates: list[str] = []
    candidate_decisions: dict[str, str] = {}
    if not isinstance(candidates, list):
        issues.append("candidates must be an array")
    else:
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, Mapping):
                issues.append(f"candidates[{index}] must be an object")
                continue
            candidate_required = {
                "variantId", "baseAgentReleaseId", "experiencePackReleaseId", "decision",
                "verifiedSampleSize", "conservativeConfidence", "scoreComponents",
                "mcpResolution", "reasonCodes",
            }
            _require_keys(candidate, candidate_required, issues, f"candidates[{index}]")
            _reject_unknown(candidate, candidate_required, issues, f"candidates[{index}]")
            for key in ("variantId", "baseAgentReleaseId", "experiencePackReleaseId"):
                if not isinstance(candidate.get(key), str) or not _ID_RE.fullmatch(candidate[key]):
                    issues.append(f"candidates[{index}].{key} is invalid")
            decision = candidate.get("decision")
            if decision not in {"selected", "fallback", "excluded"}:
                issues.append(f"candidates[{index}].decision is invalid")
            variant_id = candidate.get("variantId")
            if isinstance(variant_id, str):
                if variant_id in candidate_decisions:
                    issues.append(f"duplicate candidate variantId: {variant_id}")
                else:
                    candidate_decisions[variant_id] = str(decision)
            if decision == "selected":
                selected_candidates.append(str(variant_id))
            sample = candidate.get("verifiedSampleSize")
            if not isinstance(sample, int) or isinstance(sample, bool) or sample < 0:
                issues.append(f"candidates[{index}].verifiedSampleSize must be non-negative")
            confidence = candidate.get("conservativeConfidence")
            if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
                issues.append(f"candidates[{index}].conservativeConfidence must be 0..1")
            components = candidate.get("scoreComponents")
            required_components = {
                "verifiedTaskSuccess",
                "environmentCompatibility",
                "mcpCompatibility",
                "recency",
                "reputation",
                "tokenEfficiency",
                "latencyEfficiency",
                "costEfficiency",
                "adverseEffectPenalty",
                "stalenessPenalty",
            }
            if not isinstance(components, Mapping) or not required_components.issubset(components):
                issues.append(f"candidates[{index}].scoreComponents is incomplete")
            elif isinstance(components, Mapping):
                _reject_unknown(components, required_components, issues, f"candidates[{index}].scoreComponents")
                for component, score in components.items():
                    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 1:
                        issues.append(f"candidates[{index}].scoreComponents.{component} must be 0..1")
            mcp = candidate.get("mcpResolution")
            if not isinstance(mcp, Mapping) or mcp.get("status") not in {"compatible", "degraded", "missing-required"}:
                issues.append(f"candidates[{index}].mcpResolution.status is invalid")
            else:
                _require_keys(mcp, {"status", "missingCatalogIds"}, issues, f"candidates[{index}].mcpResolution")
                _reject_unknown(mcp, {"status", "missingCatalogIds"}, issues, f"candidates[{index}].mcpResolution")
                _string_list(mcp, issues, "missingCatalogIds", min_items=0, prefix=f"candidates[{index}].mcpResolution.")
                if mcp.get("status") == "missing-required" and decision != "excluded":
                    issues.append(f"candidates[{index}] missing required MCP must exclude only that variant")
            _string_list(candidate, issues, "reasonCodes", min_items=1, prefix=f"candidates[{index}].")
    result = _enum(data, issues, "result", {"selected", "base-only", "no-compatible-variant"})
    selected = data.get("selectedVariantId")
    if result == "selected":
        if len(selected_candidates) != 1 or selected != selected_candidates[0]:
            issues.append("selected result requires exactly one matching selectedVariantId")
    elif selected is not None:
        issues.append("selectedVariantId must be null unless result=selected")
    fallback_order = _id_list(data, issues, "fallbackOrder", min_items=0)
    fallback_candidate_ids = {
        variant_id for variant_id, decision in candidate_decisions.items() if decision == "fallback"
    }
    for variant_id in fallback_order:
        decision = candidate_decisions.get(variant_id)
        if decision is None:
            issues.append(f"fallbackOrder references unevaluated variantId: {variant_id}")
        elif decision != "fallback":
            issues.append(f"fallbackOrder must contain only decision='fallback' candidates: {variant_id}")
    missing_fallbacks = sorted(fallback_candidate_ids - set(fallback_order))
    if missing_fallbacks:
        issues.append("fallbackOrder is missing fallback candidates: " + ", ".join(missing_fallbacks))
    if result == "no-compatible-variant" and any(decision != "excluded" for decision in candidate_decisions.values()):
        issues.append("no-compatible-variant cannot contain eligible candidates")
    _forbid_keys(data, _RAW_EXPERIENCE_KEYS | {"credentialvalue"}, issues, "RentalResolutionReceipt")
    _forbid_secrets(data, issues, "RentalResolutionReceipt")
    _raise(issues)


@dataclass
class ReceiptReplayGuard:
    """Small in-memory/idempotency primitive used by local and hosted stores.

    Production stores should persist the three values behind unique indexes.
    This class defines the cross-runtime behavior and makes replay handling
    testable without introducing a public-core database.
    """

    receipt_ids: set[str] = field(default_factory=set)
    idempotency_keys: set[str] = field(default_factory=set)
    receipt_hashes: set[str] = field(default_factory=set)

    def accept(self, receipt: Mapping[str, Any]) -> None:
        validate_run_receipt(receipt)
        data = dict(receipt)
        collisions = []
        if data["receiptId"] in self.receipt_ids:
            collisions.append("receiptId")
        if data["idempotencyKey"] in self.idempotency_keys:
            collisions.append("idempotencyKey")
        if data["receiptHash"] in self.receipt_hashes:
            collisions.append("receiptHash")
        if collisions:
            raise ContractValidationError(["duplicate RunReceipt replay: " + ", ".join(collisions)])
        self.receipt_ids.add(data["receiptId"])
        self.idempotency_keys.add(data["idempotencyKey"])
        self.receipt_hashes.add(data["receiptHash"])


@dataclass
class PreferenceReceiptReplayGuard:
    """Reject duplicate human A/B receipts before they affect a taste aggregate."""

    receipt_ids: set[str] = field(default_factory=set)
    idempotency_keys: set[str] = field(default_factory=set)
    receipt_hashes: set[str] = field(default_factory=set)

    def accept(self, receipt: Mapping[str, Any]) -> None:
        validate_pairwise_preference_receipt(receipt)
        data = dict(receipt)
        collisions = []
        if data["receiptId"] in self.receipt_ids:
            collisions.append("receiptId")
        if data["idempotencyKey"] in self.idempotency_keys:
            collisions.append("idempotencyKey")
        if data["receiptHash"] in self.receipt_hashes:
            collisions.append("receiptHash")
        if collisions:
            raise ContractValidationError(
                ["duplicate PairwisePreferenceReceipt replay: " + ", ".join(collisions)]
            )
        self.receipt_ids.add(data["receiptId"])
        self.idempotency_keys.add(data["idempotencyKey"])
        self.receipt_hashes.add(data["receiptHash"])


def _mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError([f"{label} must be an object"])
    return dict(value)


def _require_keys(data: Mapping[str, Any], required: set[str], issues: list[str], label: str) -> None:
    missing = sorted(required - set(data))
    if missing:
        issues.append(f"{label} missing required fields: {', '.join(missing)}")


def _reject_unknown(data: Mapping[str, Any], allowed: set[str], issues: list[str], label: str) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        issues.append(f"{label} contains unknown fields: {', '.join(unknown)}")


def _identity(data: Mapping[str, Any], issues: list[str], *keys: str) -> None:
    for key in keys:
        _id(data, issues, key)


def _id(data: Mapping[str, Any], issues: list[str], key: str, *, prefix: str = "") -> Any:
    value = data.get(key)
    if not isinstance(value, str) or not _ID_RE.fullmatch(value):
        issues.append(f"{prefix}{key} must be an opaque stable id")
    return value


def _nullable_id(data: Mapping[str, Any], issues: list[str], key: str) -> None:
    value = data.get(key)
    if value is not None and (not isinstance(value, str) or not _ID_RE.fullmatch(value)):
        issues.append(f"{key} must be null or an opaque stable id")


def _relative_path(data: Mapping[str, Any], issues: list[str], key: str) -> None:
    value = data.get(key)
    if (
        not isinstance(value, str)
        or not value
        or value.startswith(("/", "\\"))
        or ".." in value.replace("\\", "/").split("/")
        or not re.fullmatch(r"[A-Za-z0-9._/\\-]+", value)
    ):
        issues.append(f"{key} must be a safe package-relative path")


def _hash(data: Mapping[str, Any], issues: list[str], key: str, *, prefix: str = "") -> None:
    value = data.get(key)
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        issues.append(f"{prefix}{key} must be sha256:<64 lowercase hex>")


def _expect(data: Mapping[str, Any], issues: list[str], key: str, expected: Any, *, prefix: str = "") -> None:
    if data.get(key) != expected:
        issues.append(f"{prefix}{key} must equal {expected!r}")


def _enum(
    data: Mapping[str, Any],
    issues: list[str],
    key: str,
    allowed: set[str],
    *,
    prefix: str = "",
) -> Any:
    value = data.get(key)
    if value not in allowed:
        issues.append(f"{prefix}{key} must be one of {sorted(allowed)}")
    return value


def _bool(data: Mapping[str, Any], issues: list[str], key: str) -> bool | None:
    value = data.get(key)
    if not isinstance(value, bool):
        issues.append(f"{key} must be boolean")
        return None
    return value


def _false(data: Mapping[str, Any], issues: list[str], key: str, *, prefix: str = "") -> None:
    if data.get(key) is not False:
        issues.append(f"{prefix}{key} must be false")


def _bounded_string(data: Mapping[str, Any], issues: list[str], key: str, minimum: int, maximum: int) -> None:
    value = data.get(key)
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        issues.append(f"{key} must be a {minimum}..{maximum} character string")


def _string_list(
    data: Mapping[str, Any],
    issues: list[str],
    key: str,
    *,
    min_items: int,
    max_items: int | None = None,
    prefix: str = "",
) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or len(value) < min_items or any(not isinstance(item, str) or not item for item in value):
        issues.append(f"{prefix}{key} must be an array with at least {min_items} non-empty strings")
        return []
    if len(value) != len(set(value)):
        issues.append(f"{prefix}{key} must not contain duplicates")
    if max_items is not None and len(value) > max_items:
        issues.append(f"{prefix}{key} must contain at most {max_items} values")
    return value


def _id_list(
    data: Mapping[str, Any],
    issues: list[str],
    key: str,
    *,
    min_items: int,
    max_items: int | None = None,
    prefix: str = "",
) -> list[str]:
    values = _string_list(data, issues, key, min_items=min_items, max_items=max_items, prefix=prefix)
    for index, value in enumerate(values):
        if not _ID_RE.fullmatch(value):
            issues.append(f"{prefix}{key}[{index}] must be an opaque stable id")
    return values


def _env_list(data: Mapping[str, Any], issues: list[str], key: str, *, prefix: str = "") -> list[str]:
    values = _string_list(data, issues, key, min_items=1, max_items=32, prefix=prefix)
    for index, value in enumerate(values):
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", value):
            issues.append(f"{prefix}{key}[{index}] must be an uppercase environment name")
    return values


def _optional_hostname_list(
    data: Mapping[str, Any],
    issues: list[str],
    key: str,
    *,
    prefix: str = "",
) -> list[str]:
    if key not in data:
        return []
    values = _string_list(data, issues, key, min_items=1, max_items=64, prefix=prefix)
    for index, value in enumerate(values):
        if len(value) > 255 or not _MCP_HOST_RE.fullmatch(value):
            issues.append(
                f"{prefix}{key}[{index}] must be a hostname with an optional leading '*.' wildcard"
            )
    return values


def _optional_scope_list(
    data: Mapping[str, Any],
    issues: list[str],
    key: str,
    *,
    prefix: str = "",
) -> list[str]:
    if key not in data:
        return []
    values = _string_list(data, issues, key, min_items=1, max_items=64, prefix=prefix)
    for index, value in enumerate(values):
        if not _MCP_SCOPE_RE.fullmatch(value):
            issues.append(f"{prefix}{key}[{index}] must be a 1..128 character opaque scope id")
    return values


def _validate_https_setup_url(value: Any, issues: list[str]) -> None:
    message = (
        "credentialMetadata.setupUrl must be an HTTPS host/path URL without "
        "userinfo, port, query, or fragment"
    )
    if not isinstance(value, str):
        issues.append(message)
        return
    try:
        parsed = urlsplit(value)
    except ValueError:
        parsed = None
    try:
        port = parsed.port if parsed is not None else None
    except ValueError:
        port = -1
    if (
        parsed is None
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or bool(parsed.query)
        or bool(parsed.fragment)
        or len(value) > 2048
        or not _MCP_SETUP_URL_RE.fullmatch(value)
    ):
        issues.append(message)


def _child(data: Mapping[str, Any], issues: list[str], key: str) -> dict[str, Any] | None:
    value = data.get(key)
    if not isinstance(value, Mapping):
        issues.append(f"{key} must be an object")
        return None
    return dict(value)


def _validate_context_budget(value: Any, issues: list[str], label: str) -> None:
    if not isinstance(value, Mapping):
        issues.append(f"{label} must be an object")
        return
    limits = {
        "coreMemoryMaxTokens": CORE_MEMORY_MAX_TOKENS,
        "experienceRetrievalMaxTokens": EXPERIENCE_RETRIEVAL_MAX_TOKENS,
        "experienceRetrievalMaxItems": EXPERIENCE_RETRIEVAL_MAX_ITEMS,
    }
    _require_keys(value, set(limits), issues, label)
    _reject_unknown(value, set(limits), issues, label)
    for key, maximum in limits.items():
        actual = value.get(key)
        if not isinstance(actual, int) or isinstance(actual, bool) or not 0 <= actual <= maximum:
            issues.append(f"{label}.{key} must be an integer from 0 to {maximum}")


def _validate_public_safe_asset_text(
    values: list[tuple[str, str]],
    issues: list[str],
    label: str,
) -> None:
    """Reject private evidence patterns from a public-safe asset projection."""

    text = "\n".join(value for _, value in values)
    privacy_findings = {
        finding
        for path, value in values
        for finding in scan_public_field(path, value)
    }
    if "local_path" in privacy_findings:
        issues.append(f"{label} contains absolute local path, traversal, or file URL")
    if any(finding != "local_path" for finding in privacy_findings):
        issues.append(f"{label} contains a personal/customer identifier")
    if _PUBLIC_TRANSCRIPT_RE.search(text):
        issues.append(f"{label} contains raw transcript, base prompt, or package marker")
    if any(
        _PUBLIC_OPAQUE_BLOB_RE.search(value)
        for path, value in values
        if not is_allowed_protocol_metadata(path, value)
    ):
        issues.append(f"{label} contains long opaque encoded blob")


def _validate_public_safe_experience_text(values: list[tuple[str, str]], issues: list[str]) -> None:
    """Reject private evidence patterns from a public-safe item projection.

    Private candidates may retain these strings in local storage for curation.
    Labelling the same text public-safe is the forbidden transition.
    """

    _validate_public_safe_asset_text(values, issues, "public-safe ExperienceItem")


def _validate_mcp_safe_text(values: list[tuple[str, str]], issues: list[str]) -> None:
    text = "\n".join(value for _, value in values)
    privacy_findings = {
        finding
        for path, value in values
        for finding in scan_public_field(path, value)
    }
    if "local_path" in privacy_findings:
        issues.append("MCPRequirement contains absolute local path, traversal, or file URL")
    if any(finding != "local_path" for finding in privacy_findings):
        issues.append("MCPRequirement contains a personal/customer identifier")
    if _PUBLIC_TRANSCRIPT_RE.search(text):
        issues.append("MCPRequirement contains raw transcript, base prompt, or package marker")
    if any(
        _PUBLIC_OPAQUE_BLOB_RE.search(value)
        for path, value in values
        if not is_allowed_protocol_metadata(path, value)
    ):
        issues.append("MCPRequirement contains long opaque encoded blob")
    if any(pattern.search(text) for pattern in _SECRET_PATTERNS):
        issues.append("MCPRequirement contains a secret-like value")
    if any(pattern.search(text) for pattern in _MCP_PROMPT_INJECTION_PATTERNS):
        issues.append("MCPRequirement contains a prompt-injection instruction")


def _forbid_keys(value: Any, blocked: set[str], issues: list[str], label: str, path: str = "") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            next_path = f"{path}.{key}" if path else str(key)
            if normalized in blocked:
                issues.append(f"{label} forbids field {next_path}")
            _forbid_keys(child, blocked, issues, label, next_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _forbid_keys(child, blocked, issues, label, f"{path}[{index}]")


def _forbid_secrets(value: Any, issues: list[str], label: str) -> None:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if any(pattern.search(serialized) for pattern in _SECRET_PATTERNS):
        issues.append(f"{label} contains a secret-like value")


def _raise(issues: list[str]) -> None:
    if issues:
        raise ContractValidationError(issues)
