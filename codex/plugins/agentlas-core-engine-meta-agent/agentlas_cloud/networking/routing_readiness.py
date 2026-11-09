"""Validate recorded routing readiness without requiring development tooling."""

from __future__ import annotations

from typing import Any


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def validate_benchmark_state(report: Any) -> dict[str, Any]:
    """Validate the persisted fields that make a benchmark receipt routable."""

    blockers: list[dict[str, Any]] = []
    if not isinstance(report, dict):
        return {
            "ready": False,
            "blockers": [
                {
                    "code": "benchmark_not_run",
                    "message": "benchmark receipt is missing or unreadable",
                }
            ],
        }

    suites = report.get("suites")
    if not isinstance(suites, list) or not any(isinstance(item, str) and item.strip() for item in suites):
        blockers.append({"code": "no_suites", "message": "benchmark has no loaded suites"})

    metrics = report.get("metrics")
    case_count = metrics.get("cases") if isinstance(metrics, dict) else None
    if not _is_count(case_count) or case_count == 0:
        blockers.append({"code": "no_cases", "message": "benchmark has zero runnable cases"})

    diagnostics = report.get("diagnostics")
    if not isinstance(diagnostics, dict):
        blockers.append(
            {
                "code": "identity_diagnostics_missing",
                "message": "benchmark receipt has no case-identity diagnostics; rerun the benchmark",
            }
        )
        return {"ready": False, "blockers": blockers}

    case_rows = diagnostics.get("case_rows")
    unique_cases = diagnostics.get("unique_cases")
    duplicate_cases = diagnostics.get("duplicate_case_identities")
    metrics_unique_cases = metrics.get("unique_cases") if isinstance(metrics, dict) else None
    if not _is_count(case_rows) or not _is_count(unique_cases) or not isinstance(duplicate_cases, list):
        blockers.append(
            {
                "code": "identity_diagnostics_invalid",
                "message": "benchmark case-identity diagnostics are malformed",
            }
        )
        return {"ready": False, "blockers": blockers}

    if _is_count(case_count) and case_rows != case_count:
        blockers.append(
            {
                "code": "case_count_mismatch",
                "message": "benchmark metrics and identity diagnostics disagree on case rows",
                "metrics_cases": case_count,
                "diagnostic_case_rows": case_rows,
            }
        )
    if not _is_count(metrics_unique_cases) or metrics_unique_cases != unique_cases:
        blockers.append(
            {
                "code": "unique_case_count_mismatch",
                "message": "benchmark metrics and identity diagnostics disagree on unique cases",
                "metrics_unique_cases": metrics_unique_cases,
                "diagnostic_unique_cases": unique_cases,
            }
        )
    if unique_cases > case_rows or (not duplicate_cases and unique_cases != case_rows):
        blockers.append(
            {
                "code": "identity_count_invalid",
                "message": "benchmark unique-case counts are inconsistent with duplicate diagnostics",
                "case_rows": case_rows,
                "unique_cases": unique_cases,
            }
        )
    if duplicate_cases:
        identities = sorted(
            str(item.get("identity"))
            for item in duplicate_cases
            if isinstance(item, dict) and item.get("identity") is not None
        )
        blockers.append(
            {
                "code": "duplicate_case_identities",
                "message": f"benchmark contains {len(duplicate_cases)} duplicate case identities",
                "count": len(duplicate_cases),
                "identities": identities,
            }
        )

    return {"ready": not blockers, "blockers": blockers}
