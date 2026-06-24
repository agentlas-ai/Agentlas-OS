"""Optional Jina Reader/Search cartridges.

These adapters call public Jina endpoints only when selected by policy. Plain
URL reads are not sent to Jina by default; callers must explicitly allow
`read.jina` or use the `research search` command for `search.jina`.
"""

from __future__ import annotations

import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from agentlas_cloud.networking.bootstrap import utc_now

from ..contracts import ResearchAttempt, ResearchModuleManifest, ResearchRequest, ResearchResult, _stable_hash
from ..policy import DEFAULT_MAX_BYTES, classify_url
from ..redaction import redacted_exception_reason


JINA_READER_BASE = "https://r.jina.ai/"
JINA_SEARCH_BASE = "https://s.jina.ai/"


class JinaReaderAdapter:
    module_id = "read.jina"
    capabilities = ("read.url", "read.markdown")
    weight = "external_light"
    manifest = ResearchModuleManifest(
        module_id=module_id,
        capabilities=list(capabilities),
        weight=weight,
        slot="reader",
        activation="explicit_allow",
        requires=["network:r.jina.ai"],
        permissions=["network:r.jina.ai"],
        default_state="available_if_allowed",
        privacy="external_reader_receives_requested_url",
        failure_modes=["module_unavailable", "rate_limited", "external_reader_error", "ssrf_blocked"],
        install_hint="No install required; explicitly allow read.jina when external URL-to-markdown is acceptable.",
    )

    def __init__(self, *, timeout_seconds: int = 30, max_bytes: int = DEFAULT_MAX_BYTES):
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes

    def can_handle(self, source_hint: str, request: ResearchRequest) -> bool:
        url = _reader_source_url(source_hint)
        if urlsplit(url).scheme.lower() not in {"http", "https"}:
            return False
        return self.module_id in request.allowed_modules or source_hint.lower().startswith("jina:")

    def read(self, source_hint: str, request: ResearchRequest) -> tuple[ResearchResult | None, ResearchAttempt]:
        source_url = _reader_source_url(source_hint)
        safe, reason = classify_url(source_url)
        if not safe:
            return (
                ResearchResult.blocked(source_url, reason=f"ssrf_blocked:{reason}"),
                ResearchAttempt(self.module_id, "blocked", f"ssrf_blocked:{reason}", source_url, weight=self.weight),
            )

        reader_url = _jina_reader_url(source_url)
        try:
            markdown = self._fetch_text(reader_url)
        except HTTPError as exc:
            reason = _status_reason(exc.code)
            return (
                ResearchResult.blocked(source_url, reason=reason),
                ResearchAttempt(self.module_id, "blocked", f"{reason}:{exc.code}", reader_url, weight=self.weight),
            )
        except (URLError, TimeoutError, OSError) as exc:
            return (
                None,
                ResearchAttempt(self.module_id, "error", redacted_exception_reason(exc, max_length=160), reader_url, weight=self.weight),
            )

        title = _title_from_markdown(markdown) or source_url
        result = ResearchResult(
            source_id=_stable_hash(source_url),
            url=source_url,
            title=title,
            platform="web",
            content_markdown=markdown.strip(),
            extracted_at=utc_now(),
            freshness=request.freshness,
            confidence="usable" if markdown.strip() else "weak",
            limits=["external_reader", "jina_reader"],
            citations=[{"label": title, "url": source_url}, {"label": "jina-reader", "url": reader_url}],
        )
        return result, ResearchAttempt(self.module_id, "ok", "jina_reader", reader_url, weight=self.weight)

    def _fetch_text(self, url: str) -> str:
        req = Request(
            url,
            headers={
                "User-Agent": "AgentlasResearchEngine/0.1 (+https://agentlas.cloud)",
                "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.5",
            },
        )
        with urlopen(req, timeout=self.timeout_seconds) as resp:
            raw = resp.read(self.max_bytes + 1)
        return raw[: self.max_bytes].decode("utf-8", errors="replace")


class JinaSearchAdapter:
    module_id = "search.jina"
    capabilities = ("search.web", "read.search_results")
    weight = "external_light"
    manifest = ResearchModuleManifest(
        module_id=module_id,
        capabilities=list(capabilities),
        weight=weight,
        slot="search",
        activation="configured",
        requires=["api_key:jina", "network:s.jina.ai"],
        permissions=["network:s.jina.ai"],
        default_state="available_if_configured",
        privacy="no_raw_token_to_model; external_search_receives_query",
        failure_modes=["module_unavailable", "rate_limited", "external_search_error", "empty_results"],
        install_hint="Set AGENTLAS_JINA_API_KEY or JINA_API_KEY and choose provider=jina or loadout=full.",
    )

    def __init__(self, *, timeout_seconds: int = 30, max_bytes: int = DEFAULT_MAX_BYTES):
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes

    def can_handle(self, source_hint: str, request: ResearchRequest) -> bool:
        return source_hint.lower().startswith("search:jina:")

    def read(self, source_hint: str, request: ResearchRequest) -> tuple[ResearchResult | None, ResearchAttempt]:
        query = _search_query(source_hint)
        if not query:
            return None, ResearchAttempt(self.module_id, "error", "empty_jina_query", source_hint, weight=self.weight)

        api_key = self._api_key()
        if not api_key:
            return (
                None,
                ResearchAttempt(
                    self.module_id,
                    "module_unavailable",
                    "AGENTLAS_JINA_API_KEY or JINA_API_KEY not configured",
                    source_hint,
                    weight=self.weight,
                ),
            )

        search_url = _jina_search_url(query)
        try:
            markdown = self._fetch_text(search_url, api_key=api_key)
        except HTTPError as exc:
            reason = _status_reason(exc.code)
            return (
                ResearchResult.blocked(search_url, reason=reason),
                ResearchAttempt(self.module_id, "blocked", f"{reason}:{exc.code}", search_url, weight=self.weight),
            )
        except (URLError, TimeoutError, OSError) as exc:
            return (
                None,
                ResearchAttempt(self.module_id, "error", redacted_exception_reason(exc, max_length=160), search_url, weight=self.weight),
            )

        title = f"Jina search: {query}"
        citations = _search_citations_from_markdown(markdown, search_url=search_url, title=title)
        result = ResearchResult(
            source_id=_stable_hash(f"search:jina:{query}"),
            url=search_url,
            title=title,
            platform="web_search",
            content_markdown=markdown.strip(),
            extracted_at=utc_now(),
            freshness=request.freshness,
            confidence="usable" if markdown.strip() else "weak",
            limits=["external_search", "jina_search"],
            citations=citations,
        )
        return result, ResearchAttempt(self.module_id, "ok", "jina_search", search_url, weight=self.weight)

    def _api_key(self) -> str:
        return os.environ.get("AGENTLAS_JINA_API_KEY") or os.environ.get("JINA_API_KEY") or ""

    def _fetch_text(self, url: str, *, api_key: str) -> str:
        req = Request(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "AgentlasResearchEngine/0.1 (+https://agentlas.cloud)",
                "Accept": "text/plain, text/markdown;q=0.9, */*;q=0.5",
            },
        )
        with urlopen(req, timeout=self.timeout_seconds) as resp:
            raw = resp.read(self.max_bytes + 1)
        return raw[: self.max_bytes].decode("utf-8", errors="replace")


def _reader_source_url(source_hint: str) -> str:
    if source_hint.lower().startswith("jina:"):
        return source_hint.split(":", 1)[1].strip()
    return source_hint.strip()


def _search_query(source_hint: str) -> str:
    return source_hint.split(":", 2)[2].strip() if source_hint.lower().startswith("search:jina:") else source_hint.strip()


def _jina_reader_url(source_url: str) -> str:
    return f"{JINA_READER_BASE}{source_url}"


def _jina_search_url(query: str) -> str:
    return f"{JINA_SEARCH_BASE}?q={quote(query, safe='')}"


def _search_citations_from_markdown(markdown: str, *, search_url: str, title: str, max_results: int = 15) -> list[dict[str, str]]:
    citations = [{"label": title, "url": search_url}]
    seen = {search_url}
    for label, url in _markdown_links(markdown):
        if url in seen:
            continue
        seen.add(url)
        citations.append({"label": label or url, "url": url})
        if len(citations) - 1 >= max_results:
            break
    return citations


def _markdown_links(markdown: str) -> list[tuple[str, str]]:
    links: list[tuple[str, str]] = []
    for match in re.finditer(r"\[([^\]]{1,200})\]\((https?://[^)\s]+)\)", markdown or ""):
        label = re.sub(r"\s+", " ", match.group(1)).strip()
        url = _clean_url(match.group(2))
        if _is_public_http_url(url):
            links.append((label, url))
    for match in re.finditer(r"https?://[^\s<>)\"']+", markdown or ""):
        url = _clean_url(match.group(0))
        if _is_public_http_url(url):
            links.append((url, url))
    return links


def _clean_url(url: str) -> str:
    return (url or "").rstrip(".,;:]}")


def _is_public_http_url(url: str) -> bool:
    parsed = urlsplit(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname)


def _title_from_markdown(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()[:120]
        if stripped:
            return stripped[:120]
    return ""


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
