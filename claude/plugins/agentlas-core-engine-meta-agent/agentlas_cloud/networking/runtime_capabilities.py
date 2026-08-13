"""Provider-opaque Runtime Fabric capability descriptors.

The host runtime owns the truth about its native features. Core only consumes a
bounded descriptor and never treats a model/provider name as a capability. An
invalid or absent descriptor is therefore represented as unknown and does not
block native execution.
"""

from __future__ import annotations

import re
from typing import Any, Mapping


SCHEMA_VERSION = "agentlas.runtime-fabric-capability-descriptor.v1"
PLANE_NAMES = ("behavior", "tools", "observation", "control", "ui", "telemetry")
PLANE_STATUSES = {"declared", "installed", "observed", "unknown"}
SOURCE_KINDS = {"host-declared", "acp-initialize", "agentlas-observed", "absent"}
SOURCE_TRUST = {"unknown", "declared", "observed"}
RUNTIME_TRANSPORTS = {"native", "acp", "stdio", "websocket", "desktop-bridge", "unknown"}
RUNTIME_KIND_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
FEATURE_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
CONTROL_RE = re.compile(r"[\x00-\x1f]")


def _unknown_plane() -> dict[str, Any]:
    return {"status": "unknown", "native": False, "features": []}


def _safe_string(value: Any, *, max_length: int) -> str | None:
    if not isinstance(value, str) or not value or len(value) > max_length or CONTROL_RE.search(value):
        return None
    return value


def _normalize_plane(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return _unknown_plane()
    status = str(value.get("status") or "unknown").lower()
    if status not in PLANE_STATUSES:
        return _unknown_plane()
    native = value.get("native")
    if not isinstance(native, bool):
        return _unknown_plane()
    features: list[str] = []
    seen: set[str] = set()
    raw_features = value.get("features")
    if isinstance(raw_features, list):
        for raw in raw_features[:64]:
            if not isinstance(raw, str):
                continue
            feature = raw.strip().lower()
            if FEATURE_RE.fullmatch(feature) and feature not in seen:
                seen.add(feature)
                features.append(feature)
    notes: list[str] = []
    raw_notes = value.get("notes")
    if isinstance(raw_notes, list):
        for raw in raw_notes[:8]:
            note = _safe_string(raw, max_length=240)
            if note is not None:
                notes.append(note)
    return {
        "status": status,
        "native": native,
        "features": features,
        **({"notes": notes} if notes else {}),
    }


def unknown_runtime_capability_descriptor(
    *,
    runtime_kind: str = "unknown",
    descriptor_id: str = "runtime:unknown",
) -> dict[str, Any]:
    """Return a non-blocking descriptor for an unreported host."""

    runtime = runtime_kind.strip().lower()
    if not RUNTIME_KIND_RE.fullmatch(runtime):
        runtime = "unknown"
    safe_id = descriptor_id if IDENTIFIER_RE.fullmatch(descriptor_id) else "runtime:unknown"
    return {
        "schemaVersion": SCHEMA_VERSION,
        "descriptorId": safe_id,
        "runtime": {"kind": runtime, "transport": "unknown"},
        "planes": {name: _unknown_plane() for name in PLANE_NAMES},
        "source": {"kind": "absent", "trust": "unknown"},
        "compatibility": {
            "nativePreserved": True,
            "hotPathUnblocked": True,
            "localFallback": True,
        },
    }


def normalize_runtime_capability_descriptor(
    raw: Any,
    *,
    runtime_kind: str = "unknown",
    descriptor_id: str | None = None,
) -> dict[str, Any]:
    """Normalize a host descriptor without granting authority or blocking work."""

    if not isinstance(raw, Mapping):
        return unknown_runtime_capability_descriptor(
            runtime_kind=runtime_kind,
            descriptor_id=descriptor_id or f"runtime:{runtime_kind or 'unknown'}",
        )
    runtime = raw.get("runtime") if isinstance(raw.get("runtime"), Mapping) else {}
    kind = str(runtime.get("kind") or runtime_kind or "unknown").strip().lower()
    if not RUNTIME_KIND_RE.fullmatch(kind):
        kind = "unknown"
    raw_id = str(raw.get("descriptorId") or descriptor_id or f"runtime:{kind}")
    safe_id = raw_id if IDENTIFIER_RE.fullmatch(raw_id) else f"runtime:{kind}"
    source = raw.get("source") if isinstance(raw.get("source"), Mapping) else {}
    source_kind = str(source.get("kind") or "absent")
    source_trust = str(source.get("trust") or "unknown")
    if source_kind not in SOURCE_KINDS or source_trust not in SOURCE_TRUST:
        source_kind, source_trust = "absent", "unknown"
    compatibility = raw.get("compatibility") if isinstance(raw.get("compatibility"), Mapping) else {}
    return {
        "schemaVersion": SCHEMA_VERSION,
        "descriptorId": safe_id,
        "runtime": {
            "kind": kind,
            **(
                {"version": _safe_string(runtime.get("version"), max_length=160)}
                if _safe_string(runtime.get("version"), max_length=160) is not None
                else {}
            ),
            "transport": str(runtime.get("transport") or "unknown")
            if str(runtime.get("transport") or "unknown") in {"native", "acp", "stdio", "websocket", "desktop-bridge", "unknown"}
            else "unknown",
        },
        "planes": {
            name: _normalize_plane((raw.get("planes") or {}).get(name))
            if isinstance(raw.get("planes"), Mapping)
            else _unknown_plane()
            for name in PLANE_NAMES
        },
        "source": {"kind": source_kind, "trust": source_trust},
        "compatibility": {
            "nativePreserved": compatibility.get("nativePreserved") is True,
            "hotPathUnblocked": compatibility.get("hotPathUnblocked") is True,
            "localFallback": compatibility.get("localFallback") is True,
        },
    }


def validate_runtime_capability_descriptor(value: Any) -> list[str]:
    """Validate the strict semantic contract without requiring jsonschema."""

    issues: list[str] = []
    if not isinstance(value, Mapping):
        return ["descriptor must be an object"]
    required = {"schemaVersion", "descriptorId", "runtime", "planes", "source", "compatibility"}
    extra = set(value) - required
    missing = required - set(value)
    if extra:
        issues.append(f"unsupported fields: {sorted(extra)}")
    if missing:
        issues.append(f"missing fields: {sorted(missing)}")
    if value.get("schemaVersion") != SCHEMA_VERSION:
        issues.append("schemaVersion is unsupported")
    descriptor_id = value.get("descriptorId")
    if not isinstance(descriptor_id, str) or not IDENTIFIER_RE.fullmatch(descriptor_id):
        issues.append("descriptorId is invalid")
    runtime = value.get("runtime")
    if not isinstance(runtime, Mapping):
        issues.append("runtime must be an object")
    else:
        unsupported_runtime = set(runtime) - {"kind", "version", "transport"}
        if unsupported_runtime:
            issues.append(f"runtime has unsupported fields: {sorted(unsupported_runtime)}")
        if not RUNTIME_KIND_RE.fullmatch(str(runtime.get("kind") or "")):
            issues.append("runtime.kind is invalid")
        if "version" in runtime and _safe_string(runtime.get("version"), max_length=160) is None:
            issues.append("runtime.version is invalid")
        if "transport" in runtime and runtime.get("transport") not in RUNTIME_TRANSPORTS:
            issues.append("runtime.transport is invalid")
    planes = value.get("planes")
    if not isinstance(planes, Mapping):
        issues.append("planes must be an object")
    else:
        if set(planes) != set(PLANE_NAMES):
            issues.append("planes must contain exactly the six declared planes")
        for name in PLANE_NAMES:
            plane = planes.get(name)
            if not isinstance(plane, Mapping):
                issues.append(f"planes.{name} must be an object")
                continue
            unsupported_plane = set(plane) - {"status", "native", "features", "notes"}
            if unsupported_plane:
                issues.append(f"planes.{name} has unsupported fields: {sorted(unsupported_plane)}")
            if plane.get("status") not in PLANE_STATUSES:
                issues.append(f"planes.{name}.status is invalid")
            if not isinstance(plane.get("native"), bool):
                issues.append(f"planes.{name}.native must be boolean")
            features = plane.get("features")
            if not isinstance(features, list) or len(features) > 64:
                issues.append(f"planes.{name}.features is invalid")
            else:
                if any(not isinstance(feature, str) or not FEATURE_RE.fullmatch(feature) for feature in features):
                    issues.append(f"planes.{name}.features contains an invalid feature")
                elif len(set(features)) != len(features):
                    issues.append(f"planes.{name}.features contains duplicates")
            if "notes" in plane:
                notes = plane.get("notes")
                if (
                    not isinstance(notes, list)
                    or len(notes) > 8
                    or any(_safe_string(note, max_length=240) is None for note in notes)
                ):
                    issues.append(f"planes.{name}.notes is invalid")
    source = value.get("source")
    if (
        not isinstance(source, Mapping)
        or set(source) - {"kind", "trust"}
        or source.get("kind") not in SOURCE_KINDS
        or source.get("trust") not in SOURCE_TRUST
    ):
        issues.append("source is invalid")
    compatibility = value.get("compatibility")
    if (
        not isinstance(compatibility, Mapping)
        or set(compatibility) != {"nativePreserved", "hotPathUnblocked", "localFallback"}
        or not all(isinstance(compatibility.get(key), bool) for key in ("nativePreserved", "hotPathUnblocked", "localFallback"))
    ):
        issues.append("compatibility is invalid")
    return issues


def descriptor_from_session(raw: Any, session_id: str) -> dict[str, Any]:
    """Read an optional host descriptor; malformed input becomes unknown."""

    supplied = raw.get("capability_descriptor") if isinstance(raw, Mapping) else None
    descriptor = normalize_runtime_capability_descriptor(
        supplied,
        runtime_kind=(str(raw.get("family") or raw.get("provider") or "unknown") if isinstance(raw, Mapping) else "unknown"),
        descriptor_id=f"session:{session_id}",
    )
    if supplied is not None and validate_runtime_capability_descriptor(supplied):
        return unknown_runtime_capability_descriptor(
            runtime_kind=descriptor["runtime"]["kind"],
            descriptor_id=f"session:{session_id}",
        )
    return descriptor


__all__ = [
    "PLANE_NAMES",
    "SCHEMA_VERSION",
    "descriptor_from_session",
    "normalize_runtime_capability_descriptor",
    "unknown_runtime_capability_descriptor",
    "validate_runtime_capability_descriptor",
]
