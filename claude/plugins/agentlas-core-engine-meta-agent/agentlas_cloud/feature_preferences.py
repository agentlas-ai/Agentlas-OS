"""Shared, user-local on/off preferences for optional engine features.

Availability and installation are separate from activation. Features are off
unless an explicit preference, a documented compatibility environment
override, or a supported desktop host default enables them. Memory is the
exception: it is on by default everywhere (owner decision 2026-11-03). This module never
imports host adapters or project code.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping

SCHEMA_VERSION = "agentlas.engine-features.v1"
FEATURES = (
    "project-bootstrap",
    "auto-update",
    "memory-hooks",
    "network-index",
    "build-telemetry",
    "project-index",
    "context-map",
    "storm",
)
_FEATURE_SET = frozenset(FEATURES)
_DESKTOP_HOSTS = frozenset(
    {"desktop", "agentlas-desktop", "agentlas_desktop", "runtime:desktop"}
)
# Agentlas product hosts that wire optional features themselves keep the
# previous on-by-default behavior: Desktop, and the Agentlas Terminal, which
# launches Core directly and may attach to the engine bundled with Desktop.
_PRODUCT_HOSTS = _DESKTOP_HOSTS | frozenset({"agentlas-terminal"})
_DESKTOP_DEFAULT_FEATURES = frozenset(
    {"project-bootstrap", "project-index", "memory-hooks", "context-map", "storm", "auto-update"}
)
# Owner decision 2026-11-03: memory is on by default on every host, independent
# of One. An OFF saved before that decision is ignored once; a choice saved
# afterwards carries this marker and is honored.
_DEFAULT_ON_FEATURES = frozenset({"memory-hooks"})
MEMORY_DEFAULT_ON_MARKER = "memoryDefaultOn20261103"
_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})
_LOCK_WAIT_SECONDS = 10.0
_LOCK_RETRY_SECONDS = 0.02
_O_BINARY = getattr(os, "O_BINARY", 0)
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_THREAD_LOCKS: dict[str, threading.RLock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class FeaturePreferenceError(ValueError):
    """A feature name, value, or persisted preference document is invalid."""


def _home_path(home: str | os.PathLike[str] | None) -> Path:
    return Path(home).expanduser() if home is not None else Path.home()


def _config_path(home: str | os.PathLike[str] | None) -> Path:
    return _home_path(home) / ".agentlas" / "engine-features.json"


def _read_config(home: str | os.PathLike[str] | None) -> tuple[dict[str, Any] | None, str]:
    path = _config_path(home)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"schemaVersion": SCHEMA_VERSION, "features": {}}, "missing"
    except (OSError, UnicodeError):
        return None, "invalid"

    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, RecursionError):
        return None, "invalid"
    if (
        not isinstance(document, dict)
        or document.get("schemaVersion") != SCHEMA_VERSION
        or not isinstance(document.get("features"), dict)
        or any(
            not isinstance(name, str) or type(value) is not bool
            for name, value in document["features"].items()
        )
    ):
        return None, "invalid"
    return document, "ok"


def _env_flag(environ: Mapping[str, str], name: str) -> tuple[bool | None, str | None]:
    if name not in environ:
        return None, None
    value = str(environ[name]).strip().lower()
    if value in _TRUE:
        return True, name
    if value in _FALSE:
        return False, name
    # An explicitly supplied but malformed override must not enable a feature.
    return False, f"{name}:invalid"


def _environment_override(
    name: str,
    environ: Mapping[str, str],
    *,
    mcp: bool,
) -> tuple[bool | None, str | None]:
    if name == "project-bootstrap":
        values = []
        if mcp and "AGENTLAS_MCP_PROJECT_BOOTSTRAP_AUTO" in environ:
            values.append(_env_flag(environ, "AGENTLAS_MCP_PROJECT_BOOTSTRAP_AUTO"))
        if "AGENTLAS_PROJECT_BOOTSTRAP_AUTO" in environ:
            values.append(_env_flag(environ, "AGENTLAS_PROJECT_BOOTSTRAP_AUTO"))
        # Any explicit opt-out wins, even when another host variable opts in.
        if any(value is False for value, _ in values):
            return False, next(source for value, source in values if value is False)
        if any(value is True for value, _ in values):
            return True, next(source for value, source in values if value is True)
        return (False, values[0][1]) if values else (None, None)

    if name == "auto-update":
        values = [
            _env_flag(environ, variable)
            for variable in ("HEPHAESTUS_AUTO_UPDATE", "HEPHAESTUS_UPDATE_CHECK")
            if variable in environ
        ]
        # Either legacy opt-out wins; a legacy opt-in only applies when neither
        # variable explicitly disables checking.
        if any(value is False for value, _ in values):
            source = next(source for value, source in values if value is False)
            return False, source
        if any(value is True for value, _ in values):
            source = next(source for value, source in values if value is True)
            return True, source
        return (False, values[0][1]) if values else (None, None)

    if name == "build-telemetry":
        do_not_track, dnt_source = _env_flag(environ, "DO_NOT_TRACK")
        if do_not_track is True or (dnt_source is not None and dnt_source.endswith(":invalid")):
            return False, dnt_source
        telemetry, telemetry_source = _env_flag(environ, "AGENTLAS_TELEMETRY")
        if telemetry is False:
            return False, telemetry_source
        if telemetry is not None:
            return telemetry, telemetry_source
        return None, None

    return None, None


def _thread_lock_for(path: Path) -> threading.RLock:
    key = str(path.resolve(strict=False))
    with _THREAD_LOCKS_GUARD:
        return _THREAD_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def _settings_lock(home: str | os.PathLike[str] | None) -> Iterator[None]:
    """Serialize preference updates across threads and processes; fail closed."""

    config_path = _config_path(home)
    parent = config_path.parent
    if parent.is_symlink():
        raise FeaturePreferenceError("preference directory must not be a symlink")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_path = parent / ".engine-features.lock"
    if lock_path.is_symlink():
        raise FeaturePreferenceError("preference lock must not be a symlink")

    thread_lock = _thread_lock_for(lock_path)
    if not thread_lock.acquire(timeout=_LOCK_WAIT_SECONDS):
        raise FeaturePreferenceError("engine feature preferences are busy; existing file preserved")

    descriptor: int | None = None
    platform_lock: str | None = None
    try:
        flags = os.O_CREAT | os.O_RDWR | _O_BINARY | _O_NOFOLLOW
        descriptor = os.open(lock_path, flags, 0o600)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise FeaturePreferenceError(
                "preference lock is not a regular file; existing file preserved"
            )
        if os.name != "nt" and hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        deadline = time.monotonic() + _LOCK_WAIT_SECONDS
        if os.name == "nt":
            import msvcrt

            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            while True:
                os.lseek(descriptor, 0, os.SEEK_SET)
                try:
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    platform_lock = "windows"
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise FeaturePreferenceError(
                            "engine feature preference lock unavailable; existing file preserved"
                        ) from exc
                    time.sleep(_LOCK_RETRY_SECONDS)
        elif os.name == "posix":
            import fcntl

            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    platform_lock = "posix"
                    break
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise FeaturePreferenceError(
                            "engine feature preference lock unavailable; existing file preserved"
                        ) from exc
                    time.sleep(_LOCK_RETRY_SECONDS)
        else:
            raise FeaturePreferenceError(
                "engine feature preference locking is unsupported; existing file preserved"
            )
        yield
    except FeaturePreferenceError:
        raise
    except (ImportError, OSError) as exc:
        raise FeaturePreferenceError(
            "engine feature preference lock unavailable; existing file preserved"
        ) from exc
    finally:
        try:
            if descriptor is not None:
                try:
                    if platform_lock == "posix":
                        import fcntl

                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                    elif platform_lock == "windows":
                        import msvcrt

                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                finally:
                    os.close(descriptor)
        finally:
            thread_lock.release()


def _validate_name(name: str) -> bool:
    return isinstance(name, str) and name in _FEATURE_SET


def _host_default(name: str, environ: Mapping[str, str]) -> bool | None:
    """Return the opt-in default for a positively identified product host."""

    if name not in _DESKTOP_DEFAULT_FEATURES:
        return None
    host_runtime = str(environ.get("AGENTLAS_HOST_RUNTIME") or "").strip().lower()
    return host_runtime in _PRODUCT_HOSTS


def _effective(
    name: str,
    document: dict[str, Any] | None,
    config_status: str,
    environ: Mapping[str, str],
    *,
    mcp: bool,
) -> dict[str, Any]:
    if not _validate_name(name):
        return {"enabled": False, "configured": None, "source": "unknown-feature"}
    if config_status == "invalid":
        return {"enabled": False, "configured": None, "source": "invalid-config"}
    override, source = _environment_override(name, environ, mcp=mcp)
    configured = (
        document["features"].get(name)
        if config_status == "ok" and document is not None
        else None
    )
    # OFF is a veto: a saved opt-out or any explicit environment opt-out wins
    # over every ON source. Report the veto that actually determined the state.
    if configured is False and name in _DEFAULT_ON_FEATURES and not (document or {}).get(MEMORY_DEFAULT_ON_MARKER):
        configured = None
    if configured is False:
        return {"enabled": False, "configured": False, "source": "config"}
    if override is False:
        return {"enabled": False, "configured": configured, "source": source}
    if override is True:
        return {"enabled": True, "configured": configured, "source": source}
    if configured is True:
        return {"enabled": True, "configured": True, "source": "config"}
    host_default = _host_default(name, environ)
    if host_default:
        return {"enabled": True, "configured": None, "source": "host-default"}
    if name in _DEFAULT_ON_FEATURES:
        return {"enabled": True, "configured": None, "source": "default-on"}
    return {"enabled": False, "configured": None, "source": "default"}


def feature_enabled(
    name: str,
    home: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
    mcp: bool = False,
) -> bool:
    """Return effective feature state; unknown names or invalid config fail closed."""

    document, config_status = _read_config(home)
    environment = os.environ if environ is None else environ
    return bool(_effective(name, document, config_status, environment, mcp=mcp)["enabled"])


def storm_enabled(*, runtime: str | None = None) -> bool:
    """Apply the explicit product host default without overriding an opt-out."""
    product_host = str(runtime or "").strip().lower() in _PRODUCT_HOSTS
    environment = {**os.environ, "AGENTLAS_HOST_RUNTIME": "desktop"} if product_host else None
    return feature_enabled("storm", environ=environment)


def _write_config(path: Path, document: dict[str, Any]) -> None:
    parent = path.parent
    if parent.is_symlink():
        raise FeaturePreferenceError("preference directory must not be a symlink")
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not parent.is_dir() or path.is_symlink():
        raise FeaturePreferenceError("preference path is not a regular local file")

    payload = (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd, temporary_name = tempfile.mkstemp(prefix=".engine-features.", suffix=".tmp", dir=parent)
    temporary = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            os.chmod(path, 0o600)
        try:
            directory_fd = os.open(parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def set_feature(
    name: str,
    enabled: bool,
    home: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    """Persist an explicit on/off choice without discarding other settings."""

    if not _validate_name(name):
        raise FeaturePreferenceError(f"unknown feature: {name!r}")
    if type(enabled) is not bool:
        raise FeaturePreferenceError("enabled must be a boolean")
    write_attempted = False
    write_completed = False
    updated: dict[str, Any] | None = None
    try:
        with _settings_lock(home):
            document, config_status = _read_config(home)
            if document is None or config_status == "invalid":
                raise FeaturePreferenceError("engine feature preferences are invalid; existing file preserved")
            updated = dict(document)
            features = dict(document["features"])
            features[name] = enabled
            updated["features"] = features
            if name in _DEFAULT_ON_FEATURES:
                updated[MEMORY_DEFAULT_ON_MARKER] = True
            write_attempted = True
            _write_config(_config_path(home), updated)
            write_completed = True
    except Exception as exc:
        if not write_attempted:
            raise
        # The lock's release or a post-replace write step can fail after the
        # file changed. Report one readback, rather than claiming preservation.
        try:
            observed, config_status = _read_config(home)
        except (OSError, ValueError):
            observed, config_status = None, "invalid"
        matches = observed is not None and observed == updated
        result = _status_from_snapshot(observed, config_status, os.environ)
        result["writeOutcome"] = {
            "state": "applied" if write_completed and matches else "uncertain",
            "observed": "matches_requested" if matches else "unverified_or_different",
            "issue": "lock_release_failed" if write_completed else "write_failed",
            "errorType": type(exc).__name__,
        }
        return result
    return feature_status(home=home)


def feature_status(
    home: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Report effective and saved state for all known optional features."""

    document, config_status = _read_config(home)
    environment = os.environ if environ is None else environ
    return _status_from_snapshot(document, config_status, environment)


def _status_from_snapshot(document: dict[str, Any] | None, config_status: str, environment: Mapping[str, str]) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "configStatus": config_status,
        "features": {
            name: _effective(name, document, config_status, environment, mcp=False)
            for name in FEATURES
        },
        "mcpProjectBootstrap": _effective(
            "project-bootstrap", document, config_status, environment, mcp=True
        ),
    }


__all__ = [
    "FEATURES",
    "SCHEMA_VERSION",
    "FeaturePreferenceError",
    "feature_enabled",
    "feature_status",
    "set_feature",
]
