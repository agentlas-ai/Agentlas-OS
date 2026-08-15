"""Stdlib-only ACP (Agent Client Protocol) v1 client.

Why this exists
---------------
Agentlas Core has no pip surface (no setup.py/pyproject) and runs on Python
3.9+ stdlib, so the official ``agent-client-protocol`` SDK cannot be a
dependency. This module speaks the wire protocol directly: JSON-RPC 2.0 over
the agent subprocess' stdio, newline-delimited. It follows the pattern already
proven by ``research/adapters/agentlas_browser.py::_McpSession`` (Popen +
daemon reader thread + queue + deadline).

What it is for
--------------
* ``initialize`` -> a Runtime Fabric capability descriptor with
  ``runtime.transport = "acp"`` and ``source.kind = "acp-initialize"``.
  ★ The initialize response is the agent's *self-report*: a tool surface,
  never a trust surface. It must not decide credentials, permission widening,
  or Shadow Agent promotion (PRD 2026-08-13 §8 round 2).
* ``session/new`` -> the agent's *entitlement-filtered* model list, read from
  ``configOptions[category == "model"]`` (fallback ``id == "model"``) plus any
  vendor extension such as codex-acp's ``models.availableModels``. Zero text
  parsing — this is the primary model-discovery path for every ACP runtime.
* ``session/prompt`` -> one turn with streamed ``session/update``
  notifications handed to a callback.

Two traps this client refuses to fall into (both measured 2026-08-14):
* ``authMethods`` non-empty means authenticate *before* ``session/new``
  (Paseo broke on JetBrains Junie by skipping it, agent-client-protocol #477).
* ``authMethods`` is a menu, not a priority list. codex-acp advertises
  ``[api-key, chat-gpt]``; picking ``[0]`` fails with "CODEX_API_KEY not set"
  even when the user is logged in via ChatGPT. Methods that need a secret env
  var are chosen only when that variable is present.

Model identifiers returned here are inventory values for the
``session_inventory[].model`` channel. They are never written into
``capability_descriptor.planes.*.features[]`` (invariant enforced by
``execution_fabric`` via ``scrub_identity_features``).
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from typing import Any, Callable, Mapping, Optional

from .runtime_capabilities import normalize_runtime_capability_descriptor

PROTOCOL_VERSION = 1

# Auth methods whose id looks like these need a secret in the environment. The
# list is deliberately small and matches on the *method id*, not the vendor.
_SECRET_AUTH_METHOD_ENV: list[tuple[str, tuple[str, ...]]] = [
    ("api-key", ("CODEX_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY")),
    ("api_key", ("CODEX_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY")),
    ("apikey", ("CODEX_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY")),
]

# ACP tool-call kinds — the protocol's fixed vocabulary, identical across agents.
TOOL_KINDS = ("read", "edit", "delete", "move", "search", "execute", "think", "fetch", "other")


class AcpError(RuntimeError):
    """Protocol-level failure (unsupported version, JSON-RPC error, timeout)."""

    def __init__(self, message: str, *, code: Optional[int] = None, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


class AcpProtocolVersionError(AcpError):
    """The agent negotiated a protocol version we do not speak (v2 is a draft)."""


class AcpTimeout(AcpError):
    """No response before the deadline; the subprocess is killed by the caller."""


def choose_auth_method(methods: list[Mapping[str, Any]], env: Mapping[str, str]) -> Optional[Mapping[str, Any]]:
    """Pick an advertised auth method that can actually work on this machine.

    Methods that need a secret env var are usable only when the var is set.
    Everything else (agent-owned login sessions) is preferred. Never asks the
    user for a credential and never invents one.
    """

    def needs_missing_secret(method: Mapping[str, Any]) -> bool:
        method_id = str(method.get("id") or "").lower()
        for needle, env_vars in _SECRET_AUTH_METHOD_ENV:
            if needle in method_id:
                return not any(env.get(name) for name in env_vars)
        return False

    usable = [m for m in methods if isinstance(m, Mapping) and not needs_missing_secret(m)]
    if usable:
        return usable[0]
    return methods[0] if methods and isinstance(methods[0], Mapping) else None


def model_options_from_new_session(response: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Read the structured model list from a ``session/new`` response.

    Priority: ``configOptions[category=="model"]`` -> ``configOptions[id=="model"]``
    -> vendor ``models.availableModels[]``. Each row is
    ``{"id", "name", "description", "current", "source"}``. The spec says
    ``category`` is a UX hint, so unknown categories are ignored gracefully.
    """

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def push(model_id: Any, name: Any, description: Any, current: bool, source: str) -> None:
        mid = str(model_id or "").strip()
        if not mid or mid in seen:
            return
        seen.add(mid)
        rows.append(
            {
                "id": mid,
                "name": str(name or mid),
                "description": str(description or ""),
                "current": bool(current),
                "source": source,
            }
        )

    options = response.get("configOptions")
    picked: Optional[Mapping[str, Any]] = None
    if isinstance(options, list):
        for option in options:
            if isinstance(option, Mapping) and str(option.get("category") or "") == "model":
                picked = option
                break
        if picked is None:
            for option in options:
                if isinstance(option, Mapping) and str(option.get("id") or "") == "model":
                    picked = option
                    break
    if picked is not None:
        current = picked.get("currentValue")
        for choice in picked.get("options") or []:
            if isinstance(choice, Mapping):
                value = choice.get("value")
                push(value, choice.get("name"), choice.get("description"), value == current, "acp:configOptions")

    vendor = response.get("models")
    if isinstance(vendor, Mapping):
        current = vendor.get("currentModelId")
        for choice in vendor.get("availableModels") or []:
            if isinstance(choice, Mapping):
                model_id = choice.get("modelId") or choice.get("id")
                push(model_id, choice.get("name"), choice.get("description"), model_id == current, "acp:vendor.models")
    return rows


def descriptor_from_acp_initialize(
    init: Mapping[str, Any],
    *,
    runtime_kind: str,
    descriptor_id: Optional[str] = None,
) -> dict[str, Any]:
    """Turn an ``initialize`` result into a Runtime Fabric capability descriptor.

    Only *feature names* from the agent's capability object become features;
    provider/model identity never does. ``source.trust`` is ``declared`` — the
    agent said so, nobody observed it.
    """

    caps = init.get("agentCapabilities") if isinstance(init.get("agentCapabilities"), Mapping) else {}
    tools: list[str] = []
    control: list[str] = []
    observation = ["session-update", "tool-call", "agent-thought-chunk", "plan", "usage-update"]
    if caps.get("loadSession"):
        control.append("load-session")
    prompt_caps = caps.get("promptCapabilities") if isinstance(caps.get("promptCapabilities"), Mapping) else {}
    for key in ("image", "audio", "embeddedContext"):
        if prompt_caps.get(key):
            tools.append("prompt:" + key.lower())
    mcp_caps = caps.get("mcpCapabilities") if isinstance(caps.get("mcpCapabilities"), Mapping) else {}
    for key in ("http", "sse"):
        if mcp_caps.get(key):
            tools.append("mcp:" + key)
    tools.extend("tool:" + kind for kind in TOOL_KINDS if kind != "other")
    auth_methods = init.get("authMethods") if isinstance(init.get("authMethods"), list) else []
    if auth_methods:
        control.append("auth-required")
    agent_info = init.get("agentInfo") if isinstance(init.get("agentInfo"), Mapping) else {}
    version = str(agent_info.get("version") or "").strip() or None

    raw = {
        "schemaVersion": "agentlas.runtime-fabric-capability-descriptor.v1",
        "descriptorId": descriptor_id or f"runtime:{runtime_kind}",
        "runtime": {"kind": runtime_kind, "transport": "acp", **({"version": version} if version else {})},
        "planes": {
            "behavior": {"status": "declared", "native": True, "features": ["prompt-turn"]},
            "tools": {"status": "declared", "native": True, "features": tools},
            "observation": {"status": "declared", "native": True, "features": observation},
            "control": {"status": "declared", "native": True, "features": ["cancel"] + control},
            "ui": {"status": "unknown", "native": False, "features": []},
            "telemetry": {"status": "declared", "native": False, "features": ["context-usage"]},
        },
        "source": {"kind": "acp-initialize", "trust": "declared"},
        # ACP runs as a child we can always abandon: the native runtime is never
        # blocked by this transport, and a broken agent leaves local fallback.
        "compatibility": {"nativePreserved": True, "hotPathUnblocked": True, "localFallback": True},
    }
    return normalize_runtime_capability_descriptor(raw, runtime_kind=runtime_kind, descriptor_id=raw["descriptorId"])


class AcpClient:
    """Synchronous ACP v1 client over an agent subprocess (stdio, ndjson)."""

    def __init__(
        self,
        command: list[str],
        *,
        cwd: Optional[str] = None,
        env: Optional[Mapping[str, str]] = None,
        timeout: float = 30.0,
        client_info: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if not command:
            raise ValueError("command must not be empty")
        self.command = list(command)
        self.cwd = cwd
        self.env = dict(env) if env is not None else dict(os.environ)
        self.timeout = float(timeout)
        self.client_info = dict(client_info or {"name": "agentlas-core", "version": "1.0"})
        self._id = 0
        self._responses: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self._notifications: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self._requests: "queue.Queue[dict[str, Any]]" = queue.Queue()
        self._lock = threading.Lock()
        self.stderr_tail = ""
        self.protocol_version: Optional[int] = None
        self.agent_capabilities: dict[str, Any] = {}
        self.auth_methods: list[dict[str, Any]] = []
        self.proc = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=self.env,
            text=True,
            bufsize=1,
        )
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()
        self._err_reader = threading.Thread(target=self._stderr_loop, daemon=True)
        self._err_reader.start()

    # ------------------------------------------------------------ transport
    def _read_loop(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            if "id" in msg and "method" in msg:
                self._requests.put(msg)          # agent -> client request
            elif "id" in msg:
                self._responses.put(msg)         # response to our request
            elif "method" in msg:
                self._notifications.put(msg)     # notification (session/update)

    def _stderr_loop(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.stderr_tail = (self.stderr_tail + line)[-4000:]

    def _send(self, obj: Mapping[str, Any]) -> None:
        assert self.proc.stdin is not None
        with self._lock:
            self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self.proc.stdin.flush()

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    def _request(
        self,
        method: str,
        params: Mapping[str, Any],
        *,
        timeout: Optional[float] = None,
        on_update: Optional[Callable[[dict[str, Any]], None]] = None,
        on_request: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        want = self._next_id()
        self._send({"jsonrpc": "2.0", "id": want, "method": method, "params": dict(params)})
        deadline = time.time() + (self.timeout if timeout is None else timeout)
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise AcpTimeout(f"ACP {method} timed out after {self.timeout:.0f}s; stderr: {self.stderr_tail[-300:]}")
            self._drain_side_channels(on_update, on_request)
            try:
                msg = self._responses.get(timeout=min(0.1, remaining))
            except queue.Empty:
                if self.proc.poll() is not None and self._responses.empty():
                    raise AcpError(
                        f"ACP agent exited (code {self.proc.returncode}) before answering {method}; stderr: {self.stderr_tail[-300:]}"
                    )
                continue
            if msg.get("id") != want:
                continue  # stale response for a request we no longer await
            # The reader thread is single and ordered: every notification that
            # preceded this response is already queued. Deliver them before
            # returning so a caller never sees the result ahead of its stream.
            self._drain_side_channels(on_update, on_request)
            if "error" in msg:
                err = msg["error"] if isinstance(msg["error"], dict) else {"message": str(msg["error"])}
                raise AcpError(str(err.get("message") or "ACP error"), code=err.get("code"), data=err.get("data"))
            result = msg.get("result")
            return result if isinstance(result, dict) else {}

    def _drain_side_channels(
        self,
        on_update: Optional[Callable[[dict[str, Any]], None]],
        on_request: Optional[Callable[[dict[str, Any]], dict[str, Any]]],
    ) -> None:
        while True:
            try:
                note = self._notifications.get_nowait()
            except queue.Empty:
                break
            if on_update is not None and note.get("method") == "session/update":
                params = note.get("params")
                if isinstance(params, dict):
                    try:
                        on_update(params)
                    except Exception:  # observer must never break the turn
                        pass
        while True:
            try:
                req = self._requests.get_nowait()
            except queue.Empty:
                break
            self._answer_agent_request(req, on_request)

    def _answer_agent_request(
        self,
        req: Mapping[str, Any],
        on_request: Optional[Callable[[dict[str, Any]], dict[str, Any]]],
    ) -> None:
        method = str(req.get("method") or "")
        params = req.get("params") if isinstance(req.get("params"), dict) else {}
        result: Optional[dict[str, Any]] = None
        error: Optional[dict[str, Any]] = None
        if on_request is not None:
            try:
                result = on_request({"method": method, "params": params})
            except Exception as exc:  # pragma: no cover - defensive
                error = {"code": -32603, "message": f"client handler failed: {exc}"}
        if result is None and error is None:
            if method == "session/request_permission":
                result = _default_permission_answer(params)
            else:
                # We advertise no fs/terminal capabilities, so anything else is
                # a method we did not agree to serve.
                error = {"code": -32601, "message": f"Method not found: {method}"}
        reply: dict[str, Any] = {"jsonrpc": "2.0", "id": req.get("id")}
        if error is not None:
            reply["error"] = error
        else:
            reply["result"] = result
        self._send(reply)

    # ------------------------------------------------------------ protocol
    def initialize(self) -> dict[str, Any]:
        result = self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}, "terminal": False},
                "clientInfo": self.client_info,
            },
        )
        negotiated = result.get("protocolVersion")
        if negotiated != PROTOCOL_VERSION:
            raise AcpProtocolVersionError(
                f"ACP agent negotiated protocolVersion={negotiated!r}; this client speaks v{PROTOCOL_VERSION} only (v2 is a draft with breaking prompt-turn semantics)"
            )
        self.protocol_version = negotiated
        caps = result.get("agentCapabilities")
        self.agent_capabilities = dict(caps) if isinstance(caps, dict) else {}
        methods = result.get("authMethods")
        self.auth_methods = [m for m in methods if isinstance(m, dict)] if isinstance(methods, list) else []
        return result

    def authenticate(self, method_id: str) -> dict[str, Any]:
        return self._request("authenticate", {"methodId": method_id})

    def authenticate_if_needed(self) -> Optional[str]:
        """Authenticate with a viable method when the agent advertised any. Returns the method id used."""

        if not self.auth_methods:
            return None
        chosen = choose_auth_method(self.auth_methods, self.env)
        if chosen is None:
            return None
        method_id = str(chosen.get("id") or "")
        try:
            self.authenticate(method_id)
        except AcpError:
            # An agent that is already logged in via its own session may still
            # accept session/new; if not, session/new fails loudly there.
            return method_id
        return method_id

    def new_session(self, cwd: Optional[str] = None, mcp_servers: Optional[list[Any]] = None) -> dict[str, Any]:
        result = self._request("session/new", {"cwd": cwd or self.cwd or os.getcwd(), "mcpServers": list(mcp_servers or [])})
        if not result.get("sessionId"):
            raise AcpError("session/new returned no sessionId")
        return result

    def prompt(
        self,
        session_id: str,
        text: str,
        on_update: Optional[Callable[[dict[str, Any]], None]] = None,
        *,
        on_request: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
        timeout: Optional[float] = None,
    ) -> dict[str, Any]:
        return self._request(
            "session/prompt",
            {"sessionId": session_id, "prompt": [{"type": "text", "text": text}]},
            timeout=timeout,
            on_update=on_update,
            on_request=on_request,
        )

    def cancel(self, session_id: str) -> None:
        self._send({"jsonrpc": "2.0", "method": "session/cancel", "params": {"sessionId": session_id}})

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=2)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass

    def __enter__(self) -> "AcpClient":
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()


def _default_permission_answer(params: Mapping[str, Any]) -> dict[str, Any]:
    """Conservative default: allow read-only kinds once, reject anything mutating.

    This is NOT the trust boundary (agents may run with bypassPermissions and
    never ask). It only keeps an unattended Core session from silently
    approving edits when it is asked.
    """

    options = params.get("options") if isinstance(params.get("options"), list) else []
    tool = params.get("toolCall") if isinstance(params.get("toolCall"), Mapping) else {}
    kind = str(tool.get("kind") or "other")
    mutating = kind not in ("read", "search", "fetch", "think")

    def find(*kinds: str) -> Optional[Mapping[str, Any]]:
        for option in options:
            if isinstance(option, Mapping) and str(option.get("kind") or "") in kinds:
                return option
        return None

    if mutating:
        reject = find("reject_once", "reject_always")
        if reject is not None:
            return {"outcome": {"outcome": "selected", "optionId": reject.get("optionId")}}
        return {"outcome": {"outcome": "cancelled"}}
    allow = find("allow_once", "allow_always")
    if allow is not None:
        return {"outcome": {"outcome": "selected", "optionId": allow.get("optionId")}}
    return {"outcome": {"outcome": "cancelled"}}


def discover_models_via_acp(
    command: list[str],
    *,
    cwd: Optional[str] = None,
    env: Optional[Mapping[str, str]] = None,
    timeout: float = 30.0,
    runtime_kind: str = "unknown",
) -> dict[str, Any]:
    """One-shot: spawn, initialize, auth if needed, session/new, read models, close.

    Returns ``{"status": "ok"|"failed", "models": [...], "descriptor": {...},
    "sessionId": str|None, "reason": str|None}``. Never raises — discovery is
    advisory and must not block a host.
    """

    client: Optional[AcpClient] = None
    try:
        client = AcpClient(command, cwd=cwd, env=env, timeout=timeout)
        init = client.initialize()
        descriptor = descriptor_from_acp_initialize(init, runtime_kind=runtime_kind)
        client.authenticate_if_needed()
        session = client.new_session(cwd=cwd)
        models = model_options_from_new_session(session)
        return {
            "status": "ok",
            "models": models,
            "descriptor": descriptor,
            "sessionId": session.get("sessionId"),
            "reason": None,
        }
    except Exception as exc:  # noqa: BLE001 - advisory path
        return {"status": "failed", "models": [], "descriptor": None, "sessionId": None, "reason": str(exc)}
    finally:
        if client is not None:
            client.close()


__all__ = [
    "PROTOCOL_VERSION",
    "TOOL_KINDS",
    "AcpClient",
    "AcpError",
    "AcpProtocolVersionError",
    "AcpTimeout",
    "choose_auth_method",
    "descriptor_from_acp_initialize",
    "discover_models_via_acp",
    "model_options_from_new_session",
]
