"""Ephemeral consumer for authenticated Web memory jobs, never local memory.

The server owns job leasing, source scope and completion admission. The native
host owns credentials and its concrete no-tools HTTP runtime. No remote model
request can select a provider or turn an arbitrary command into a safe adapter.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

from ..auth import normalize_base_url, read_token_record
from ..memory_runtime import configured_no_tools_runtime, run_configured_no_tools
from ..memory_owner_binding import host_binding
from ..windows_console import no_console_window

_SLOTS = {"agentlas.record_agent_memory": "curation",
          "agentlas.decide_agent_learning": "curation",
          "agentlas.memory_curation_request": "request"}
_COMPLETE = "agentlas.complete_memory_curation"
_LOCK = threading.Lock()
_CAPACITY = threading.BoundedSemaphore(4)
_SEEN: dict[tuple[str, ...], float] = {}
MEMORY_TOOLS = frozenset((*_SLOTS, "agentlas.memory_session_open", "agentlas.memory_session_recap", _COMPLETE))
_SUBJECT_RE = re.compile(r"sha256:[0-9a-f]{64}")


def binding_identity(binding):
    # Renewal may extend expiry; it never changes an already captured identity.
    return {k: v for k, v in binding.items() if k != "expires_at"} if binding else None


def _subject(value: Any) -> bool:
    return isinstance(value, str) and _SUBJECT_RE.fullmatch(value) is not None


def _identity_subject(base: str, token: str) -> str | None:
    # The owner is proven through an MCP resource this token is scoped to. The
    # Web session route reads only the cookie and ignores a bearer, so asking it
    # always said "signed out" and every curation job was dropped.
    identity = _bounded_route({"kind": "identity", "base": base, "token": token}, 3)
    subject = identity.get("accountSubject") if isinstance(identity, dict) else None
    return subject if _subject(subject) else None


def assert_web_memory_binding(base: str, token: str | None):
    """Only descriptor-bound native memory RPCs require this host/account fence.
    Standalone OAuth transport retains its own verified Web server authority.
    """
    binding = host_binding()
    if binding is None:
        return None
    pin = _record_pin(base, token) if token else None
    if not pin or not _text(binding.get("user_id")):
        raise ValueError("memory_web_owner_unavailable")
    # The Web identity tool returns only the opaque account subject, so a
    # binding without one cannot be checked against the server: typed, not
    # reported as an owner change.
    if not _subject(binding.get("account_subject")):
        raise ValueError("memory_web_owner_unverifiable")
    subject = _identity_subject(base, token)
    if subject is None or subject != pin[0] or subject != binding["account_subject"]:
        raise ValueError("memory_web_owner_changed")
    if binding_identity(host_binding()) != binding_identity(binding) or _record_pin(base, token) != pin:
        raise ValueError("memory_host_binding_changed")
    return binding


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def strict_urlopen(request, *, timeout):
    """A private job never forwards credentials or source through redirects."""
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def _remote_route(payload: dict[str, Any]) -> dict[str, Any]:
    """Child's fixed authenticated route; no token refresh or local admission."""
    from .hub_client import _call_hub_tool_once
    if payload["kind"] == "identity":
        result = _call_hub_tool_once("agentlas.account_context", {}, base_url=payload["base"], timeout=3,
                                     token=payload["token"], endpoint_path="/api/mcp/v1", strict_endpoint=True)
        subject = result.get("accountSubject") if isinstance(result, dict) else None
        if not _subject(subject):
            raise ValueError("hub_identity_response_invalid")
        return {"accountSubject": subject}
    return _call_hub_tool_once(_COMPLETE, payload["arguments"], base_url=payload["base"],
                              timeout=5, token=payload["token"], endpoint_path=payload["path"],
                              strict_endpoint=True)


def _bounded_route(payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    # Socket timeouts alone do not bound a slow-drip stream or DNS. The private
    # route child owns no tools and is killed at the overall request deadline.
    code = ("import sys,json; from agentlas_cloud.networking.remote_memory_curation import _remote_route; "
            "json.dump(_remote_route(json.load(sys.stdin)),sys.stdout)")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    result = subprocess.run([sys.executable, "-c", code], input=json.dumps(payload), text=True, encoding="utf-8", env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout,
                            cwd=str(Path(__file__).resolve().parents[2]), **no_console_window())
    if result.returncode or len(result.stdout.encode("utf-8")) > 128 * 1024:
        raise ValueError("hub_private_route_unavailable")
    return json.loads(result.stdout)


def _text(value: Any, limit: int = 512) -> bool:
    return isinstance(value, str) and bool(value.strip()) and "\0" not in value and len(value.encode("utf-8")) <= limit


def _record_pin(base_url: str, token: str) -> tuple[str, str, str] | None:
    record = read_token_record(base_url)
    if not isinstance(record, dict) or record.get("access_token") != token:
        return None
    subject, login = record.get("account_subject"), record.get("login_instance_id")
    if not (_text(subject) and re.fullmatch(r"sha256:[0-9a-f]{64}", subject) and _text(login)):
        return None
    expires = record.get("expires_at")
    if not isinstance(expires, (int, float)) or expires <= time.time():
        return None
    return subject, login, hashlib.sha256(token.encode("utf-8")).hexdigest()


def _packet(name: str, result: dict[str, Any]) -> dict[str, Any] | None:
    if result.get("error") or result.get("isError") is True:
        return None
    slot = _SLOTS.get(name)
    p = result.get(slot) if slot else None
    if not isinstance(p, dict) or p.get("schemaVersion") != "agentlas.automatic-memory-request.v1":
        return None
    if p.get("tools") != [] or p.get("requireNoTools") is not True or p.get("completeTool") != _COMPLETE:
        return None
    if any(not _text(p.get(k)) for k in ("jobId", "leaseToken", "inputDigest", "bindingId")) or not _text(p.get("sourceRef"), 1024):
        return None
    if any(k not in p or (p[k] is not None and not _text(p[k], 512)) for k in ("visibilityDomain", "originTaskId")):
        return None
    owner = p.get("owner")
    if not isinstance(owner, dict) or any(not _text(owner.get(k)) for k in ("workspaceId", "userId")):
        return None
    if not _text(p.get("system"), 16 * 1024) or not _text(p.get("input"), 128 * 1024):
        return None
    tokens, timeout = p.get("maxOutputTokens"), p.get("timeoutMs")
    if type(tokens) is not int or not 1 <= tokens <= 1600 or type(timeout) is not int or not 250 <= timeout <= 300000:
        return None
    # Web hashes JSON.stringify(input), where input itself is a JSON string.
    serialized = json.dumps(p["input"], ensure_ascii=False, separators=(",", ":"))
    if hashlib.sha256(serialized.encode("utf-8")).hexdigest() != p["inputDigest"]:
        return None
    return {"owner": {k: owner[k] for k in ("workspaceId", "userId")},
            **{k: p[k] for k in ("jobId", "leaseToken", "inputDigest", "bindingId",
                                "sourceRef", "system", "input", "maxOutputTokens", "timeoutMs")},
            "visibilityDomain": p.get("visibilityDomain"), "originTaskId": p.get("originTaskId")}


def make_observer(name: str, *, base_url: str, token: str | None,
                  endpoint_path: str, current_base: Callable[[], str]) -> Callable | None:
    """Capture trusted host pins before the foreground authenticated request."""
    if name not in _SLOTS:
        return None
    base, pin, runtime, binding = base_url, None, None, None
    try:
        base = normalize_base_url(base_url)
        if token and base == base_url and normalize_base_url(current_base()) == base:
            pin = _record_pin(base, token)
            runtime = configured_no_tools_runtime()
            binding = host_binding()
    except Exception:
        pass

    def current() -> bool:
        selection = configured_no_tools_runtime()
        return (normalize_base_url(current_base()) == base and _record_pin(base, token) == pin
                and binding_identity(host_binding()) == binding_identity(binding)
                and selection is not None and selection["fingerprint"] == runtime["fingerprint"])

    def owner_matches(p: dict[str, Any]) -> bool:
        if not current():
            return False
        if binding is not None and not _subject(binding.get("account_subject")):
            return False
        # The packet arrived on this token's own authenticated call and the
        # server scoped it to that account; the server identity for the token
        # must still be the account pinned in the local token record.
        subject = _identity_subject(base, token)
        return (subject is not None and subject == pin[0]
                and (binding is None or (binding["account_subject"] == subject
                     and binding.get("user_id") == p["owner"]["userId"]
                     and (binding.get("workspace_id") is None or binding["workspace_id"] == p["owner"]["workspaceId"])))
                and current())

    def observe(result: dict[str, Any], resolved_url: str | None) -> dict[str, Any]:
        p = _packet(name, result)
        if p is None:
            return result
        def projected(state):
            safe = dict(result)
            safe.pop(_SLOTS[name], None)
            safe.pop("nextAction", None)
            if name == "agentlas.record_agent_memory":
                safe.pop("source", None)
            safe["automaticMemory"] = {"state": state}
            return safe
        if not token or not pin or not runtime:
            return projected("awaiting_runtime")
        if resolved_url != base + endpoint_path:
            return projected("deferred")
        # Deep-copy the bounded packet: callers may mutate foreground results.
        p = json.loads(json.dumps(p, ensure_ascii=False))
        key = (base, endpoint_path, *pin, p["jobId"], p["leaseToken"], p["inputDigest"])
        with _LOCK:
            now = time.monotonic()
            for old in [k for k, expires in _SEEN.items() if expires <= now]:
                del _SEEN[old]
            if key in _SEEN:
                return projected("background_pending")
            if len(_SEEN) >= 128 or not _CAPACITY.acquire(blocking=False):
                return projected("deferred")
            _SEEN[key] = now + 3600

        def work() -> None:
            try:
                if not owner_matches(p):
                    return
                # A local catalogue may retain a server-owned reference only
                # when this native host also has a current local owner binding.
                # It never stores the remote packet, lease, source body or token.
                if binding is not None:
                    try:
                        from ..memory_sources import producer, register_source
                        from ..memory_runtime import MemoryRuntime
                        local = MemoryRuntime(binding["owner_namespace"])
                        try:
                            with local.db:
                                producer_id = producer(local.db, local.owner, "portable-core", "canonical-owner:" + local.owner)
                                register_source(local.db, local.owner, producer_id, actor_id=None,
                                    visibility_domain=json.dumps(["web", p["owner"]["workspaceId"], p["visibilityDomain"]], ensure_ascii=False, separators=(",", ":")),
                                    logical_key=p["bindingId"] + ":" + p["sourceRef"], source_kind="web-reference",
                                    reader_contract="agentlas.authenticated-web-source.v1", writer_contract="web-server",
                                    schema_version="agentlas.automatic-memory-request.v1", source_revision=p["inputDigest"],
                                    address={"endpoint": base + endpoint_path, "ref": p["sourceRef"]})
                        finally:
                            local.close()
                    except Exception:
                        pass  # Remote authority and completion do not depend on this view.
                    if not owner_matches(p):
                        return
                output = run_configured_no_tools(runtime, p["system"], p["input"],
                          max_output_tokens=p["maxOutputTokens"], timeout_s=300)
                if not owner_matches(p):
                    return
                _bounded_route({"kind": "complete", "base": base, "token": token, "path": endpoint_path,
                                "arguments": {"jobId": p["jobId"], "leaseToken": p["leaseToken"],
                                "inputDigest": p["inputDigest"], "model": runtime["model"], "output": output}}, 5)
            except Exception:
                # The remote lease/retry remains authoritative; no local receipt,
                # credential refresh, foreground failure or inferred admission.
                pass
            finally:
                _CAPACITY.release()

        try:
            # Non-daemon prevents a one-shot Core caller dropping its leased job.
            # Scheduling returns immediately; private work is bounded separately.
            threading.Thread(target=work, name="agentlas-web-memory", daemon=False).start()
        except Exception:
            _CAPACITY.release()
            with _LOCK:
                _SEEN.pop(key, None)
            return projected("deferred")
        return projected("background_pending")

    return observe
