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
from typing import Any
from urllib.parse import urlsplit

from agentlas_cloud.networking.bootstrap import utc_now

from ..contracts import ResearchAttempt, ResearchModuleManifest, ResearchRequest, ResearchResult, _stable_hash
from ..hardpoints import active_hardpoint_argv
from ..policy import classify_url
from ..redaction import redact_secret_values, redacted_exception_reason
from ...windows_console import no_console_window


class AgentBrowserCliAdapter:
    module_id = "browser.agent_cli"
    capabilities = ("browser.snapshot", "browser.automation", "read.url")
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

        browser_args = list(getattr(request, "browser_args", []) or [])
        keep_open = bool(getattr(request, "browser_keep_open", False))
        base = binary + browser_args

        try:
            opened = self._run(base + ["open", source_hint])
            if opened.returncode != 0:
                return None, ResearchAttempt(
                    self.module_id,
                    "error",
                    _stderr_reason(opened.stderr),
                    source_hint,
                    weight=self.weight,
                )
            snapshot = self._run(base + ["snapshot", "-i"])
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
            if not keep_open:
                try:
                    if binary:
                        self._run(base + ["close"], timeout=10)
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
            limits=_read_limits(browser_args, keep_open),
            citations=[{"label": title, "url": source_hint}],
        )
        return result, ResearchAttempt(self.module_id, "ok", "snapshot", source_hint, weight=self.weight)

    def automate(
        self,
        source_hint: str,
        instruction: str,
        *,
        browser_args: list[str] | None = None,
        keep_open: bool = False,
    ) -> dict[str, Any]:
        """Run the real agent-browser automation surface for one public URL."""

        safe, reason = classify_url(source_hint)
        if not safe:
            return {
                "status": "blocked",
                "reason": f"ssrf_blocked:{reason}",
                "url": source_hint,
                "module": self.module_id,
                "steps": [],
            }

        command = instruction.strip()
        if not command:
            return {
                "status": "needs_instruction",
                "reason": "automation_instruction_required",
                "url": source_hint,
                "module": self.module_id,
                "steps": [],
            }

        binary = self._find_binary()
        if not binary:
            return {
                "status": "module_unavailable",
                "reason": "agent-browser binary not found",
                "url": source_hint,
                "module": self.module_id,
                "steps": [],
            }

        base = binary + list(browser_args or [])
        steps: list[dict[str, Any]] = []
        snapshot_text = ""
        chat_text = ""
        status = "ok"
        reason = ""
        try:
            opened = self._run_step(steps, "open", base + ["open", source_hint])
            if opened.returncode != 0:
                return _automation_payload(
                    status="error",
                    reason=_stderr_reason(opened.stderr),
                    url=source_hint,
                    module=self.module_id,
                    steps=steps,
                )

            chat = self._run_step(steps, "chat", base + ["-q", "chat", command])
            chat_text = _bounded_text(chat.stdout or "")
            if chat.returncode != 0:
                status = "error"
                reason = _stderr_reason(chat.stderr)

            snapshot = self._run_step(steps, "snapshot", base + ["snapshot", "-i"])
            snapshot_text = _bounded_text(snapshot.stdout or "")
            if snapshot.returncode != 0 and status == "ok":
                status = "error"
                reason = _stderr_reason(snapshot.stderr)
        except subprocess.TimeoutExpired:
            status = "error"
            reason = "timeout"
        except OSError as exc:
            status = "error"
            reason = _exception_reason(exc)
        finally:
            if not keep_open:
                try:
                    self._run_step(steps, "close", base + ["close"], timeout=10)
                except Exception:
                    pass

        return _automation_payload(
            status=status,
            reason=reason,
            url=source_hint,
            module=self.module_id,
            steps=steps,
            instruction=command,
            chat_text=chat_text,
            snapshot_text=snapshot_text,
            keep_open=keep_open,
            browser_args=list(browser_args or []),
        )

    def run_actions(
        self,
        source_hint: str,
        actions: list[dict[str, str]],
        *,
        browser_args: list[str] | None = None,
        keep_open: bool = False,
        wait_ms: int = 0,
    ) -> dict[str, Any]:
        """Run explicit browser primitives without requiring an LLM provider."""

        safe, reason = classify_url(source_hint)
        if not safe:
            return {
                "status": "blocked",
                "reason": f"ssrf_blocked:{reason}",
                "url": source_hint,
                "module": self.module_id,
                "steps": [],
            }
        if not actions:
            return {
                "status": "needs_action",
                "reason": "browser_action_required",
                "url": source_hint,
                "module": self.module_id,
                "steps": [],
            }

        binary = self._find_binary()
        if not binary:
            return {
                "status": "module_unavailable",
                "reason": "agent-browser binary not found",
                "url": source_hint,
                "module": self.module_id,
                "steps": [],
            }

        base = binary + list(browser_args or [])
        steps: list[dict[str, Any]] = []
        snapshot_text = ""
        status = "ok"
        reason = ""
        try:
            opened = self._run_step(steps, "open", base + ["open", source_hint])
            if opened.returncode != 0:
                return _automation_payload(
                    status="error",
                    reason=_stderr_reason(opened.stderr),
                    url=source_hint,
                    module=self.module_id,
                    steps=steps,
                    browser_args=list(browser_args or []),
                    keep_open=keep_open,
                )

            if _actions_need_ref_snapshot(actions):
                preflight = self._run_step(steps, "snapshot:preflight", base + ["snapshot", "-i"])
                if preflight.returncode != 0:
                    status = "error"
                    reason = _stderr_reason(preflight.stderr)

            for index, action in enumerate(actions):
                if status != "ok":
                    break
                action_type = str(action.get("type") or "").strip().lower()
                target = str(action.get("target") or "").strip()
                if action_type != "click" or not target:
                    if action_type == "find_text_click" and target:
                        clicked = self._run_step(
                            steps,
                            f"find_text_click:{index + 1}",
                            base + ["find", "text", target, "click"],
                        )
                    else:
                        status = "error"
                        reason = f"unsupported_action:{action_type or 'empty'}"
                        break
                else:
                    clicked = self._run_step(steps, f"click:{index + 1}", base + ["click", target])
                if clicked.returncode != 0:
                    status = "error"
                    reason = _stderr_reason(clicked.stderr)
                    break

            if wait_ms > 0 and status == "ok":
                waited = self._run_step(steps, "wait", base + ["wait", str(wait_ms)])
                if waited.returncode != 0:
                    status = "error"
                    reason = _stderr_reason(waited.stderr)

            snapshot = self._run_step(steps, "snapshot", base + ["snapshot", "-i"])
            snapshot_text = _bounded_text(snapshot.stdout or "")
            if snapshot.returncode != 0 and status == "ok":
                status = "error"
                reason = _stderr_reason(snapshot.stderr)
        except subprocess.TimeoutExpired:
            status = "error"
            reason = "timeout"
        except OSError as exc:
            status = "error"
            reason = _exception_reason(exc)
        finally:
            if not keep_open:
                try:
                    self._run_step(steps, "close", base + ["close"], timeout=10)
                except Exception:
                    pass

        return _automation_payload(
            status=status,
            reason=reason,
            url=source_hint,
            module=self.module_id,
            steps=steps,
            instruction=" ".join(f"{item.get('type')}:{item.get('target')}" for item in actions),
            snapshot_text=snapshot_text,
            keep_open=keep_open,
            browser_args=list(browser_args or []),
        )

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
            **no_console_window(),
        )

    def _run_step(
        self,
        steps: list[dict[str, Any]],
        label: str,
        argv: list[str],
        *,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        result = self._run(argv, timeout=timeout)
        steps.append(
            {
                "label": label,
                "argv": _argv_summary(argv),
                "returncode": result.returncode,
                "stdout": _bounded_text(result.stdout or ""),
                "stderr": _bounded_text(_stderr_reason(result.stderr or "")) if result.stderr else "",
            }
        )
        return result


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


def _automation_payload(
    *,
    status: str,
    reason: str,
    url: str,
    module: str,
    steps: list[dict[str, Any]],
    instruction: str = "",
    chat_text: str = "",
    snapshot_text: str = "",
    keep_open: bool = False,
    browser_args: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "agentlas.research.browser_automation.v0",
        "status": status,
        "reason": reason,
        "module": module,
        "url": url,
        "instruction": instruction,
        "browser_args": list(browser_args or []),
        "keep_open": keep_open,
        "steps": steps,
        "chat_text": chat_text,
        "snapshot": snapshot_text,
        "browser_execution": {
            "engine": "agent-browser",
            "mode": "automation",
            "cdp_capable": True,
            "commands": ["open", "chat", "snapshot", "close" if not keep_open else "keep-open"],
        },
    }


def _read_limits(browser_args: list[str], keep_open: bool) -> list[str]:
    limits = ["browser_snapshot"]
    if "--cdp" in browser_args:
        limits.append("browser_cdp_attach")
    if "--profile" in browser_args:
        limits.append("browser_persistent_profile")
    if "--auto-connect" in browser_args:
        limits.append("browser_auto_connect")
    if keep_open:
        limits.append("browser_left_open")
    return limits


def _actions_need_ref_snapshot(actions: list[dict[str, str]]) -> bool:
    for action in actions:
        target = str(action.get("target") or "").strip()
        if target.startswith("@") or re.fullmatch(r"e\d+", target):
            return True
    return False


def _argv_summary(argv: list[str]) -> list[str]:
    out: list[str] = []
    for item in argv:
        if len(item) > 180:
            out.append(item[:177] + "...")
        else:
            out.append(item)
    return out


def _bounded_text(value: str, limit: int = 4000) -> str:
    text = redact_secret_values(str(value or "").strip())
    return text if len(text) <= limit else text[: limit - 3] + "..."
