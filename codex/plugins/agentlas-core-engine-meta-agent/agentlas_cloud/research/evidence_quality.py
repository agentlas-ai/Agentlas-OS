"""Evidence quality scoring for bounded research receipts."""

from __future__ import annotations

from collections import Counter
from typing import Any
from urllib.parse import urlsplit

from .contracts import ResearchAttempt, ResearchResult


CODE_HOSTS = {"github.com", "gitlab.com", "bitbucket.org"}
COMMUNITY_HOSTS = {"reddit.com", "old.reddit.com", "www.reddit.com", "news.ycombinator.com", "stackoverflow.com"}
NEWS_DOMAINS = {"reuters.com", "apnews.com", "bloomberg.com", "ft.com", "nytimes.com", "wsj.com"}
OFFICIAL_HINTS = ("docs.", "developer.", "developers.", "dev.", "learn.", "support.", "help.")
OFFICIAL_PATH_HINTS = ("/docs", "/documentation", "/developers", "/developer")


def analyze_evidence_quality(
    results: list[ResearchResult],
    *,
    attempts: list[ResearchAttempt],
) -> dict[str, Any]:
    """Classify result quality without fetching any additional sources."""

    usable = [result for result in results if result.confidence != "blocked"]
    blocked = [result for result in results if result.confidence == "blocked"]
    search_results = [result for result in usable if result.platform == "web_search"]
    direct_reads = [result for result in usable if result.platform not in {"web_search"}]
    class_counts: Counter[str] = Counter()
    platform_counts: Counter[str] = Counter()
    for result in usable:
        platform_counts[result.platform] += 1
        for evidence_class in _classes_for_result(result):
            class_counts[evidence_class] += 1

    score = _score(
        usable_count=len(usable),
        direct_read_count=len(direct_reads),
        search_result_count=len(search_results),
        blocked_count=len(blocked),
        class_counts=class_counts,
        attempts=attempts,
    )
    return {
        "schema": "agentlas.research.evidence_quality.v0",
        "status": _quality_status(
            score,
            usable_count=len(usable),
            direct_read_count=len(direct_reads),
            search_result_count=len(search_results),
        ),
        "score": score,
        "result_count": len(results),
        "usable_result_count": len(usable),
        "blocked_result_count": len(blocked),
        "search_result_count": len(search_results),
        "direct_read_count": len(direct_reads),
        "source_class_counts": dict(sorted(class_counts.items())),
        "platform_counts": dict(sorted(platform_counts.items())),
        "attempt_status_counts": dict(sorted(Counter(attempt.status for attempt in attempts).items())),
        "recommendations": _recommendations(
            search_result_count=len(search_results),
            direct_read_count=len(direct_reads),
            class_counts=class_counts,
            attempts=attempts,
        ),
    }


def _score(
    *,
    usable_count: int,
    direct_read_count: int,
    search_result_count: int,
    blocked_count: int,
    class_counts: Counter[str],
    attempts: list[ResearchAttempt],
) -> int:
    score = 0
    score += min(24, usable_count * 6)
    score += min(36, direct_read_count * 18)
    score += min(10, search_result_count * 5)
    score += min(20, len(class_counts) * 5)
    if class_counts.get("official"):
        score += 10
    if class_counts.get("code"):
        score += 8
    if class_counts.get("community"):
        score += 6
    if any(attempt.status == "module_unavailable" for attempt in attempts):
        score -= 8
    score -= min(20, blocked_count * 8)
    if search_result_count and direct_read_count == 0:
        score = min(score, 39)
    return max(0, min(100, score))


def _quality_status(score: int, *, usable_count: int, direct_read_count: int, search_result_count: int) -> str:
    if usable_count <= 0:
        return "none"
    if search_result_count and direct_read_count == 0:
        return "thin"
    if score >= 70:
        return "strong"
    if score >= 45:
        return "usable"
    return "thin"


def _classes_for_result(result: ResearchResult) -> list[str]:
    classes: list[str] = []
    if result.platform == "web_search":
        classes.append("search_snippet")
    if result.platform == "reddit":
        classes.append("community")
    if result.platform == "threads":
        classes.append("social")
    if result.platform == "browser":
        classes.append("browser_snapshot")
    for citation in result.citations or [{"url": result.url}]:
        url = str(citation.get("url") or "").strip()
        host, path = _host_path(url)
        if not host:
            continue
        if _is_code_host(host):
            classes.append("code")
        elif _is_community_host(host):
            classes.append("community")
        elif _is_news_host(host):
            classes.append("news")
        elif _is_official_source(host, path):
            classes.append("official")
        else:
            classes.append("web")
    return _dedupe(classes)


def _recommendations(
    *,
    search_result_count: int,
    direct_read_count: int,
    class_counts: Counter[str],
    attempts: list[ResearchAttempt],
) -> list[str]:
    recommendations: list[str] = []
    if search_result_count and not direct_read_count:
        recommendations.append("increase_follow_results_to_read_cited_pages")
    if not class_counts.get("official"):
        recommendations.append("add_docs_or_official_query_variant")
    if any(attempt.module.startswith("browser.") and attempt.status == "module_unavailable" for attempt in attempts):
        recommendations.append("configure_requested_browser_hardpoint")
    if any(attempt.module == "platform.threads" and attempt.status == "module_unavailable" for attempt in attempts):
        recommendations.append("configure_threads_token_for_social_evidence")
    if any(attempt.module == "platform.reddit.oauth" and attempt.status == "module_unavailable" for attempt in attempts):
        recommendations.append("configure_reddit_oauth_for_durable_reddit_evidence")
    return _dedupe(recommendations)


def _host_path(url: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "", ""
    return (parsed.hostname or "").lower(), parsed.path.lower()


def _is_code_host(host: str) -> bool:
    return host in CODE_HOSTS or any(host.endswith(f".{item}") for item in CODE_HOSTS)


def _is_community_host(host: str) -> bool:
    return host in COMMUNITY_HOSTS or any(host.endswith(f".{item}") for item in COMMUNITY_HOSTS)


def _is_news_host(host: str) -> bool:
    return host.startswith("news.") or any(host == item or host.endswith(f".{item}") for item in NEWS_DOMAINS)


def _is_official_source(host: str, path: str) -> bool:
    return any(host.startswith(prefix) for prefix in OFFICIAL_HINTS) or any(hint in path for hint in OFFICIAL_PATH_HINTS)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
