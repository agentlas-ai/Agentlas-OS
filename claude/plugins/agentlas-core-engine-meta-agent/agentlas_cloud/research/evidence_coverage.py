"""Evidence coverage summaries for research receipts."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from .contracts import ResearchAttempt, ResearchResult


OFFICIAL_SOCIAL_LIMITS = {"official_api", "reddit_oauth"}
PUBLIC_SOCIAL_FALLBACK_LIMITS = {
    "public_json_fallback",
    "public_rss_fallback",
    "public_html_fallback",
}
SOCIAL_PLATFORMS = {"reddit", "threads"}


def analyze_evidence_coverage(
    results: list[ResearchResult],
    *,
    attempts: list[ResearchAttempt],
    browser_execution: dict[str, object],
) -> dict[str, Any]:
    """Summarize what kind of evidence was actually collected."""

    usable = [result for result in results if result.confidence != "blocked"]
    search_results = [result for result in usable if result.platform == "web_search"]
    direct_reads = [result for result in usable if result.platform != "web_search"]
    official_social = [result for result in usable if _is_official_social_result(result)]
    public_social = [result for result in usable if _is_public_social_result(result)]
    public_social_platforms = sorted(
        {
            platform
            for result in usable
            for platform in _public_social_platforms_for_result(result)
        }
    )
    browser_evidence = bool(browser_execution.get("succeeded")) or any(result.platform == "browser" for result in usable)
    missing = _missing_official_social(results=usable, attempts=attempts)
    warnings = _warnings(
        search_only=bool(search_results and not direct_reads and not browser_evidence),
        public_social_fallback=bool(public_social),
        missing_credentials=missing,
        browser_execution=browser_execution,
    )

    return {
        "schema": "agentlas.research.evidence_coverage.v0",
        "status": _coverage_status(
            usable_count=len(usable),
            search_evidence=bool(search_results),
            direct_read_evidence=bool(direct_reads),
            official_social_evidence=bool(official_social),
            public_social_fallback_evidence=bool(public_social_platforms),
            browser_evidence=browser_evidence,
        ),
        "result_count": len(results),
        "usable_result_count": len(usable),
        "search_evidence": bool(search_results),
        "direct_read_evidence": bool(direct_reads),
        "search_only": bool(search_results and not direct_reads and not browser_evidence),
        "official_social_evidence": bool(official_social),
        "public_social_fallback_evidence": bool(public_social_platforms),
        "browser_evidence": browser_evidence,
        "social_platforms": sorted(
            {result.platform for result in usable if result.platform in SOCIAL_PLATFORMS}.union(public_social_platforms)
        ),
        "public_social_fallback_platforms": public_social_platforms,
        "official_social_modules_missing": missing["modules"],
        "missing_credentials": missing["credentials"],
        "completion_blockers": missing["proofs"],
        "warnings": warnings,
    }


def _is_official_social_result(result: ResearchResult) -> bool:
    return result.platform in SOCIAL_PLATFORMS and bool(OFFICIAL_SOCIAL_LIMITS.intersection(result.limits))


def _is_public_social_result(result: ResearchResult) -> bool:
    return result.platform in SOCIAL_PLATFORMS and bool(PUBLIC_SOCIAL_FALLBACK_LIMITS.intersection(result.limits))


def _public_social_platforms_for_result(result: ResearchResult) -> list[str]:
    platforms: list[str] = []
    if _is_public_social_result(result):
        platforms.append(result.platform)
    if result.platform == "web_search":
        for citation in result.citations or [{"url": result.url}]:
            host = _host(str(citation.get("url") or ""))
            if _is_threads_host(host):
                platforms.append("threads")
            elif _is_reddit_host(host):
                platforms.append("reddit")
    return _dedupe(platforms)


def _coverage_status(
    *,
    usable_count: int,
    search_evidence: bool,
    direct_read_evidence: bool,
    official_social_evidence: bool,
    public_social_fallback_evidence: bool,
    browser_evidence: bool,
) -> str:
    if usable_count <= 0 and not browser_evidence:
        return "missing"
    if search_evidence and not direct_read_evidence and not browser_evidence:
        return "search_only"
    if official_social_evidence and public_social_fallback_evidence:
        return "mixed_social"
    if official_social_evidence:
        return "official_social"
    if public_social_fallback_evidence:
        return "public_social_fallback"
    if browser_evidence:
        return "browser_backed"
    if direct_read_evidence and search_evidence:
        return "direct_plus_search"
    if direct_read_evidence:
        return "direct_read"
    return "missing"


def _missing_official_social(*, results: list[ResearchResult], attempts: list[ResearchAttempt]) -> dict[str, list[str]]:
    missing = _missing_credentials_from_attempts(attempts)
    official_platforms = {
        result.platform
        for result in results
        if _is_official_social_result(result)
    }
    for result in results:
        if not _is_public_social_result(result) or result.platform in official_platforms:
            continue
        if result.platform == "reddit" and ("oauth_preferred" in result.limits or "public_json_fallback" in result.limits or "public_rss_fallback" in result.limits):
            missing["modules"].append("platform.reddit.oauth")
            missing["credentials"].extend(["AGENTLAS_REDDIT_BEARER_TOKEN", "REDDIT_BEARER_TOKEN"])
            missing["proofs"].append("reddit_oauth_live_check")
        elif result.platform == "threads" and ("official_api_preferred" in result.limits or "public_html_fallback" in result.limits):
            missing["modules"].append("platform.threads")
            missing["credentials"].extend(["AGENTLAS_THREADS_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN"])
            missing["proofs"].append("threads_live_graph_check")
    return {
        "modules": _ordered(
            missing["modules"],
            ["platform.reddit.oauth", "platform.threads"],
        ),
        "credentials": _ordered(
            missing["credentials"],
            [
                "AGENTLAS_REDDIT_BEARER_TOKEN",
                "REDDIT_BEARER_TOKEN",
                "AGENTLAS_THREADS_ACCESS_TOKEN",
                "THREADS_ACCESS_TOKEN",
            ],
        ),
        "proofs": _ordered(
            missing["proofs"],
            ["reddit_oauth_live_check", "threads_live_graph_check"],
        ),
    }


def _missing_credentials_from_attempts(attempts: list[ResearchAttempt]) -> dict[str, list[str]]:
    modules: list[str] = []
    credentials: list[str] = []
    proofs: list[str] = []
    for attempt in attempts:
        if (
            attempt.module == "platform.reddit.oauth"
            and attempt.status == "module_unavailable"
            and (
                "REDDIT_BEARER_TOKEN not configured" in attempt.reason
                or "reddit_oauth_credentials_not_configured" in attempt.reason
            )
        ):
            modules.append("platform.reddit.oauth")
            credentials.extend(["AGENTLAS_REDDIT_BEARER_TOKEN", "REDDIT_BEARER_TOKEN"])
            proofs.append("reddit_oauth_live_check")
        elif attempt.module == "platform.reddit" and attempt.status in {"blocked", "error"}:
            modules.append("platform.reddit.oauth")
            credentials.extend(["AGENTLAS_REDDIT_BEARER_TOKEN", "REDDIT_BEARER_TOKEN"])
            proofs.append("reddit_oauth_live_check")
        elif (
            attempt.module == "platform.threads"
            and attempt.status == "module_unavailable"
            and "THREADS_ACCESS_TOKEN not configured" in attempt.reason
        ):
            modules.append("platform.threads")
            credentials.extend(["AGENTLAS_THREADS_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN"])
            proofs.append("threads_live_graph_check")
        elif attempt.module == "platform.threads.public" and attempt.status in {"blocked", "error"}:
            modules.append("platform.threads")
            credentials.extend(["AGENTLAS_THREADS_ACCESS_TOKEN", "THREADS_ACCESS_TOKEN"])
            proofs.append("threads_live_graph_check")
    return {
        "modules": _dedupe(modules),
        "credentials": _dedupe(credentials),
        "proofs": _dedupe(proofs),
    }


def _warnings(
    *,
    search_only: bool,
    public_social_fallback: bool,
    missing_credentials: dict[str, list[str]],
    browser_execution: dict[str, object],
) -> list[str]:
    warnings: list[str] = []
    if search_only:
        warnings.append("search_snippets_need_followup")
    if "platform.reddit.oauth" in missing_credentials["modules"]:
        warnings.append("official_reddit_missing")
    if "platform.threads" in missing_credentials["modules"]:
        warnings.append("official_threads_missing")
    if public_social_fallback and missing_credentials["modules"]:
        warnings.append("public_social_fallback_not_official")
    browser_status = str(browser_execution.get("status") or "")
    if browser_status in {"unavailable", "blocked_by_policy", "failed"}:
        warnings.append(f"browser_{browser_status}")
    return _dedupe(warnings)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _ordered(values: list[str], preferred: list[str]) -> list[str]:
    unique = _dedupe(values)
    preferred_index = {value: index for index, value in enumerate(preferred)}
    return sorted(unique, key=lambda value: (preferred_index.get(value, len(preferred)), value))


def _host(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _is_threads_host(host: str) -> bool:
    host = host[4:] if host.startswith("www.") else host
    return host in {"threads.com", "threads.net"} or host.endswith(".threads.com") or host.endswith(".threads.net")


def _is_reddit_host(host: str) -> bool:
    host = host[4:] if host.startswith("www.") else host
    return host in {"reddit.com", "old.reddit.com"} or host.endswith(".reddit.com")
