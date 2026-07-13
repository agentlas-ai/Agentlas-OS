"""Small safe HTTP reader used by the phase-0 research core."""

from __future__ import annotations

import html
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from agentlas_cloud.networking.bootstrap import utc_now

from ..contracts import ResearchAttempt, ResearchModuleManifest, ResearchRequest, ResearchResult, _stable_hash
from ..policy import DEFAULT_MAX_BYTES, DEFAULT_MAX_REDIRECTS, classify_url
from ..redaction import redacted_exception_reason


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


class HttpReaderAdapter:
    module_id = "read.http"
    capabilities = ("read.url",)
    weight = "light"
    manifest = ResearchModuleManifest(
        module_id=module_id,
        capabilities=list(capabilities),
        weight=weight,
        slot="reader",
        activation="auto",
        permissions=["network:http", "network:https"],
        default_state="available",
        failure_modes=["blocked", "auth_required", "not_found", "rate_limited", "ssrf_blocked"],
    )

    def __init__(self, *, timeout_seconds: int = 20, max_bytes: int = DEFAULT_MAX_BYTES):
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes

    def can_handle(self, source_hint: str, request: ResearchRequest) -> bool:
        scheme = urlsplit(source_hint).scheme.lower()
        return scheme in {"http", "https"}

    def read(self, source_hint: str, request: ResearchRequest) -> tuple[ResearchResult | None, ResearchAttempt]:
        safe, reason = classify_url(source_hint)
        if not safe:
            return (
                ResearchResult.blocked(source_hint, reason=f"ssrf_blocked:{reason}"),
                ResearchAttempt(self.module_id, "blocked", f"ssrf_blocked:{reason}", source_hint, weight=self.weight),
            )

        try:
            status, body, final_url, content_type = self._fetch(source_hint)
        except HTTPError as exc:
            reason = _status_reason(exc.code)
            return (
                ResearchResult.blocked(source_hint, reason=reason),
                ResearchAttempt(self.module_id, "blocked", f"{reason}:{exc.code}", source_hint, weight=self.weight),
            )
        except (URLError, TimeoutError, OSError, ValueError) as exc:
            return (
                None,
                ResearchAttempt(self.module_id, "error", redacted_exception_reason(exc, max_length=160), source_hint, weight=self.weight),
            )

        title = _extract_title(body)
        text = _html_to_text(body) if "html" in content_type.lower() else body.strip()
        auth_reason = _auth_wall_reason(final_url=final_url, title=title, text=text)
        if auth_reason:
            return (
                ResearchResult.blocked(final_url, reason=auth_reason),
                ResearchAttempt(self.module_id, "blocked", f"{auth_reason};status={status}", final_url, weight=self.weight),
            )
        confidence = "usable" if 200 <= status < 300 and text else "weak"
        limits: list[str] = []
        if len(body.encode("utf-8", "ignore")) >= self.max_bytes:
            limits.append("truncated")
        result = ResearchResult(
            source_id=_stable_hash(final_url),
            url=final_url,
            title=title,
            platform="web",
            content_markdown=text,
            extracted_at=utc_now(),
            freshness=request.freshness,
            confidence=confidence,
            limits=limits,
            citations=[{"label": title or final_url, "url": final_url}],
        )
        return result, ResearchAttempt(self.module_id, "ok", f"status={status}", final_url, weight=self.weight)

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


def _decode(raw: bytes, content_type: str) -> str:
    charset = "utf-8"
    match = re.search(r"charset=([\w.-]+)", content_type or "", re.I)
    if match:
        charset = match.group(1)
    return raw.decode(charset, errors="replace")


def _extract_title(body: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", body or "")
    if not match:
        return ""
    return html.unescape(re.sub(r"\s+", " ", match.group(1))).strip()


def _html_to_text(body: str) -> str:
    text = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", body or "")
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</(p|div|section|article|li|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def _auth_wall_reason(*, final_url: str, title: str, text: str) -> str:
    parsed = urlsplit(final_url)
    path = (parsed.path or "").lower()
    lowered = " ".join([title, text[:1200]]).lower()
    if path.startswith(("/login", "/signin", "/accounts/login")):
        return "auth_required"
    auth_patterns = (
        "sign in to continue",
        "log in to continue",
        "login required",
        "authentication required",
        "log in with your instagram",
        "threads • log in",
        "threads - log in",
    )
    if any(pattern in lowered for pattern in auth_patterns):
        return "auth_required"
    paywall_patterns = (
        "subscribe to continue",
        "subscription required",
        "paid subscribers only",
        "paywall",
    )
    if any(pattern in lowered for pattern in paywall_patterns):
        return "paywall_detected"
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
