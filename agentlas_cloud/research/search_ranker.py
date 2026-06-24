"""Search-result candidate ranking for bounded follow-up reads."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .contracts import ResearchResult


SEARCH_SHELL_HOSTS = {
    "duckduckgo.com",
    "lite.duckduckgo.com",
    "google.com",
    "www.google.com",
    "news.google.com",
    "bing.com",
    "www.bing.com",
}
TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "msclkid", "mc_cid", "mc_eid", "igshid", "ref_src"}
SOCIAL_HOSTS = {
    "reddit": {"reddit.com", "old.reddit.com"},
    "threads": {"threads.com", "threads.net"},
}
SOCIAL_QUERY_HINTS = {
    "reddit": ("reddit", "reddit.com", "레딧"),
    "threads": ("threads", "threads.com", "threads.net", "쓰레드"),
}


@dataclass
class SearchCandidate:
    url: str
    canonical_url: str
    host: str
    score: int
    sources: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "url": self.url,
            "canonical_url": self.canonical_url,
            "host": self.host,
            "score": self.score,
            "sources": list(self.sources),
            "labels": list(self.labels[:3]),
            "reasons": list(self.reasons),
        }


@dataclass
class SearchCandidateReport:
    candidates: list[SearchCandidate]
    total_candidates: int
    unique_hosts: int
    direct_candidates: int
    search_shell_candidates: int
    source_counts: dict[str, int]
    host_counts: dict[str, int]
    diversity_strategy: str = "host_round_robin_v1"

    def to_dict(self) -> dict[str, object]:
        return {
            "total_candidates": self.total_candidates,
            "unique_hosts": self.unique_hosts,
            "direct_candidates": self.direct_candidates,
            "search_shell_candidates": self.search_shell_candidates,
            "source_counts": dict(self.source_counts),
            "host_counts": dict(self.host_counts),
            "diversity_strategy": self.diversity_strategy,
            "top_candidates": [candidate.to_dict() for candidate in self.candidates],
        }


def rank_followup_candidates(results: list[ResearchResult], *, query: str, limit: int) -> list[SearchCandidate]:
    return analyze_search_candidates(results, query=query, limit=limit).candidates


def analyze_search_candidates(
    results: list[ResearchResult],
    *,
    query: str,
    limit: int,
    max_per_host: int = 1,
) -> SearchCandidateReport:
    ranked = _rank_all_candidates(results, query=query)
    selected = _select_diverse_candidates(ranked, limit=limit, max_per_host=max_per_host)
    return SearchCandidateReport(
        candidates=selected,
        total_candidates=len(ranked),
        unique_hosts=len({candidate.host for candidate in ranked}),
        direct_candidates=sum(1 for candidate in ranked if candidate.host not in SEARCH_SHELL_HOSTS),
        search_shell_candidates=sum(1 for candidate in ranked if candidate.host in SEARCH_SHELL_HOSTS),
        source_counts=_count_sources(ranked),
        host_counts=_count_hosts(ranked),
    )


def _rank_all_candidates(results: list[ResearchResult], *, query: str) -> list[SearchCandidate]:
    candidates: dict[str, SearchCandidate] = {}
    query_tokens = _tokens(query)
    query_text = str(query or "").lower()
    for result in results:
        if result.platform != "web_search":
            continue
        source = _search_source(result)
        source_query_text = _source_query_text(query_text, result)
        search_canonical = _canonicalize_url(str(result.url or ""))
        for index, citation in enumerate(result.citations):
            raw_url = str(citation.get("url") or "").strip()
            label = _compact(str(citation.get("label") or ""))
            canonical = _canonicalize_url(raw_url)
            if not canonical or canonical == search_canonical:
                continue
            parsed = urlsplit(canonical)
            host = (parsed.hostname or "").lower()
            if parsed.scheme not in {"http", "https"} or not host:
                continue
            score, reasons = _score_candidate(
                canonical,
                label=label,
                source=source,
                index=index,
                query_tokens=query_tokens,
                query_text=source_query_text,
            )
            existing = candidates.get(canonical)
            if existing:
                existing.score += 12
                if source not in existing.sources:
                    existing.sources.append(source)
                    existing.score += 8
                    existing.reasons.append("source_consensus")
                if label and label not in existing.labels:
                    existing.labels.append(label)
                continue
            candidates[canonical] = SearchCandidate(
                url=canonical,
                canonical_url=canonical,
                host=host,
                score=score,
                sources=[source],
                labels=[label] if label else [],
                reasons=reasons,
            )

    ranked = sorted(
        candidates.values(),
        key=lambda candidate: (-candidate.score, _host_penalty_sort(candidate.host), candidate.url),
    )
    return ranked


def _select_diverse_candidates(
    ranked: list[SearchCandidate],
    *,
    limit: int,
    max_per_host: int,
) -> list[SearchCandidate]:
    if limit <= 0:
        return []
    selected: list[SearchCandidate] = []
    per_host: dict[str, int] = {}
    for candidate in ranked:
        if per_host.get(candidate.host, 0) >= max_per_host:
            continue
        selected.append(candidate)
        per_host[candidate.host] = per_host.get(candidate.host, 0) + 1
        if len(selected) >= limit:
            return selected
    selected_urls = {candidate.canonical_url for candidate in selected}
    for candidate in ranked:
        if candidate.canonical_url in selected_urls:
            continue
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def _score_candidate(
    url: str,
    *,
    label: str,
    source: str,
    index: int,
    query_tokens: set[str],
    query_text: str,
) -> tuple[int, list[str]]:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    text = f"{label} {host} {parsed.path}".lower()
    reasons: list[str] = []
    score = max(2, 40 - (index * 2))

    if source == "search.ddg_html":
        score += 24
        reasons.append("general_web")
    elif source == "search.github_repos":
        score += 22
        reasons.append("github_repository_search")
    elif source == "search.jina":
        score += 18
        reasons.append("external_search")
    elif source == "search.news_rss":
        score += 10
        reasons.append("news_search")

    matches = sum(1 for token in query_tokens if token in text)
    if matches:
        score += min(24, matches * 6)
        reasons.append("query_match")

    if host in SEARCH_SHELL_HOSTS:
        score -= 45
        reasons.append("search_shell_penalty")
    else:
        score += 12
        reasons.append("direct_url")

    social_target = _social_target_for_host(host)
    if social_target and _query_requests_social_target(query_text, social_target):
        score += 30
        reasons.append("social_host_requested")

    return score, reasons


def _social_target_for_host(host: str) -> str:
    normalized = host[4:] if host.startswith("www.") else host
    for target, hosts in SOCIAL_HOSTS.items():
        if normalized in hosts or any(normalized.endswith(f".{candidate}") for candidate in hosts):
            return target
    return ""


def _query_requests_social_target(query_text: str, target: str) -> bool:
    return any(hint in query_text for hint in SOCIAL_QUERY_HINTS.get(target, ()))


def _source_query_text(query_text: str, result: ResearchResult) -> str:
    return " ".join(
        part.lower()
        for part in [
            query_text,
            str(result.url or ""),
            str(result.title or ""),
        ]
        if part
    )


def _search_source(result: ResearchResult) -> str:
    limits = set(result.limits)
    url = str(result.url or "")
    if "public_html_search" in limits or "duckduckgo" in url:
        return "search.ddg_html"
    if "github_repository_search" in limits or "api.github.com/search/repositories" in url:
        return "search.github_repos"
    if "jina_search" in limits or "s.jina.ai" in url:
        return "search.jina"
    if "public_rss_search" in limits or "news.google.com" in url:
        return "search.news_rss"
    return "search.unknown"


def _canonicalize_url(url: str) -> str:
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    host = parsed.hostname.lower()
    if parsed.port:
        host = f"{host}:{parsed.port}"
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    query = _canonical_query(parsed.query)
    return urlunsplit((parsed.scheme.lower(), host, path, query, ""))


def _canonical_query(query: str) -> str:
    kept: list[tuple[str, str]] = []
    for key, value in parse_qsl(query, keep_blank_values=True):
        lowered = key.lower()
        if lowered in TRACKING_QUERY_KEYS or any(lowered.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        kept.append((key, value))
    return urlencode(sorted(kept), doseq=True)


def _tokens(value: str) -> set[str]:
    return {part.lower() for part in re.findall(r"[a-zA-Z0-9가-힣]{3,}", value or "")}


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _host_penalty_sort(host: str) -> int:
    return 1 if host in SEARCH_SHELL_HOSTS else 0


def _count_sources(candidates: list[SearchCandidate]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        for source in candidate.sources:
            counts[source] = counts.get(source, 0) + 1
    return dict(sorted(counts.items()))


def _count_hosts(candidates: list[SearchCandidate]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for candidate in candidates:
        counts[candidate.host] = counts.get(candidate.host, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:10])
