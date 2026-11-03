"""Explicit optional memory host activation, separate from legacy adapters."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .feature_preferences import feature_enabled

_DESKTOP_HOSTS = {"desktop", "agentlas-desktop", "agentlas_desktop", "runtime:desktop"}


def activation(*, install: bool = False) -> dict[str, Any]:
    """Observe native registration; only explicit ON may register a plugin."""
    if not feature_enabled("memory-hooks"):
        return {"status": "disabled", "reason": "feature_disabled", "writeAttempted": False}
    if str(os.environ.get("AGENTLAS_HOST_RUNTIME") or "").strip().lower() in _DESKTOP_HOSTS:
        return {"status": "host_managed", "reason": "desktop_native_memory", "writeAttempted": False}
    try:
        from . import host_core
    except ImportError:
        return {"status": "partial", "reason": "host_activation_module_unavailable", "writeAttempted": False}
    root, home = Path(__file__).resolve().parent.parent, Path.home()
    hosts = [host for host in ("claude", "codex") if shutil.which(host)]
    if not hosts:
        return {"status": "partial", "reason": "supported_hook_host_unavailable", "hosts": [], "writeAttempted": False}
    results = []
    for host in hosts:
        if not feature_enabled("memory-hooks"):
            break
        try:
            operation = host_core.install if install else host_core.status
            result = operation(root, home, host, plugin_kind="memory")
        except Exception as exc:
            result = {"host": host, "status": "error", "reason": "host_activation_failed", "errorType": type(exc).__name__}
        results.append(result)
    if not feature_enabled("memory-hooks"):
        return {"status": "disabled", "reason": "preference_changed_during_activation", "hosts": results, "writeAttempted": install}
    connected = len(results) == len(hosts) and all(row.get("status") == "connected" for row in results)
    from .memory_runtime import configured_no_tools_runtime
    configured = configured_no_tools_runtime() is not None
    return {"status": "connected" if connected else "partial", "hosts": results,
            "writeAttempted": install, "scope": "available_claude_codex_hosts",
            "curation": {"status": "configured" if configured else "deferred",
                         "reason": "runtime_configuration_present" if configured else "no_supported_no_tools_model_runtime",
                         "modelInvocationVerified": False},
            "sessionReloadRequired": bool(install and connected)}
