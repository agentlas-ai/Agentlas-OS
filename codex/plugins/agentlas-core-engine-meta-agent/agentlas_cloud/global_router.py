"""Install Hephaestus global routing instructions into host prompt files."""

from __future__ import annotations

import os
import hashlib
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from .prompt_order import compose_prompt

_O_BINARY = getattr(os, "O_BINARY", 0)  # Windows: os.open() fds are text mode without it

BEGIN = "<!-- HEPHAESTUS:GLOBAL-ROUTER:BEGIN -->"
END = "<!-- HEPHAESTUS:GLOBAL-ROUTER:END -->"
VERSION = "global-router.v8"


@dataclass(frozen=True)
class Target:
    id: str
    path: Path
    label: str


@dataclass(frozen=True)
class _TargetSpec:
    """Everything host-specific about one router target, in one row."""

    file: str  # home-relative prompt file
    label: str
    host: str
    browser_instruction: str
    network_instruction: str
    scope_instruction: str
    call_instruction: str
    host_surface_note: str


# Claude Code and Antigravity share the /hep-* slash-command surface verbatim.
_HEP_SLASH_COMMANDS = {
    "browser_instruction": "Use `/hep-browser <url-or-query>`",
    "network_instruction": "Use `/hep-network <request>`",
    "scope_instruction": "Use `/hep-local`, `/hep-cloud`, or `/hep-hub`",
    "call_instruction": "Use `/hep-call <agent-slugs> <context>`",
}

# One row per supported router target. _router_block, default_targets,
# _select_targets, and the CLI's --target choices all derive from this table,
# so adding a host is one new row here — before this, the per-host strings
# lived in an if/elif chain whose bare else silently meant Antigravity for any
# unknown id, and the three-target list was typed out in three more places.
ROUTER_TARGETS: dict[str, _TargetSpec] = {
    "codex": _TargetSpec(
        file=".codex/AGENTS.md",
        label="Codex AGENTS.md",
        host="Codex",
        browser_instruction=(
            "Ask for Agentlas Browser in plain language; Codex dispatches it through "
            "the typed MCP surface"
        ),
        network_instruction="Use `$hephaestus-network <request>`",
        scope_instruction=(
            "Use `$hephaestus-cloud <request>` for owner Cloud. Request exact Local "
            "or public Hub scope in plain language through typed Workforce MCP"
        ),
        call_instruction=(
            "Request the exact named Cloud or Hub agents in plain language through typed MCP"
        ),
        host_surface_note="""
- host: Codex 0.117+ uses installed `$hephaestus-build|network|cloud|upload|storm|graph` skills; Browser, Local, Hub, Search, Call = plain language via typed MCP; `/prompts:hep-*` is legacy (<0.117), do not offer it""",
    ),
    "claude": _TargetSpec(
        file=".claude/CLAUDE.md",
        label="Claude CLAUDE.md",
        host="Claude Code",
        host_surface_note="",
        **_HEP_SLASH_COMMANDS,
    ),
    "antigravity": _TargetSpec(
        file=".gemini/GEMINI.md",
        label="Antigravity GEMINI.md",
        host="Antigravity",
        host_surface_note="""
- host: Antigravity is an independent runtime target; its instruction file lives in the ~/.gemini config home, install and selection separate""",
        **_HEP_SLASH_COMMANDS,
    ),
}

ROUTER_TARGET_IDS: tuple[str, ...] = tuple(ROUTER_TARGETS)


def default_targets(home: Path | None = None) -> dict[str, Target]:
    root = home or Path.home()
    return {
        target_id: Target(target_id, root / spec.file, spec.label)
        for target_id, spec in ROUTER_TARGETS.items()
    }


def install_global_router(
    *,
    home: Path | None = None,
    targets: list[str] | None = None,
    backup: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    selected = _select_targets(home=home, targets=targets)
    results = []
    for target in selected:
        text = _read_text(target.path)
        new_text, changed = _upsert_block(text, _router_block(target.id, _router_workflow_path(target.path)))
        backup_path = None
        workflow = _router_workflow(target.id)
        workflow_path = _router_workflow_path(target.path)
        workflow_changed = _read_text(workflow_path) != workflow
        if workflow_changed and not dry_run:
            workflow_path.parent.mkdir(parents=True, exist_ok=True)
            with _target_mutation_lock(workflow_path):
                prior_workflow = _read_text(workflow_path)
                if prior_workflow != workflow:
                    if backup and workflow_path.exists():
                        _backup(workflow_path, prior_workflow)
                    workflow_path.write_text(workflow, encoding="utf-8")
        if changed and not dry_run:
            target.path.parent.mkdir(parents=True, exist_ok=True)
            with _target_mutation_lock(target.path):
                # Re-read after acquiring the cross-process lock. A retry or a
                # parallel installer may already have applied the exact block;
                # in that case the truthful result is unchanged and no backup
                # or byte rewrite should occur.
                text = _read_text(target.path)
                new_text, changed = _upsert_block(text, _router_block(target.id, _router_workflow_path(target.path)))
                if changed:
                    if backup and target.path.exists():
                        backup_path = _backup(target.path, text)
                    target.path.write_text(new_text, encoding="utf-8")
        results.append(
            {
                "target": target.id,
                "path": str(target.path),
                "status": "would_update" if dry_run and changed else "updated" if changed else "unchanged",
                "installed": BEGIN in new_text and END in new_text,
                "backup": str(backup_path) if backup_path else None,
                "workflow_path": str(workflow_path),
                "workflow_sha256": hashlib.sha256(workflow.encode("utf-8")).hexdigest(),
                "workflow_status": "would_update" if dry_run and workflow_changed else "updated" if workflow_changed else "unchanged",
            }
        )
    return {"action": "global_router_install", "version": VERSION, "results": results}


def remove_global_router(
    *,
    home: Path | None = None,
    targets: list[str] | None = None,
    backup: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    selected = _select_targets(home=home, targets=targets)
    results = []
    for target in selected:
        text = _read_text(target.path)
        new_text, changed = _remove_block(text)
        backup_path = None
        if changed and not dry_run:
            with _target_mutation_lock(target.path):
                text = _read_text(target.path)
                new_text, changed = _remove_block(text)
                if changed:
                    if backup and target.path.exists():
                        backup_path = _backup(target.path, text)
                    target.path.write_text(new_text, encoding="utf-8")
        results.append(
            {
                "target": target.id,
                "path": str(target.path),
                "status": "would_remove" if dry_run and changed else "removed" if changed else "not_installed",
                "installed": BEGIN in new_text and END in new_text,
                "backup": str(backup_path) if backup_path else None,
            }
        )
    return {"action": "global_router_remove", "version": VERSION, "results": results}


def global_router_status(*, home: Path | None = None, targets: list[str] | None = None) -> dict[str, Any]:
    selected = _select_targets(home=home, targets=targets)
    results = []
    for target in selected:
        text = _read_text(target.path)
        results.append(
            {
                "target": target.id,
                "path": str(target.path),
                "exists": target.path.exists(),
                "installed": BEGIN in text and END in text,
                "version": VERSION if BEGIN in text and END in text else None,
                "workflow_path": str(_router_workflow_path(target.path)),
                "workflow_ready": _read_text(_router_workflow_path(target.path)) == _router_workflow(target.id),
            }
        )
    return {"action": "global_router_status", "version": VERSION, "results": results}


def _select_targets(*, home: Path | None, targets: list[str] | None) -> list[Target]:
    available = default_targets(home)
    ids = targets or list(ROUTER_TARGET_IDS)
    unknown = [item for item in ids if item not in available]
    if unknown:
        raise ValueError(f"unknown global router target(s): {', '.join(unknown)}")
    return [available[item] for item in ids]


def _router_workflow_path(instruction_path: Path) -> Path:
    return instruction_path.with_name("agentlas-global-router-workflow.md")


def _router_workflow(target_id: str | None = None) -> str:
    host_note = ROUTER_TARGETS[target_id].host_surface_note if target_id else ""
    return compose_prompt([
        {"id": "purpose.router.workflow.policy", "revision": 2, "stability": "fixed-policy", "changeTriggers": ["release"], "text": """# Agentlas Global Router workflow
staff: redacted WorkOrder -> workforce.search_candidates(sourceScope, selectionSessionId) -> host-authored Selection -> workforce.validate_selection(workOrder, selection) -> workforce.prepare_execution(accepted federatedSelection, projectDir).
Core restores pinned federation; never echo menu as federationResult or send the merged set to remote Hub validation/preparation. Preserve exact source sessions/digests, agentDefinitionId, release/package/content hashes. Proven immutable lineage shadows Local > Cloud > Hub; ambiguous identity collisions quarantine. No lexical router, scoring, reranking or silent substitution.
execute: BYOM prepared bundles run on this host, distinct worker/synthesis/verifier calls, artifact handoffs and independent verifier. Preparation/selection/scheduling is never proof of execution; validate the actual host receipt locally.
privacy: Hub receives redacted requirements, never raw prompts/local files/memory/secrets. Installs/ratings/revenue/history/callability never decide fit.
refusal: Hub is free with host model/API; insufficient_credits means stale server, no top-up advice. owner_only/no_cloud_package/agent_not_found remain exact. Report the boundary before any different surface. Named remote agent missing means it did not run; never claim a local fallback ran it.
report: actual workers only, Korean 사용 에이전트 / English Agents used plus short reason; real local skill fallback uses 사용 스킬 / Skills used, never registered-worker claims.
"""},
        {"id": "purpose.router.workflow.host", "revision": 1, "stability": "configuration", "changeTriggers": ["runtime", "profile"], "text": host_note},
    ]) + "\n"



def _router_block(target_id: str, workflow_path: Path | None = None) -> str:
    spec = ROUTER_TARGETS.get(target_id)
    if spec is None:
        raise ValueError(f"unknown global router target: {target_id}")
    path = workflow_path or _router_workflow_path(default_targets()[target_id].path)
    digest = hashlib.sha256(_router_workflow(target_id).encode("utf-8")).hexdigest()
    return compose_prompt([
        {"id": "purpose.router.frame", "revision": 1, "stability": "fixed-policy", "changeTriggers": ["release"], "order": -10, "text": BEGIN},
        {"id": "purpose.router.menu", "revision": 2, "stability": "fixed-policy", "changeTriggers": ["release"], "text": "simple question: direct answer\nrunner: ~/.agentlas/runtime/current/bin/hephaestus; preparation ≠ execution"},
        {"id": "purpose.router.host", "revision": 1, "stability": "configuration", "changeTriggers": ["runtime", "profile", "skill-package"], "text": f"router: {VERSION}; host={spec.host}\nread before staffing: {path} (installed workflow sha256={digest}); native file read. Unreadable => report exact boundary; use local host skills only if Workforce unavailable, never claim registered workers.\nbrowser/render/login: {spec.browser_instruction}\nsubstantial: {spec.network_instruction}; Network=Local+owner Cloud+public Hub"},
        {"id": "purpose.router.scope.final", "revision": 1, "stability": "final-boundary", "changeTriggers": ["runtime", "profile"], "text": f"exact scope: {spec.scope_instruction}; never widen; named agents: {spec.call_instruction}\n{END}"},
    ]) + "\n"



def _upsert_block(text: str, block: str) -> tuple[str, bool]:
    if BEGIN in text and END in text:
        start = text.index(BEGIN)
        end = text.index(END, start) + len(END)
        if end < len(text) and text[end : end + 1] == "\n":
            end += 1
        prefix = text[:start].rstrip()
        new_text = (prefix + "\n\n" if prefix else "") + block.rstrip() + "\n" + text[end:].lstrip("\n")
    else:
        prefix = text.rstrip()
        new_text = (prefix + "\n\n" if prefix else "") + block.rstrip() + "\n"
    return new_text, new_text != text


def _remove_block(text: str) -> tuple[str, bool]:
    if BEGIN not in text or END not in text:
        return text, False
    start = text.index(BEGIN)
    end = text.index(END, start) + len(END)
    if end < len(text) and text[end : end + 1] == "\n":
        end += 1
    new_text = (text[:start].rstrip() + "\n\n" + text[end:].lstrip("\n")).strip() + "\n"
    if new_text == "\n":
        new_text = ""
    return new_text, new_text != text


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


@contextmanager
def _target_mutation_lock(path: Path, *, timeout_seconds: float = 15.0) -> Iterator[None]:
    """Serialize router mutations without a crash-stale lock contract.

    The small persistent lock file is intentional: advisory locks are released
    by the OS when a process exits, while unlinking a lock file can let a third
    process lock a new inode as an existing waiter still owns the old one.
    """

    lock_path = path.with_name(f".{path.name}.agentlas-router.lock")
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR | _O_BINARY, 0o600)
    try:
        try:
            os.chmod(lock_path, 0o600)
        except OSError:
            pass
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    if os.fstat(descriptor).st_size == 0:
                        os.write(descriptor, b"\0")
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError) as exc:
                if time.monotonic() >= deadline:
                    raise ValueError(f"global router target is busy: {path.name}") from exc
                time.sleep(0.02)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _backup(path: Path, content: str) -> Path:
    """Create an exclusive snapshot and never reuse or overwrite a receipt."""

    stamp = time.strftime("%Y%m%d-%H%M%S")
    base_name = f"{path.name}.bak.{stamp}.{time.time_ns()}"
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    for suffix in range(10_000):
        name = base_name if suffix == 0 else f"{base_name}.{suffix}"
        backup = path.with_name(name)
        try:
            descriptor = os.open(backup, flags | _O_BINARY, 0o600)
        except FileExistsError:
            continue
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            backup.unlink(missing_ok=True)
            raise
        return backup
    raise OSError(f"could not allocate a unique backup for {path.name}")
