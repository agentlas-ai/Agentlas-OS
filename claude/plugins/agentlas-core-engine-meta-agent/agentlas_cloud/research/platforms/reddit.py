"""Reddit public reader cartridge.

The durable product path should be OAuth-first. This adapter provides a
truthful-User-Agent public JSON fallback for explicit Reddit URLs and labels the
result as a fallback so callers do not confuse it with approved API coverage.
"""

from __future__ import annotations

import base64
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from agentlas_cloud.networking.bootstrap import utc_now

from ..contracts import ResearchAttempt, ResearchModuleManifest, ResearchRequest, ResearchResult, _stable_hash
from ..policy import classify_url
from ..redaction import redacted_exception_reason


class RedditOAuthAdapter:
    module_id = "platform.reddit.oauth"
    capabilities = ("search.platform.reddit", "read.platform.reddit", "read.url")
    weight = "credentialed_medium"
    manifest = ResearchModuleManifest(
        module_id=module_id,
        capabilities=list(capabilities),
        weight=weight,
        slot="platform",
        activation="configured",
        requires=["oauth:reddit", "permission:read"],
        permissions=["network:oauth.reddit.com"],
        default_state="available_if_configured",
        privacy="no_raw_token_to_model; rate_limit_headers_only",
        failure_modes=["module_unavailable", "token_exchange_failed", "rate_limited", "auth_required", "blocked", "partial_comments", "ssrf_blocked"],
        install_hint=(
            "Set AGENTLAS_REDDIT_BEARER_TOKEN/REDDIT_BEARER_TOKEN, or configure "
            "AGENTLAS_REDDIT_CLIENT_ID plus AGENTLAS_REDDIT_CLIENT_SECRET for app-only OAuth."
        ),
    )

    def __init__(self, *, timeout_seconds: int = 20, max_comments: int = 200):
        self.timeout_seconds = timeout_seconds
        self.max_comments = max_comments

    def can_handle(self, source_hint: str, request: ResearchRequest) -> bool:
        return _is_reddit_source_hint(source_hint)

    def read(self, source_hint: str, request: ResearchRequest) -> tuple[ResearchResult | None, ResearchAttempt]:
        token, token_source, token_error = self._oauth_token()
        if not token:
            return (
                None,
                ResearchAttempt(
                    self.module_id,
                    "module_unavailable",
                    token_error or "reddit_oauth_credentials_not_configured",
                    source_hint,
                    weight=self.weight,
                ),
            )
        reddit_url = _reddit_source_url(source_hint)
        if not reddit_url:
            return None, ResearchAttempt(self.module_id, "error", "invalid_reddit_source_hint", source_hint, weight=self.weight)
        oauth_url = _oauth_url(reddit_url)
        safe, reason = classify_url(oauth_url)
        if not safe:
            return (
                ResearchResult.blocked(reddit_url, reason=f"ssrf_blocked:{reason}"),
                ResearchAttempt(self.module_id, "blocked", f"ssrf_blocked:{reason}", reddit_url, weight=self.weight),
            )

        try:
            payload, rate_limits = self._fetch_oauth_json(oauth_url, token=token)
        except HTTPError as exc:
            reason = _status_reason(exc.code)
            return (
                ResearchResult.blocked(reddit_url, reason=reason),
                ResearchAttempt(self.module_id, "blocked", f"{reason}:{exc.code}", oauth_url, weight=self.weight),
            )
        except (URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            return (
                None,
                ResearchAttempt(self.module_id, "error", redacted_exception_reason(exc, max_length=160), oauth_url, weight=self.weight),
            )

        result = _payload_to_result(payload, reddit_url, oauth_url, self.max_comments, request, base_limits=["reddit_oauth"])
        result.limits = _dedupe(result.limits + [token_source] + rate_limits)
        result.citations = [{"label": result.title or "Reddit", "url": reddit_url}, {"label": "reddit-oauth", "url": oauth_url}]
        return result, ResearchAttempt(self.module_id, "ok", "oauth_read", oauth_url, weight=self.weight)

    def _oauth_token(self) -> tuple[str, str, str]:
        bearer = self._bearer_token()
        if bearer:
            return bearer, "reddit_bearer_env", ""
        client_id = os.environ.get("AGENTLAS_REDDIT_CLIENT_ID") or os.environ.get("REDDIT_CLIENT_ID") or ""
        client_secret = os.environ.get("AGENTLAS_REDDIT_CLIENT_SECRET") or os.environ.get("REDDIT_CLIENT_SECRET") or ""
        if client_id and client_secret:
            try:
                return self._fetch_app_only_token(client_id=client_id, client_secret=client_secret), "reddit_app_only_oauth", ""
            except (HTTPError, URLError, OSError, ValueError, json.JSONDecodeError) as exc:
                return "", "", redacted_exception_reason(exc, max_length=160, prefix="reddit_app_only_token_error:")
        return "", "", "reddit_oauth_credentials_not_configured"

    def _bearer_token(self) -> str:
        return os.environ.get("AGENTLAS_REDDIT_BEARER_TOKEN") or os.environ.get("REDDIT_BEARER_TOKEN") or ""

    def _fetch_app_only_token(self, *, client_id: str, client_secret: str) -> str:
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        data = urlencode({"grant_type": "client_credentials"}).encode("ascii")
        req = Request(
            "https://www.reddit.com/api/v1/access_token",
            data=data,
            headers={
                "Authorization": f"Basic {basic}",
                "User-Agent": "python:agentlas-research-engine:v0.1 (by /u/agentlas)",
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            method="POST",
        )
        with urlopen(req, timeout=self.timeout_seconds) as resp:
            raw = resp.read(100_000)
        payload = json.loads(raw.decode("utf-8", errors="replace"))
        token = str(payload.get("access_token") or "")
        if not token:
            raise ValueError("reddit_access_token_missing")
        return token

    def _fetch_oauth_json(self, url: str, *, token: str):
        req = Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "python:agentlas-research-engine:v0.1 (by /u/agentlas)",
                "Accept": "application/json",
            },
        )
        with urlopen(req, timeout=self.timeout_seconds) as resp:
            raw = resp.read(1_000_000)
            rate_limits = _rate_limit_limits(resp.headers)
        return json.loads(raw.decode("utf-8", errors="replace")), rate_limits


class RedditPublicAdapter:
    module_id = "platform.reddit"
    capabilities = ("search.platform.reddit", "read.platform.reddit", "read.url")
    weight = "adaptive_medium"
    manifest = ResearchModuleManifest(
        module_id=module_id,
        capabilities=list(capabilities),
        weight=weight,
        slot="platform",
        activation="auto_for_reddit_urls",
        requires=["recommended_oauth:reddit"],
        permissions=["network:www.reddit.com", "network:reddit.com", "network:old.reddit.com"],
        default_state="public_fallback_available",
        privacy="no_raw_token_to_model",
        failure_modes=["rate_limited", "auth_required", "blocked", "partial_comments", "public_fallback_only"],
        install_hint="Public fallback works for explicit Reddit URLs; prefer platform.reddit.oauth for durable reads.",
    )

    def __init__(self, *, timeout_seconds: int = 20, max_comments: int = 200):
        self.timeout_seconds = timeout_seconds
        self.max_comments = max_comments

    def can_handle(self, source_hint: str, request: ResearchRequest) -> bool:
        return _is_reddit_source_hint(source_hint)

    def read(self, source_hint: str, request: ResearchRequest) -> tuple[ResearchResult | None, ResearchAttempt]:
        reddit_url = _reddit_source_url(source_hint)
        if not reddit_url:
            return None, ResearchAttempt(self.module_id, "error", "invalid_reddit_source_hint", source_hint, weight=self.weight)
        json_url = _json_url(reddit_url)
        safe, reason = classify_url(json_url)
        if not safe:
            return (
                ResearchResult.blocked(reddit_url, reason=f"ssrf_blocked:{reason}"),
                ResearchAttempt(self.module_id, "blocked", f"ssrf_blocked:{reason}", reddit_url, weight=self.weight),
            )

        try:
            payload = self._fetch_json(json_url)
        except HTTPError as exc:
            if exc.code in {403, 404, 429}:
                return self._read_rss_fallback(reddit_url, request, reason=f"json_{_status_reason(exc.code)}:{exc.code}")
            reason = _status_reason(exc.code)
            return (
                ResearchResult.blocked(reddit_url, reason=reason),
                ResearchAttempt(self.module_id, "blocked", f"{reason}:{exc.code}", json_url, weight=self.weight),
            )
        except (URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            fallback = self._read_rss_fallback(reddit_url, request, reason=f"json_error:{type(exc).__name__}")
            if fallback[0] is not None:
                return fallback
            return (
                None,
                ResearchAttempt(self.module_id, "error", redacted_exception_reason(exc, max_length=160), json_url, weight=self.weight),
            )

        result = _payload_to_result(payload, reddit_url, json_url, self.max_comments, request)
        return result, ResearchAttempt(self.module_id, "ok", "public_json_fallback", json_url, weight=self.weight)

    def _read_rss_fallback(self, source_hint: str, request: ResearchRequest, *, reason: str) -> tuple[ResearchResult | None, ResearchAttempt]:
        rss_url = _rss_url(source_hint)
        safe, safe_reason = classify_url(rss_url)
        if not safe:
            return (
                ResearchResult.blocked(source_hint, reason=f"ssrf_blocked:{safe_reason}"),
                ResearchAttempt(self.module_id, "blocked", f"ssrf_blocked:{safe_reason}", rss_url, weight=self.weight),
            )
        try:
            body = self._fetch_text(rss_url)
        except HTTPError as exc:
            status_reason = _status_reason(exc.code)
            return (
                ResearchResult.blocked(source_hint, reason=status_reason),
                ResearchAttempt(self.module_id, "blocked", f"{reason};rss_{status_reason}:{exc.code}", rss_url, weight=self.weight),
            )
        except (URLError, OSError, ValueError, ElementTree.ParseError) as exc:
            return (
                None,
                ResearchAttempt(
                    self.module_id,
                    "error",
                    redacted_exception_reason(exc, max_length=160, prefix=f"{reason};rss_error:"),
                    rss_url,
                    weight=self.weight,
                ),
            )
        result = _rss_to_result(body, source_hint, rss_url, request)
        return result, ResearchAttempt(self.module_id, "ok", f"public_rss_fallback;{reason}", rss_url, weight=self.weight)

    def _fetch_json(self, url: str):
        req = Request(
            url,
            headers={
                "User-Agent": "python:agentlas-research-engine:v0.1 (by /u/agentlas)",
                "Accept": "application/json",
            },
        )
        with urlopen(req, timeout=self.timeout_seconds) as resp:
            raw = resp.read(1_000_000)
        return json.loads(raw.decode("utf-8", errors="replace"))

    def _fetch_text(self, url: str) -> str:
        req = Request(
            url,
            headers={
                "User-Agent": "python:agentlas-research-engine:v0.1 (by /u/agentlas)",
                "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml;q=0.9,*/*;q=0.5",
            },
        )
        with urlopen(req, timeout=self.timeout_seconds) as resp:
            raw = resp.read(1_000_000)
        return raw.decode("utf-8", errors="replace")


def _json_url(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/")
    if not path.endswith(".json"):
        path = f"{path}.json" if path else "/.json"
    query = dict(parse_qsl(parsed.query, keep_blank_values=False))
    query.setdefault("limit", "100")
    query.setdefault("raw_json", "1")
    host = parsed.netloc
    if host.startswith("old.reddit.com"):
        host = host.replace("old.reddit.com", "www.reddit.com", 1)
    return urlunsplit((parsed.scheme or "https", host, path, urlencode(query), ""))


def _is_reddit_source_hint(source_hint: str) -> bool:
    return bool(_reddit_source_url(source_hint))


def _reddit_source_url(source_hint: str) -> str:
    source_hint = source_hint.strip()
    parsed = urlsplit(source_hint)
    if parsed.scheme in {"http", "https"}:
        host = (parsed.hostname or "").lower()
        host = host[4:] if host.startswith("www.") else host
        return source_hint if host in {"reddit.com", "old.reddit.com"} or host.endswith(".reddit.com") else ""

    lowered = source_hint.lower()
    if lowered.startswith(("reddit:subreddit:", "reddit:r:")):
        name = source_hint.split(":", 2)[2].strip()
        subreddit = _safe_reddit_name(name, prefixes=("r/", "/r/"))
        return f"https://www.reddit.com/r/{subreddit}/" if subreddit else ""
    if lowered.startswith(("reddit:user:", "reddit:u:")):
        name = source_hint.split(":", 2)[2].strip()
        username = _safe_reddit_name(name, prefixes=("u/", "/u/", "user/", "/user/"))
        return f"https://www.reddit.com/user/{username}/" if username else ""
    if lowered.startswith("reddit:search:"):
        query = source_hint.split(":", 2)[2].strip()
        if not query:
            return ""
        params = {"q": query[:240], "sort": "relevance", "t": "month"}
        return f"https://www.reddit.com/search/?{urlencode(params)}"
    return ""


def _safe_reddit_name(value: str, *, prefixes: tuple[str, ...]) -> str:
    value = value.strip()
    lowered = value.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            value = value[len(prefix) :]
            break
    return value if re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_]{1,24}", value) else ""


def _oauth_url(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/")
    if not path.endswith(".json"):
        path = f"{path}.json" if path else "/.json"
    query = dict(parse_qsl(parsed.query, keep_blank_values=False))
    query.setdefault("limit", "100")
    query.setdefault("raw_json", "1")
    return urlunsplit(("https", "oauth.reddit.com", path, urlencode(query), ""))


def _rss_url(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path.rstrip("/")
    if not path:
        path = "/"
    if not path.endswith(".rss"):
        path = f"{path}.rss" if path != "/" else "/.rss"
    query = dict(parse_qsl(parsed.query, keep_blank_values=False))
    query.setdefault("limit", "100")
    host = parsed.netloc
    if host.startswith("old.reddit.com"):
        host = host.replace("old.reddit.com", "www.reddit.com", 1)
    return urlunsplit((parsed.scheme or "https", host, path, urlencode(query), ""))


def _payload_to_result(
    payload,
    source_url: str,
    json_url: str,
    max_comments: int,
    request: ResearchRequest,
    *,
    base_limits: list[str] | None = None,
) -> ResearchResult:
    title = "Reddit"
    lines: list[str] = []
    comments_seen = 0

    if isinstance(payload, list) and payload:
        post = _first_listing_child(payload[0])
        if post:
            data = post.get("data") or {}
            title = str(data.get("title") or title)
            subreddit = data.get("subreddit")
            author = data.get("author")
            lines.append(f"# {title}")
            meta = " ".join(part for part in [f"r/{subreddit}" if subreddit else "", f"u/{author}" if author else ""] if part)
            if meta:
                lines.append(meta)
            selftext = str(data.get("selftext") or "").strip()
            if selftext:
                lines.append("")
                lines.append(selftext)
        if len(payload) > 1:
            comments = ((payload[1].get("data") or {}).get("children") or []) if isinstance(payload[1], dict) else []
            comment_lines, comments_seen = _flatten_comments(comments, max_comments=max_comments)
            if comment_lines:
                lines.append("")
                lines.append("## Comments")
                lines.extend(comment_lines)
    elif isinstance(payload, dict):
        children = _listing_children(payload)
        if children:
            first = children[0].get("data") or {}
            title = str(first.get("display_name_prefixed") or first.get("title") or "Reddit listing")
            lines.append(f"# {title}")
            for child in children[:25]:
                data = child.get("data") or {}
                item_title = str(data.get("title") or data.get("display_name_prefixed") or "").strip()
                if not item_title:
                    continue
                permalink = str(data.get("permalink") or data.get("url") or "").strip()
                if permalink.startswith("/"):
                    permalink = f"https://www.reddit.com{permalink}"
                subreddit = str(data.get("subreddit") or "").strip()
                author = str(data.get("author") or "").strip()
                meta = " ".join(part for part in [f"r/{subreddit}" if subreddit else "", f"u/{author}" if author else ""] if part)
                line = f"- {item_title}"
                if meta:
                    line += f" ({meta})"
                if permalink:
                    line += f" {permalink}"
                text = _compact(str(data.get("selftext") or data.get("public_description") or "").strip())
                if text:
                    line += f": {text[:280]}"
                lines.append(line)
            if len(children) > 25:
                lines.append(f"- ... {len(children) - 25} more items omitted")

    markdown = "\n".join(line for line in lines if line is not None).strip()
    limits = list(base_limits or ["public_json_fallback", "oauth_preferred"])
    if comments_seen >= max_comments:
        limits.append("partial_comments")
    if isinstance(payload, dict) and len(_listing_children(payload)) > 25:
        limits.append("partial_listing")
    return ResearchResult(
        source_id=_stable_hash(source_url),
        url=source_url,
        title=title,
        platform="reddit",
        content_markdown=markdown,
        extracted_at=utc_now(),
        freshness=request.freshness,
        confidence="usable" if markdown else "weak",
        limits=limits,
        citations=[{"label": title, "url": source_url}, {"label": "reddit-json", "url": json_url}],
    )


def _rss_to_result(body: str, source_url: str, rss_url: str, request: ResearchRequest) -> ResearchResult:
    root = ElementTree.fromstring(body)
    title = _first_text(root, [".//channel/title", ".//{http://www.w3.org/2005/Atom}title", ".//title"]) or "Reddit"
    lines = [f"# {title}"]
    items = root.findall(".//item")
    if not items:
        items = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    citations = [{"label": title, "url": source_url}, {"label": "reddit-rss", "url": rss_url}]
    for item in items[:25]:
        item_title = _first_text(item, ["title", "{http://www.w3.org/2005/Atom}title"]) or "Untitled"
        link = _first_text(item, ["link", "{http://www.w3.org/2005/Atom}link"])
        summary = _first_text(
            item,
            ["description", "summary", "{http://www.w3.org/2005/Atom}summary", "{http://www.w3.org/2005/Atom}content"],
        )
        clean = _compact(_strip_html(summary))
        line = f"- {item_title}"
        if link:
            line += f" ({link})"
            citations.append({"label": item_title, "url": link})
        if clean:
            line += f": {clean}"
        lines.append(line)
    limits = ["public_rss_fallback", "oauth_preferred", "listing_only"]
    if len(items) > 25:
        limits.append("partial_feed")
    return ResearchResult(
        source_id=_stable_hash(source_url),
        url=source_url,
        title=title,
        platform="reddit",
        content_markdown="\n".join(lines).strip(),
        extracted_at=utc_now(),
        freshness=request.freshness,
        confidence="usable" if len(lines) > 1 else "weak",
        limits=limits,
        citations=citations[:50],
    )


def _first_listing_child(listing) -> dict | None:
    if not isinstance(listing, dict):
        return None
    children = (listing.get("data") or {}).get("children") or []
    for child in children:
        if isinstance(child, dict) and child.get("kind") != "more":
            return child
    return None


def _listing_children(listing) -> list[dict]:
    if not isinstance(listing, dict):
        return []
    children = (listing.get("data") or {}).get("children") or []
    return [child for child in children if isinstance(child, dict) and child.get("kind") != "more"]


def _rate_limit_limits(headers) -> list[str]:
    limits: list[str] = []
    for header, label in (
        ("x-ratelimit-used", "reddit_rate_used"),
        ("x-ratelimit-remaining", "reddit_rate_remaining"),
        ("x-ratelimit-reset", "reddit_rate_reset"),
    ):
        value = headers.get(header) or headers.get(header.title())
        if value is not None:
            limits.append(f"{label}:{str(value)[:40]}")
    return limits


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _flatten_comments(children, *, max_comments: int, depth: int = 0) -> tuple[list[str], int]:
    lines: list[str] = []
    seen = 0
    for child in children:
        if seen >= max_comments:
            break
        if not isinstance(child, dict) or child.get("kind") == "more":
            continue
        data = child.get("data") or {}
        body = str(data.get("body") or "").strip()
        author = str(data.get("author") or "[deleted]")
        if body:
            indent = "  " * min(depth, 4)
            lines.append(f"{indent}- u/{author}: {_compact(body)}")
            seen += 1
        replies = data.get("replies")
        if isinstance(replies, dict):
            nested = (replies.get("data") or {}).get("children") or []
            nested_lines, nested_seen = _flatten_comments(
                nested,
                max_comments=max_comments - seen,
                depth=depth + 1,
            )
            lines.extend(nested_lines)
            seen += nested_seen
    return lines, seen


def _compact(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _strip_html(text: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", text or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return text


def _first_text(root, paths: list[str]) -> str:
    for path in paths:
        node = root.find(path)
        if node is not None:
            if path.endswith("link") and node.get("href"):
                return str(node.get("href") or "").strip()
            if node.text and node.text.strip():
                return node.text.strip()
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
