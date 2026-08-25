"""Anonymous, fail-silent build telemetry for the hep-build CLI surface.

Contract (owner decision 2026-08-10):
- Works in local, signed-out runs: nothing here reads auth state or tokens.
- Invisible: no function in this module ever prints or raises. A telemetry
  bug, an offline machine, or a dead server kills ONLY the telemetry — the
  build command's output, exit code, and latency stay untouched.
- Anonymous: a random per-install id plus machine codes, durations, and
  version strings. Never file paths, package ids/slugs, prompts, error prose,
  usernames, emails, or anything user-authored.

Transport: the parent CLI process spawns a short-lived detached worker
(``python -m agentlas_cloud.build_telemetry --send <json>``) with stdio on
devnull, exactly like ``update._spawn_auto_update_worker``. The worker POSTs
one JSON event with a 3 second timeout and swallows every outcome, so the
parent never waits on the network.

Opt-out (checked before anything is generated, persisted, or sent):
- env  ``AGENTLAS_TELEMETRY`` in {"0", "false", "off", "no"}
- env  ``DO_NOT_TRACK`` in {"1", "true", "yes", "on"}
- file ``~/.agentlas/networking/config.json`` with ``"telemetry": false``
  (see ``networking.bootstrap.telemetry_enabled_in_config``).
"""

from __future__ import annotations

import json
import os
import platform
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SEND_TIMEOUT_SECONDS = 3
_ENDPOINT_PATH = "/api/telemetry/build"
_INSTALL_ID_KEY = "telemetry_install_id"
_COOLDOWN_KEY = "telemetry_retry_after"
# A rate-limited client that keeps sending at full rate is what keeps it
# rate-limited. Honour the server's 429 by going quiet until it lifts, and
# bound the quiet window so a bogus Retry-After cannot mute telemetry for
# good. The floor keeps a header-less 429 from turning into a hot retry.
_COOLDOWN_FLOOR_SECONDS = 300
_COOLDOWN_CEILING_SECONDS = 24 * 60 * 60
_COOLDOWN_DEFAULT_SECONDS = 3600
_EVENT_NAMES = {"scaffold", "complete", "verify", "package"}
_MODES = {"single", "team", "package"}
# Machine codes only. Anything with a separator a path/message would carry
# ("/", spaces, ":", quotes) fails this and is dropped before it can leave
# the machine.
_CODE_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


def _env_flag_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_flag_falsy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"0", "false", "off", "no"}


def telemetry_enabled() -> bool:
    """True when anonymous build telemetry may run. Never raises."""
    try:
        if _env_flag_falsy("AGENTLAS_TELEMETRY"):
            return False
        if _env_flag_truthy("DO_NOT_TRACK"):
            return False
        from .networking.bootstrap import telemetry_enabled_in_config

        return telemetry_enabled_in_config()
    except Exception:
        # An unreadable config must not silently turn telemetry ON in the face
        # of a possible user opt-out we could not read.
        return False


def _telemetry_url() -> str:
    override = os.environ.get("AGENTLAS_BUILD_TELEMETRY_URL", "").strip()
    if override:
        return override
    from .plugin_discovery import hub_base_url

    return hub_base_url() + _ENDPOINT_PATH


def _engine_version() -> str | None:
    try:
        from .update import current_release

        return current_release()
    except Exception:
        return None


def _install_id() -> str:
    """Random, persistent, anonymous install id. Never raises.

    Stored in ``~/.agentlas/networking/config.json`` next to the ``telemetry``
    opt-out key. If the file cannot be read or written, an ephemeral id is
    used for this event only (still anonymous, just not stable).
    """
    ephemeral = "eph-" + secrets.token_urlsafe(16)
    try:
        from .networking.bootstrap import atomic_write_json, default_config, networking_home, read_json

        config_path = networking_home() / "config.json"
        config = read_json(config_path, default=None)
        if isinstance(config, dict):
            existing = config.get(_INSTALL_ID_KEY)
            if isinstance(existing, str) and existing:
                return existing
        else:
            config = default_config()
        config[_INSTALL_ID_KEY] = secrets.token_urlsafe(16)
        atomic_write_json(config_path, config)
        return config[_INSTALL_ID_KEY]
    except Exception:
        return ephemeral


def _config_path_and_body() -> tuple[Any, dict[str, Any]]:
    """(path, config dict) for the shared networking config. Raises on failure."""
    from .networking.bootstrap import default_config, networking_home, read_json

    config_path = networking_home() / "config.json"
    config = read_json(config_path, default=None)
    if not isinstance(config, dict):
        config = default_config()
    return config_path, config


def _cooling_down() -> bool:
    """True while the server's last 429 is still in force. Never raises."""
    try:
        _, config = _config_path_and_body()
        until = config.get(_COOLDOWN_KEY)
        if not isinstance(until, (int, float)):
            return False
        return time.time() < float(until)
    except Exception:
        # An unreadable config must not silently lift a cooldown we set.
        return True


def _cooldown_seconds(retry_after: Any) -> int:
    """Clamp the server's Retry-After into the bounded quiet window."""
    seconds = _COOLDOWN_DEFAULT_SECONDS
    try:
        if isinstance(retry_after, str) and retry_after.strip().isdigit():
            seconds = int(retry_after.strip())
    except Exception:
        seconds = _COOLDOWN_DEFAULT_SECONDS
    return max(_COOLDOWN_FLOOR_SECONDS, min(_COOLDOWN_CEILING_SECONDS, seconds))


def _begin_cooldown(retry_after: Any) -> None:
    """Persist the quiet window so later commands do not spawn a sender."""
    try:
        from .networking.bootstrap import atomic_write_json

        config_path, config = _config_path_and_body()
        config[_COOLDOWN_KEY] = time.time() + _cooldown_seconds(retry_after)
        atomic_write_json(config_path, config)
    except Exception:
        pass


def _sanitize_code(value: Any) -> str | None:
    try:
        if not isinstance(value, str):
            return None
        candidate = value.strip().lower()
        if _CODE_RE.fullmatch(candidate):
            return candidate
        return None
    except Exception:
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _spawn_send_worker(payload: dict[str, Any]) -> None:
    """Detached fire-and-forget worker spawn. Never raises."""
    try:
        runtime_root = Path(__file__).resolve().parent.parent
        env = os.environ.copy()
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = str(runtime_root) + (
            os.pathsep + existing_pythonpath if existing_pythonpath else ""
        )
        with open(os.devnull, "rb") as stdin, open(os.devnull, "wb") as stdout, open(os.devnull, "wb") as stderr:
            subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "agentlas_cloud.build_telemetry",
                    "--send",
                    json.dumps(payload, ensure_ascii=False, sort_keys=True),
                ],
                cwd=str(runtime_root),
                env=env,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                close_fds=True,
                start_new_session=True,
            )
    except Exception:
        pass


class _BuildEventTracker:
    """One CLI command's telemetry lifecycle: a start event at construction,
    one success/fail event on ``finish``. Every method swallows everything."""

    def __init__(self, event: str, mode: str | None) -> None:
        self._enabled = False
        self._finished = False
        try:
            self._event = event if event in _EVENT_NAMES else None
            self._mode = mode if mode in _MODES else None
            if self._event is None or not telemetry_enabled():
                return
            # Going quiet costs one config read; staying loud costs the server a
            # 429 per event and this install every later measurement.
            if _cooling_down():
                return
            self._install_id = _install_id()
            self._run_id = secrets.token_urlsafe(8)
            self._started = time.monotonic()
            self._enabled = True
            self._emit(phase="start", ok=None, error_code=None, blocker_count=None, duration_ms=None)
        except Exception:
            self._enabled = False

    def _emit(
        self,
        *,
        phase: str,
        ok: bool | None,
        error_code: str | None,
        blocker_count: int | None,
        duration_ms: int | None,
    ) -> None:
        try:
            payload: dict[str, Any] = {
                "installId": self._install_id,
                "runId": self._run_id,
                "event": self._event,
                "phase": phase,
                "ok": ok,
                "errorCode": _sanitize_code(error_code),
                "blockerCount": blocker_count if isinstance(blocker_count, int) and blocker_count >= 0 else None,
                "durationMs": duration_ms,
                "mode": self._mode,
                "engineVersion": _engine_version(),
                "platform": sys.platform,
                "pythonVersion": platform.python_version(),
                "ts": _utc_now(),
            }
            _spawn_send_worker(payload)
        except Exception:
            pass

    def finish(
        self,
        ok: bool,
        error_code: str | None = None,
        blocker_count: int | None = None,
    ) -> None:
        try:
            if not self._enabled or self._finished:
                return
            self._finished = True
            duration_ms = max(0, int((time.monotonic() - self._started) * 1000))
            self._emit(
                phase="success" if ok else "fail",
                ok=bool(ok),
                error_code=error_code,
                blocker_count=blocker_count,
                duration_ms=duration_ms,
            )
        except Exception:
            pass


def build_event_tracker(event: str, mode: str | None = None) -> _BuildEventTracker:
    """Create a fail-silent tracker for one hep-build CLI command.

    Always returns a tracker object (possibly inert). Never raises.
    """
    try:
        return _BuildEventTracker(event, mode)
    except Exception:
        inert = _BuildEventTracker.__new__(_BuildEventTracker)
        inert._enabled = False
        inert._finished = True
        return inert


def _send_once(raw: str) -> None:
    """Worker-side single POST. Swallows every outcome, prints nothing."""
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        request = urllib.request.Request(
            _telemetry_url(),
            data=body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "hephaestus-build-telemetry",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=_SEND_TIMEOUT_SECONDS):
            pass
    except urllib.error.HTTPError as exc:
        # 429 is the one status worth reacting to: it is the server asking this
        # install to stop, and swallowing it means the next command sends at the
        # same rate into the same wall.
        try:
            if exc.code == 429:
                _begin_cooldown(exc.headers.get("Retry-After"))
        except Exception:
            pass
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 2 and args[0] == "--send":
        _send_once(args[1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
