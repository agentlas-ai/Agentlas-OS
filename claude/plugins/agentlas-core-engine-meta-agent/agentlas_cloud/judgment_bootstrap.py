"""Wire the resident judge to a host-supplied model endpoint.

The engine itself stays BYOC: it never hardcodes a model and never calls one on
its own. But a host that owns a connected runtime (Agentlas Desktop / Terminal,
or any MCP harness) can OPT IN by exporting ``AGENTLAS_JUDGE_RUNTIME`` before it
spawns this runtime. When that env is present and reachable, the judged sites
(pipeline stages, research loadout, content-guard adjudication, package scan,
privacy) decide by MEANING through the host's own model. When it is absent or
unreachable, ``set_judgment_runner`` is left unset and every judged site returns
its labeled "no connected model" outcome — never a silent keyword verdict.

``AGENTLAS_JUDGE_RUNTIME`` is compact JSON:

    {"kind": "ollama", "endpoint": "http://127.0.0.1:11434", "model": "qwen3:30b"}
    {"kind": "openai-compatible", "endpoint": "https://api.openai.com/v1",
     "model": "gpt-5.4-mini", "apiKey": "sk-..."}

stdlib only (urllib) — the runtime ships dependency-free. The judge passes its
own timeout deadline; this honors it on the HTTP request so a slow or hung model
aborts instead of stalling an OS operation.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import urllib.error
import urllib.request
from typing import Any

from . import judgment

JUDGE_RUNTIME_ENV = "AGENTLAS_JUDGE_RUNTIME"

_DEFAULT_TIMEOUT_S = 300.0
_MODEL_RESPONSE_MAX_BYTES = 128 * 1024


def _connected_model_timeout_s(value: float | None) -> float:
    if os.environ.get("AGENTLAS_TEST_JUDGMENT_TIMEOUTS") == "1":
        try:
            parsed = float(value) if value is not None else _DEFAULT_TIMEOUT_S
            if math.isfinite(parsed) and parsed > 0:
                return min(_DEFAULT_TIMEOUT_S, parsed)
        except (TypeError, ValueError):
            pass
    return _DEFAULT_TIMEOUT_S


def _read_model_response(response) -> bytes:
    raw = response.read(_MODEL_RESPONSE_MAX_BYTES + 1)
    if len(raw) > _MODEL_RESPONSE_MAX_BYTES:
        raise ValueError("model_response_too_large")
    return raw


def _output_limit(value: int | None) -> int | None:
    if value is not None and (type(value) is not int or not 1 <= value <= 1600):
        raise ValueError("model_output_limit_invalid")
    return value


def _model_urlopen(request, *, timeout: float, strict_endpoint: bool):
    if not strict_endpoint:
        return urllib.request.urlopen(request, timeout=timeout)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    response = urllib.request.build_opener(NoRedirect()).open(request, timeout=timeout)
    if response.geturl() != request.full_url:
        response.close()
        raise ValueError("model_endpoint_changed")
    return response


def _host_cmd_runner(cmd: list[str]):
    """Universal bridge: delegate the classification to the host's own runner.

    The host (Desktop/Terminal) already speaks every runtime it supports —
    Claude/Codex/Antigravity CLIs, all BYOK providers, and local models — and picks an
    appropriate (cheap) model for a lightweight classification. Rather than
    reimplement each provider's API here, the OS judge hands the host a
    ``{"system","prompt"}`` request on stdin and reads the reply text on stdout.
    This is what lets a provider/CLI user's OS-side judgment work without local
    Ollama and without hardcoding any model.
    """

    def run(system: str, prompt: str, *, timeout_s: float | None = None) -> str:
        payload = json.dumps({"system": system, "prompt": prompt})
        proc = subprocess.run(
            cmd,
            input=payload,
            capture_output=True,
            text=True,
            timeout=_connected_model_timeout_s(timeout_s),
        )
        return proc.stdout or ""

    return run


class ModelContextExceeded(ValueError):
    """The request does not fit the largest window the model (and this machine) allow. Nothing was cut.

    A ValueError, so every existing caller that maps model failures to its labeled "no verdict" outcome keeps doing so;
    ``code`` is the typed cause for callers that report it.
    """

    code = "local_context_limit_exceeded"


# Twin of Desktop electron/runtime/ollama-native.ts and Terminal engine/runtimes/ollama-context.cjs: Ollama without
# num_ctx uses its own default (4096 on a machine without VRAM) and cuts a longer prompt to its first 4 tokens plus the
# tail without telling the caller (Windows 1.3.88 test 2026-10-23: "truncating input prompt" 6463 -> 2050).
_OLLAMA_CONTEXT_TIERS = (4096, 8192, 16384, 32768, 65536, 131072, 262144)
_OLLAMA_DEFAULT_CONTEXT_CEILING = 65536
_OLLAMA_DEFAULT_OUTPUT_RESERVE = 2048


def _estimate_tokens(text: str) -> int:
    """Conservative token count without a tokenizer: UTF-8 bytes / 3 (BPE prose is ~4 bytes/token, Hangul ~3)."""

    return -(-len(text.encode("utf-8")) // 3)


def _ollama_model_max(endpoint: str, model: str, *, timeout: float, strict_endpoint: bool) -> int | None:
    """The model's trained maximum window (/api/show model_info "<arch>.context_length"); None when not reported."""

    request = urllib.request.Request(
        endpoint.rstrip("/") + "/api/show",
        data=json.dumps({"model": model}).encode("utf-8"),
        headers={"content-type": "application/json"},
    )
    try:
        with _model_urlopen(request, timeout=min(timeout, 10.0), strict_endpoint=strict_endpoint) as resp:
            info = (json.loads(_read_model_response(resp).decode("utf-8")) or {}).get("model_info") or {}
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None
    for name, raw in info.items():
        if name.endswith(".context_length") and type(raw) is int and raw > 0:
            return raw
    return None


def _ollama_num_ctx(prompt_tokens: int, output_reserve: int, model_max: int | None) -> tuple[int, bool]:
    """(num_ctx, fits): the smallest tier holding the request with 1.25x headroom, capped by the model maximum."""

    ceiling = max(_OLLAMA_CONTEXT_TIERS[0], min(_OLLAMA_DEFAULT_CONTEXT_CEILING, model_max or _OLLAMA_DEFAULT_CONTEXT_CEILING))
    need = prompt_tokens + output_reserve
    wanted = -(-need * 5 // 4)
    tier = next((value for value in _OLLAMA_CONTEXT_TIERS if value >= wanted), _OLLAMA_CONTEXT_TIERS[-1])
    num_ctx = min(ceiling, tier)
    return num_ctx, need <= num_ctx


def _is_context_refusal(status: int, body: str) -> bool:
    """Ollama relays llama-server's machine error as a JSON string; read the nested object, never the prose."""

    if status == 413:
        return True
    try:
        error = json.loads(body).get("error")
        if isinstance(error, str):
            error = json.loads(error).get("error")
    except (ValueError, AttributeError):
        return False
    return isinstance(error, dict) and (
        error.get("type") in ("exceed_context_size_error", "context_length_exceeded") or error.get("code") == "context_length_exceeded"
    )


def _ollama_runner(endpoint: str, model: str):
    url = endpoint.rstrip("/") + "/api/chat"

    def run(system: str, prompt: str, *, timeout_s: float | None = None, max_output_tokens: int | None = None, strict_endpoint: bool = False) -> str:
        timeout = _connected_model_timeout_s(timeout_s)
        output_limit = _output_limit(max_output_tokens)
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        num_ctx, fits = _ollama_num_ctx(
            _estimate_tokens(json.dumps(messages, ensure_ascii=False)),
            output_limit if output_limit is not None else _OLLAMA_DEFAULT_OUTPUT_RESERVE,
            _ollama_model_max(endpoint, model, timeout=timeout, strict_endpoint=strict_endpoint),
        )
        if not fits:
            raise ModelContextExceeded(f"model_context_exceeded: request does not fit the {num_ctx}-token window")
        options: dict[str, int] = {"num_ctx": num_ctx}
        if output_limit is not None:
            options["num_predict"] = output_limit
        body = json.dumps(
            {
                "model": model,
                "stream": False,
                # The server refuses (HTTP 400) instead of cutting the prompt when the window is still too small.
                "truncate": False,
                "options": options,
                "messages": messages,
            }
        ).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
        try:
            with _model_urlopen(req, timeout=timeout, strict_endpoint=strict_endpoint) as resp:
                data = json.loads(_read_model_response(resp).decode("utf-8"))
        except urllib.error.HTTPError as error:
            detail = error.read(_MODEL_RESPONSE_MAX_BYTES).decode("utf-8", "replace") if error.fp else ""
            if _is_context_refusal(error.code, detail):
                raise ModelContextExceeded(f"model_context_exceeded: the server refused a {num_ctx}-token window") from error
            raise
        return ((data.get("message") or {}).get("content")) or ""

    return run


def _openai_compatible_runner(endpoint: str, model: str, api_key: str | None):
    url = endpoint.rstrip("/") + "/chat/completions"

    def run(system: str, prompt: str, *, timeout_s: float | None = None, max_output_tokens: int | None = None, strict_endpoint: bool = False) -> str:
        body = json.dumps(
            {
                "model": model,
                "temperature": 0,
                **({"max_tokens": _output_limit(max_output_tokens)} if max_output_tokens is not None else {}),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
            }
        ).encode("utf-8")
        headers = {"content-type": "application/json"}
        if api_key:
            headers["authorization"] = f"Bearer {api_key}"
        req = urllib.request.Request(url, data=body, headers=headers)
        with _model_urlopen(req, timeout=_connected_model_timeout_s(timeout_s), strict_endpoint=strict_endpoint) as resp:
            data = json.loads(_read_model_response(resp).decode("utf-8"))
        choices = data.get("choices") or []
        if not choices:
            return ""
        return ((choices[0] or {}).get("message") or {}).get("content") or ""

    return run


def _build_runner(config: dict[str, Any]):
    kind = str(config.get("kind") or "").strip().lower()
    # Universal host callback — works for every runtime the host supports
    # (CLI subscriptions + all BYOK providers + local), no provider code here.
    if kind == "host-cmd":
        cmd = config.get("cmd")
        if isinstance(cmd, list) and cmd and all(isinstance(part, str) for part in cmd):
            return _host_cmd_runner(cmd)
        return None
    # Direct HTTP modes (the host may prefer these for a purely local model).
    endpoint = str(config.get("endpoint") or "").strip()
    model = str(config.get("model") or "").strip()
    if not endpoint or not model:
        return None
    if kind == "ollama":
        return _ollama_runner(endpoint, model)
    if kind in ("openai-compatible", "openai", "byok", "custom"):
        api_key = config.get("apiKey") or config.get("api_key")
        return _openai_compatible_runner(endpoint, model, str(api_key) if api_key else None)
    return None


def install_judgment_from_env(env: dict[str, str] | None = None) -> bool:
    """Install the judge runner from ``AGENTLAS_JUDGE_RUNTIME`` if the host set it.

    Returns True when a runner was installed, False otherwise. Never raises: a
    malformed env or an unreachable endpoint simply leaves the judge unset, so
    judged sites fall to their labeled "connect a model" outcome.
    """
    source = env if env is not None else os.environ
    raw = (source.get(JUDGE_RUNTIME_ENV) or "").strip()
    if not raw:
        return False
    try:
        config = json.loads(raw)
    except (ValueError, TypeError):
        return False
    if not isinstance(config, dict):
        return False
    runner = _build_runner(config)
    if runner is None:
        return False

    def judge_runner(system: str, prompt: str) -> str:
        try:
            return runner(system, prompt) or ""
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            subprocess.TimeoutExpired,
            subprocess.SubprocessError,
            OSError,
            ValueError,
        ):
            # Unreachable / slow / malformed → the judge treats an empty string as
            # "no verdict" and the site returns its labeled connect-a-model outcome.
            return ""

    judgment.set_judgment_runner(judge_runner)
    return True
