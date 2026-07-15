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
    data = json.loads(source.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != "agentlas.workforce-ontology.v1":
        raise ValueError("unsupported workforce ontology")
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
