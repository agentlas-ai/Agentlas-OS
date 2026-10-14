"""Original package declarations observed by admitted runtime readers only."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any, Callable
from .memory_sources import producer, register_source


def generated_declaration(text: str) -> bool:
    try:
        value = json.loads(text)
        return isinstance(value, dict) and value.get('schemaVersion') == 'agentlas.memory-view.v1' and value.get('generated') is True
    except (ValueError, TypeError):
        return False


def capture_owner() -> tuple[str, str, int] | None:
    from .memory_runtime import owner_binding, memory_root, MemoryRuntime
    try:
        owner = owner_binding(create=False)
        if not owner: return None
        runtime = MemoryRuntime(owner)
        try: return owner, str(memory_root()), runtime.epoch()
        finally: runtime.close()
    except Exception:
        return None


def observe_declarations(captured: tuple[str, str, int] | None, *, actor: str, root: Path,
                         version: str, assets: list[dict[str, Any]], assert_current: Callable[[], None]) -> list[dict[str, Any]]:
    if captured is None: return []
    from .memory_runtime import owner_binding, memory_root, MemoryRuntime
    runtime = None
    try:
        def current() -> None:
            assert_current()
            if owner_binding(create=False) != captured[0] or str(memory_root()) != captured[1] or (runtime and runtime.epoch() != captured[2]):
                raise ValueError('memory_package_owner_changed')
        root = root.absolute()
        if root.is_relative_to(memory_root()): raise ValueError('generated_memory_not_package_declaration')
        runtime = MemoryRuntime(captured[0]);refs=[]
        with runtime.db:
            current();p = producer(runtime.db, runtime.owner, 'portable-core', 'canonical-owner:' + runtime.owner)
            for asset in assets:
                if asset.get('generated') or asset['role'] not in {'instruction','skill','manifest','knowledge','tool'}: continue
                relative = asset['path']
                if relative.startswith('.agentlas/') or Path(relative).name in {'memory.json','memory.md','memory.jsonl'} or Path(relative).suffix in {'.sqlite','.db'}: continue
                old = runtime.db.execute("SELECT metadata_revision FROM memory_source_catalogue WHERE producer_id=? AND owner_namespace=? AND actor_id=? AND visibility_domain=? AND reader_contract='core.admitted-package.v1' AND logical_key=?", (p, runtime.owner, actor, 'package:' + actor, relative)).fetchone()
                ref = register_source(runtime.db, runtime.owner, p, actor_id=actor, visibility_domain='package:' + actor,
                    logical_key=relative, source_kind='portable-package-' + asset['role'], reader_contract='core.admitted-package.v1',
                    writer_contract='original-package-owner', schema_version='agentlas.runtime-assets.v1',
                    source_revision=json.dumps([version,asset['digest']],separators=(',',':')), address={'path':str(root),'ref':relative},
                    range_unit='utf8',range_end=asset['byteLength'],content_digest=asset['digest'],
                    adopt_address=True,expected_metadata_revision=old[0] if old else None)
                refs.append({'path':relative,**ref})
            current()
        return refs
    except Exception:
        return []
    finally:
        if runtime: runtime.close()


def observe_shipped_operations(source: Path, body: str, captured: tuple[str, str, int] | None) -> list[dict[str, Any]]:
    # This fixed shipped module location is selected by the original One seed,
    # never by a catalogue path, model argument or package title.
    root = Path(__file__).resolve().parent.parent / 'skills' / 'agentlas-operations'
    original = source.absolute();raw=body.encode('utf-8');digest=hashlib.sha256(raw).hexdigest()
    def current() -> None:
        if original.parent != root or original.is_symlink() or original.name not in {'SKILL.md','INDEX.md'}:
            raise ValueError('package_source_not_shipped')
        if hashlib.sha256(original.read_bytes()).hexdigest() != digest: raise ValueError('package_source_changed')
    return observe_declarations(captured,actor='agentlas-one',root=root,version='agentlas.operations-declaration.v1',
        assets=[{'path':original.name,'role':'skill','digest':digest,'byteLength':len(raw),'generated':generated_declaration(body)}],assert_current=current)


class LazyPackageRead:
    """Per-read host closure. Not serializable, and never a read permission."""
    def __init__(self, admitted: dict[str, Any], owner: tuple[str, str, int]):
        self.admitted, self.owner = admitted, owner

    def observe(self, raw: bytes) -> dict[str, Any] | None:
        try:
            text = raw.decode('utf-8')
            if generated_declaration(text): return None
            digest = hashlib.sha256(raw).hexdigest()
            root, relative = self.admitted['root'], self.admitted['path']
            target = root / relative
            def current() -> None:
                self.admitted['assert_current']()
                if target.is_symlink() or any(p.is_symlink() for p in target.parents):
                    raise ValueError('memory_package_asset_changed')
                from .workforce.local_registry import _bounded_nofollow_text
                if _bounded_nofollow_text(target, maximum=512*1024).encode('utf-8') != raw:
                    raise ValueError('memory_package_asset_changed')
            refs = observe_declarations(self.owner, actor=self.admitted['actor'], root=root,
                version=self.admitted['version'], assets=[{'path':relative,'role':self.admitted['role'],
                    'digest':digest,'byteLength':len(raw),'generated':False}], assert_current=current)
            return refs[0] if refs else None
        except Exception:
            # Optional metadata never widens or revokes the original read.
            return None


def capture_lazy_read(root: Path, relative: str) -> LazyPackageRead | None:
    """Capture existing registry authority before an original lazy file read."""
    try:
        from .workforce.local_registry import LocalWorkforceRegistry, default_local_workforce_home
        home = default_local_workforce_home()
        if not home.is_dir(): return None
        admitted = LocalWorkforceRegistry(home).admitted_lazy_asset(root, relative)
        if not admitted: return None
        owner = capture_owner()
        return LazyPackageRead(admitted, owner) if owner else None
    except Exception:
        return None
