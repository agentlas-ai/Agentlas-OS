"""Cross-process file locks and an atomic replace that survives Windows sharing races.

POSIX keeps exactly what the callers did before: ``fcntl.flock`` and a single ``os.replace``.

Windows has no ``fcntl``, so the JSONL ledgers and the networking init lock were written with
no lock at all; parallel hooks and subagents could interleave or overwrite lines (the C runtime
emulates ``O_APPEND`` with a seek before each write). Windows locks are mandatory byte-range
locks, so locking byte 0 would make every reader of the file fail while a line is appended.
The lock is therefore taken on one byte far past any real end of file (the trick SQLite uses
for its lock bytes): appenders serialize on it, readers never touch it, and an append-mode
write still lands at the end of the file.

``os.replace`` onto a file another process has open (an indexer, an antivirus scan, a reader
in another runtime) fails on Windows with a sharing violation that clears within milliseconds;
``replace_with_retry`` retries those briefly and re-raises anything else at once.
"""
from __future__ import annotations

import errno
import os
import time
from typing import IO, Any

try:  # POSIX
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - Windows
    _fcntl = None  # type: ignore[assignment]

try:  # Windows
    import msvcrt as _msvcrt
except ImportError:  # pragma: no cover - POSIX
    _msvcrt = None  # type: ignore[assignment]

WINDOWS_LOCK_OFFSET = 1 << 62
_WINDOWS_SHARING_ERRORS = {5, 32, 33}  # access denied, sharing violation, lock violation
_REPLACE_DELAYS = (0.01, 0.02, 0.05, 0.1, 0.2, 0.4)


def lock_handle(handle: IO[Any]) -> bool:
    """Take an exclusive lock for this open file. Returns whether a lock is held."""
    if _fcntl is not None:
        _fcntl.flock(handle.fileno(), _fcntl.LOCK_EX)
        return True
    if _msvcrt is not None:
        descriptor = handle.fileno()
        try:
            os.lseek(descriptor, WINDOWS_LOCK_OFFSET, os.SEEK_SET)
            # LK_LOCK retries once a second for ~10 s, then raises. Fail open, as before.
            _msvcrt.locking(descriptor, _msvcrt.LK_LOCK, 1)
        except OSError:
            return False
        return True
    return False


def unlock_handle(handle: IO[Any]) -> None:
    if _fcntl is not None:
        _fcntl.flock(handle.fileno(), _fcntl.LOCK_UN)
        return
    if _msvcrt is not None:
        try:
            handle.flush()
        except (OSError, ValueError):
            pass
        descriptor = handle.fileno()
        try:
            os.lseek(descriptor, WINDOWS_LOCK_OFFSET, os.SEEK_SET)
            _msvcrt.locking(descriptor, _msvcrt.LK_UNLCK, 1)
        except OSError:
            pass


def _transient_windows_replace_error(error: OSError) -> bool:
    if os.name != "nt":
        return False
    return getattr(error, "winerror", None) in _WINDOWS_SHARING_ERRORS or error.errno in {errno.EACCES}


def replace_with_retry(source: str | os.PathLike[str], destination: str | os.PathLike[str]) -> None:
    """``os.replace`` that waits out a Windows sharing violation (POSIX: one plain call)."""
    for delay in _REPLACE_DELAYS:
        try:
            os.replace(source, destination)
            return
        except OSError as error:
            if not _transient_windows_replace_error(error):
                raise
            time.sleep(delay)
    os.replace(source, destination)
