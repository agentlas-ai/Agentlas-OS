"""Long Windows paths for the memory tree, in one place.

Windows opens a path longer than 259 characters (248 for a folder) only when it carries the extended prefix ``\\\\?\\``
(``\\\\?\\UNC\\`` for a network share) unless the machine turned ``LongPathsEnabled`` on, and it is off by default. The memory
tree is deep by design (``owners/<64 hex>/views/agents/<64 hex>/.memory-<uuid>.tmp`` is 198 characters under the memory
root), so a user name of ordinary length is enough to go over: before this module the views were written again with
``FileNotFoundError`` and the forget ended ``partial``.

What this module does, and nothing else:

* ``extended(path, reserve)`` gives back the path the file calls should use. On POSIX, and on Windows when the path with
  ``reserve`` more characters still fits, it is the same path. Otherwise it is the absolute path with the prefix.
  The prefix is applied once, at the roots the memory tree is built from, so every path below carries it.
* ``plain(path)`` takes the prefix off again. Anything that is stored, answered or compared to a value somebody else
  wrote (an address in the source registry, the host binding's ``memory_root``) uses it: the prefix is an
  implementation detail of a file call and never leaves it.
* ``file_uri(path)`` is the SQLite URI of a path (read-only opens); SQLite takes a long path only in the escaped form.
* ``too_long(error)`` and ``busy(error)`` say why a file call failed, so the answer can carry a machine code.

``_ACTIVE`` is ``os.name == "nt"``; tests flip it, together with ``_extend_text``, to run the Windows branch on any host.
"""
from __future__ import annotations

import errno
import ntpath
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

PREFIX = "\\\\?\\"
UNC_PREFIX = "\\\\?\\UNC\\"
# A folder whose path (NUL included) is 248 characters or longer cannot be created without the prefix, a file at 260.
SAFE_CHARS = 248
# The deepest file of the memory tree is owners/<64>/views/agents/<64>/.memory-<36>.tmp, 199 characters below the root; a file opens
# up to 259 characters and a folder up to 247 (SAFE_CHARS), so the reserve is 199 - 11.
MEMORY_TREE_RESERVE = 188
# The same measured from the owner's folder (owners/<64>, 72 characters below the root) instead of the root.
OWNER_FOLDER_RESERVE = 116
WINDOWS_SHARING_ERRORS = (5, 32, 33)  # access denied, sharing violation, lock violation: another process holds the file

_ACTIVE = os.name == "nt"


def _extend_text(text: str) -> str:
    """The extended form of an absolute Windows path (pure: it works on any host). A path that cannot carry it is returned as it is."""
    if text.startswith(PREFIX):
        return text
    absolute = ntpath.normpath(text)
    if absolute.startswith("\\\\"):  # \\server\share\folder; a device path (\\.\) has no extended form
        return absolute if absolute.startswith("\\\\.\\") else UNC_PREFIX + absolute[2:]
    if len(absolute) >= 3 and absolute[1] == ":" and absolute[2] == "\\":
        return PREFIX + absolute
    return text


def _is_extended(text: str) -> bool:
    return text.startswith(PREFIX)


def active() -> bool:
    return _ACTIVE


def extended(path: "str | os.PathLike[str]", reserve: int = 0) -> Path:
    """The path to hand to file calls: ``path`` itself unless this is Windows and the path plus ``reserve`` characters would not open."""
    if not _ACTIVE:
        return path if isinstance(path, Path) else Path(path)
    text = os.fspath(path)
    if _is_extended(text) or len(text) + reserve < SAFE_CHARS:
        return path if isinstance(path, Path) else Path(text)
    return Path(_extend_text(text))


def extended_text(path: "str | os.PathLike[str]", reserve: int = 0) -> str:
    return str(extended(path, reserve)) if _ACTIVE else os.fspath(path)


def plain_text(text: str) -> str:
    if text.startswith(UNC_PREFIX):
        return "\\\\" + text[len(UNC_PREFIX):]
    if text.startswith(PREFIX):
        return text[len(PREFIX):]
    return text


def plain(path: "str | os.PathLike[str]") -> Any:
    """``path`` without the extended prefix, as the same kind of object (a str stays a str, a Path a Path)."""
    if isinstance(path, str):
        return plain_text(path)
    text = os.fspath(path)
    stripped = plain_text(text)
    return path if stripped == text else Path(stripped)


def _uri_of_extended(text: str) -> str:
    # SQLite reads this form (escaped, no authority) and opens the long path; "file:///C:/..." (what Path.as_uri gives) it does not.
    return "file:" + quote(text, safe="")


def file_uri(path: "str | os.PathLike[str]") -> str:
    """``Path(path).resolve().as_uri()``, and for a path that needs the prefix the form SQLite opens."""
    resolved = Path(path).resolve()
    if _ACTIVE:
        text = os.fspath(resolved)
        if _is_extended(text) or len(text) >= SAFE_CHARS:
            return _uri_of_extended(_extend_text(text) if not _is_extended(text) else text)
    return resolved.as_uri()


def raw_read_only_uri(path: "str | os.PathLike[str]") -> str:
    """``f"file:{path}?mode=ro"``, the form a few readers always used (it is not percent-encoded, so POSIX keeps those bytes), and on
    Windows the escaped form SQLite opens for a path that carries the prefix."""
    return file_uri(path) + "?mode=ro" if _ACTIVE else f"file:{path}?mode=ro"


def too_long(error: BaseException) -> bool:
    """True when ``error`` is a file call that failed because the path is too long for the machine (not because it is not there)."""
    if not isinstance(error, OSError):
        return False
    if getattr(error, "winerror", None) in WINDOWS_SHARING_ERRORS:
        return False  # the file is there and in use, whatever the length of its path
    if error.errno == errno.ENAMETOOLONG or getattr(error, "winerror", None) == 206:
        return True
    name = getattr(error, "filename", None)
    if _ACTIVE and name is not None:
        try:
            text = os.fspath(name)
        except TypeError:
            return False
        return isinstance(text, str) and not _is_extended(text) and len(text) >= SAFE_CHARS
    return False


def busy(error: BaseException) -> bool:
    """True when another process holds the file (an indexer, an antivirus scan, a reader): Windows only, and it passes by itself."""
    if not _ACTIVE or not isinstance(error, OSError):
        return False
    return getattr(error, "winerror", None) in WINDOWS_SHARING_ERRORS or error.errno == errno.EACCES
