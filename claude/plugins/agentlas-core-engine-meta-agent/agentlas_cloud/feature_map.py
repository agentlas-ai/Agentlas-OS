"""Feature-intent map lookup — which feature owns an identifier, and its siblings.

The feature map is a first-class project map next to the sitemap and the code
map: one row per product feature, keyed by INTENT, with one pointer per surface
binding the exact current identifier (symbol/route/table/wire id). Agents ask
this module "what feature owns this identifier / what are its sibling surfaces"
so cross-surface work aligns by intent, not spelling.

Map locations, in resolution order for a project root:
  * ``<project>/.agentlas/feature-map.json`` — the per-project map every
    activated project gets seeded on first contact (project_bootstrap).
  * ``<project>/contracts/feature-map.json`` — the engine workspace's own map
    (Agentlas-OS keeps its instance in contracts/ because it is version-
    controlled contract material, not private local state).

Sibling ``repo`` fields resolve relative to the map's parent workspace, exactly
like scripts/verify-feature-map.py: the workspace's own directory name means
the workspace itself; anything else is ``<workspace>/../<repo>``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

FEATURE_MAP_SCHEMA = "agentlas.feature-map.v1"
MAX_MAP_BYTES = 32 * 1024 * 1024
MAX_MATCHES = 50


class FeatureMapError(RuntimeError):
    """Machine-readable feature-map failure; ``code`` is the marker."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


def locate_map(project: str | Path) -> Path | None:
    """Return the project's feature map path, or None when neither exists."""

    root = Path(project).expanduser().resolve()
    for candidate in (
        root / ".agentlas" / "feature-map.json",
        root / "contracts" / "feature-map.json",
    ):
        if candidate.is_file():
            return candidate
    return None


def workspace_root(map_path: Path) -> Path:
    """The workspace a map belongs to (mirrors scripts/verify-feature-map.py)."""

    map_path = Path(map_path).expanduser().resolve()
    if map_path.parent.name in {"contracts", ".agentlas"}:
        return map_path.parent.parent
    return map_path.parent


def resolve_repo(repo: str, workspace: Path) -> Path:
    if repo == workspace.name:
        return workspace
    if repo == "Agentlas-OS" and (workspace / "agentlas_cloud" / "feature_map.py").is_file():
        # The engine map may live in a checkout named something other than
        # Agentlas-OS; the canonical name still means "this workspace".
        return workspace
    return workspace.parent / repo


def load_map(map_path: str | Path) -> dict[str, Any]:
    path = Path(map_path).expanduser().resolve()
    if not path.is_file():
        raise FeatureMapError("feature_map_not_found", str(path))
    try:
        if path.stat().st_size > MAX_MAP_BYTES:
            raise FeatureMapError("feature_map_too_large", str(path))
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FeatureMapError("feature_map_unreadable", str(exc)) from exc
    except json.JSONDecodeError as exc:
        raise FeatureMapError("feature_map_unparseable", str(exc)) from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != FEATURE_MAP_SCHEMA:
        raise FeatureMapError("feature_map_schema_mismatch", str(path))
    if not isinstance(payload.get("features"), list):
        raise FeatureMapError("feature_map_features_invalid", str(path))
    return payload


def _surface_row(surface: dict[str, Any], workspace: Path) -> dict[str, Any]:
    repo = str(surface.get("repo") or "")
    row = {
        "repo": repo,
        "kind": surface.get("kind"),
        "path": surface.get("path"),
        "identifier": surface.get("identifier"),
        "meaning": surface.get("meaning"),
    }
    if surface.get("localOnly"):
        row["localOnly"] = True
    if repo:
        row["resolvedRepoPresent"] = resolve_repo(repo, workspace).is_dir()
    return row


def _feature_match(
    feature: dict[str, Any],
    matched_surfaces: list[dict[str, Any]],
    matched_on: str,
    workspace: Path,
) -> dict[str, Any]:
    surfaces = [s for s in feature.get("surfaces") or [] if isinstance(s, dict)]
    matched_ids = {id(s) for s in matched_surfaces}
    return {
        "featureId": feature.get("featureId"),
        "intent": feature.get("intent"),
        "ownerSurface": feature.get("ownerSurface"),
        "matchedOn": matched_on,
        "matchedSurfaces": [_surface_row(s, workspace) for s in matched_surfaces],
        "siblingSurfaces": [
            _surface_row(s, workspace) for s in surfaces if id(s) not in matched_ids
        ],
        "aliases": feature.get("aliases") or [],
    }


def lookup(
    identifier: str,
    *,
    map_path: str | Path,
) -> dict[str, Any]:
    """Which feature owns ``identifier``, and what are its sibling surfaces.

    Exact matches (surface identifier, featureId, alias name) are returned as
    ``matches``. When there is no exact match, case-insensitive substring
    matches are returned separately as ``fuzzyMatches`` — a near-name must
    never be silently presented as ownership.
    """

    query = identifier.strip()
    if not query:
        raise FeatureMapError("empty_identifier")
    path = Path(map_path).expanduser().resolve()
    payload = load_map(path)
    workspace = workspace_root(path)

    matches: list[dict[str, Any]] = []
    fuzzy: list[dict[str, Any]] = []
    lowered = query.lower()

    for feature in payload["features"]:
        if not isinstance(feature, dict):
            continue
        surfaces = [s for s in feature.get("surfaces") or [] if isinstance(s, dict)]
        exact_surfaces = [s for s in surfaces if s.get("identifier") == query]
        alias_names = [
            str(a.get("name") or "")
            for a in feature.get("aliases") or []
            if isinstance(a, dict)
        ]
        if exact_surfaces:
            matches.append(_feature_match(feature, exact_surfaces, "surface.identifier", workspace))
        elif feature.get("featureId") == query:
            matches.append(_feature_match(feature, [], "featureId", workspace))
        elif query in alias_names:
            matches.append(_feature_match(feature, [], "alias", workspace))
        else:
            near_surfaces = [
                s for s in surfaces if lowered in str(s.get("identifier") or "").lower()
            ]
            near = (
                near_surfaces
                or lowered in str(feature.get("featureId") or "").lower()
                or any(lowered in name.lower() for name in alias_names)
            )
            if near:
                fuzzy.append(
                    _feature_match(feature, near_surfaces, "substring", workspace)
                )

    return {
        "action": "feature_map.lookup",
        "schemaVersion": FEATURE_MAP_SCHEMA,
        "status": "ok",
        "identifier": query,
        "map": str(path),
        "workspace": str(workspace),
        "featureCount": len(payload["features"]),
        "matches": matches[:MAX_MATCHES],
        "fuzzyMatches": [] if matches else fuzzy[:MAX_MATCHES],
        "owned": bool(matches),
    }
