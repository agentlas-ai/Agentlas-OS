"""Small JSON-RPC client for the public Agentlas Hub MCP endpoint."""

from __future__ import annotations

import inspect
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Collection, Mapping

from ..auth import ensure_access_token, invalidate_access_token
from .bootstrap import networking_home, read_json

_HUB_TIMEOUT_SECONDS = 15
_HUB_CAPABILITY_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_HUB_TOOL_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_HUB_ERROR_MAX_RESPONSE_BYTES = 64 * 1024
_HUB_ERROR_MAX_TRAVERSAL_NODES = 512
_HUB_ERROR_MAX_TRAVERSAL_DEPTH = 12


class HubToolError(RuntimeError):
    """Raised when the Hub MCP endpoint returns a protocol or tool error."""

    def __init__(self, message: str, *, code: str = "source_unavailable"):
        self.code = code
        super().__init__(message)


class HubAuthRequiredError(HubToolError):
    """Raised when the Hub says this tool needs an Agentlas sign-in."""

    def __init__(self, message: str):
        super().__init__(message, code="source_unauthorized")


_FINITE_HUB_TOOL_ERROR_CODES = frozenset(
    {
        "insufficient_credits",
        "owner_only",
        "no_cloud_package",
        "agent_not_found",
        "source_not_configured",
        "source_not_supported",
        "source_unavailable",
        "source_timeout",
        "source_unauthorized",
        "source_forbidden",
        "source_rate_limited",
    }
)


def finite_hub_tool_error_code(
    value: Any,
    *,
    allowed_codes: Collection[str] | None = None,
    default: str = "source_unavailable",
) -> str:
    """Extract one allowlisted error code from a bounded nested payload.

    Hub refusals can arrive as JSON-RPC errors, MCP text, or nested HTTP error
    bodies.  This parser is deliberately finite: it walks a bounded number of
    nodes and returns only an explicitly allowed code, never arbitrary server
    text.  Specific entitlement/package refusals outrank a generic outer
    ``source_unavailable`` wrapper.
    """

    source_codes = _FINITE_HUB_TOOL_ERROR_CODES if allowed_codes is None else allowed_codes
    allowed = frozenset(
        code.lower()
        for code in source_codes
        if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{1,95}", code.lower())
    )
    buckets: dict[str, list[str]] = {"code": [], "signal": [], "text": []}
    stack: list[tuple[Any, int, str]] = [(value, 0, "text")]
    visited = 0

    while stack and visited < _HUB_ERROR_MAX_TRAVERSAL_NODES:
        current, depth, origin = stack.pop()
        visited += 1
        if depth > _HUB_ERROR_MAX_TRAVERSAL_DEPTH:
            continue
        if isinstance(current, Mapping):
            items = list(current.items())
            for raw_key, item in reversed(items):
                key = str(raw_key).lower()
                next_origin = (
                    "code"
                    if key == "code"
                    else "signal"
                    if key in {"error", "status"}
                    else "text"
                )
                stack.append((item, depth + 1, next_origin))
            continue
        if isinstance(current, (list, tuple)):
            for item in reversed(current):
                stack.append((item, depth + 1, origin))
            continue
        if not isinstance(current, str):
            continue

        text = current.strip()
        if not text:
            continue
        for token in re.findall(r"[a-z][a-z0-9_]{1,95}", text.lower()):
            if token in allowed and token not in buckets[origin]:
                buckets[origin].append(token)
        if text[:1] in {"{", "["}:
            try:
                decoded = json.loads(text)
            except (TypeError, ValueError):
                decoded = None
            if isinstance(decoded, (Mapping, list, tuple)):
                stack.append((decoded, depth + 1, origin))

    specific_refusals = {
        "insufficient_credits",
        "owner_only",
        "no_cloud_package",
        "agent_not_found",
    }
    for bucket in (buckets["code"], buckets["signal"], buckets["text"]):
        for candidate in bucket:
            if candidate in specific_refusals:
                return candidate
    for bucket in (buckets["code"], buckets["signal"], buckets["text"]):
        for candidate in bucket:
            if candidate != "source_unavailable":
                return candidate
    if any("source_unavailable" in bucket for bucket in buckets.values()):
        return "source_unavailable"
    return default


def _http_error_detail(exc: urllib.error.HTTPError, *, label: str) -> Any:
    """Read an HTTP error body without allowing an unbounded allocation."""

    try:
        raw = _read_bounded_response(
            exc,
            maximum=_HUB_ERROR_MAX_RESPONSE_BYTES,
            label=label,
        )
    except (HubToolError, OSError, ValueError):
        return None
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        return text


def _http_error_code(exc: urllib.error.HTTPError, detail: Any) -> str:
    code = finite_hub_tool_error_code(detail, default="")
    if code:
        return code
    return {
        402: "insufficient_credits",
        403: "source_forbidden",
        408: "source_timeout",
        429: "source_rate_limited",
        504: "source_timeout",
    }.get(exc.code, "source_unavailable")


def hub_url(home: Path | str | None = None) -> str:
    base = Path(home) if home else networking_home()
    config = read_json(base / "config.json", default={}) or {}
    return str(config.get("hub_url") or "https://agentlas.cloud").rstrip("/")


_INTERACTIVE_LOGIN_LOCK = threading.Lock()


def _interactive_auth_allowed() -> bool:
    """로그인 창을 띄워도 되는 자리인지 — 이 기계에 화면이 있는가.

    오너 정정 2026-08-24: 처음엔 TTY 로 갈랐는데 그건 틀렸다. 일반 사용자가
    Claude Code 같은 호스트에서 /hep-network 나 클라우드 명령을 칠 때 stdin 은
    TTY 가 아니지만 **사람은 화면 앞에 있다** — 로그인이 안 되어 있으면 바로
    브라우저 로그인 창을 여는 것이 기본값이어야 한다. 즉시 거절해야 하는 것은
    화면이 없는 자리(CI·서버·리눅스 무디스플레이)와 자동화가 명시로 끈 경우
    (HEPHAESTUS_AUTO_AUTH=0)뿐이다. 브라우저를 열지 못한 경우의 180초 대기는
    login 쪽 require_browser_open 이 즉시 실패로 끊는다.
    """

    override = os.environ.get("HEPHAESTUS_AUTO_AUTH")
    if override == "0":
        return False
    if override == "1":
        return True
    if sys.platform == "darwin" or os.name == "nt":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def interactive_auth_allowed() -> bool:
    """Public face of the sign-in-window gate.

    `auth ensure` is the pre-step every hep command runs first, in every
    runtime, with `--timeout 180`. It called `ensure_access_token` with a
    hard-coded `interactive=True`, so the documented kill-switch
    (HEPHAESTUS_AUTO_AUTH=0) had no effect there — measured by the independent
    audit 2026-08-25: unset/0/1 all burned the full timeout and tried to open
    a window. A signed-out machine's scheduled run would stall three minutes
    per command and pop a browser at night. The gate existed; nothing on that
    path consulted it.
    """

    return _interactive_auth_allowed()


def call_hub_tool(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    home: Path | str | None = None,
    timeout: int = _HUB_TIMEOUT_SECONDS,
    auto_auth: bool = True,
) -> dict[str, Any]:
    """Call an Agentlas Hub MCP tool and return its parsed JSON payload."""

    base_url = hub_url(home)
    token = ensure_access_token(base_url, interactive=False)
    try:
        return _call_hub_tool_once(name, arguments or {}, base_url=base_url, timeout=timeout, token=token)
    except HubAuthRequiredError:
        # The server just told us this credential is not accepted. The stored
        # record cannot know that on its own — its `expires_at` can sit months
        # in the future while the token is revoked — so retrying without
        # invalidating it replays the identical dead token and the refresh and
        # browser-login branches below are never reached. Measured: owner-scoped
        # cloud staffing failed `source_unauthorized` on every attempt while
        # `auth status` kept reporting `authenticated`.
        invalidate_access_token(base_url)
        if not auto_auth or not _interactive_auth_allowed():
            raise
        # 동시 소스 호출(예: network 페더레이션의 cloud+prepare)이 로그인 창을
        # 두 개 띄우지 않게 잠근다. 잠금을 얻었을 때 다른 쪽이 이미 로그인을
        # 끝냈으면 저장된 새 토큰을 그대로 쓴다.
        with _INTERACTIVE_LOGIN_LOCK:
            token = ensure_access_token(base_url, interactive=False)
            if not token:
                token = ensure_access_token(
                    base_url,
                    interactive=True,
                    force_refresh=True,
                    require_browser_open=True,
                )
        if not token:
            raise
        return _call_hub_tool_once(name, arguments or {}, base_url=base_url, timeout=timeout, token=token)


def list_hub_tools(
    *,
    home: Path | str | None = None,
    timeout: int = _HUB_TIMEOUT_SECONDS,
) -> list[dict[str, Any]]:
    """Probe standard MCP capabilities without opening an interactive login."""

    base_url = hub_url(home)
    token = ensure_access_token(base_url, interactive=False)
    url = base_url + "/api/mcp/v1"
    body = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "hephaestus-network-capability-probe",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(
                _read_bounded_response(
                    response,
                    maximum=_HUB_CAPABILITY_MAX_RESPONSE_BYTES,
                    label="hub capability probe",
                ).decode("utf-8")
            )
    except urllib.error.HTTPError as exc:
        detail = _http_error_detail(exc, label="hub capability probe error")
        if exc.code == 401 or _is_auth_required(detail):
            raise HubAuthRequiredError("hub capability probe requires Agentlas sign-in") from exc
        code = _http_error_code(exc, detail)
        raise HubToolError(
            f"hub capability probe failed: HTTP {exc.code} ({code})",
            code=code,
        ) from exc
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise HubToolError(f"hub capability probe failed: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise HubToolError("hub capability probe returned a protocol error")
    if payload.get("error"):
        if _is_auth_required(payload.get("error")):
            raise HubAuthRequiredError("hub capability probe requires Agentlas sign-in")
        raise HubToolError(
            "hub capability probe returned a protocol error",
            code=finite_hub_tool_error_code(payload.get("error")),
        )
    result = payload.get("result")
    tools = result.get("tools") if isinstance(result, Mapping) else None
    if not isinstance(tools, list) or any(not isinstance(item, Mapping) for item in tools):
        raise HubToolError("hub capability probe returned no tool list")
    return [dict(item) for item in tools]


def _call_hub_tool_once(
    name: str,
    arguments: dict[str, Any],
    *,
    base_url: str,
    timeout: int,
    token: str | None,
) -> dict[str, Any]:
    url = base_url + "/api/mcp/v1"
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments or {}},
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "hephaestus-network-hub-invoke",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(
                _read_bounded_response(
                    response,
                    maximum=_HUB_TOOL_MAX_RESPONSE_BYTES,
                    label=f"hub tool {name}",
                ).decode("utf-8")
            )
    except urllib.error.HTTPError as exc:
        detail = _http_error_detail(exc, label=f"hub tool {name} error")
        if exc.code == 401 or _is_auth_required(detail):
            raise HubAuthRequiredError(f"hub tool {name} requires Agentlas sign-in") from exc
        code = _http_error_code(exc, detail)
        raise HubToolError(
            f"hub tool {name} failed: HTTP {exc.code} ({code})",
            code=code,
        ) from exc
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        raise HubToolError(f"hub tool {name} failed: {exc}") from exc

    if not isinstance(payload, dict):
        raise HubToolError(f"hub tool {name} returned a non-object response")
    if payload.get("error"):
        if _is_auth_required(payload.get("error")):
            raise HubAuthRequiredError(f"hub tool {name} requires Agentlas sign-in")
        raise HubToolError(
            f"hub tool {name} error: {payload['error']}",
            code=finite_hub_tool_error_code(payload["error"]),
        )

    result = payload.get("result")
    if not isinstance(result, dict):
        raise HubToolError(f"hub tool {name} returned no result object")
    if result.get("isError"):
        text = _first_text(result)
        if _is_auth_required(text or result):
            raise HubAuthRequiredError(f"hub tool {name} requires Agentlas sign-in")
        raise HubToolError(
            f"hub tool {name} error: {text or result}",
            code=finite_hub_tool_error_code(text or result),
        )

    text = _first_text(result)
    if text is not None:
        try:
            parsed = json.loads(text)
        except ValueError as exc:
            raise HubToolError(f"hub tool {name} returned non-JSON text") from exc
        if isinstance(parsed, dict):
            return parsed
        return {"value": parsed}
    return result


def _read_bounded_response(response: Any, *, maximum: int, label: str) -> bytes:
    """Reject oversized Hub responses before or during allocation."""

    headers = getattr(response, "headers", None)
    raw_length = headers.get("Content-Length") if headers is not None else None
    if raw_length is not None:
        try:
            content_length = int(raw_length)
        except (TypeError, ValueError) as exc:
            raise HubToolError(f"{label} returned an invalid Content-Length") from exc
        if content_length < 0 or content_length > maximum:
            raise HubToolError(f"{label} response_too_large")
    reader = getattr(response, "read", None)
    if not callable(reader):
        raise HubToolError(f"{label} response is unreadable")
    try:
        payload = reader(maximum + 1)
    except TypeError:
        # Some local urllib-compatible adapters expose only read(). The real
        # HTTPResponse path above always accepts a bound; permit a no-argument
        # adapter only when its signature proves it cannot accept a size, then
        # still reject the result before parsing.
        try:
            parameters = inspect.signature(reader).parameters
        except (TypeError, ValueError) as exc:
            raise HubToolError(f"{label} response reader is incompatible") from exc
        if parameters:
            raise HubToolError(f"{label} response reader is incompatible")
        payload = reader()
    if not isinstance(payload, bytes):
        raise HubToolError(f"{label} response is not bytes")
    if len(payload) > maximum:
        raise HubToolError(f"{label} response_too_large")
    return payload


def _is_auth_required(value: Any) -> bool:
    if isinstance(value, dict):
        haystack = json.dumps(value, ensure_ascii=False).lower()
    else:
        haystack = str(value or "").lower()
        try:
            parsed = json.loads(haystack)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            haystack = json.dumps(parsed, ensure_ascii=False).lower()
    return "auth_required" in haystack or "authentication required" in haystack or "sign-in" in haystack


def _first_text(result: dict[str, Any]) -> str | None:
    content = result.get("content")
    if not isinstance(content, list):
        return None
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            return str(item.get("text") or "")
    return None
