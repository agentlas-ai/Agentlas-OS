"""One process-liveness probe for lock and claim owners, correct on Windows.

On Windows `os.kill(pid, 0)` is not a probe: it calls GenerateConsoleCtrlEvent(CTRL_C_EVENT) and raises a plain
OSError (WinError 87) for an ordinary live pid, so callers that read OSError as "dead" stole live claims and callers
that read it as "alive" never reclaimed a crashed holder. Windows asks the kernel instead (OpenProcess +
WaitForSingleObject, the psutil semantics) and never calls `os.kill`.

`pid_alive` returns True (alive), False (provably gone) or None (unknown). Callers must not steal on None.
"""
from __future__ import annotations

import os
from typing import Any, Callable

_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_ERROR_ACCESS_DENIED = 5
_ERROR_INVALID_PARAMETER = 87
_WAIT_OBJECT_0 = 0x0
_WAIT_TIMEOUT = 0x102


def _kernel32() -> tuple[Any, Callable[[], int]]:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    return kernel32, ctypes.get_last_error


def _windows_pid_alive(pid: int) -> bool | None:
    try:
        kernel32, last_error = _kernel32()
    except (ImportError, AttributeError, OSError):
        return None
    handle = kernel32.OpenProcess(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        error = last_error()
        if error == _ERROR_INVALID_PARAMETER:
            return False
        if error == _ERROR_ACCESS_DENIED:
            return True
        return None
    try:
        state = kernel32.WaitForSingleObject(handle, 0)
    finally:
        kernel32.CloseHandle(handle)
    if state == _WAIT_TIMEOUT:
        return True
    if state == _WAIT_OBJECT_0:
        return False
    return None


def pid_alive(pid: int) -> bool | None:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return None
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None
    return True
