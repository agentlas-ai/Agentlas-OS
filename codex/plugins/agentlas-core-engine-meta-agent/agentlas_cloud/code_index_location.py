"""Where a project's code index (the five ``code-map`` files) lives.

Until now the index sat in the project folder, ``<project>/.agentlas/code-map/``. Under the memory layout it belongs to
the project's memory folder, next to the project store (``projects/<key>/memory.sqlite``):

    ``<memory root>/owners/<sha256(owner)>/projects/<sha256(project key)[:32]>/index/<sha256(real path)[:12]>/``

The folder is picked by ``memory_stores.project_ref`` (no new hash rule). The last step is the folder's real path:
``cp -r`` keeps the marker's ``projectUid``, so two copies share the project key but never share an index (each map is
bound to its own path hash and would otherwise overwrite the other's). The path itself is stored nowhere but
``manifest.json`` (``projectRoot``, used only to find orphans).

Nothing here changes the index format, the generator or any reader. It only answers *which folder*:

* ``code_map_dir(root)``               read: the new or the old folder, whichever holds a complete map (the later
                                       manifest wins; a tie goes to the new one). Never opens the root database.
* ``code_map_dir(root, for_write=True)`` write: the new folder only when the layout switch is on (``memory_layout`` is
                                       exactly ``split-1``), otherwise the old one, exactly as before.
* ``adopt_old_map(root, root_hash)``   one ``os.rename`` of the old folder into the new place. Any failure (other volume,
                                       permission, an open handle on Windows) gives up silently; the next refresh builds
                                       the map in the new place instead. No copy, no verify step.
* ``reclaim_old(root)``                the old folder goes only when the new map is complete and the old manifest has
                                       not been touched for 30 days (an older engine still writing there keeps it alive,
                                       so the two never take turns rebuilding).
* ``stamp_root(root)``                 writes ``projectRoot`` into a new-place manifest that has none (an adopted map), so
                                       ``prune_orphans`` can find it once the project is gone.
* ``prune_orphans(root)``              index folders of projects whose folder is gone (or whose key changed), untouched
                                       for 30 days.
* ``delete_project_index(owner, key)`` a project's whole index (the project-memory delete chain calls this; deleting the
                                       project's memory folder or the account removes it as well, it is nested).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
from pathlib import Path

from . import long_path

INDEX_DIRNAME = "index"
LEGACY_PARTS = (".agentlas", "code-map")
CORE_FILES = ("project-map.json", "manifest.json", ".cache.json")
ALL_FILES = ("project-map.json", "project-map.md", "project-seed.json", ".cache.json", "manifest.json")
# Windows stops at 260 characters; elsewhere the limit only guards against absurd roots. Desktop uses the same numbers.
MAX_PATH_CHARS = 240 if os.name == "nt" else 900
STALE_SECONDS = 30 * 24 * 60 * 60
# Same bound the ontology reader already applies to a map; a bigger old map is not worth moving (it was built by an
# older generator without a size limit) and the new place builds a bounded one.
ADOPT_MAX_BYTES = 64 * 1024 * 1024
PRUNE_SCAN_LIMIT = 64


def legacy_dir(root: str | Path) -> Path:
    return Path(root).joinpath(*LEGACY_PARTS)


def _real(root: str | Path) -> str:
    try:
        return os.path.realpath(str(root))
    except (OSError, ValueError):
        return str(root)


def _path_hash(root: str | Path) -> str:
    return hashlib.sha256(_real(root).encode("utf-8", errors="replace")).hexdigest()[:12]


def _owner() -> str | None:
    try:
        from .memory_runtime import owner_binding

        return owner_binding(create=False)
    except Exception:  # noqa: BLE001 - location never fails a read
        return None


def _links_inside(path: Path, boundary: Path) -> bool:
    """True when ``path`` or a folder between it and ``boundary`` is a link (existing parts only)."""
    try:
        for part in (path, *path.parents):
            if part == boundary:
                return False
            if part.is_symlink():
                return True
    except OSError:
        return True
    return False


def project_folder(owner: str, root: str | Path) -> Path | None:
    """``projects/<key>/`` of this project for this owner (the folder that holds the project store)."""
    try:
        from . import memory_stores
        from .project_identity import project_key

        return memory_stores.project_ref(owner, project_key(root)).path.parent
    except Exception:  # noqa: BLE001
        return None


def index_dir(root: str | Path) -> Path | None:
    """The new-place folder of this project's code map, or None when it cannot be resolved safely (no owner yet, a link
    or an over-long path): None means "use the old place". Computes a path; creates nothing."""
    try:
        owner = _owner()
        if not owner:
            return None
        folder = project_folder(owner, root)
        if folder is None:
            return None
        target = folder / INDEX_DIRNAME / _path_hash(root)
        from .memory_runtime import memory_io_root

        if len(str(long_path.plain(target))) > MAX_PATH_CHARS or _links_inside(target, memory_io_root()):
            return None
        return target
    except Exception:  # noqa: BLE001
        return None


def _regular(path: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink()
    except OSError:
        return False


def _complete_stamp(folder: Path | None) -> float | None:
    """manifest mtime when the three files a reader needs are regular files in ``folder``, else None."""
    if folder is None:
        return None
    try:
        if not all(_regular(folder / name) for name in CORE_FILES):
            return None
        return (folder / "manifest.json").stat().st_mtime
    except OSError:
        return None


def write_switch_on() -> bool:
    """True only when the root store's ``memory_layout`` is exactly ``split-1``. Read-only, never creates a store, any
    failure reads as off. Used by writes and adoption, never by the read path."""
    try:
        owner = _owner()
        if not owner:
            return False
        from . import memory_stores
        from .memory_runtime import memory_path

        path = memory_path(owner)
        if not path.is_file():
            return False
        db = sqlite3.connect(long_path.file_uri(path) + "?mode=ro", uri=True, timeout=0.25)
        try:
            row = db.execute("SELECT value FROM memory_store_meta WHERE key=?", (memory_stores.LAYOUT_KEY,)).fetchone()
        finally:
            db.close()
        return bool(row) and row[0] == memory_stores.SPLIT_LAYOUT
    except Exception:  # noqa: BLE001
        return False


def code_map_dir(root: str | Path, *, for_write: bool = False) -> Path:
    old = legacy_dir(root)
    new = index_dir(root)
    if new is None:
        return old
    if for_write:
        return new if write_switch_on() else old
    new_stamp, old_stamp = _complete_stamp(new), _complete_stamp(old)
    if new_stamp is None and old_stamp is None:
        # Neither is whole. Point at the one that holds anything, so diagnostics describe it; the old place on a tie.
        return new if _regular(new / "project-map.json") and not _regular(old / "project-map.json") else old
    if new_stamp is None:
        return old
    if old_stamp is None:
        return new
    return new if new_stamp >= old_stamp else old


def new_place_writable(folder: Path) -> bool:
    """Create the parent folders of the new place (owner-only) and check they accept writes. False = keep the old place."""
    try:
        for part in reversed([p for p in folder.parents if not p.exists()]):
            part.mkdir(mode=0o700, exist_ok=True)
        return os.access(folder.parent, os.W_OK)
    except OSError:
        return False


def receipt_name(name: str) -> str:
    """The label receipts and ``created`` lists have always used, whichever place holds the file."""
    return f".agentlas/code-map/{name}"


def _read_manifest(folder: Path) -> dict:
    try:
        payload = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def adopt_old_map(root: str | Path, root_hash: str) -> bool:
    """Move the old folder into the new place with one rename. Call only when the switch is on and the target is the
    new place. Returns True when the rename happened. Never raises, never copies."""
    try:
        old, new = legacy_dir(root), index_dir(root)
        if new is None or _complete_stamp(new) is not None or _complete_stamp(old) is None:
            return False
        if old.is_symlink() or (old / "project-map.json").stat().st_size > ADOPT_MAX_BYTES:
            return False
        manifest = _read_manifest(old)
        # A copied project carries the original's map: it is bound to the other path and is not adopted.
        if manifest.get("complete") is not True or manifest.get("projectRootHash") != root_hash:
            return False
        new.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.rename(old, new)
        return True
    except Exception:  # noqa: BLE001 - EXDEV, permissions, Windows handles: the new place is simply built fresh
        return False


def reclaim_old(root: str | Path) -> bool:
    """Delete the old folder when the new map is complete and the old manifest is more than 30 days old."""
    try:
        old, new = legacy_dir(root), index_dir(root)
        if new is None or _complete_stamp(new) is None or old.is_symlink() or not old.is_dir():
            return False
        stamps = []
        for name in ("manifest.json", "project-map.json"):
            try:
                stamps.append((old / name).stat().st_mtime)
            except OSError:
                pass
        if not stamps or time.time() - max(stamps) <= STALE_SECONDS:
            return False
        for name in os.listdir(old):
            target = old / name
            if name in ALL_FILES or name.startswith("."):
                try:
                    target.unlink()
                except OSError:
                    pass
        os.rmdir(old)
        return True
    except Exception:  # noqa: BLE001
        return False


def record_root(manifest: dict, root: str | Path) -> dict:
    """The one optional key a new-place manifest carries, so a gone project's index can be found later."""
    return {**manifest, "projectRoot": str(root)}


def stamp_root(root: str | Path) -> bool:
    """Give a new-place manifest the ``projectRoot`` key when it has none (a map adopted by rename from the old place was
    written by an engine that never wrote it, so ``prune_orphans`` could not tell when its project was gone). The file is
    replaced atomically with every other key unchanged and keeps its modification time (this is not a rebuild, so it neither
    delays the 30-day rule nor wins the "later manifest" comparison). The path stays in this one file: no receipt, upload or
    response carries it. True when the key was written. Never raises."""
    temp = None
    try:
        new = index_dir(root)
        if new is None or _complete_stamp(new) is None:
            return False
        path = new / "manifest.json"
        manifest = _read_manifest(new)
        if not manifest:
            return False
        if isinstance(manifest.get("projectRoot"), str) and manifest["projectRoot"]:
            return False
        before = path.stat()
        temp = path.with_name(f".manifest.json.tmp-{os.getpid()}-{time.time_ns()}")
        text = json.dumps(record_root(manifest, root), ensure_ascii=False, separators=(",", ":")) + "\n"
        descriptor = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.utime(temp, ns=(before.st_atime_ns, before.st_mtime_ns))
        os.replace(temp, path)
        temp = None
        return True
    except Exception:  # noqa: BLE001
        return False
    finally:
        if temp is not None:
            try:
                temp.unlink()
            except OSError:
                pass


def prune_orphans(root: str | Path) -> int:
    """Remove index folders (of this owner's projects) whose project folder no longer exists, or whose project key
    changed, when untouched for 30 days. At most 64 folders are looked at per call. Returns how many were removed."""
    removed = 0
    try:
        owner = _owner()
        if not owner:
            return 0
        from . import memory_stores
        from .project_identity import project_key

        projects = memory_stores.account_dir(owner) / "projects"
        looked = 0
        for project in sorted(projects.iterdir()):
            index = project / INDEX_DIRNAME
            if project.is_symlink() or index.is_symlink() or not index.is_dir():
                continue
            for entry in sorted(index.iterdir()):
                looked += 1
                if looked > PRUNE_SCAN_LIMIT:
                    return removed
                stamp = _complete_stamp(entry)
                manifest_path = entry / "manifest.json"
                if entry.is_symlink() or not entry.is_dir() or not manifest_path.is_file():
                    continue
                try:
                    age = time.time() - manifest_path.stat().st_mtime
                except OSError:
                    continue
                if age <= STALE_SECONDS:
                    continue
                recorded = _read_manifest(entry).get("projectRoot")
                if not isinstance(recorded, str) or not recorded:
                    continue
                gone = not Path(recorded).is_dir()
                superseded = False
                if not gone:
                    folder = memory_stores.project_ref(owner, project_key(recorded)).path.parent
                    superseded = folder != project or _path_hash(recorded) != entry.name
                if (gone or superseded) and _remove_tree(entry, memory_stores.account_dir(owner)):
                    removed += 1
            try:
                index.rmdir()  # only when empty
            except OSError:
                pass
    except Exception:  # noqa: BLE001
        pass
    return removed


def _remove_tree(path: Path, boundary: Path) -> bool:
    try:
        if _links_inside(path, boundary) or long_path.plain(boundary.resolve()) not in long_path.plain(path.resolve()).parents:
            return False
        shutil.rmtree(path)
        return not path.exists()
    except OSError:
        return False


def delete_project_index(owner: str, key: str) -> bool:
    """Remove one project's whole ``index/`` folder. True when nothing is left."""
    try:
        from . import memory_stores

        folder = memory_stores.project_ref(owner, key).path.parent / INDEX_DIRNAME
        if not folder.exists() and not folder.is_symlink():
            return True
        if folder.is_symlink():
            folder.unlink()
            return True
        return _remove_tree(folder, memory_stores.account_dir(owner))
    except Exception:  # noqa: BLE001
        return False
