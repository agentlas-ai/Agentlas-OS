"""Memory and playbook control-plane helpers for Network receipts."""

from __future__ import annotations

from typing import Any


def default_playbook_registry() -> dict[str, Any]:
    return {
        "schemaVersion": "2.0",
        "mode": "memory_playbook_control_plane",
        "write_policy": "candidate_first",
        "scopes": ["session", "project", "agent_repo", "team_memory", "user_global"],
        "promotion": {
            "default": "candidate_only",
            "global_requires": ["memory_curator", "policy_gate_or_pm_soul"],
            "forbidden": ["raw_prompts", "secrets", "private_paths", "full_transcripts"],
        },
        "note": "Operational memory and reusable playbooks are proposed by routed agents and promoted by local owners; Hub agents never write durable/global memory directly.",
    }


def build_memory_playbook_context(
    *,
    action: str,
    query_tokens: list[str],
    task_force: dict[str, Any] | None = None,
    policy_decision: dict[str, Any] | None = None,
) -> dict[str, Any]:
    tokens = {str(token).lower() for token in query_tokens}
    candidates: list[dict[str, Any]] = []
    applied: list[str] = []

    if action == "pipeline" or (task_force or {}).get("temporary_tf"):
        candidates.append(
            {
                "kind": "routing_playbook_candidate",
                "id": "candidate:temporary-task-force",
                "summary": "Reuse the staged TF shape when a later task has similar stage and artifact requirements.",
                "scope": "team_memory",
                "status": "candidate_only",
            }
        )

    if action == "hub_candidates":
        candidates.append(
            {
                "kind": "agent_performance_candidate",
                "id": "candidate:hub-selection-pattern",
                "summary": "Track which Hub candidates were selected and whether they completed the task before promoting routing memory.",
                "scope": "user_global",
                "status": "candidate_only",
            }
        )

    if {"release", "릴리즈", "deploy", "배포"} & tokens:
        applied.append("release_final_gate_playbook")
        candidates.append(
            {
                "kind": "playbook_candidate",
                "id": "candidate:release-end-to-end",
                "summary": "Release work should keep docs, tests, changelog, version sync, and smoke proof tied to one receipt.",
                "scope": "project",
                "status": "candidate_only",
            }
        )

    return {
        "mode": "memory_playbook_control_plane",
        "write_policy": "candidate_first",
        "applied": applied,
        "candidates": candidates,
        "durable_write": "blocked_for_router",
        "promotion": "curator_or_pm_soul_after_evidence",
        "policy_decision": (policy_decision or {}).get("decision", "allow"),
    }
