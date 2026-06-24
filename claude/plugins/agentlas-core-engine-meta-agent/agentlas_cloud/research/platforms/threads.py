"""Threads official API cartridge.

Threads public search is credentialed and permission-gated. This adapter only
uses the official Graph endpoint and returns `module_unavailable` when no token
is configured; it does not scrape Threads pages silently.
"""

from __future__ import annotations

import html
import json
import os
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from agentlas_cloud.networking.bootstrap import utc_now

from ..contracts import ResearchAttempt, ResearchModuleManifest, ResearchRequest, ResearchResult, _stable_hash
from ..policy import DEFAULT_MAX_BYTES, DEFAULT_MAX_REDIRECTS, classify_url
from ..redaction import redacted_exception_reason


THREADS_GRAPH_BASE = "https://graph.threads.net/v1.0"
THREADS_SEARCH_ENDPOINT = f"{THREADS_GRAPH_BASE}/keyword_search"
THREADS_PROFILE_FIELDS = "id,username,name,threads_profile_picture_url,threads_biography,is_verified"
THREADS_MEDIA_FIELDS = "id,text,media_type,permalink,timestamp,username,has_replies,is_quote_post,is_reply"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


class ThreadsSearchAdapter:
    module_id = "platform.threads"
    capabilities = ("search.platform.threads", "read.platform.threads", "read.platform.threads_profile")
    weight = "credentialed_medium"
    manifest = ResearchModuleManifest(
        module_id=module_id,
        capabilities=list(capabilities),
        weight=weight,
        slot="platform",
        activation="configured",
        requires=["oauth:threads", "permission:threads_basic", "permission:threads_keyword_search"],
        permissions=["network:graph.threads.net"],
        default_state="available_if_configured",
        privacy="no_raw_token_to_model",
        failure_modes=["module_unavailable", "permission_required", "rate_limited", "sensitive_query_empty", "empty_results"],
        install_hint="Set THREADS_ACCESS_TOKEN or AGENTLAS_THREADS_ACCESS_TOKEN and choose loadout=social/full.",
    )

    def __init__(self, *, timeout_seconds: int = 20):
        self.timeout_seconds = timeout_seconds

    def can_handle(self, source_hint: str, request: ResearchRequest) -> bool:
        lowered = source_hint.lower()
        return (
            lowered.startswith("threads:keyword:")
            or lowered.startswith("threads:tag:")
            or lowered.startswith("threads:profile:")
            or lowered.startswith("threads:lookup:")
            or lowered.startswith("threads:posts:")
            or lowered.startswith("threads:user:")
            or lowered.startswith("threads:replies:")
            or lowered == "threads:me"
        )

    def read(self, source_hint: str, request: ResearchRequest) -> tuple[ResearchResult | None, ResearchAttempt]:
        token = self._access_token()
        if not token:
            return (
                None,
                ResearchAttempt(
                    self.module_id,
                    "module_unavailable",
                    "THREADS_ACCESS_TOKEN not configured",
                    source_hint,
                    weight=self.weight,
                ),
            )

        mode, query = _parse_source_hint(source_hint)
        if not query:
            return None, ResearchAttempt(self.module_id, "error", "empty_threads_query", source_hint, weight=self.weight)

        try:
            if mode in {"keyword", "tag"}:
                payload = self._search(query, mode=mode, token=token)
                result = _search_payload_to_result(payload, query=query, mode=mode, request=request)
                return result, ResearchAttempt(self.module_id, "ok", f"{mode}_search", _safe_endpoint(query, mode), weight=self.weight)
            if mode == "profile":
                payload = self._profile(query, token=token)
                result = _profile_payload_to_result(payload, target=query, request=request)
                return result, ResearchAttempt(self.module_id, "ok", "profile_read", _safe_endpoint(query, mode), weight=self.weight)
            if mode == "lookup":
                payload = self._profile_lookup(query, token=token)
                result = _profile_payload_to_result(payload, target=query, request=request, lookup=True)
                return result, ResearchAttempt(self.module_id, "ok", "profile_lookup", _safe_endpoint(query, mode), weight=self.weight)
            if mode == "posts":
                payload = self._user_posts(query, token=token)
                result = _posts_payload_to_result(payload, target=query, mode=mode, request=request)
                return result, ResearchAttempt(self.module_id, "ok", "posts_read", _safe_endpoint(query, mode), weight=self.weight)
            if mode == "replies":
                payload = self._user_replies(query, token=token)
                result = _posts_payload_to_result(payload, target=query, mode=mode, request=request)
                return result, ResearchAttempt(self.module_id, "ok", "replies_read", _safe_endpoint(query, mode), weight=self.weight)
            return None, ResearchAttempt(self.module_id, "error", "unsupported_threads_source_hint", source_hint, weight=self.weight)
        except HTTPError as exc:
            reason = _status_reason(exc.code)
            return (
                ResearchResult.blocked(source_hint, reason=reason),
                ResearchAttempt(self.module_id, "blocked", f"{reason}:{exc.code}", _safe_endpoint(query, mode), weight=self.weight),
            )
        except (URLError, OSError, ValueError, json.JSONDecodeError) as exc:
            return (
                None,
                ResearchAttempt(self.module_id, "error", redacted_exception_reason(exc, max_length=160), _safe_endpoint(query, mode), weight=self.weight),
            )

    def _access_token(self) -> str:
        return os.environ.get("AGENTLAS_THREADS_ACCESS_TOKEN") or os.environ.get("THREADS_ACCESS_TOKEN") or ""

    def _search(self, query: str, *, mode: str, token: str):
        params = {
            "q": query,
            "search_mode": "TAG" if mode == "tag" else "KEYWORD",
            "search_type": "RECENT",
            "fields": "id,text,media_type,permalink,timestamp,username,has_replies,is_quote_post,is_reply",
            "limit": "25",
        }
        url = f"{THREADS_SEARCH_ENDPOINT}?{urlencode(params)}"
        return self._fetch_json(url, token=token)

    def _profile(self, user_id: str, *, token: str):
        url = f"{THREADS_GRAPH_BASE}/{user_id}?{urlencode({'fields': THREADS_PROFILE_FIELDS})}"
        return self._fetch_json(url, token=token)

    def _profile_lookup(self, username: str, *, token: str):
        username = username[1:] if username.startswith("@") else username
        params = {"username": username, "fields": THREADS_PROFILE_FIELDS}
        url = f"{THREADS_GRAPH_BASE}/profile_lookup?{urlencode(params)}"
        return self._fetch_json(url, token=token)

    def _user_posts(self, user_id: str, *, token: str):
        params = {"fields": THREADS_MEDIA_FIELDS, "limit": "25"}
        url = f"{THREADS_GRAPH_BASE}/{user_id}/threads?{urlencode(params)}"
        return self._fetch_json(url, token=token)

    def _user_replies(self, user_id: str, *, token: str):
        params = {"fields": THREADS_MEDIA_FIELDS, "limit": "25"}
        url = f"{THREADS_GRAPH_BASE}/{user_id}/replies?{urlencode(params)}"
        return self._fetch_json(url, token=token)

    def _fetch_json(self, url: str, *, token: str):
        req = Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "User-Agent": "AgentlasResearchEngine/0.1 (+https://agentlas.cloud)",
            },
        )
        with urlopen(req, timeout=self.timeout_seconds) as resp:
            raw = resp.read(1_000_000)
        return json.loads(raw.decode("utf-8", errors="replace"))


class ThreadsPublicWebAdapter:
    module_id = "platform.threads.public"
    capabilities = ("read.platform.threads_public", "read.url")
    weight = "adaptive_medium"
    manifest = ResearchModuleManifest(
        module_id=module_id,
        capabilities=list(capabilities),
        weight=weight,
        slot="platform",
        activation="auto_for_threads_urls",
        requires=[],
        permissions=["network:www.threads.net", "network:threads.net", "network:www.threads.com", "network:threads.com"],
        default_state="public_fallback_available",
        privacy="public_html_only; no_raw_token_to_model",
        failure_modes=["blocked", "auth_required", "not_found", "rate_limited", "ssrf_blocked", "thin_public_html"],
        install_hint="Use explicit Threads public URLs or username/profile hints; official Graph API remains the durable search path.",
    )

    def __init__(self, *, timeout_seconds: int = 20, max_bytes: int = DEFAULT_MAX_BYTES):
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes

    def can_handle(self, source_hint: str, request: ResearchRequest) -> bool:
        return bool(_threads_public_url(source_hint))

    def read(self, source_hint: str, request: ResearchRequest) -> tuple[ResearchResult | None, ResearchAttempt]:
        public_url = _threads_public_url(source_hint)
        if not public_url:
            return None, ResearchAttempt(self.module_id, "error", "unsupported_threads_public_hint", source_hint, weight=self.weight)
        safe, reason = classify_url(public_url)
        if not safe:
            return (
                ResearchResult.blocked(public_url, reason=f"ssrf_blocked:{reason}"),
                ResearchAttempt(self.module_id, "blocked", f"ssrf_blocked:{reason}", public_url, weight=self.weight),
            )
        try:
            status, body, final_url, content_type = self._fetch(public_url)
        except HTTPError as exc:
            reason = _status_reason(exc.code)
            return (
                ResearchResult.blocked(public_url, reason=reason),
                ResearchAttempt(self.module_id, "blocked", f"{reason}:{exc.code}", public_url, weight=self.weight),
            )
        except (URLError, TimeoutError, OSError) as exc:
            return None, ResearchAttempt(self.module_id, "error", redacted_exception_reason(exc, max_length=160), public_url, weight=self.weight)

        title, description = _threads_meta(body)
        text = _html_to_text(body) if "html" in content_type.lower() else body.strip()
        auth_wall_reason = _threads_auth_wall_reason(final_url=final_url, title=title, description=description, text=text)
        if auth_wall_reason:
            return (
                ResearchResult.blocked(final_url, reason=auth_wall_reason),
                ResearchAttempt(self.module_id, "blocked", f"{auth_wall_reason};public_html_status={status}", final_url, weight=self.weight),
            )
        content = _threads_public_markdown(title=title, description=description, text=text, url=final_url)
        limits = ["public_html_fallback", "official_api_preferred"]
        if not description:
            limits.append("thin_public_html")
        if len(body.encode("utf-8", "ignore")) >= self.max_bytes:
            limits.append("truncated")
        result = ResearchResult(
            source_id=_stable_hash(final_url),
            url=final_url,
            title=title or "Threads public page",
            platform="threads",
            content_markdown=content,
            extracted_at=utc_now(),
            freshness=request.freshness,
            confidence="usable" if description or text else "weak",
            limits=limits,
            citations=[{"label": title or "Threads public page", "url": final_url}],
        )
        return result, ResearchAttempt(self.module_id, "ok", f"public_html_status={status}", final_url, weight=self.weight)

    def _fetch(self, url: str) -> tuple[int, str, str, str]:
        opener = build_opener(_NoRedirect)
        current = url
        for _ in range(DEFAULT_MAX_REDIRECTS + 1):
            req = Request(
                current,
                headers={
                    "User-Agent": "AgentlasResearchEngine/0.1 (+https://agentlas.cloud)",
                    "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
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
                raise
        raise URLError("too_many_redirects")


def _parse_source_hint(source_hint: str) -> tuple[str, str]:
    if source_hint.lower() == "threads:me":
        return "profile", "me"
    if source_hint.lower().startswith("threads:tag:"):
        return "tag", source_hint.split(":", 2)[2].strip()
    if source_hint.lower().startswith("threads:keyword:"):
        return "keyword", source_hint.split(":", 2)[2].strip()
    if source_hint.lower().startswith("threads:profile:"):
        return "profile", source_hint.split(":", 2)[2].strip()
    if source_hint.lower().startswith("threads:lookup:"):
        return "lookup", source_hint.split(":", 2)[2].strip()
    if source_hint.lower().startswith("threads:posts:"):
        return "posts", source_hint.split(":", 2)[2].strip()
    if source_hint.lower().startswith("threads:user:"):
        return "posts", source_hint.split(":", 2)[2].strip()
    if source_hint.lower().startswith("threads:replies:"):
        return "replies", source_hint.split(":", 2)[2].strip()
    return "keyword", source_hint.strip()


def _threads_public_url(source_hint: str) -> str:
    source_hint = source_hint.strip()
    parsed = urlsplit(source_hint)
    if parsed.scheme in {"http", "https"}:
        return source_hint if _is_threads_host(parsed.hostname or "") else ""
    lowered = source_hint.lower()
    if lowered.startswith(("threads:url:", "threads:web:", "threads:post:")):
        candidate = source_hint.split(":", 2)[2].strip()
        parsed_candidate = urlsplit(candidate)
        return candidate if parsed_candidate.scheme in {"http", "https"} and _is_threads_host(parsed_candidate.hostname or "") else ""
    if lowered.startswith(("threads:lookup:", "threads:profile:", "threads:user:", "threads:posts:")):
        target = source_hint.split(":", 2)[2].strip()
        username = _public_threads_username(target)
        return f"https://www.threads.net/@{username}" if username else ""
    return ""


def _public_threads_username(value: str) -> str:
    value = value.strip()
    if value.lower() == "me":
        return ""
    parsed = urlsplit(value)
    if parsed.scheme in {"http", "https"} and _is_threads_host(parsed.hostname or ""):
        parts = [part for part in parsed.path.split("/") if part]
        if parts and parts[0].startswith("@"):
            value = parts[0]
    if value.startswith("@"):
        value = value[1:]
    return value if re.fullmatch(r"[A-Za-z0-9_.]{1,30}", value) else ""


def _is_threads_host(host: str) -> bool:
    host = (host or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return host in {"threads.net", "threads.com"} or host.endswith(".threads.net") or host.endswith(".threads.com")


def _search_payload_to_result(payload: dict, *, query: str, mode: str, request: ResearchRequest) -> ResearchResult:
    items = payload.get("data") if isinstance(payload, dict) else []
    lines = [f"# Threads {mode} search: {query}"]
    citations: list[dict[str, str]] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            username = str(item.get("username") or "").strip()
            permalink = str(item.get("permalink") or "").strip()
            timestamp = str(item.get("timestamp") or "").strip()
            prefix = f"@{username}" if username else "Threads"
            if timestamp:
                prefix += f" {timestamp}"
            if text:
                lines.append(f"- {prefix}: {text}")
            if permalink:
                citations.append({"label": username or permalink, "url": permalink})
    limits = ["official_api", "permission_gated"]
    if not citations:
        limits.append("empty_results")
    return ResearchResult(
        source_id=_stable_hash(f"threads:{mode}:{query}"),
        url=_safe_endpoint(query, mode),
        title=f"Threads {mode}: {query}",
        platform="threads",
        content_markdown="\n".join(lines).strip(),
        extracted_at=utc_now(),
        freshness=request.freshness,
        confidence="usable" if citations else "weak",
        limits=limits,
        citations=citations or [{"label": "threads-search", "url": _safe_endpoint(query, mode)}],
    )


def _profile_payload_to_result(payload: dict, *, target: str, request: ResearchRequest, lookup: bool = False) -> ResearchResult:
    data = payload if isinstance(payload, dict) else {}
    username = str(data.get("username") or target).strip()
    name = str(data.get("name") or "").strip()
    bio = str(data.get("threads_biography") or "").strip()
    verified = data.get("is_verified")
    picture = str(data.get("threads_profile_picture_url") or "").strip()
    title = f"Threads profile: @{username}" if username else f"Threads profile: {target}"
    lines = [f"# {title}"]
    if name:
        lines.append(f"Name: {name}")
    if verified is not None:
        lines.append(f"Verified: {bool(verified)}")
    if bio:
        lines.append("")
        lines.append(bio)
    if picture:
        lines.append("")
        lines.append(f"Profile picture: {picture}")
    limits = ["official_api", "permission_gated", "profile_lookup" if lookup else "profile_read"]
    if not data:
        limits.append("empty_results")
    return ResearchResult(
        source_id=_stable_hash(f"threads:profile:{target}"),
        url=_safe_endpoint(target, "lookup" if lookup else "profile"),
        title=title,
        platform="threads",
        content_markdown="\n".join(lines).strip(),
        extracted_at=utc_now(),
        freshness=request.freshness,
        confidence="usable" if data else "weak",
        limits=limits,
        citations=[{"label": title, "url": _safe_endpoint(target, "lookup" if lookup else "profile")}],
    )


def _posts_payload_to_result(payload: dict, *, target: str, mode: str, request: ResearchRequest) -> ResearchResult:
    items = payload.get("data") if isinstance(payload, dict) else []
    label = "replies" if mode == "replies" else "posts"
    lines = [f"# Threads {label}: {target}"]
    citations: list[dict[str, str]] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            username = str(item.get("username") or "").strip()
            permalink = str(item.get("permalink") or "").strip()
            timestamp = str(item.get("timestamp") or "").strip()
            media_type = str(item.get("media_type") or "").strip()
            prefix = f"@{username}" if username else "Threads"
            if timestamp:
                prefix += f" {timestamp}"
            if media_type:
                prefix += f" [{media_type}]"
            if text:
                lines.append(f"- {prefix}: {text}")
            elif permalink:
                lines.append(f"- {prefix}: {permalink}")
            if permalink:
                citations.append({"label": username or permalink, "url": permalink})
    limits = ["official_api", "permission_gated", f"{label}_read"]
    if not citations:
        limits.append("empty_results")
    return ResearchResult(
        source_id=_stable_hash(f"threads:{mode}:{target}"),
        url=_safe_endpoint(target, mode),
        title=f"Threads {label}: {target}",
        platform="threads",
        content_markdown="\n".join(lines).strip(),
        extracted_at=utc_now(),
        freshness=request.freshness,
        confidence="usable" if citations else "weak",
        limits=limits,
        citations=citations or [{"label": f"threads-{label}", "url": _safe_endpoint(target, mode)}],
    )


def _decode(raw: bytes, content_type: str) -> str:
    charset = "utf-8"
    match = re.search(r"charset=([\w.-]+)", content_type or "", re.I)
    if match:
        charset = match.group(1)
    return raw.decode(charset, errors="replace")


def _threads_meta(body: str) -> tuple[str, str]:
    title = _meta_content(body, "og:title") or _title(body)
    description = _meta_content(body, "og:description") or _meta_content(body, "description")
    return title, description


def _threads_auth_wall_reason(*, final_url: str, title: str, description: str, text: str) -> str:
    parsed = urlsplit(final_url)
    path = (parsed.path or "").lower()
    combined = " ".join([title, description, text[:800]]).lower()
    if path.startswith("/login"):
        return "auth_required"
    if "log in with your instagram" in combined:
        return "auth_required"
    if "threads • log in" in combined or "threads - log in" in combined:
        return "auth_required"
    if "join threads" in combined and "log in" in combined and "instagram" in combined:
        return "auth_required"
    return ""


def _meta_content(body: str, key: str) -> str:
    patterns = [
        rf'(?is)<meta[^>]+(?:property|name)=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']*)["\']',
        rf'(?is)<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{re.escape(key)}["\']',
    ]
    for pattern in patterns:
        match = re.search(pattern, body or "")
        if match:
            return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()
    return ""


def _title(body: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", body or "")
    return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip() if match else ""


def _html_to_text(body: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", body or "")
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</(p|div|section|article|li|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(_dedupe([line for line in lines if line]))[:4000]


def _threads_public_markdown(*, title: str, description: str, text: str, url: str) -> str:
    lines = [f"# {title or 'Threads public page'}", f"URL: {url}"]
    if description:
        lines.extend(["", description])
    if text and text != description:
        lines.extend(["", "## Public page text", text[:2000]])
    return "\n".join(lines).strip()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _safe_endpoint(query: str, mode: str) -> str:
    if mode == "profile":
        return f"{THREADS_GRAPH_BASE}/{query}?fields={THREADS_PROFILE_FIELDS}"
    if mode == "lookup":
        return f"{THREADS_GRAPH_BASE}/profile_lookup?username={query}"
    if mode == "posts":
        return f"{THREADS_GRAPH_BASE}/{query}/threads"
    if mode == "replies":
        return f"{THREADS_GRAPH_BASE}/{query}/replies"
    return f"{THREADS_SEARCH_ENDPOINT}?q={query}&search_mode={mode}"


def _status_reason(status: int) -> str:
    if status in {401, 403}:
        return "permission_required"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    return "http_error"
