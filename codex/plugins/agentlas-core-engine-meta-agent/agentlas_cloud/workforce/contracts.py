"""Shared helpers for Agent Workforce Ontology public contracts."""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Mapping


ID_SAFE_RE = re.compile(r"[^a-z0-9._:/@-]+")
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._:/@+-]*|[가-힣]{2,}", re.IGNORECASE)
WORKFORCE_ONTOLOGY_VERSION = "awo:2026-07-15.2"
WORKFORCE_ONTOLOGY_SNAPSHOT_SHA256 = "d6d30d45fe8d35fb785e165d1e80c6471a72436f0160c3933c21d4a31bf2fb32"
WORKFORCE_WORK_ORDER_SCHEMA_VERSION = "agentlas.workforce-work-order.v1"
WORKFORCE_SELECTION_SCHEMA_VERSION = "agentlas.workforce-selection.v1"
WORKFORCE_WORK_ORDER_SCHEMA_RESOURCE = "schemas/workforce-work-order.schema.json"
WORKFORCE_SELECTION_SCHEMA_RESOURCE = "schemas/workforce-selection.schema.json"
WORKFORCE_ONTOLOGY_RESOURCE = "agentlas_cloud/workforce/ontology_v1.json"
WORKFORCE_WORK_ORDER_SCHEMA_ID = "https://agentlas.ai/schemas/workforce-work-order.schema.json"
WORKFORCE_SELECTION_SCHEMA_ID = "https://agentlas.ai/schemas/workforce-selection.schema.json"

# Human-readable identifiers allowed by the original v1 fixtures and public
# contract. Novel identifiers must use an explicit non-semantic ordinal or
# one-way opaque form (for example ``slot:ordinal-2`` or
# ``knowledge:opaque-<sha256>``). This prevents a private company/person/project
# name from being disguised as a structured identifier.
WORKFORCE_V1_PUBLIC_WORK_ORDER_IDS = frozenset({
    "work-order:backend-payment",
    "work-order:payments-api",
    "work-order:test",
})
WORKFORCE_V1_PUBLIC_ARTIFACT_IDS = frozenset({
    "artifact:api-spec",
    "artifact:codebase_change",
    "artifact:decision-record",
    "artifact:source-code",
    "artifact:team-result",
    "artifact:unavailable-deliverable",
    "artifact:worker-result",
})
WORKFORCE_V1_PUBLIC_AUTHORITY_IDS = frozenset({
    "authority:database-write",
    "authority:file-read",
    "authority:network",
    "authority:payment",
    "authority:shell",
})
WORKFORCE_V1_PUBLIC_RUNTIME_IDS = frozenset({
    "claude",
    "cloud",
    "codex",
    "desktop",
    "hub",
    "local",
    "ollama",
    "terminal",
})
WORKFORCE_V1_PUBLIC_LANGUAGE_IDS = frozenset({
    "ar", "de", "en", "es", "fr", "hi", "it", "ja", "ko", "pt",
    "zh", "zh-CN", "zh-TW",
})
WORKFORCE_V1_PUBLIC_MODALITY_IDS = frozenset({
    "audio", "image", "multimodal", "text", "video",
})
WORKFORCE_SELECTION_REASON_CODES = frozenset({
    "best-semantic-fit",
    "exact-fit",
    "reason:best-contract-fit",
    "reason:best-content-fit",
    "reason:declared-team-fit",
    "reason:edge-compatibility",
    "reason:host-semantic-judgment",
    "reason:required-capability-fit",
    "reason:required-mongodb-capability",
    "reason:team-composition-fit",
})
_OPAQUE_OR_ORDINAL_ID_RE = re.compile(
    r"^(?:[A-Za-z][A-Za-z0-9._-]*:)?(?:opaque-[0-9a-f]{64}|ordinal-[1-9][0-9]{0,8})$"
)

_CONTRACT_RESOURCES = {
    "workOrder": {
        "schemaVersion": WORKFORCE_WORK_ORDER_SCHEMA_VERSION,
        "schemaResource": WORKFORCE_WORK_ORDER_SCHEMA_RESOURCE,
        "schemaId": WORKFORCE_WORK_ORDER_SCHEMA_ID,
    },
    "selection": {
        "schemaVersion": WORKFORCE_SELECTION_SCHEMA_VERSION,
        "schemaResource": WORKFORCE_SELECTION_SCHEMA_RESOURCE,
        "schemaId": WORKFORCE_SELECTION_SCHEMA_ID,
    },
}

# The host boundary intentionally remains dependency-free.  These are all
# assertion keywords used by the two public v1 schemas.  Loading fails closed
# if a future schema starts using a keyword the bundled validator does not
# understand, rather than silently weakening that new contract.
_SUPPORTED_SCHEMA_KEYWORDS = frozenset({
    "$schema", "$id", "$ref", "$defs", "$comment", "title", "description",
    "type", "const", "enum", "pattern", "minLength", "maxLength",
    "minimum", "maximum", "minItems", "maxItems", "uniqueItems", "items",
    "required", "properties", "additionalProperties",
})


def workforce_contract_metadata(kind: str) -> dict[str, Any]:
    """Return public, canonical contract metadata for an MCP host."""

    if kind not in _CONTRACT_RESOURCES:
        raise ValueError("unsupported_workforce_contract")
    metadata = {
        **_CONTRACT_RESOURCES[kind],
        "ontologyVersion": WORKFORCE_ONTOLOGY_VERSION,
        "ontologyResource": WORKFORCE_ONTOLOGY_RESOURCE,
    }
    metadata["finiteIdPolicy"] = (
        "schema-valid redacted ontology constraints; public-v1 or "
        "<namespace>:opaque-<sha256>/<namespace>:ordinal-N for bounded host IDs"
        if kind == "workOrder"
        else "slot/release/edge IDs from the exact WorkOrder/CandidateSet; public finite reason codes"
    )
    metadata["ontologyCatalog"] = workforce_ontology_catalog()
    if kind == "workOrder":
        metadata["publicIdCatalog"] = {
            "workOrderIds": sorted(WORKFORCE_V1_PUBLIC_WORK_ORDER_IDS),
            "slotIds": sorted(workforce_public_slot_ids()),
            "artifactIds": sorted(WORKFORCE_V1_PUBLIC_ARTIFACT_IDS),
            "authorityIds": sorted(WORKFORCE_V1_PUBLIC_AUTHORITY_IDS),
            "runtimeIds": sorted(WORKFORCE_V1_PUBLIC_RUNTIME_IDS),
            "languageIds": sorted(WORKFORCE_V1_PUBLIC_LANGUAGE_IDS),
            "modalityIds": sorted(WORKFORCE_V1_PUBLIC_MODALITY_IDS),
            "novelIdForms": ["<namespace>:opaque-<64 lowercase hex>", "<namespace>:ordinal-N"],
        }
    else:
        metadata["reasonCodeCatalog"] = sorted(WORKFORCE_SELECTION_REASON_CODES)
    return metadata


def _schema_path(resource: str) -> Path:
    return Path(__file__).resolve().parents[2] / resource


def _check_supported_schema(node: Any) -> None:
    if isinstance(node, Mapping):
        unsupported = set(node) - _SUPPORTED_SCHEMA_KEYWORDS
        if unsupported:
            raise ValueError("unsupported_workforce_schema_keyword")
        definitions = node.get("$defs")
        if isinstance(definitions, Mapping):
            for child in definitions.values():
                _check_supported_schema(child)
        properties = node.get("properties")
        if isinstance(properties, Mapping):
            for child in properties.values():
                _check_supported_schema(child)
        items = node.get("items")
        if isinstance(items, Mapping):
            _check_supported_schema(items)


@lru_cache(maxsize=2)
def load_workforce_contract_schema(kind: str) -> dict[str, Any]:
    """Load and pin one canonical public host contract schema."""

    metadata = workforce_contract_metadata(kind)
    schema = json.loads(_schema_path(metadata["schemaResource"]).read_text(encoding="utf-8"))
    if not isinstance(schema, dict) or schema.get("$id") != metadata["schemaId"]:
        raise ValueError("workforce_contract_schema_identity_mismatch")
    _check_supported_schema(schema)
    return schema


def _resolve_local_ref(root: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        raise ValueError("unsupported_workforce_schema_ref")
    node: Any = root
    for part in ref[2:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, Mapping) or key not in node:
            raise ValueError("invalid_workforce_schema_ref")
        node = node[key]
    if not isinstance(node, Mapping):
        raise ValueError("invalid_workforce_schema_ref")
    return node


def _child_path(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _index_path(path: str, index: int) -> str:
    return f"{path}[{index}]" if path else f"[{index}]"


def _json_type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, Mapping)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _validate_schema_node(
    value: Any,
    schema: Mapping[str, Any],
    root: Mapping[str, Any],
    path: str,
    issues: list[dict[str, str]],
) -> None:
    ref = schema.get("$ref")
    if isinstance(ref, str):
        _validate_schema_node(value, _resolve_local_ref(root, ref), root, path, issues)

    expected = schema.get("type")
    expected_types = [expected] if isinstance(expected, str) else expected
    if isinstance(expected_types, list) and not any(
        isinstance(item, str) and _json_type_matches(value, item) for item in expected_types
    ):
        issues.append({"path": path or "$", "code": "schema_type"})
        return

    if "const" in schema and value != schema["const"]:
        issues.append({"path": path or "$", "code": "schema_const"})
    enum = schema.get("enum")
    if isinstance(enum, list) and value not in enum:
        issues.append({"path": path or "$", "code": "schema_enum"})

    if isinstance(value, str):
        # A bound violation must carry the bound. A caller told only
        # "schema_max_length at roleSlots[0].task" knows a field is too long but
        # not by how much or what to aim for, so its one repair attempt writes
        # something too long again — the exact loop that discarded a completed
        # 20-agent run on 2026-07-27. Reporting limit/actual makes the repair
        # possible without the caller having to re-derive the schema.
        if isinstance(schema.get("minLength"), int) and len(value) < schema["minLength"]:
            issues.append({
                "path": path or "$", "code": "schema_min_length",
                "limit": schema["minLength"], "actual": len(value),
            })
        if isinstance(schema.get("maxLength"), int) and len(value) > schema["maxLength"]:
            issues.append({
                "path": path or "$", "code": "schema_max_length",
                "limit": schema["maxLength"], "actual": len(value),
            })
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            issues.append({"path": path or "$", "code": "schema_pattern"})

    if isinstance(value, int) and not isinstance(value, bool):
        if isinstance(schema.get("minimum"), (int, float)) and value < schema["minimum"]:
            issues.append({"path": path or "$", "code": "schema_minimum"})
        if isinstance(schema.get("maximum"), (int, float)) and value > schema["maximum"]:
            issues.append({"path": path or "$", "code": "schema_maximum"})

    if isinstance(value, list):
        if isinstance(schema.get("minItems"), int) and len(value) < schema["minItems"]:
            issues.append({"path": path or "$", "code": "schema_min_items"})
        if isinstance(schema.get("maxItems"), int) and len(value) > schema["maxItems"]:
            issues.append({"path": path or "$", "code": "schema_max_items"})
        if schema.get("uniqueItems") is True:
            serialized = [canonical_json(item) for item in value]
            if len(serialized) != len(set(serialized)):
                issues.append({"path": path or "$", "code": "schema_unique_items"})
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                _validate_schema_node(item, item_schema, root, _index_path(path, index), issues)

    if isinstance(value, Mapping):
        properties = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        for key in required:
            if isinstance(key, str) and key not in value:
                issues.append({"path": _child_path(path, key), "code": "schema_required"})
        if schema.get("additionalProperties") is False and any(key not in properties for key in value):
            # Unknown keys are deliberately not reflected: an attacker can put
            # private data in a key name just as easily as in a value.
            issues.append({"path": path or "$", "code": "schema_additional_properties"})
        for key, child_schema in properties.items():
            if key in value and isinstance(child_schema, Mapping):
                _validate_schema_node(value[key], child_schema, root, _child_path(path, key), issues)


def validate_workforce_json_schema(value: Any, kind: str) -> list[dict[str, str]]:
    """Validate a complete v1 object without normalizing or echoing values."""

    schema = load_workforce_contract_schema(kind)
    issues: list[dict[str, str]] = []
    _validate_schema_node(value, schema, schema, "", issues)
    return issues


def iter_workforce_contract_strings(value: Any, kind: str) -> Iterable[tuple[str, str]]:
    """Yield only schema-declared string values with schema-declared paths."""

    root = load_workforce_contract_schema(kind)

    def visit(current: Any, schema: Mapping[str, Any], path: str) -> Iterable[tuple[str, str]]:
        ref = schema.get("$ref")
        if isinstance(ref, str):
            yield from visit(current, _resolve_local_ref(root, ref), path)
            return
        expected = schema.get("type")
        expected_types = [expected] if isinstance(expected, str) else expected
        if isinstance(current, str) and (
            expected_types is None
            or "string" in expected_types
            or "const" in schema
            or "enum" in schema
        ):
            yield path or "$", current
        if isinstance(current, Mapping):
            properties = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
            for key, child_schema in properties.items():
                if key in current and isinstance(child_schema, Mapping):
                    yield from visit(current[key], child_schema, _child_path(path, key))
        elif isinstance(current, list) and isinstance(schema.get("items"), Mapping):
            for index, item in enumerate(current):
                yield from visit(item, schema["items"], _index_path(path, index))

    yield from visit(value, root, "")


@lru_cache(maxsize=1)
def workforce_finite_concepts() -> dict[str, frozenset[str]]:
    """Return the finite concepts defined by the pinned ontology snapshot."""

    ontology = load_ontology()
    communities = frozenset(
        str(item["id"])
        for item in ontology.get("communities") or []
        if isinstance(item, Mapping) and item.get("id")
    )
    roles = frozenset(
        str(item["id"])
        for item in ontology.get("roles") or []
        if isinstance(item, Mapping) and item.get("id")
    )
    skills = frozenset(
        str(value)
        for value in (ontology.get("skillAliases") or {}).values()
        if value
    ) | frozenset(
        str(skill)
        for role in ontology.get("roles") or []
        if isinstance(role, Mapping)
        for skill in role.get("requiredSkills") or []
    )
    tools = frozenset(
        str(value)
        for value in (ontology.get("toolCapabilityAliases") or {}).values()
        if value
    )
    return {"community": communities, "role": roles, "skill": skills, "tool": tools}


def workforce_ontology_catalog() -> dict[str, Any]:
    """Return the bounded vocabulary a remote host needs to author v1 IDs."""

    concepts = workforce_finite_concepts()
    return {
        "ontologyVersion": WORKFORCE_ONTOLOGY_VERSION,
        "communities": sorted(concepts["community"]),
        "roles": sorted(concepts["role"]),
        "skills": sorted(concepts["skill"]),
        "tools": sorted(concepts["tool"]),
    }


@lru_cache(maxsize=1)
def workforce_public_slot_ids() -> frozenset[str]:
    concepts = workforce_finite_concepts()
    suffixes = {
        item.split(":", 1)[-1]
        for item in concepts["role"] | concepts["community"]
    }
    return frozenset({
        "slot:backend", "backend", "database", "payments", "security", "quality",
        *(f"slot:{item}" for item in suffixes),
        *suffixes,
    })


def validate_work_order_semantics(work_order: Mapping[str, Any]) -> list[dict[str, str]]:
    """Validate ontology identity and bounded host IDs in a WorkOrder.

    Role, community, skill, knowledge, and tool requirements are intentionally
    open-world constraints. A schema-valid, privacy-safe concept that is absent
    from the pinned snapshot must reach eligibility evaluation and produce a
    finite aggregate coverage gap; it is not malformed input. The ontology
    catalog remains a discovery hint, not an allowlist that can hide missing
    workforce coverage.
    """

    issues: list[dict[str, str]] = []

    def add(path: str, code: str) -> None:
        issue = {"path": path, "code": code}
        if issue not in issues:
            issues.append(issue)

    if "ontologyVersion" in work_order and work_order.get("ontologyVersion") != WORKFORCE_ONTOLOGY_VERSION:
        add("ontologyVersion", "ontology_version_mismatch")

    public_slot_ids = workforce_public_slot_ids()

    def public_or_opaque(value: Any, path: str, allowed: frozenset[str] | set[str], code: str) -> None:
        if isinstance(value, str) and value not in allowed and _OPAQUE_OR_ORDINAL_ID_RE.fullmatch(value) is None:
            add(path, code)

    def public_or_opaque_list(values: Any, path: str, allowed: frozenset[str] | set[str], code: str) -> None:
        if not isinstance(values, list):
            return
        for index, value in enumerate(values):
            public_or_opaque(value, _index_path(path, index), allowed, code)

    public_or_opaque(
        work_order.get("workOrderId"),
        "workOrderId",
        WORKFORCE_V1_PUBLIC_WORK_ORDER_IDS,
        "work_order_id_not_public_finite",
    )

    slots = work_order.get("roleSlots")
    slot_ids = {
        str(slot.get("slotId"))
        for slot in slots or []
        if isinstance(slot, Mapping) and isinstance(slot.get("slotId"), str)
    } if isinstance(slots, list) else set()
    if isinstance(slots, list):
        for index, slot in enumerate(slots):
            if not isinstance(slot, Mapping):
                continue
            base = f"roleSlots[{index}]"
            public_or_opaque(slot.get("slotId"), f"{base}.slotId", public_slot_ids, "slot_id_not_public_finite")
            for field in ("consumes", "produces"):
                public_or_opaque_list(
                    slot.get(field),
                    f"{base}.{field}",
                    WORKFORCE_V1_PUBLIC_ARTIFACT_IDS,
                    "artifact_concept_not_public_finite",
                )
            for field in ("requiredAuthorities", "forbiddenAuthorities"):
                public_or_opaque_list(
                    slot.get(field),
                    f"{base}.{field}",
                    WORKFORCE_V1_PUBLIC_AUTHORITY_IDS,
                    "authority_concept_not_public_finite",
                )
            public_or_opaque_list(
                slot.get("runtimes"),
                f"{base}.runtimes",
                WORKFORCE_V1_PUBLIC_RUNTIME_IDS,
                "runtime_id_not_public_finite",
            )
            public_or_opaque_list(
                slot.get("languages"),
                f"{base}.languages",
                WORKFORCE_V1_PUBLIC_LANGUAGE_IDS,
                "language_id_not_public_finite",
            )
            public_or_opaque_list(
                slot.get("modalities"),
                f"{base}.modalities",
                WORKFORCE_V1_PUBLIC_MODALITY_IDS,
                "modality_id_not_public_finite",
            )

    edges = work_order.get("edges")
    if isinstance(edges, list):
        for index, edge in enumerate(edges):
            if not isinstance(edge, Mapping):
                continue
            for field in ("from", "to"):
                if isinstance(edge.get(field), str) and edge[field] not in slot_ids:
                    add(f"edges[{index}].{field}", "unknown_slot_id")
            public_or_opaque_list(
                edge.get("artifactKinds"),
                f"edges[{index}].artifactKinds",
                WORKFORCE_V1_PUBLIC_ARTIFACT_IDS,
                "artifact_concept_not_public_finite",
            )
    return issues

# Exact finite aggregate codes emitted by the Hub workforce search boundary.
# These codes describe eligibility classes only. They must never embed a
# candidate/release identity, raw profile content, history, or a free-form
# reason supplied by an agent.
WORKFORCE_COVERAGE_GAP_CODES = (
    "gap:minimum-candidate-count",
    "gap:no-hard-eligible-candidate",
    "gap:excluded:forbidden-community",
    "gap:excluded:release-not-active",
    "gap:excluded:structural-or-security-invalid",
    "gap:excluded:release-not-routing-eligible",
    "gap:excluded:entity-kind-mismatch",
    "gap:excluded:excluded-community",
    "gap:excluded:missing-required-role",
    "gap:excluded:missing-required-skill",
    "gap:excluded:missing-required-knowledge",
    "gap:excluded:missing-required-tool",
    "gap:excluded:missing-consumed-artifact",
    "gap:excluded:missing-produced-artifact",
    "gap:excluded:missing-required-authority",
    "gap:excluded:forbidden-authority-conflict",
    "gap:excluded:candidate-prohibits-required-authority",
    "gap:excluded:runtime-mismatch",
    "gap:excluded:language-mismatch",
    "gap:excluded:modality-mismatch",
    "gap:excluded:missing-required-community",
    "gap:excluded:required-skill-evidence-below-minimum",
    "gap:excluded:required-tool-evidence-below-minimum",
    # A required term that no live profile declares cannot discriminate — it can
    # only empty the menu. Such a term is demoted to a ranking signal and
    # reported here, so a stated contract is never silently unenforced.
    # Core must know every code the Hub can emit or it discards the whole
    # candidate set; community joined the ranked-not-enforced set on 2026-07-28.
    "gap:requirement-vocabulary-unsupported:community",
    "gap:requirement-vocabulary-unsupported:role",
    "gap:requirement-vocabulary-unsupported:skill",
    "gap:requirement-vocabulary-unsupported:knowledge",
    "gap:requirement-vocabulary-unsupported:tool",
    # A candidate was dropped because it violated the portable contract itself.
    # Reported so an incomplete menu is never mistaken for an exhausted catalogue.
    "gap:candidate-contract-invalid",
    "gap:requirement-vocabulary-unsupported:consumed-artifact",
    "gap:requirement-vocabulary-unsupported:produced-artifact",
    "gap:requirement-vocabulary-unsupported:runtime",
    "gap:requirement-vocabulary-unsupported:language",
    "gap:requirement-vocabulary-unsupported:modality",
    # Authority joined the demotion set on 2026-07-30. Capability attaches to
    # the executing runtime, not the BYOM bundle, so almost no card declares
    # authorities; the Hub's old always-hard gate excluded every relevant
    # candidate and kept only the newest metadata-complete uploads (measured:
    # 2 irrelevant -> 6 relevant candidates on the same slot when lifted).
    # Real authority enforcement lives in prepare-time permission policy pins.
    # Declaring this code opts Core into the Hub's rank-and-report demotion.
    "gap:requirement-vocabulary-unsupported:authority",
)
_WORKFORCE_COVERAGE_GAP_CODE_SET = frozenset(WORKFORCE_COVERAGE_GAP_CODES)


def validate_coverage_gap_codes(value: Any) -> list[str]:
    """Validate the public finite aggregate vocabulary without reflecting data."""

    if not isinstance(value, list) or len(value) > len(WORKFORCE_COVERAGE_GAP_CODES):
        raise ValueError("candidate_set_coverage_gaps_invalid")
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str) or item not in _WORKFORCE_COVERAGE_GAP_CODE_SET or item in seen:
            # Do not echo an unknown value: it may contain a candidate identity
            # or other private text from an untrusted remote response.
            raise ValueError("candidate_set_coverage_gaps_invalid")
        seen.add(item)
        result.append(item)
    return result


def validate_candidate_set_coverage_gaps(candidate_set: Mapping[str, Any]) -> None:
    """Validate every candidate-set slot against the public finite vocabulary."""

    slots = candidate_set.get("slots") if isinstance(candidate_set, Mapping) else None
    if not isinstance(slots, list) or not slots:
        raise ValueError("candidate_set_coverage_gaps_invalid")
    for slot in slots:
        if not isinstance(slot, Mapping) or not isinstance(slot.get("slotId"), str):
            raise ValueError("candidate_set_coverage_gaps_invalid")
        validate_coverage_gap_codes(slot.get("coverageGaps"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_id(prefix: str, value: Any) -> str:
    normalized = ID_SAFE_RE.sub("-", str(value or "").strip().lower().replace("_", "-")).strip("-.")
    if not normalized:
        normalized = hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}:{normalized[:220]}"


def normalized_strings(value: Any, *, limit: int = 256) -> list[str]:
    if value is None:
        return []
    items: Iterable[Any]
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set, frozenset)):
        items = value
    else:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text[:500])
        if len(result) >= limit:
            break
    return result


def concept_ids(value: Any, prefix: str) -> list[str]:
    result: list[str] = []
    for item in normalized_strings(value):
        concept = item if ":" in item else stable_id(prefix, item)
        if concept not in result:
            result.append(concept)
    return result


def content_tokens(*values: Any) -> set[str]:
    text_parts: list[str] = []
    for value in values:
        if isinstance(value, Mapping):
            text_parts.extend(str(item) for item in value.values())
        elif isinstance(value, (list, tuple, set, frozenset)):
            text_parts.extend(str(item) for item in value)
        elif value is not None:
            text_parts.append(str(value))
    text = " ".join(text_parts).lower().replace("_", " ").replace("-", " ")
    tokens = {match.group(0) for match in TOKEN_RE.finditer(text)}
    hangul = [token for token in tokens if re.fullmatch(r"[가-힣]{2,}", token)]
    for token in hangul:
        tokens.update(token[index : index + 2] for index in range(len(token) - 1))
    return tokens


@lru_cache(maxsize=4)
def load_ontology(path: str | Path | None = None) -> dict[str, Any]:
    source = Path(path) if path else Path(__file__).with_name("ontology_v1.json")
    raw = source.read_bytes()
    data = json.loads(raw.decode("utf-8"))
    if data.get("schemaVersion") != "agentlas.workforce-ontology.v1":
        raise ValueError("unsupported workforce ontology")
    if path is None:
        observed_hash = hashlib.sha256(raw).hexdigest()
        if observed_hash != WORKFORCE_ONTOLOGY_SNAPSHOT_SHA256:
            raise ValueError("packaged workforce ontology snapshot hash mismatch")
        if data.get("ontologyVersion") != WORKFORCE_ONTOLOGY_VERSION:
            raise ValueError("packaged workforce ontology version mismatch")
    return data


def assertion_concepts(assertions: Any) -> set[str]:
    if not isinstance(assertions, list):
        return set()
    return {
        str(item.get("concept"))
        for item in assertions
        if isinstance(item, Mapping) and item.get("concept")
    }


def tool_concepts(assertions: Any) -> set[str]:
    if not isinstance(assertions, list):
        return set()
    return {
        str(item.get("capability"))
        for item in assertions
        if isinstance(item, Mapping) and item.get("capability")
    }


def verify_profile_integrity(profile: Mapping[str, Any]) -> None:
    provenance = profile.get("provenance") if isinstance(profile.get("provenance"), Mapping) else {}
    expected = canonical_digest({"semantic": profile.get("semantic"), "qualification": profile.get("qualification")})
    if provenance.get("contentDigest") != expected:
        raise ValueError("workforce profile content digest mismatch")
    package_hash = str(profile.get("packageHash") or "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", package_hash):
        raise ValueError("workforce profile package hash is invalid")
