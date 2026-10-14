"""Trusted native host ownership, independent of model DTOs and provider choice."""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import time
from pathlib import Path
from typing import Any

SCHEMA = "agentlas.memory-owner-binding.v1"
FILE_ENV = "AGENTLAS_MEMORY_BINDING_FILE"
REV_ENV = "AGENTLAS_MEMORY_BINDING_REVISION"


def _private_json(path: Path, maximum: int = 16384) -> dict[str, Any]:
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("memory_host_binding_path_invalid")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > maximum:
            raise ValueError("memory_host_binding_file_invalid")
        if os.name == "posix" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
            raise ValueError("memory_host_binding_file_permissions")
        raw = os.read(fd, maximum + 1)
        current = path.stat(follow_symlinks=False)
        if current.st_ino != info.st_ino or current.st_dev != info.st_dev or len(raw) > maximum:
            raise ValueError("memory_host_binding_changed")
    finally:
        os.close(fd)
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("memory_host_binding_invalid")
    return value


def host_binding() -> dict[str, Any] | None:
    file, revision = os.environ.get(FILE_ENV), os.environ.get(REV_ENV)
    if not file and not revision:
        return None
    try:
        if not file or not revision:
            raise ValueError("memory_host_binding_missing")
        if Path(file + ".revoked." + revision).exists():
            raise ValueError("memory_host_binding_revoked")
        p = _private_json(Path(file))
        if Path(file + ".revoked." + revision).exists():
            raise ValueError("memory_host_binding_revoked")
        root = Path(os.environ.get("AGENTLAS_MEMORY_ROOT", "")).expanduser()
        if p.get("state") == "unavailable" and p.get("reason") == "memory_account_binding_unavailable":
            raise ValueError("memory_account_binding_unavailable")
        if (p.get("schema_version") != SCHEMA or p.get("binding_revision") != revision or p.get("state") != "active"):
            raise ValueError("memory_host_binding_revoked")
        if not root.is_absolute() or p.get("memory_root") != str(root):
            raise ValueError("memory_host_binding_root_changed")
        if not Path(file).is_relative_to(root / "runtime-bindings"):
            raise ValueError("memory_host_binding_path_invalid")
        if p.get("owner_namespace") != os.environ.get("AGENTLAS_MEMORY_OWNER_NAMESPACE"):
            raise ValueError("memory_host_binding_owner_changed")
        if not isinstance(p.get("source_id"), str) or not p["source_id"]:
            raise ValueError("memory_host_binding_source_missing")
        expires = p.get("expires_at")
        if type(expires) is not int or expires <= int(time.time() * 1000):
            raise ValueError("memory_host_binding_expired")
        if type(p.get("revocation_epoch")) is not int or p["revocation_epoch"] < 0:
            raise ValueError("memory_host_binding_epoch_invalid")
        registry = _private_json(root / "registry.json")
        if registry.get("schemaVersion") != "agentlas.memory-registry.v1" or registry.get("deviceCustodyId") != p.get("device_custody_id"):
            raise ValueError("memory_host_binding_custody_changed")
        return p
    except (OSError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("memory_host_binding_unavailable") from exc


def assert_host_binding(owner: str, root: Path) -> None:
    binding = host_binding()
    if binding and (binding["owner_namespace"] != owner or binding["memory_root"] != str(root)):
        raise ValueError("memory_host_binding_owner_changed")
    if binding is None:
        from .memory_runtime import owner_binding, memory_root
        if memory_root() != root or owner_binding(create=False) != owner:
            raise ValueError("memory_host_binding_owner_changed")


def has_account_credential() -> bool:
    """Presence is a refusal signal, never a namespace or authentication proof."""
    home = Path(os.environ.get("AGENTLAS_AUTH_HOME") or
                str(Path(os.environ.get("AGENTLAS_HOME") or "~/.agentlas").expanduser() / "auth")).expanduser()
    if not home.exists():
        return False
    if home.is_symlink():
        return True
    files = list(home.glob("*.json"))
    if len(files) > 64:
        return True
    for file in files:
        try:
            value = _private_json(file)
            if value.get("access_token") or value.get("refresh_token"):
                return True
        except (OSError, ValueError):
            return True
    return False


class BindingCursor(sqlite3.Cursor):
    def execute(self, *args, **kwargs):
        self.connection._binding_guard()
        return super().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        self.connection._binding_guard()
        return super().executemany(*args, **kwargs)

    def fetchone(self):
        self.connection._binding_guard()
        return super().fetchone()

    def fetchall(self):
        self.connection._binding_guard()
        return super().fetchall()

    def fetchmany(self, *args):
        self.connection._binding_guard()
        return super().fetchmany(*args)

    def __next__(self):
        self.connection._binding_guard()
        return super().__next__()


class BindingConnection(sqlite3.Connection):
    def _binding_guard(self):
        owner = getattr(self, "binding_owner", None)
        if owner:
            assert_host_binding(owner, self.binding_root)
            binding = host_binding()
            if binding:
                exists = sqlite3.Connection.execute(self, "SELECT 1 FROM sqlite_master WHERE name='memory_forget_clock'").fetchone()
                if exists:
                    row = sqlite3.Connection.execute(self, "SELECT epoch FROM memory_forget_clock WHERE id=1").fetchone()
                    if row and row[0] != binding["revocation_epoch"]:
                        raise ValueError("memory_host_binding_epoch_changed")

    def cursor(self, *args, **kwargs):
        self._binding_guard()
        return super().cursor(factory=BindingCursor)

    def execute(self, *args, **kwargs):
        return self.cursor().execute(*args, **kwargs)

    def executemany(self, *args, **kwargs):
        return self.cursor().executemany(*args, **kwargs)

    def executescript(self, *args, **kwargs):
        self._binding_guard()
        return super().executescript(*args, **kwargs)

    def commit(self):
        self._binding_guard()
        return super().commit()
    # Rollback, close and cancellation deliberately remain unconditional.
