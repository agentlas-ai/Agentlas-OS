"""Short-lived, source-scoped circuit breaking for remote Workforce calls."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from threading import Lock
import time
from typing import Callable


TRANSIENT_REMOTE_FAILURES = frozenset({"source_timeout", "source_unavailable"})


@dataclass
class _OpenCircuit:
    opened_at: float


class WorkforceRemoteCircuit:
    """Skip repeated dead remote calls without changing local execution.

    State is process-local and bounded by a cooldown. The key is supplied by
    the host turn/session when available; direct callers fall back to an exact
    WorkOrder digest in ``WorkforceSourceService``. Cloud and Hub are tracked
    separately, so one source cannot suppress another source or Local.
    """

    def __init__(
        self,
        *,
        cooldown_seconds: float = 30.0,
        max_entries: int = 1024,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds must be positive")
        if max_entries <= 0:
            raise ValueError("max_entries must be positive")
        self.cooldown_seconds = float(cooldown_seconds)
        self.max_entries = int(max_entries)
        self._clock = clock or time.monotonic
        self._lock = Lock()
        self._open: dict[str, _OpenCircuit] = {}

    def _prune_expired(self, now: float) -> None:
        expired = [
            key
            for key, state in self._open.items()
            if now - state.opened_at >= self.cooldown_seconds
        ]
        for key in expired:
            self._open.pop(key, None)

    def _make_room(self) -> None:
        while len(self._open) >= self.max_entries:
            oldest_key = min(self._open, key=lambda key: self._open[key].opened_at)
            self._open.pop(oldest_key, None)

    @staticmethod
    def _state_key(context_key: str, source: str) -> str:
        material = f"{context_key}\x00{source}".encode("utf-8", "replace")
        return hashlib.sha256(material).hexdigest()

    def allow(self, context_key: str, source: str) -> tuple[bool, int | None]:
        """Return whether a remote attempt may start and the retry delay."""

        state_key = self._state_key(context_key, source)
        now = self._clock()
        with self._lock:
            self._prune_expired(now)
            state = self._open.get(state_key)
            if state is None:
                return True, None
            elapsed = now - state.opened_at
            remaining_ms = max(100, int((self.cooldown_seconds - elapsed) * 1_000))
            return False, remaining_ms

    def record_failure(self, context_key: str, source: str, code: str) -> None:
        if code not in TRANSIENT_REMOTE_FAILURES:
            return
        state_key = self._state_key(context_key, source)
        now = self._clock()
        with self._lock:
            self._prune_expired(now)
            if state_key not in self._open:
                self._make_room()
            self._open[state_key] = _OpenCircuit(opened_at=now)

    def record_success(self, context_key: str, source: str) -> None:
        """Close stale state after a transport reaches the source again."""

        state_key = self._state_key(context_key, source)
        with self._lock:
            self._open.pop(state_key, None)

    def reset(self) -> None:
        with self._lock:
            self._open.clear()


DEFAULT_WORKFORCE_REMOTE_CIRCUIT = WorkforceRemoteCircuit()


__all__ = [
    "DEFAULT_WORKFORCE_REMOTE_CIRCUIT",
    "TRANSIENT_REMOTE_FAILURES",
    "WorkforceRemoteCircuit",
]
