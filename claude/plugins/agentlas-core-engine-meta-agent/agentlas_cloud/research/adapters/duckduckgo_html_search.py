"""No-key DuckDuckGo HTML search cartridge."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlsplit
from urllib.request import Request, urlopen

from agentlas_cloud.networking.bootstrap import utc_now

from ..contracts import ResearchAttempt, ResearchModuleManifest, ResearchRequest, ResearchResult, _stable_hash
from ..policy import DEFAULT_MAX_BYTES
from ..redaction import redacted_exception_reason


DUCKDUCKGO_LITE_SEARCH = "https://lite.duckduckgo.com/lite/"


class DuckDuckGoHtmlSearchAdapter:
    module_id = "search.ddg_html"
    capabilities = ("search.web", "read.search_results")
    weight = "light"
    manifest = ResearchModuleManifest(
        module_id=module_id,
        capabilities=list(capabilities),
        weight=weight,
        slot="search",
        activation="auto",
        requires=[],
        permissions=["network:lite.duckduckgo.com"],
        default_state="available",
        privacy="external_search_receives_query",
        failure_modes=["rate_limited", "empty_results", "html_parse_error", "search_error"],
    )

    def __init__(self, *, timeout_seconds: int = 20, max_bytes: int = DEFAULT_MAX_BYTES, max_results: int = 15):
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_results = max_results

    def can_handle(self, source_hint: str, request: ResearchRequest) -> bool:
        lowered = source_hint.lower()
        return (
            lowered.startswith("search:ddg_html:")
            or lowered.startswith("search:duckduckgo:")
            or lowered.startswith("search:web:")
        )

    def read(self, source_hint: str, request: ResearchRequest) -> tuple[ResearchResult | None, ResearchAttempt]:
        query = _search_query(source_hint)
        if not query:
            return None, ResearchAttempt(self.module_id, "error", "empty_ddg_query", source_hint, weight=self.weight)
        search_url = _search_url(query)
        try:
            body = self._fetch_text(search_url)
            result = _html_to_result(body, query=query, search_url=search_url, request=request, max_results=self.max_results)
        except HTTPError as exc:
            reason = _status_reason(exc.code)
            return (
                ResearchResult.blocked(search_url, reason=reason),
                ResearchAttempt(self.module_id, "blocked", f"{reason}:{exc.code}", search_url, weight=self.weight),
            )
        except (URLError, OSError, ValueError) as exc:
            return (
                None,
                ResearchAttempt(self.module_id, "error", redacted_exception_reason(exc, max_length=160), search_url, weight=self.weight),
            )
        return result, ResearchAttempt(self.module_id, "ok", f"html_results={len(result.citations) - 1}", search_url, weight=self.weight)

    def _fetch_text(self, url: str) -> str:
        req = Request(
            url,
            headers={
                "User-Agent": "AgentlasResearchEngine/0.1 (+https://agentlas.cloud)",
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
            },
        )
        with urlopen(req, timeout=self.timeout_seconds) as resp:
            raw = resp.read(self.max_bytes + 1)
        return raw[: self.max_bytes].decode("utf-8", errors="replace")


class _LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href = ""
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr_map = {key.lower(): value or "" for key, value in attrs}
        self._href = attr_map.get("href", "")
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        label = _compact(" ".join(self._parts))
        self.links.append((label, self._href))
        self._href = ""
        self._parts = []


def _search_query(source_hint: str) -> str:
    if source_hint.lower().startswith("search:ddg_html:"):
        return source_hint.split(":", 2)[2].strip()
    if source_hint.lower().startswith("search:duckduckgo:"):
        return source_hint.split(":", 2)[2].strip()
    if source_hint.lower().startswith("search:web:"):
        return source_hint.split(":", 2)[2].strip()
    return source_hint.strip()


def _search_url(query: str) -> str:
    return f"{DUCKDUCKGO_LITE_SEARCH}?q={quote_plus(query)}"


def _html_to_result(body: str, *, query: str, search_url: str, request: ResearchRequest, max_results: int) -> ResearchResult:
    parser = _LinkParser()
    parser.feed(body)
    citations = [{"label": "duckduckgo-html-search", "url": search_url}]
    lines = [f"# DuckDuckGo HTML search: {query}"]
    seen: set[str] = set()
    for label, raw_href in parser.links:
        url = _normalize_result_url(raw_href, search_url)
        if not url or url in seen:
            continue
        seen.add(url)
        result_label = label or url
        citations.append({"label": result_label, "url": url})
        lines.append(f"- {result_label} ({url})")
        if len(seen) >= max_results:
            break
    limits = ["public_html_search", "search_results_not_deep_read"]
    if not seen:
        limits.append("empty_results")
    return ResearchResult(
        source_id=_stable_hash(f"search:ddg_html:{query}"),
        url=search_url,
        title=f"DuckDuckGo HTML search: {query}",
        platform="web_search",
        content_markdown="\n".join(lines).strip(),
        extracted_at=utc_now(),
        freshness=request.freshness,
        confidence="usable" if seen else "weak",
        limits=limits,
        citations=citations,
    )


def _normalize_result_url(href: str, search_url: str) -> str:
    url = html.unescape(href or "").strip()
    if not url:
        return ""
    absolute = urljoin(search_url, url)
    parsed = urlsplit(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.hostname.endswith("duckduckgo.com"):
        target = parse_qs(parsed.query).get("uddg")
        if not target:
            return ""
        absolute = unquote(target[0])
        parsed = urlsplit(absolute)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    return parsed.geturl()


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(text or "")).strip()


def _status_reason(status: int) -> str:
    if status in {401, 407}:
        return "auth_required"
    if status == 403:
        return "blocked"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    return "http_error"
