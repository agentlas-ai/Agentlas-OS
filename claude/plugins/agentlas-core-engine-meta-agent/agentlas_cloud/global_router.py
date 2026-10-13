"""Install Hephaestus global routing instructions into host prompt files."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

BEGIN = "<!-- HEPHAESTUS:GLOBAL-ROUTER:BEGIN -->"
END = "<!-- HEPHAESTUS:GLOBAL-ROUTER:END -->"
VERSION = "global-router.v7"


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
- host: Antigravity is an independent runtime target, not a Gemini CLI mode; same config path possible, install and selection separate""",
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
        new_text, changed = _upsert_block(text, _router_block(target.id))
        backup_path = None
        if changed and not dry_run:
            target.path.parent.mkdir(parents=True, exist_ok=True)
            with _target_mutation_lock(target.path):
                # Re-read after acquiring the cross-process lock. A retry or a
                # parallel installer may already have applied the exact block;
                # in that case the truthful result is unchanged and no backup
                # or byte rewrite should occur.
                text = _read_text(target.path)
                new_text, changed = _upsert_block(text, _router_block(target.id))
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


def _router_block(target_id: str) -> str:
    spec = ROUTER_TARGETS.get(target_id)
    if spec is None:
        # Unknown ids used to fall through a bare else into the Antigravity
        # copy; a typo must fail loudly, not install the wrong host's block.
        raise ValueError(f"unknown global router target: {target_id}")
    host = spec.host
    browser_instruction = spec.browser_instruction
    network_instruction = spec.network_instruction
    scope_instruction = spec.scope_instruction
    call_instruction = spec.call_instruction
    host_surface_note = spec.host_surface_note
    return f"""{BEGIN}
# Hephaestus Global Router ({VERSION})
installed_for: {host}
- simple question: answer directly, no routing
- runner: `~/.agentlas/runtime/current/bin/hephaestus`
{host_surface_note}
- substantial work, route in order:
  1. Agentlas Browser first (rendered/JS pages, click/form flows, login state, browser evidence): {browser_instruction}
  2. Hephaestus Network: {network_instruction}; host LLM staffs a task force from the Local + owner Cloud + public Hub Workforce menu
  3. scope-only, when user restricts staffing to registered Local / owner Cloud / public Hub: {scope_instruction}; source scopes, not fallback tiers
  4. local host skills: only if Workforce unavailable; never report them as registered Local workers
- named agents: {call_instruction}
- scopes: network = local + cloud + hub; local = registered local; cloud = owner cloud; hub = public Hub; public demos/distribution proof use hub scope explicitly
- network flow: host LLM writes one redacted WorkOrder -> `workforce.search_candidates` (`sourceScope=network`, returns `selectionSessionId`) -> host writes Selection -> `workforce.validate_selection(workOrder, selection)` (Core restores the pinned result from the session; do not echo the projected menu as `federationResult`) -> `workforce.prepare_execution` with accepted `federatedSelection` + mandatory `projectDir`
- federation: no scoring, reranking or staffing decision; same `agentDefinitionId` shadows Local > Cloud > Hub only with proven same lineage and exact immutable release; ambiguous/different-release collisions quarantine only that identity; host picks exact releases
- session: federated CandidateSet is Core-owned, validate locally with its federation receipt; prepare with each row's pinned original source session/digest + exact release/package/content hashes; never send the merged set to remote Hub validate/prepare; no legacy lexical router first
- Hub agents: BYOM bundles; execute each prepared exact release in this host, grounded in the project; no server-side completion; selection or prepared bundle != proof that manager, workers, synthesis or verifier ran
- Hub calls free, host supplies model/API; `insufficient_credits` = free contract not active on that stale server, no top-up advice; `owner_only`, `no_cloud_package`, `agent_not_found`: report the exact refusal; general task: report the boundary before trying another labelled surface; exact named remote agent: never claim a local fallback ran it; never replace a missing role with an unrelated agent
- privacy: never send raw local memory, private files or secrets to Hub search (redacted work-order requirements only); installs, ratings, invocation history, revenue, local callability never decide semantic fit
- report: by workers that did the task, not by routing narration (conciseness, not secrecy; explain `hep-network` or this block if asked)
- agents selected: Korean `사용 에이전트: <agent names>. 이유: <short reason>.` / English `Agents used: <agent names>. Reason: <short reason>.`
- host skills fallback: Korean `사용 스킬: <skill names>. 이유: <short reason>.` / English `Skills used: <skill names>. Reason: <short reason>.`
{END}
"""


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
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
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
            descriptor = os.open(backup, flags, 0o600)
        except FileExistsError:
            continue
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        except BaseException:
            backup.unlink(missing_ok=True)
            raise
        return backup
    raise OSError(f"could not allocate a unique backup for {path.name}")
