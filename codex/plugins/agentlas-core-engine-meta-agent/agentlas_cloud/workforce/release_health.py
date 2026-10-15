"""Say what is wrong with a local agent that cannot be called, and how to fix it.

``LocalWorkforceRegistry.runtime_bundle`` refuses with a bare code
(``local_runtime_bundle_snapshot_drift``). The host was handed that token and no
way out, so a broken agent ended the task where a repair, or another agent,
would have finished it.

This module turns each code into a machine-readable repair plan. It decides
nothing semantic and it never swaps an agent: a prepared execution is pinned to
one immutable release, so a repair produces a NEW release the host must select
again (``reselectionRequired``), exactly like any other substitution.

Actions, in the order a host should try them:

- ``refresh_from_source``: the registered source folder still exists, so
  re-import it as a new release (``workforce local-repair-release``).
- ``reinstall``: the folder is gone and the snapshot is damaged; restore the
  package from Agent Cloud or the Hub, or rebuild it, then register it again.
- ``unregister``: nothing can be recovered; remove the registration so it stops
  appearing in menus (``workforce local-remove``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

# code -> (what is wrong, whether re-importing the source can fix it)
_CODES: dict[str, tuple[str, bool]] = {
    "local_release_not_found": ("the stored release is missing or unreadable", True),
    "local_runtime_bundle_identity_mismatch": ("the stored release no longer matches its registration", True),
    "local_runtime_bundle_snapshot_drift": ("the stored package copy changed after it was registered", True),
    "local_runtime_bundle_entrypoint_invalid": ("the package entry file is missing or unsafe", True),
    "local_runtime_bundle_manifest_invalid": ("the package manifest is not valid JSON", True),
    "generated_memory_not_package_declaration": ("the entry file holds generated memory, not the package's own instructions", True),
}


def known_code(code: str) -> bool:
    return code in _CODES


def diagnose(registry: Any, release_id: str, code: str) -> dict[str, Any]:
    """Return the repair plan for a failed release; never raises and never writes."""

    meaning, refreshable = _CODES.get(code, ("the local agent could not be loaded", False))
    record = next(
        (row for row in registry._records() if row.get("currentReleaseId") == release_id),
        None,
    )
    source_root = str((record or {}).get("sourceRoot") or "")
    source_present = bool(source_root) and Path(source_root).expanduser().is_dir()
    definition_id = str((record or {}).get("agentDefinitionId") or "")

    actions: list[dict[str, Any]] = []
    if refreshable and source_present:
        actions.append(
            {
                "action": "refresh_from_source",
                "available": True,
                "command": f"hephaestus workforce local-repair-release {definition_id}",
                "effect": "rebuilds the stored copy from the source folder; if the source changed since registration the agent becomes a new release and must be selected again",
            }
        )
    actions.append(
        {
            "action": "reinstall",
            "available": True,
            "effect": "restore the package from Agent Cloud or the Hub, or rebuild it, then register it again",
        }
    )
    if definition_id:
        actions.append(
            {
                "action": "unregister",
                "available": True,
                "command": f"hephaestus workforce local-remove {definition_id}",
                "effect": "removes the registration so it stops appearing in menus",
            }
        )
    return {
        "brokenReason": code,
        "meaning": meaning,
        "sourcePresent": source_present,
        "agentDefinitionId": definition_id or None,
        "repair": actions,
        "reselectionRequired": True,
    }


def repair_release(registry: Any, target: str) -> dict[str, Any]:
    """Re-import the source of a registered local agent as a new release.

    ``target`` is a definition id or a source folder. Nothing is removed and the
    old release is kept by the registry's own rule, so a failed repair loses
    nothing. A successful repair changes the release id, so the caller must
    select the agent again.
    """

    record = registry._find(target)
    if record is None:
        return {"status": "not_registered", "target": str(target)}
    source_root = str(record.get("sourceRoot") or "")
    if not source_root or not Path(source_root).expanduser().is_dir():
        return {
            "status": "source_missing",
            "agentDefinitionId": record.get("agentDefinitionId"),
            "sourceRoot": source_root,
            "repair": [
                {"action": "reinstall", "available": True},
                {"action": "unregister", "available": True, "command": f"hephaestus workforce local-remove {record.get('agentDefinitionId')}"},
            ],
        }
    before = str(record.get("currentReleaseId") or "")
    was_loadable = _loadable(registry, before)
    # The release id comes from the package hash, so an unchanged source maps to
    # the same release; the stored copy must be rebuilt, not replayed.
    outcome = registry.register(
        source_root,
        managed_by=str(record.get("managedBy") or "explicit"),
        force_restage=True,
    )
    after = (registry._find(target) or {}).get("currentReleaseId")
    if outcome.get("status") == "quarantined":
        return {
            "status": "refused",
            "agentDefinitionId": record.get("agentDefinitionId"),
            **{key: outcome[key] for key in ("reasonCode", "message", "remediation") if key in outcome},
        }
    now_loadable = bool(after) and _loadable(registry, str(after))
    if not now_loadable:
        return {"status": "still_broken", "agentDefinitionId": record.get("agentDefinitionId"), "currentReleaseId": after}
    return {
        "status": "unchanged" if was_loadable and after == before else "repaired",
        "agentDefinitionId": record.get("agentDefinitionId"),
        "previousReleaseId": before,
        "currentReleaseId": after,
        "reselectionRequired": bool(after and after != before),
    }


def _loadable(registry: Any, release_id: str) -> bool:
    try:
        registry.runtime_bundle(release_id)
    except (KeyError, OSError, ValueError):
        return False
    return True
