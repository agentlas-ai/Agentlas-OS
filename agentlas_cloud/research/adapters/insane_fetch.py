"""Adaptive public fetch-chain inspired by insane-search.

This is not the upstream Claude Code plugin. It is Agentlas' own lightweight
cartridge that tries documented/public routes in a bounded order when the user
explicitly mounts `read.insane_fetch`.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree

from agentlas_cloud.networking.bootstrap import utc_now

from ..contracts import ResearchAttempt, ResearchModuleManifest, ResearchRequest, ResearchResult, _stable_hash
from ..policy import DEFAULT_MAX_BYTES, DEFAULT_MAX_REDIRECTS, classify_url
from .jina_reader import JINA_READER_BASE


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


@dataclass(frozen=True)
class FetchRoute:
    name: str
    phase: str
    url: str
    parser: str = "auto"
    external: bool = False


class InsaneFetchAdapter:
    module_id = "read.insane_fetch"
    capabilities = ("read.url", "read.adaptive_fetch", "read.metadata", "read.feed")
    weight = "adaptive_medium"
    manifest = ResearchModuleManifest(
        module_id=module_id,
        capabilities=list(capabilities),
        weight=weight,
        slot="reader",
        activation="explicit_allow",
        requires=[],
        permissions=["network:http", "network:https", "network:r.jina.ai"],
        default_state="available_if_allowed",
        privacy="public_routes_only; external_reader_receives_requested_url_when_jina_route_used",
        failure_modes=["all_routes_failed", "auth_required", "paywall_detected", "ssrf_blocked", "rate_limited"],
        install_hint="No mandatory install; choose loadout=public-web/social/browser/full or allow read.insane_fetch.",
    )

    def __init__(self, *, timeout_seconds: int = 25, max_bytes: int = DEFAULT_MAX_BYTES):
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes

    def can_handle(self, source_hint: str, request: ResearchRequest) -> bool:
        source_url = _source_url(source_hint)
        if urlsplit(source_url).scheme.lower() not in {"http", "https"}:
            return False
        return self.module_id in request.allowed_modules or source_hint.lower().startswith("insane:")

    def read(self, source_hint: str, request: ResearchRequest) -> tuple[ResearchResult | None, ResearchAttempt]:
        source_url = _source_url(source_hint)
        safe, reason = classify_url(source_url)
        if not safe:
            return (
                ResearchResult.blocked(source_url, reason=f"ssrf_blocked:{reason}"),
                ResearchAttempt(self.module_id, "blocked", f"ssrf_blocked:{reason}", source_url, weight=self.weight),
            )

        routes = _routes_for(source_url)
        evaluated: list[str] = []
        tried: list[str] = []
        failures: list[str] = []
        trace: list[str] = []
        for route in routes:
            evaluated.append(route.name)
            safe, reason = classify_url(route.url)
            if not safe:
                failures.append(f"{route.name}:ssrf_blocked:{reason}")
                trace.append(f"{route.name}=ssrf_blocked")
                continue
            tried.append(route.name)
            try:
                status, body, final_url, content_type = self._fetch(route.url)
            except (URLError, TimeoutError, OSError) as exc:
                failures.append(f"{route.name}:{type(exc).__name__}")
                trace.append(f"{route.name}={type(exc).__name__}")
                continue

            auth_reason = _auth_wall_reason(status, body)
            if auth_reason:
                trace.append(f"{route.name}={auth_reason}")
                blocked = ResearchResult.blocked(source_url, reason=auth_reason)
                blocked.limits = _dedupe(
                    blocked.limits
                    + [
                        "adaptive_chain",
                        f"phase:{route.phase}",
                        f"route:{route.name}",
                        f"stop_reason:{auth_reason}",
                        *_trace_limits(trace),
                        *_untried_routes_limits(routes, evaluated),
                    ]
                )
                return (
                    blocked,
                    ResearchAttempt(
                        self.module_id,
                        "blocked",
                        f"{auth_reason}:route={route.name};trace={','.join(trace)}",
                        final_url,
                        next_allowed=_untried_route_names(routes, evaluated),
                        weight=self.weight,
                    ),
                )
            if status in {403, 404, 429}:
                status_reason = _status_reason(status)
                failures.append(f"{route.name}:{status_reason}")
                trace.append(f"{route.name}={status_reason}")
                continue

            text, title, limits = _parse_body(body, content_type, route)
            if not text:
                failures.append(f"{route.name}:empty")
                trace.append(f"{route.name}=empty")
                continue
            thin_reason = _thin_public_shell_reason(source_url=source_url, title=title, text=text)
            if thin_reason:
                failures.append(f"{route.name}:{thin_reason}")
                trace.append(f"{route.name}={thin_reason}")
                continue

            trace.append(f"{route.name}=ok:{status}")
            limits.extend(
                [
                    "adaptive_chain",
                    f"phase:{route.phase}",
                    f"route:{route.name}",
                    "stop_reason:route_success",
                    *_trace_limits(trace),
                    *_untried_routes_limits(routes, evaluated),
                ]
            )
            limits.extend(_platform_fallback_limits(source_url, route))
            if route.external:
                limits.append("external_reader")
            platform = _platform_for(source_url)
            result = ResearchResult(
                source_id=_stable_hash(source_url),
                url=source_url,
                title=title or source_url,
                platform=platform,
                content_markdown=text,
                extracted_at=utc_now(),
                freshness=request.freshness,
                confidence="usable",
                limits=_dedupe(limits),
                citations=[{"label": title or source_url, "url": source_url}, {"label": route.name, "url": final_url}],
            )
            reason = f"route={route.name};phase={route.phase};status={status};tried={','.join(tried)};trace={','.join(trace)}"
            return (
                result,
                ResearchAttempt(
                    self.module_id,
                    "ok",
                    reason,
                    final_url,
                    next_allowed=_untried_route_names(routes, evaluated),
                    weight=self.weight,
                ),
            )

        reason = "all_routes_failed"
        if failures:
            reason = f"{reason}:{';'.join(failures[:6])}"
        if trace:
            reason = f"{reason};trace={','.join(trace[:6])}"
        return (
            None,
            ResearchAttempt(
                self.module_id,
                "error",
                reason,
                source_url,
                next_allowed=_untried_route_names(routes, evaluated),
                weight=self.weight,
            ),
        )

    def _fetch(self, url: str) -> tuple[int, str, str, str]:
        opener = build_opener(_NoRedirect)
        current = url
        for _ in range(DEFAULT_MAX_REDIRECTS + 1):
            req = Request(
                current,
                headers={
                    "User-Agent": _browserish_user_agent(current),
                    "Accept": "text/html,application/xhtml+xml,application/xml,text/xml,text/plain;q=0.9,*/*;q=0.7",
                    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
                    "Referer": _referer_for(current),
                },
            )
            try:
                with opener.open(req, timeout=self.timeout_seconds) as resp:
                    status = int(getattr(resp, "status", 200))
                    content_type = resp.headers.get("content-type", "")
                    raw = resp.read(self.max_bytes + 1)
                    return status, _decode(raw[: self.max_bytes], content_type), current, content_type
            except HTTPError as exc:
                if exc.code in {301, 302, 303, 307, 308}:
                    location = exc.headers.get("location")
                    if not location:
                        raise
                    next_url = urljoin(current, location)
                    safe, reason = classify_url(next_url)
                    if not safe:
                        raise URLError(f"ssrf_redirect_blocked:{reason}")
                    current = next_url
                    continue
                content_type = exc.headers.get("content-type", "")
                raw = exc.read(self.max_bytes + 1)
                return exc.code, _decode(raw[: self.max_bytes], content_type), current, content_type
        raise URLError("too_many_redirects")


def _source_url(source_hint: str) -> str:
    if source_hint.lower().startswith("insane:"):
        return source_hint.split(":", 1)[1].strip()
    return source_hint.strip()


def _routes_for(source_url: str) -> list[FetchRoute]:
    routes: list[FetchRoute] = []
    reddit_rss = _reddit_rss_url(source_url)
    if reddit_rss:
        routes.append(FetchRoute("reddit_rss", "0", reddit_rss, parser="feed"))
    routes.append(FetchRoute("direct", "0", source_url))
    routes.append(FetchRoute("jina_reader", "1", f"{JINA_READER_BASE}{source_url}", parser="markdown", external=True))
    return _dedupe_routes(routes)


def _reddit_rss_url(source_url: str) -> str:
    parsed = urlsplit(source_url)
    host = (parsed.hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    if host not in {"reddit.com", "old.reddit.com"} and not host.endswith(".reddit.com"):
        return ""
    path = parsed.path.rstrip("/")
    if not path:
        path = "/"
    if not path.endswith(".rss"):
        path = f"{path}.rss" if path != "/" else "/.rss"
    query = dict(parse_qsl(parsed.query, keep_blank_values=False))
    query.setdefault("limit", "100")
    return urlunsplit((parsed.scheme or "https", parsed.netloc, path, urlencode(query), ""))


def _parse_body(body: str, content_type: str, route: FetchRoute) -> tuple[str, str, list[str]]:
    if route.parser == "markdown":
        title = _title_from_markdown(body)
        return body.strip(), title, ["markdown_reader"]
    lowered = content_type.lower()
    if route.parser == "feed" or "xml" in lowered or "rss" in lowered or "atom" in lowered:
        text, title = _feed_to_markdown(body)
        if text:
            return text, title, ["feed_reader"]
    if "json" in lowered:
        text, title = _json_to_markdown(body)
        if text:
            return text, title, ["json_reader"]
    title = _extract_title(body)
    metadata = _extract_metadata(body)
    text = _html_to_text(body) if "<" in body[:2000] else body.strip()
    parts = []
    if metadata.get("description"):
        parts.append(metadata["description"])
    if metadata.get("article_body"):
        parts.append(metadata["article_body"])
    if text:
        parts.append(text)
    limits = ["metadata_scanned"] if metadata else []
    return "\n\n".join(_dedupe([part.strip() for part in parts if part.strip()])), title or metadata.get("title", ""), limits


def _feed_to_markdown(body: str) -> tuple[str, str]:
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return "", ""
    channel_title = _first_text(root, [".//channel/title", ".//{http://www.w3.org/2005/Atom}title", ".//title"])
    lines = [f"# {channel_title or 'Feed'}"]
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    for item in items[:25]:
        title = _first_text(item, ["title", "{http://www.w3.org/2005/Atom}title"]) or "Untitled"
        link = _first_text(item, ["link", "{http://www.w3.org/2005/Atom}link"])
        summary = _first_text(
            item,
            ["description", "summary", "{http://www.w3.org/2005/Atom}summary", "{http://www.w3.org/2005/Atom}content"],
        )
        clean = _compact(_html_to_text(summary or ""))
        line = f"- {title}"
        if link:
            line += f" ({link})"
        if clean:
            line += f": {clean}"
        lines.append(line)
    return "\n".join(lines).strip(), channel_title


def _json_to_markdown(body: str) -> tuple[str, str]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return "", ""
    title = ""
    lines: list[str] = []
    if isinstance(payload, dict):
        title = str(payload.get("title") or payload.get("name") or "")
        for key in ("title", "name", "description", "summary", "text", "body", "articleBody"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                lines.append(f"{key}: {value.strip()}")
    if isinstance(payload, list):
        for item in payload[:20]:
            if isinstance(item, dict):
                label = str(item.get("title") or item.get("name") or item.get("id") or "item")
                text = str(item.get("description") or item.get("summary") or item.get("text") or "").strip()
                lines.append(f"- {label}: {text}" if text else f"- {label}")
    return "\n".join(lines).strip(), title


def _extract_title(body: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", body or "")
    if not match:
        return ""
    return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()


def _extract_metadata(body: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for match in re.finditer(r"(?is)<meta\s+([^>]+)>", body or ""):
        attrs = _attrs(match.group(1))
        name = (attrs.get("property") or attrs.get("name") or "").lower()
        content = html.unescape(attrs.get("content") or "").strip()
        if not content:
            continue
        if name in {"og:title", "twitter:title"}:
            metadata.setdefault("title", content)
        elif name in {"description", "og:description", "twitter:description"}:
            metadata.setdefault("description", content)
    for match in re.finditer(r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', body or ""):
        try:
            payload = json.loads(html.unescape(match.group(1)).strip())
        except json.JSONDecodeError:
            continue
        for item in _jsonld_items(payload):
            for key in ("headline", "name"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    metadata.setdefault("title", value.strip())
            desc = item.get("description")
            if isinstance(desc, str) and desc.strip():
                metadata.setdefault("description", desc.strip())
            article_body = item.get("articleBody")
            if isinstance(article_body, str) and article_body.strip():
                metadata.setdefault("article_body", article_body.strip())
    return metadata


def _jsonld_items(payload) -> list[dict]:
    if isinstance(payload, dict):
        graph = payload.get("@graph")
        items = graph if isinstance(graph, list) else [payload]
        return [item for item in items if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _attrs(raw: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in re.finditer(r'''([:\w-]+)\s*=\s*(['"])(.*?)\2''', raw or ""):
        attrs[match.group(1).lower()] = match.group(3)
    return attrs


def _html_to_text(body: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", body or "")
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</(p|div|section|article|li|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _auth_wall_reason(status: int, body: str) -> str:
    lowered = _compact(_html_to_text(body)).lower()
    if status in {401, 407}:
        return "auth_required"
    paywall_patterns = ("subscribe to continue", "subscription required", "paywall", "paid subscribers only")
    auth_patterns = (
        "sign in to continue",
        "log in to continue",
        "login required",
        "authentication required",
        "threads • log in",
        "threads - log in",
        "log in with your instagram",
    )
    if any(pattern in lowered for pattern in paywall_patterns):
        return "paywall_detected"
    if any(pattern in lowered for pattern in auth_patterns):
        return "auth_required"
    return ""


def _decode(raw: bytes, content_type: str) -> str:
    charset = "utf-8"
    match = re.search(r"charset=([\w.-]+)", content_type or "", re.I)
    if match:
        charset = match.group(1)
    return raw.decode(charset, errors="replace")


def _status_reason(status: int) -> str:
    if status == 403:
        return "blocked"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    return f"http_{status}"


def _title_from_markdown(markdown: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()[:120]
        if stripped:
            return stripped[:120]
    return ""


def _first_text(root, paths: list[str]) -> str:
    for path in paths:
        node = root.find(path)
        if node is not None:
            if path.endswith("link") and node.get("href"):
                return str(node.get("href") or "").strip()
            if node.text and node.text.strip():
                return html.unescape(node.text.strip())
    return ""


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _browserish_user_agent(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if host.endswith("reddit.com"):
        return "AgentlasResearchEngine/0.1 (+https://agentlas.cloud; public RSS reader)"
    return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 AgentlasResearchEngine/0.1"


def _referer_for(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))


def _platform_for(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    if "reddit.com" in host:
        return "reddit"
    if "threads.com" in host or "threads.net" in host:
        return "threads"
    return "web"


def _platform_fallback_limits(url: str, route: FetchRoute) -> list[str]:
    platform = _platform_for(url)
    if platform == "reddit":
        fallback = "public_rss_fallback" if route.name == "reddit_rss" else "public_html_fallback"
        return [fallback, "oauth_preferred"]
    if platform == "threads":
        return ["public_html_fallback", "official_api_preferred"]
    return []


def _thin_public_shell_reason(*, source_url: str, title: str, text: str) -> str:
    platform = _platform_for(source_url)
    compact_text = _compact(text).lower()
    compact_title = _compact(title).lower()
    if platform == "threads" and compact_title in {"threads", "threads • log in", "threads - log in"}:
        if compact_text in {"threads", "threads threads"} or len(compact_text) < 80:
            return "thin_public_shell"
    return ""


def _trace_limits(trace: list[str]) -> list[str]:
    return [f"trace:{item}" for item in trace[:6]]


def _untried_route_names(routes: list[FetchRoute], evaluated: list[str]) -> list[str]:
    evaluated_set = set(evaluated)
    return [route.name for route in routes if route.name not in evaluated_set]


def _untried_routes_limits(routes: list[FetchRoute], evaluated: list[str]) -> list[str]:
    names = _untried_route_names(routes, evaluated)
    return [f"untried_routes:{','.join(names)}"] if names else []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _dedupe_routes(routes: list[FetchRoute]) -> list[FetchRoute]:
    seen: set[str] = set()
    out: list[FetchRoute] = []
    for route in routes:
        if route.url in seen:
            continue
        seen.add(route.url)
        out.append(route)
    return out
