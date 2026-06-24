"""Shared command bridge for optional browser snapshot hardpoints."""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
from urllib.parse import urlsplit

from agentlas_cloud.networking.bootstrap import utc_now

from ..contracts import ResearchAttempt, ResearchModuleManifest, ResearchRequest, ResearchResult, _stable_hash
from ..policy import DEFAULT_MAX_BYTES, classify_url
from ..redaction import redact_secret_values, redacted_exception_reason


class CommandSnapshotAdapter:
    module_id: str
    capabilities: tuple[str, ...]
    weight = "browser_heavy"
    manifest: ResearchModuleManifest
    env_var = ""
    command_label = "browser_snapshot"
    output_fields: tuple[str, ...] = ("content_markdown", "snapshot", "result", "text", "stdout")
    base_limits: tuple[str, ...] = ("browser_snapshot",)
    missing_reason = "snapshot command not configured"

    def __init__(self, *, timeout_seconds: int = 60, max_bytes: int = DEFAULT_MAX_BYTES):
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

        argv = self._snapshot_argv(source_hint)
        if not argv:
            return (
                None,
                ResearchAttempt(self.module_id, "module_unavailable", self.missing_reason, source_hint, weight=self.weight),
            )

        try:
            completed = self._run(argv)
        except subprocess.TimeoutExpired:
            return None, ResearchAttempt(self.module_id, "error", "timeout", source_hint, weight=self.weight)
        except (OSError, ValueError) as exc:
            return None, ResearchAttempt(
                self.module_id,
                "error",
                _exception_reason(exc),
                source_hint,
                weight=self.weight,
            )
        if completed.returncode != 0:
            return None, ResearchAttempt(
                self.module_id,
                "error",
                _stderr_reason(completed.stderr),
                source_hint,
                weight=self.weight,
            )

        text, title, limits = _parse_snapshot_output(completed.stdout or "", fields=self.output_fields, max_bytes=self.max_bytes)
        if not text:
            return None, ResearchAttempt(self.module_id, "error", "empty_snapshot", source_hint, weight=self.weight)

        title = title or _title_from_snapshot(text) or source_hint
        result = ResearchResult(
            source_id=_stable_hash(source_hint),
            url=source_hint,
            title=title,
            platform="browser",
            content_markdown=text,
            extracted_at=utc_now(),
            freshness=request.freshness,
            confidence="usable",
            limits=_dedupe(list(self.base_limits) + limits),
            citations=[{"label": title, "url": source_hint}],
        )
        return result, ResearchAttempt(self.module_id, "ok", self.command_label, source_hint, weight=self.weight)

    def _snapshot_argv(self, url: str) -> list[str]:
        raw = os.environ.get(self.env_var, "").strip()
        if not raw:
            return []
        argv = shlex.split(raw)
        has_placeholder = any("{url}" in arg for arg in argv)
        argv = [arg.replace("{url}", url) for arg in argv]
        if not has_placeholder:
            argv.append(url)
        return argv

    def _run(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=self.timeout_seconds,
        )


def _parse_snapshot_output(raw: str, *, fields: tuple[str, ...], max_bytes: int) -> tuple[str, str, list[str]]:
    text = raw[:max_bytes]
    limits: list[str] = []
    if len(raw.encode("utf-8", "ignore")) > max_bytes:
        limits.append("truncated")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text.strip(), "", limits
    if not isinstance(payload, dict):
        return text.strip(), "", limits
    body = ""
    for field in fields:
        value = payload.get(field)
        if value:
            body = str(value).strip()
            break
    title = str(payload.get("title") or "").strip()
    payload_limits = payload.get("limits") if isinstance(payload.get("limits"), list) else []
    return body, title, _dedupe(limits + [str(item) for item in payload_limits])


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


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
