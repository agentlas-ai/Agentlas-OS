"""Optional standalone memory: owner-local recall and current-turn intake only."""
from __future__ import annotations

import html
import json
import os
import re
import stat
import time
from pathlib import Path
from typing import Any

from .feature_preferences import feature_enabled
from .prompt_order import compose_prompt

MAX_TRANSCRIPT_BYTES = 2 * 1024 * 1024


def capsule(payload: dict[str, Any], host: str, event: str = "SessionStart") -> str | None:
    """Session-start notice of the memory tools; nothing is injected per turn.

    Owner decision 2026-11-03: per-turn recall injection is removed. Recall is
    done by the model through memory.search / memory.timeline when it needs it,
    and the model records its turn through memory.record instead of printing a
    memory ticket in the reply.
    """
    if event != "SessionStart" or not feature_enabled("memory-hooks"):
        return None
    from .prompt_composition import MEMORY_RECALL_MENU
    notice = compose_prompt([{
        "id": "os.memory-standalone.session-notice", "revision": 2,
        "stability": "fixed-policy", "changeTriggers": ["release"],
        "text": MEMORY_RECALL_MENU,
    }])
    return "<agentlas-memory-tools>\n" + html.escape(notice, quote=False) + "\n</agentlas-memory-tools>"


_MARKDOWN = re.compile(r"[*_`#>|]+")


def excerpt_summary(texts: list[str]) -> str | None:
    """First paragraph of the final reply as a fallback turn summary (no model call)."""
    if not texts:
        return None
    text = texts[-1].split("## Memory Events", 1)[0]
    text = re.sub(r"^\s*\*\*\[[^\]]{1,40}\]\*\*\s*", "", text)
    for paragraph in re.split(r"\n\s*\n", text):
        cleaned = " ".join(_MARKDOWN.sub(" ", paragraph).split())
        if len(cleaned) >= 12:
            if len(cleaned) > 300:
                cut = cleaned[:300]
                stop_at = max(cut.rfind(". "), cut.rfind("다. "), cut.rfind("요. "))
                cleaned = cut[: stop_at + 1] if stop_at > 80 else cut.rstrip() + "…"
            return cleaned
    return None


def _recorded_recently(host: str, minutes: int = 10) -> bool:
    """A memory.record ticket from this runtime in the last few minutes covers the turn."""
    try:
        import sqlite3
        from .memory_runtime import memory_path, owner_binding
        owner = owner_binding(create=False)
        if not owner:
            return False
        path = memory_path(owner)
        if not path.exists():
            return False
        db = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=0.5)
        try:
            cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - minutes * 60))
            row = db.execute("SELECT 1 FROM memory_operations WHERE source_ref LIKE 'mcp-record:%' AND actor_id LIKE ? "
                             "AND created_at >= ? LIMIT 1", ("host:%" + host.split("-")[0] + "%", cutoff)).fetchone()
            return row is not None
        finally:
            db.close()
    except Exception:
        return False


def _current_texts(payload: dict[str, Any], host: str) -> list[str]:
    """Bound reads to an explicit host transcript; never scan other sessions."""
    supplied = payload.get("assistant_texts") or payload.get("assistantTexts")
    if isinstance(supplied, str):
        supplied = [supplied]
    if isinstance(supplied, list):
        return [text[-64000:] for text in supplied[-4:] if isinstance(text, str)]
    # Current hosts may supply the final response directly without a transcript.
    final = payload.get("last_assistant_message")
    if isinstance(final, str):
        return [final[-64000:]]
    raw = next((payload[key] for key in ("transcript_path", "transcriptPath", "rollout_path", "rolloutPath")
                if isinstance(payload.get(key), str) and payload[key]), None)
    if not raw:
        return []
    expected_session = payload.get("session_id") or payload.get("sessionId") or payload.get("conversation_id")
    if not isinstance(expected_session, str) or not expected_session.strip() or host not in {"claude", "codex"}:
        return []
    home = Path.home()
    variable, directory = ("CLAUDE_CONFIG_DIR", ".claude") if host == "claude" else ("CODEX_HOME", ".codex")
    host_home = Path(os.environ.get(variable, str(home / directory))).expanduser()
    allowed = host_home / ("projects" if host == "claude" else "sessions")
    path = Path(raw).expanduser()
    if (not path.is_absolute() or ".." in path.parts or not host_home.is_absolute()
            or not host_home.is_relative_to(home) or not path.is_relative_to(allowed)
            or path.suffix != ".jsonl"):
        return []
    # Refuse linked ancestors as well as a linked leaf. The descriptor and a
    # second path identity check bind the bytes to the inspected host file.
    components = (path, *path.parents)
    if any(component.is_symlink() for component in components):
        return []
    # On platforms without descriptor-relative no-follow traversal, only the
    # host-supplied final-message form is accepted. A pathname check cannot
    # secure Windows ancestor replacement during a concurrent rename.
    if os.open not in os.supports_dir_fd or not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        return []
    directory_fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            child_fd = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = child_fd
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    finally:
        os.close(directory_fd)
    from .one_workspace import _assistant_texts_in
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
            return []
        # Codex binds the entire rollout to the first session_meta record.
        # Claude carries sessionId on each assistant row instead.
        header = os.read(descriptor, 65536).split(b"\n", 1)[0]
        if host == "codex":
            metadata = json.loads(header)
            if (not isinstance(metadata, dict) or metadata.get("type") != "session_meta"
                    or not isinstance(metadata.get("payload"), dict)
                    or metadata["payload"].get("id") != expected_session):
                return []
        offset = max(0, opened.st_size - MAX_TRANSCRIPT_BYTES)
        os.lseek(descriptor, offset, os.SEEK_SET)
        data = os.read(descriptor, MAX_TRANSCRIPT_BYTES)
        if offset:
            data = data.split(b"\n", 1)[1] if b"\n" in data else b""
        current, after = path.lstat(), os.fstat(descriptor)
        if (any(component.is_symlink() for component in components)
                or not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                or (current.st_ino, current.st_dev) != (opened.st_ino, opened.st_dev)
                or (after.st_size, after.st_mtime_ns) != (opened.st_size, opened.st_mtime_ns)):
            return []
    finally:
        os.close(descriptor)
    texts: list[str] = []
    for line in data.decode("utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
            if host == "claude" and (not isinstance(row, dict) or row.get("sessionId") != expected_session):
                continue
            found: list[str] = []
            _assistant_texts_in(row, found)
            if found:
                texts = [text[-64000:] for text in found[-4:]]
        except (ValueError, RecursionError):
            continue
    return texts


def stop(payload: dict[str, Any], host: str) -> dict[str, Any]:
    """Queue an observed current-session summary, with no legacy side effects."""
    if not feature_enabled("memory-hooks"):
        return {"state": "disabled", "reason": "feature_disabled"}
    from .memory_runtime import hook_identity, owner_binding, queue_hook_summary, schedule_worker
    if not hook_identity(payload, host):
        return {"state": "skipped", "reason": "session_identity_missing"}
    from .one_workspace import harvest_memory_events_from_texts, latest_turn_summary
    texts = _current_texts(payload, host)
    summary = latest_turn_summary(texts)
    source = "memory_events"
    if not summary:
        if _recorded_recently(host):
            return {"state": "skipped", "reason": "recorded_by_tool"}
        summary = excerpt_summary(texts)
        source = "host_excerpt"
        if summary:
            from .memory_runtime import _safe_summary
            try:
                summary = _safe_summary(summary)
            except ValueError:
                return {"state": "skipped", "reason": "excerpt_not_safe"}
    if not summary:
        return {"state": "skipped", "reason": "observed_summary_missing"}
    observations = harvest_memory_events_from_texts(texts)
    # Serialize intake with OFF's preference commit. Once OFF returns, this
    # process cannot subsequently create a queue entry from an earlier read.
    from .feature_preferences import _settings_lock
    with _settings_lock(None):
        if not feature_enabled("memory-hooks"):
            return {"state": "disabled", "reason": "feature_disabled"}
        result = queue_hook_summary(payload, host, summary, 1, observations)
    result["summarySource"] = source
    operation_id = result.get("operation_id")
    if isinstance(operation_id, str) and result.get("state") in {"queued", "deferred"} and feature_enabled("memory-hooks"):
        result["workerScheduled"] = schedule_worker(operation_id, owner_binding() or "")
    return result
