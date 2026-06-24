"""Optional agent-browser CLI hardpoint.

This adapter is intentionally a thin wrapper. It does not vendor or import a
browser library; if `agent-browser` is missing, the research core records
`module_unavailable` and keeps going.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

from agentlas_cloud.networking.bootstrap import utc_now

from ..contracts import ResearchAttempt, ResearchModuleManifest, ResearchRequest, ResearchResult, _stable_hash
from ..hardpoints import active_hardpoint_argv
from ..policy import classify_url
from ..redaction import redact_secret_values, redacted_exception_reason


class AgentBrowserCliAdapter:
    module_id = "browser.agent_cli"
    capabilities = ("browser.snapshot", "read.url")
    weight = "browser_heavy"
    manifest = ResearchModuleManifest(
        module_id=module_id,
        capabilities=list(capabilities),
        weight=weight,
        slot="browser",
        activation="installed_and_allowed",
        requires=["binary:agent-browser"],
        permissions=["local_process:agent-browser", "network:http", "network:https", "browser:local_session"],
        default_state="available_if_installed",
        failure_modes=["module_unavailable", "browser_error", "ssrf_blocked", "timeout"],
        install_hint="Install agent-browser or set AGENTLAS_AGENT_BROWSER_BIN, then choose loadout=browser/full or allow browser.agent_cli.",
    )

    def __init__(self, *, timeout_seconds: int = 45, home: Path | str | None = None):
        self.timeout_seconds = timeout_seconds
        self.home = Path(home) if home else None

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

        binary = self._find_binary()
        if not binary:
            return (
                None,
                ResearchAttempt(
                    self.module_id,
                    "module_unavailable",
                    "agent-browser binary not found",
                    source_hint,
                    weight=self.weight,
                ),
            )

        try:
            opened = self._run(binary + ["open", source_hint])
            if opened.returncode != 0:
                return None, ResearchAttempt(
                    self.module_id,
                    "error",
                    _stderr_reason(opened.stderr),
                    source_hint,
                    weight=self.weight,
                )
            snapshot = self._run(binary + ["snapshot", "-i"])
            if snapshot.returncode != 0:
                return None, ResearchAttempt(
                    self.module_id,
                    "error",
                    _stderr_reason(snapshot.stderr),
                    source_hint,
                    weight=self.weight,
                )
        except subprocess.TimeoutExpired:
            return None, ResearchAttempt(self.module_id, "error", "timeout", source_hint, weight=self.weight)
        except OSError as exc:
            return None, ResearchAttempt(
                self.module_id,
                "error",
                _exception_reason(exc),
                source_hint,
                weight=self.weight,
            )
        finally:
            try:
                if binary:
                    self._run(binary + ["close"], timeout=10)
            except Exception:
                pass

        text = (snapshot.stdout or "").strip()
        if not text:
            return None, ResearchAttempt(self.module_id, "error", "empty_snapshot", source_hint, weight=self.weight)
        title = _title_from_snapshot(text) or source_hint
        result = ResearchResult(
            source_id=_stable_hash(source_hint),
            url=source_hint,
            title=title,
            platform="browser",
            content_markdown=text,
            extracted_at=utc_now(),
            freshness=request.freshness,
            confidence="usable",
            limits=["browser_snapshot"],
            citations=[{"label": title, "url": source_hint}],
        )
        return result, ResearchAttempt(self.module_id, "ok", "snapshot", source_hint, weight=self.weight)

    def _find_binary(self) -> list[str] | None:
        override = os.environ.get("AGENTLAS_AGENT_BROWSER_BIN")
        if override:
            return shlex.split(override)
        configured = active_hardpoint_argv(self.module_id, home=self.home)
        if configured:
            return configured
        path = shutil.which("agent-browser")
        return [path] if path else None

    def _run(self, argv: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout or self.timeout_seconds,
        )


def _stderr_reason(stderr: str) -> str:
    return re.sub(r"\s+", " ", redact_secret_values(stderr or "browser_error").strip())[:180]


def _exception_reason(exc: BaseException) -> str:
    return redacted_exception_reason(exc)


def _title_from_snapshot(snapshot: str) -> str:
    for line in snapshot.splitlines():
        clean = line.strip(" -")
        match = re.search(r'(?:heading|title)\s+"([^"]+)"', clean, re.I)
        if match:
            return match.group(1)
        if clean:
            return clean[:80]
    return ""
