"""Concise completion status for the Agentlas Research Engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .doctor import run_research_doctor
from .proofs import run_research_proofs


def run_research_status(*, home: Path | str | None = None) -> dict[str, Any]:
    """Return a small, non-executing goal-readiness summary."""

    doctor = run_research_doctor(home=home)
    proofs = run_research_proofs(home=home, limit=3)
    doctor_completion = doctor.get("completion") if isinstance(doctor.get("completion"), dict) else {}
    proof_completion = proofs.get("completion") if isinstance(proofs.get("completion"), dict) else {}
    coverage = doctor.get("coverage") if isinstance(doctor.get("coverage"), dict) else {}
    proof_coverage = proofs.get("coverage") if isinstance(proofs.get("coverage"), dict) else {}
    requirements = _requirements(doctor, proofs)
    failed = [item["id"] for item in requirements if item["status"] == "failed"]
    incomplete = [item["id"] for item in requirements if item["status"] != "ok"]
    return {
        "schema": "agentlas.research.status.v0",
        "status": "failed" if failed else ("partial" if incomplete else "ok"),
        "goal_ready": not incomplete,
        "commands_will_run": False,
        "network_will_run": False,
        "credentials_exposed_to_model": False,
        "home": doctor.get("home") or proofs.get("home"),
        "summary": {
            "ok_count": len(requirements) - len(incomplete),
            "incomplete_count": len(incomplete),
            "core_engine_ok": _requirements_ok(requirements, CORE_REQUIREMENTS),
            "public_social_fallbacks_ok": bool(doctor_completion.get("public_social_fallbacks_ok")),
            "browser_hardpoint_ok": bool(doctor_completion.get("browser_hardpoint_ok")),
            "credentialed_social_ok": bool(doctor_completion.get("credentialed_social_ok")),
            "official_social_missing": list(coverage.get("credentialed_social_missing") or []),
            "missing_env": _missing_env(requirements),
            "missing_or_unready_proofs": list(proof_completion.get("missing_or_unready_proofs") or []),
            "stale_or_unknown_proofs": list(proof_completion.get("stale_or_unknown_proofs") or []),
        },
        "requirements": requirements,
        "next_commands": _next_commands(requirements),
        "proof_coverage": {
            "required_ok": list(proof_coverage.get("required_ok") or []),
            "required_missing": list(proof_coverage.get("required_missing") or []),
            "public_fallback_ok": list(proof_coverage.get("public_fallback_ok") or []),
            "public_fallback_missing": list(proof_coverage.get("public_fallback_missing") or []),
            "browser_hardpoint_status": proof_coverage.get("browser_hardpoint_status"),
        },
        "freshness_policy": proofs.get("freshness_policy") or doctor.get("freshness_policy") or {},
    }


CORE_REQUIREMENTS = {
    "core_registry",
    "auto_loadout_boundary",
    "browser_modularity",
    "web_search_recall",
    "evidence_quality",
}


REQUIREMENT_LABELS = {
    "core_registry": "Detachable slots registered",
    "auto_loadout_boundary": "Default loadout stays light",
    "browser_modularity": "Browser hardpoints are detached",
    "web_search_recall": "Search fanout and query variants ready",
    "evidence_quality": "Evidence quality receipts available",
    "reddit_public_fallback": "Reddit public fallback ready",
    "threads_public_fallback": "Threads public fallback ready",
    "browser_hardpoints": "Browser hardpoint live proof fresh",
    "platform.reddit.oauth": "Reddit OAuth live proof fresh",
    "platform.threads": "Threads Graph live proof fresh",
    "credential_safety": "Credentials are not exposed to model output",
}


def _requirements(doctor: dict[str, Any], proofs: dict[str, Any]) -> list[dict[str, Any]]:
    checks = {
        str(item.get("id")): item
        for item in doctor.get("checks", [])
        if isinstance(item, dict)
    }
    requirements = [_requirement_from_check(checks, check_id) for check_id in REQUIREMENT_LABELS if check_id in checks]
    credentials_safe = not bool(doctor.get("credentials_exposed_to_model")) and not bool(proofs.get("credentials_exposed_to_model"))
    requirements.append(
        {
            "id": "credential_safety",
            "label": REQUIREMENT_LABELS["credential_safety"],
            "status": "ok" if credentials_safe else "failed",
            "evidence": {
                "doctor_credentials_exposed_to_model": bool(doctor.get("credentials_exposed_to_model")),
                "proofs_credentials_exposed_to_model": bool(proofs.get("credentials_exposed_to_model")),
            },
        }
    )
    return requirements


def _requirement_from_check(checks: dict[str, dict[str, Any]], check_id: str) -> dict[str, Any]:
    check = checks.get(check_id, {})
    requirement = {
        "id": check_id,
        "label": REQUIREMENT_LABELS.get(check_id, check_id),
        "status": check.get("status") or "missing",
        "summary": check.get("summary") or "",
        "missing_proofs": list(check.get("missing_proofs") or []),
        "check_command": check.get("check_command") or "",
    }
    setup = _setup_from_check(check)
    if setup and requirement["status"] != "ok":
        requirement["setup"] = setup
    return requirement


def _requirements_ok(requirements: list[dict[str, Any]], ids: set[str]) -> bool:
    by_id = {item["id"]: item for item in requirements}
    return all(by_id.get(item_id, {}).get("status") == "ok" for item_id in ids)


def _next_commands(requirements: list[dict[str, Any]]) -> list[str]:
    return _dedupe(
        [
            str(item.get("check_command") or "")
            for item in requirements
            if item.get("status") != "ok"
        ]
    )


def _missing_env(requirements: list[dict[str, Any]]) -> list[str]:
    missing: list[str] = []
    for item in requirements:
        setup = item.get("setup")
        if isinstance(setup, dict):
            missing.extend(str(value) for value in setup.get("missing_env") or [])
    return _dedupe(missing)


def _setup_from_check(check: dict[str, Any]) -> dict[str, Any] | None:
    evidence = check.get("evidence") if isinstance(check.get("evidence"), dict) else {}
    readiness_payloads = list(_iter_readiness_payloads(evidence.get("readiness")))
    if not readiness_payloads:
        return None

    states: list[str] = []
    reasons: list[str] = []
    missing_env: list[str] = []
    present_env: list[str] = []
    requirements: list[str] = []
    accepted_env_sets: list[list[str]] = []
    missing_config = False
    for readiness in readiness_payloads:
        state = str(readiness.get("state") or "")
        reason = str(readiness.get("reason") or "")
        if state:
            states.append(state)
        if reason and reason != "no_runtime_setup_required":
            reasons.append(reason)
        if state and state != "ready":
            missing_config = True
        for item in _safe_readiness_checks(readiness):
            missing_env.extend(item["missing_env"])
            present_env.extend(item["present_env"])
            accepted_env_sets.extend(item["accepted_env_sets"])
            if item["requirement"]:
                requirements.append(item["requirement"])
            if item["status"] == "missing":
                missing_config = True

    missing_env = _dedupe(missing_env)
    if not missing_config and not missing_env:
        return None

    unique_states = _dedupe(states)
    return {
        "state": unique_states[0] if len(unique_states) == 1 else "mixed",
        "reason": "; ".join(_dedupe(reasons)),
        "missing_env": missing_env,
        "present_env": _dedupe(present_env),
        "requirements": _dedupe(requirements),
        "accepted_env_sets": _dedupe_env_sets(accepted_env_sets),
        "check_command": check.get("check_command") or "",
        "config_missing": bool(missing_config or missing_env),
        "secret_values_exposed": False,
    }


def _iter_readiness_payloads(value: Any):
    if not isinstance(value, dict):
        return
    if "state" in value or "checks" in value:
        yield value
        return
    for nested in value.values():
        if isinstance(nested, dict):
            yield from _iter_readiness_payloads(nested)


def _safe_readiness_checks(readiness: dict[str, Any]) -> list[dict[str, Any]]:
    checks = readiness.get("checks")
    if not isinstance(checks, list):
        return []
    safe: list[dict[str, Any]] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        safe.append(
            {
                "kind": str(check.get("kind") or ""),
                "requirement": str(check.get("requirement") or ""),
                "status": str(check.get("status") or ""),
                "missing_env": [str(value) for value in check.get("missing_env") or []],
                "present_env": [str(value) for value in check.get("present_env") or []],
                "accepted_env_sets": [
                    [str(value) for value in group]
                    for group in check.get("accepted_env_sets") or []
                    if isinstance(group, list)
                ],
            }
        )
    return safe


def _dedupe_env_sets(values: list[list[str]]) -> list[list[str]]:
    seen: set[tuple[str, ...]] = set()
    out: list[list[str]] = []
    for value in values:
        item = tuple(value)
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(list(item))
    return out


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
