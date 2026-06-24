"""No-key public GitHub repository search cartridge."""

from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from agentlas_cloud.networking.bootstrap import utc_now

from ..contracts import ResearchAttempt, ResearchModuleManifest, ResearchRequest, ResearchResult, _stable_hash
from ..policy import DEFAULT_MAX_BYTES
from ..redaction import redacted_exception_reason


GITHUB_REPOSITORY_SEARCH = "https://api.github.com/search/repositories"


class GitHubReposSearchAdapter:
    module_id = "search.github_repos"
    capabilities = ("search.github", "search.repositories", "read.search_results")
    weight = "light"
    manifest = ResearchModuleManifest(
        module_id=module_id,
        capabilities=list(capabilities),
        weight=weight,
        slot="search",
        activation="auto_for_github_hints",
        requires=["network:api.github.com"],
        permissions=["network:api.github.com"],
        default_state="available",
        privacy="external_search_receives_query; public_repositories_only",
        failure_modes=["rate_limited", "validation_failed", "empty_results", "github_search_error"],
    )

    def __init__(self, *, timeout_seconds: int = 20, max_bytes: int = DEFAULT_MAX_BYTES, max_results: int = 10):
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_results = max_results

    def can_handle(self, source_hint: str, request: ResearchRequest) -> bool:
        lowered = source_hint.lower()
        return (
            lowered.startswith("search:github:")
            or lowered.startswith("search:github_repos:")
            or lowered.startswith("github:search:")
        )

    def read(self, source_hint: str, request: ResearchRequest) -> tuple[ResearchResult | None, ResearchAttempt]:
        query = _search_query(source_hint)
        if not query:
            return None, ResearchAttempt(self.module_id, "error", "empty_github_query", source_hint, weight=self.weight)
        search_url = _search_url(query, max_results=self.max_results)
        try:
            payload = self._fetch_json(search_url)
            result = _json_to_result(
                payload,
                query=query,
                search_url=search_url,
                request=request,
                max_results=self.max_results,
            )
        except HTTPError as exc:
            reason = _status_reason(exc)
            return (
                ResearchResult.blocked(search_url, reason=reason),
                ResearchAttempt(self.module_id, "blocked", f"{reason}:{exc.code}", search_url, weight=self.weight),
            )
        except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            return (
                None,
                ResearchAttempt(self.module_id, "error", redacted_exception_reason(exc, max_length=160), search_url, weight=self.weight),
            )
        return result, ResearchAttempt(self.module_id, "ok", f"github_repos={len(result.citations) - 1}", search_url, weight=self.weight)

    def _fetch_json(self, url: str) -> dict:
        req = Request(
            url,
            headers={
                "User-Agent": "AgentlasResearchEngine/0.1 (+https://agentlas.cloud)",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urlopen(req, timeout=self.timeout_seconds) as resp:
            raw = resp.read(self.max_bytes + 1)
        payload = json.loads(raw[: self.max_bytes].decode("utf-8", errors="replace"))
        if not isinstance(payload, dict):
            raise ValueError("github_search_payload_not_object")
        return payload


def _search_query(source_hint: str) -> str:
    lowered = source_hint.lower()
    if lowered.startswith("search:github:") or lowered.startswith("search:github_repos:"):
        return source_hint.split(":", 2)[2].strip()
    if lowered.startswith("github:search:"):
        return source_hint.split(":", 2)[2].strip()
    return source_hint.strip()


def _search_url(query: str, *, max_results: int) -> str:
    compact = _bounded_query(query)
    per_page = max(1, min(100, max_results))
    return f"{GITHUB_REPOSITORY_SEARCH}?q={quote_plus(compact)}&per_page={per_page}"


def _json_to_result(payload: dict, *, query: str, search_url: str, request: ResearchRequest, max_results: int) -> ResearchResult:
    items = payload.get("items") or []
    if not isinstance(items, list):
        raise ValueError("github_search_items_not_list")
    total_count = payload.get("total_count")
    incomplete = bool(payload.get("incomplete_results"))
    citations = [{"label": "github-repository-search", "url": search_url}]
    lines = [f"# GitHub repository search: {query}"]
    if isinstance(total_count, int):
        lines.append(f"Total public matches reported by GitHub: {total_count}")
    if incomplete:
        lines.append("GitHub marked this search response as incomplete.")

    seen = 0
    for item in items[:max_results]:
        if not isinstance(item, dict):
            continue
        full_name = _compact(str(item.get("full_name") or ""))
        html_url = _compact(str(item.get("html_url") or ""))
        if not full_name or not html_url:
            continue
        description = _compact(str(item.get("description") or ""))
        stars = _int_value(item.get("stargazers_count"))
        language = _compact(str(item.get("language") or ""))
        updated_at = _compact(str(item.get("updated_at") or ""))
        details = _format_details(
            [
                f"stars={stars}" if stars is not None else "",
                f"language={language}" if language else "",
                f"updated={updated_at}" if updated_at else "",
            ]
        )
        line = f"- {full_name} ({html_url})"
        if details:
            line += f" [{details}]"
        if description:
            line += f": {description}"
        lines.append(line)
        citations.append({"label": full_name, "url": html_url})
        seen += 1

    limits = ["github_repository_search", "public_rest_api", "search_results_not_deep_read"]
    if incomplete:
        limits.append("incomplete_results")
    if not seen:
        limits.append("empty_results")
    return ResearchResult(
        source_id=_stable_hash(f"search:github_repos:{query}"),
        url=search_url,
        title=f"GitHub repository search: {query}",
        platform="web_search",
        content_markdown="\n".join(lines).strip(),
        extracted_at=utc_now(),
        freshness=request.freshness,
        confidence="usable" if seen else "weak",
        limits=limits,
        citations=citations,
    )


def _bounded_query(query: str) -> str:
    compact = _compact(query)
    return compact[:240]


def _format_details(parts: list[str]) -> str:
    return ", ".join(part for part in parts if part)


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _int_value(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _status_reason(exc: HTTPError) -> str:
    status = int(exc.code)
    remaining = (exc.headers.get("x-ratelimit-remaining") if exc.headers else "") or ""
    retry_after = (exc.headers.get("retry-after") if exc.headers else "") or ""
    if status in {401, 407}:
        return "auth_required"
    if status == 422:
        return "validation_failed"
    if status in {403, 429} and (remaining == "0" or retry_after):
        return "rate_limited"
    if status == 403:
        return "blocked"
    if status == 404:
        return "not_found"
    if status == 503:
        return "service_unavailable"
    return "http_error"
