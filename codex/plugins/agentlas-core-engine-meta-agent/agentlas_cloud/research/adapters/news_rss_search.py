"""No-key public RSS search cartridge."""

from __future__ import annotations

import html
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from agentlas_cloud.networking.bootstrap import utc_now

from ..contracts import ResearchAttempt, ResearchModuleManifest, ResearchRequest, ResearchResult, _stable_hash
from ..policy import DEFAULT_MAX_BYTES
from ..redaction import redacted_exception_reason


GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"


class NewsRssSearchAdapter:
    module_id = "search.news_rss"
    capabilities = ("search.web", "search.news", "read.search_results")
    weight = "light"
    manifest = ResearchModuleManifest(
        module_id=module_id,
        capabilities=list(capabilities),
        weight=weight,
        slot="search",
        activation="auto",
        requires=[],
        permissions=["network:news.google.com"],
        default_state="available",
        privacy="external_search_receives_query",
        failure_modes=["rate_limited", "empty_results", "rss_parse_error", "search_error"],
    )

    def __init__(self, *, timeout_seconds: int = 20, max_bytes: int = DEFAULT_MAX_BYTES, max_results: int = 15):
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_results = max_results

    def can_handle(self, source_hint: str, request: ResearchRequest) -> bool:
        lowered = source_hint.lower()
        return lowered.startswith("search:news_rss:") or lowered.startswith("search:news:")

    def read(self, source_hint: str, request: ResearchRequest) -> tuple[ResearchResult | None, ResearchAttempt]:
        query = _search_query(source_hint)
        if not query:
            return None, ResearchAttempt(self.module_id, "error", "empty_news_rss_query", source_hint, weight=self.weight)
        search_url = _search_url(query)
        try:
            body = self._fetch_text(search_url)
            result = _rss_to_result(body, query=query, search_url=search_url, request=request, max_results=self.max_results)
        except HTTPError as exc:
            reason = _status_reason(exc.code)
            return (
                ResearchResult.blocked(search_url, reason=reason),
                ResearchAttempt(self.module_id, "blocked", f"{reason}:{exc.code}", search_url, weight=self.weight),
            )
        except (URLError, OSError, ElementTree.ParseError, ValueError) as exc:
            return (
                None,
                ResearchAttempt(self.module_id, "error", redacted_exception_reason(exc, max_length=160), search_url, weight=self.weight),
            )
        return result, ResearchAttempt(self.module_id, "ok", f"rss_results={len(result.citations) - 1}", search_url, weight=self.weight)

    def _fetch_text(self, url: str) -> str:
        req = Request(
            url,
            headers={
                "User-Agent": "AgentlasResearchEngine/0.1 (+https://agentlas.cloud)",
                "Accept": "application/rss+xml,application/xml,text/xml;q=0.9,*/*;q=0.5",
            },
        )
        with urlopen(req, timeout=self.timeout_seconds) as resp:
            raw = resp.read(self.max_bytes + 1)
        return raw[: self.max_bytes].decode("utf-8", errors="replace")


def _search_query(source_hint: str) -> str:
    if source_hint.lower().startswith("search:news_rss:"):
        return source_hint.split(":", 2)[2].strip()
    if source_hint.lower().startswith("search:news:"):
        return source_hint.split(":", 2)[2].strip()
    return source_hint.strip()


def _search_url(query: str) -> str:
    return f"{GOOGLE_NEWS_RSS}?q={quote_plus(query)}&hl=en-US&gl=US&ceid=US:en"


def _rss_to_result(body: str, *, query: str, search_url: str, request: ResearchRequest, max_results: int) -> ResearchResult:
    root = ElementTree.fromstring(body)
    feed_title = _first_text(root, [".//channel/title", ".//title"]) or f"News search: {query}"
    items = root.findall(".//item")
    lines = [f"# {feed_title}"]
    citations = [{"label": "news-rss-search", "url": search_url}]
    for item in items[:max_results]:
        title = _first_text(item, ["title"]) or "Untitled"
        link = _first_text(item, ["link"])
        published = _first_text(item, ["pubDate"])
        source = _first_text(item, ["source"])
        description = _compact(_strip_html(_first_text(item, ["description"])))
        prefix = f"- {title}"
        details = " ".join(part for part in [source, published] if part)
        if details:
            prefix += f" [{details}]"
        if link:
            prefix += f" ({link})"
            citations.append({"label": title, "url": link})
        if description:
            prefix += f": {description}"
        lines.append(prefix)
    limits = ["public_rss_search", "search_results_not_deep_read"]
    if len(items) > max_results:
        limits.append("partial_results")
    if not items:
        limits.append("empty_results")
    return ResearchResult(
        source_id=_stable_hash(f"search:news_rss:{query}"),
        url=search_url,
        title=f"News RSS search: {query}",
        platform="web_search",
        content_markdown="\n".join(lines).strip(),
        extracted_at=utc_now(),
        freshness=request.freshness,
        confidence="usable" if items else "weak",
        limits=limits,
        citations=citations,
    )


def _first_text(root, paths: list[str]) -> str:
    for path in paths:
        node = root.find(path)
        if node is not None and node.text and node.text.strip():
            return html.unescape(node.text.strip())
    return ""


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", text or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return html.unescape(text)


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


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
