"""Idempotent lifecycle projection for immutable Agent releases."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable, Mapping

from .contracts import canonical_digest, verify_profile_integrity


EVENT_TYPES = {
    "definition.created",
    "release.published",
    "release.superseded",
    "release.withdrawn",
    "release.restored",
    "release.deleted",
    "ontology.version.published",
    "projection.rebuilt",
}


class WorkforceProjection:
    def __init__(self, *, ontology_version: str = "awo:2026-07-15.1") -> None:
        self.ontology_version = ontology_version
        self.definitions: set[str] = set()
        self.profiles: dict[str, dict[str, Any]] = {}
        self.active_heads: dict[str, str] = {}
        self.tombstones: dict[str, dict[str, Any]] = {}
        self.events: dict[str, dict[str, Any]] = {}
        self.last_sequence = 0

    def apply(self, event: Mapping[str, Any]) -> dict[str, Any]:
        event_id = str(event.get("eventId") or "")
        if not event_id:
            raise ValueError("eventId is required")
        if event_id in self.events:
            return {"status": "idempotent", "eventId": event_id, "projectionDigest": self.digest()}
        event_type = str(event.get("eventType") or "")
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unsupported eventType: {event_type}")
        sequence = int(event.get("sequence") or 0)
        if sequence <= self.last_sequence:
            raise ValueError("event sequence must be strictly increasing")
        definition_id = str(event.get("definitionId") or "")
        release_id = str(event.get("releaseId") or "")
        payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}

        if event_type == "definition.created":
            if not definition_id:
                raise ValueError("definition.created requires definitionId")
            self.definitions.add(definition_id)
        elif event_type == "release.published":
            profile = payload.get("profile") if isinstance(payload.get("profile"), Mapping) else None
            if not definition_id or not release_id or not profile:
                raise ValueError("release.published requires definitionId, releaseId and profile")
            if str(profile.get("agentDefinitionId")) != definition_id or str(profile.get("agentReleaseId")) != release_id:
                raise ValueError("published profile identity mismatch")
            verify_profile_integrity(profile)
            self.definitions.add(definition_id)
            previous = str(payload.get("supersedes") or self.active_heads.get(definition_id) or "")
            if previous and previous != release_id and previous in self.profiles:
                self.profiles[previous]["status"] = "superseded"
            stored = deepcopy(dict(profile))
            stored["status"] = "active"
            self.profiles[release_id] = stored
            self.active_heads[definition_id] = release_id
            self.tombstones.pop(release_id, None)
        elif event_type == "release.superseded":
            if release_id not in self.profiles:
                raise ValueError("unknown release")
            self.profiles[release_id]["status"] = "superseded"
            if self.active_heads.get(definition_id) == release_id:
                self.active_heads.pop(definition_id, None)
        elif event_type == "release.withdrawn":
            if release_id not in self.profiles:
                raise ValueError("unknown release")
            self.profiles[release_id]["status"] = "withdrawn"
            if self.active_heads.get(definition_id) == release_id:
                self.active_heads.pop(definition_id, None)
        elif event_type == "release.restored":
            if release_id not in self.profiles:
                raise ValueError("unknown release")
            current = self.active_heads.get(definition_id)
            if current and current != release_id and current in self.profiles:
                self.profiles[current]["status"] = "superseded"
            self.profiles[release_id]["status"] = "active"
            self.active_heads[definition_id] = release_id
            self.tombstones.pop(release_id, None)
        elif event_type == "release.deleted":
            if release_id not in self.profiles:
                raise ValueError("unknown release")
            self.profiles[release_id]["status"] = "deleted"
            self.tombstones[release_id] = {
                "definitionId": definition_id,
                "releaseId": release_id,
                "eventId": event_id,
                "sourceDigest": event.get("sourceDigest"),
            }
            if self.active_heads.get(definition_id) == release_id:
                self.active_heads.pop(definition_id, None)
        elif event_type == "ontology.version.published":
            version = str(payload.get("ontologyVersion") or "")
            if not version:
                raise ValueError("ontology.version.published requires ontologyVersion")
            self.ontology_version = version
        elif event_type == "projection.rebuilt":
            expected = payload.get("expectedDigest")
            if expected and expected != self.digest():
                raise ValueError("projection rebuild digest mismatch")

        self.events[event_id] = deepcopy(dict(event))
        self.last_sequence = sequence
        return {"status": "applied", "eventId": event_id, "projectionDigest": self.digest()}

    def active_profiles(self) -> list[dict[str, Any]]:
        return [deepcopy(self.profiles[release_id]) for release_id in sorted(self.active_heads.values())]

    def snapshot(self) -> dict[str, Any]:
        return {
            "ontologyVersion": self.ontology_version,
            "definitions": sorted(self.definitions),
            "activeHeads": dict(sorted(self.active_heads.items())),
            "profiles": {release_id: self.profiles[release_id] for release_id in sorted(self.profiles)},
            "tombstones": {release_id: self.tombstones[release_id] for release_id in sorted(self.tombstones)},
            "lastSequence": self.last_sequence,
        }

    def digest(self) -> str:
        return canonical_digest(self.snapshot())


def replay_events(events: Iterable[Mapping[str, Any]], *, ontology_version: str = "awo:2026-07-15.1") -> WorkforceProjection:
    projection = WorkforceProjection(ontology_version=ontology_version)
    ordered = sorted((dict(event) for event in events), key=lambda item: int(item.get("sequence") or 0))
    for event in ordered:
        projection.apply(event)
    return projection


__all__ = ["EVENT_TYPES", "WorkforceProjection", "replay_events"]
