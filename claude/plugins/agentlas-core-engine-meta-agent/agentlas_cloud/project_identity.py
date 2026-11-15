"""A project folder's own identity (Agentlas 2.0, N-B06).

``projectId`` in ``.agentlas/memory-map.json`` comes from the folder NAME, so ``clientA/app`` and ``clientB/app`` share
it and cannot be a key. A newly seeded marker also carries ``projectUid`` (a UUID). Nothing else is added to the marker:
the file travels with the folder (packages, uploads, sync), so it must not hold a path of this computer. A folder
copied with its marker therefore keeps the same uid (it is treated as the same project).

``project_key(root)`` answers "which project is this folder" and never raises, never writes:

* marker with ``projectUid`` -> that uid;
* no marker, an old marker without the field, or unreadable -> ``path:`` + sha256 of the real path (old markers are not rewritten).

Kept without a caller yet on purpose: (the project memory store) and (code map / context map) take their
store key from this function, so the key rule has exactly one definition.
"""

from __future__ import annotations

import hashlib
import json
import ntpath
import os
import sys
import unicodedata
import uuid
from pathlib import Path
from typing import Any

MARKER_RELATIVE = (".agentlas", "memory-map.json")
_MAX_MARKER_BYTES = 4 * 1024 * 1024


_F_GETPATH = 50  # macOS fcntl: the path of an open descriptor, spelled the way the disk keeps it
_PATH_MAX = 1024


def canonical_spelling(real: str, platform: str | None = None) -> str:
    """The spelling of an already resolved folder path that the disk keeps, so that one folder is one hash whatever the person typed.

    The desktop hashes ``realpath.native`` (Node), which is the disk's own spelling; Python's ``realpath`` keeps the letters it was given, so a folder
    typed ``/users/me/documents/Proj`` on a case-insensitive disk was another project to the engine. macOS: the kernel names the open folder
    (``F_GETPATH``, one call, no listing; a folder that cannot be opened, a name the kernel spells with other letters than a case or normalization
    difference, or a file keeps the given spelling). Windows: the drive letter is upper case (``realpath`` already gives the disk's spelling of the rest).
    Linux and every case-sensitive disk: unchanged. Never raises."""
    platform = platform or sys.platform
    if platform == "win32":
        drive, rest = ntpath.splitdrive(real)
        if len(drive) == 2 and drive[1] == ":" and drive[0].isalpha():
            return drive.upper() + rest
        return real
    if platform != "darwin":
        return real
    try:
        import fcntl
        fd = os.open(real, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NONBLOCK", 0))
        try:
            kernel = os.fsdecode(fcntl.fcntl(fd, getattr(fcntl, "F_GETPATH", _F_GETPATH), b"\0" * _PATH_MAX).split(b"\0", 1)[0])
        finally:
            os.close(fd)
        fold = lambda text: unicodedata.normalize("NFC", text).casefold()  # noqa: E731
        return kernel if kernel and fold(kernel) == fold(real) else real
    except (OSError, ImportError, ValueError, TypeError):
        return real


def canonical_real_path(path: str | Path, platform: str | None = None) -> str:
    """``os.path.realpath`` in the disk's spelling (see ``canonical_spelling``)."""
    return canonical_spelling(os.path.realpath(os.fspath(path)), platform)


def path_key(root: str | Path) -> str:
    """``path:`` + sha256 of the real path in the disk's spelling. Stable for a folder that does not move."""
    try:
        real = canonical_real_path(root)
    except (OSError, ValueError):
        real = str(root)
    return "path:" + hashlib.sha256(real.encode("utf-8", errors="replace")).hexdigest()


def legacy_path_key(root: str | Path) -> str | None:
    """The key before EK4 spelled the path the disk's way: sha256 of ``realpath`` as typed. ``None`` when it is the same as ``path_key`` (the usual case: the folder was typed as the
    disk spells it). A store written under it is still read (``memory_stores.project_keys`` lists it last)."""
    try:
        typed = "path:" + hashlib.sha256(os.path.realpath(os.fspath(root)).encode("utf-8", errors="replace")).hexdigest()
    except (OSError, ValueError):
        return None
    return typed if typed != path_key(root) else None


def new_project_uid() -> str:
    return str(uuid.uuid4())


def _read_marker(path: Path) -> dict[str, Any] | None:
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_MARKER_BYTES:
            return None
        payload = json.loads(path.read_text(encoding="utf-8").lstrip("﻿"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def project_key(root: str | Path) -> str:
    """The project's key: ``projectUid`` when the marker has one, else the path hash. Never raises, never writes."""
    try:
        payload = _read_marker(Path(root).expanduser().joinpath(*MARKER_RELATIVE))
        uid = payload.get("projectUid") if payload else None
        if isinstance(uid, str) and uid.strip():
            return uid
    except Exception:  # noqa: BLE001 - a hook never fails over project identity
        pass
    return path_key(root)
