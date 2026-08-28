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
VERSION = "global-router.v6"


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
- Codex 0.117 and later use installed `$hephaestus-build`,
  `$hephaestus-network`, `$hephaestus-cloud`, `$hephaestus-upload`,
  `$hephaestus-storm`, and `$hephaestus-graph` skills. Request Browser, Local,
  Hub, Search, and Call actions in plain language through typed MCP. Custom
  `/prompts:hep-*` commands are legacy surfaces limited to Codex versions before
  0.117; do not direct current Codex users to them.""",
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
- Antigravity is an independent runtime target, not a Gemini CLI mode. The two
  may read the same configuration path, but installation and runtime selection
  remain separate.""",
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

These instructions were installed by `hephaestus global install` for {host}.

- For simple questions, answer directly. Do not route trivial work through
  Hephaestus.
- Prefer the installed runner at `~/.agentlas/runtime/current/bin/hephaestus`.
{host_surface_note}
- For substantial work, choose routing in this priority order:
  1. Agentlas Browser first for browser-required work. {browser_instruction}
     when the task needs rendered pages, JS-heavy sites,
     click/form flows, login-visible state, or browser evidence.
  2. Hephaestus Network next. {network_instruction} to let the active host
     LLM staff a temporary task force from the federated Local + owner Cloud +
     public Hub Workforce menu.
  3. {scope_instruction} only when the
     user explicitly restricts staffing to registered Local, owner Cloud, or
     public Hub inventory. These are source scopes, not fallback tiers.
  4. Local host skills are an adapter fallback only when Workforce is
     unavailable; do not misreport them as registered Local workers.
- {call_instruction} when the user names exact Hub or
  Cloud agents.
- Source scopes are exact: `network = local + cloud + hub`, `local = registered
  local`, `cloud = owner cloud`, and `hub = public Hub`. Public demos and
  distribution proof must explicitly use Hub scope so private inventory is not
  presented as public availability.
- For Network staffing, the active host LLM creates one redacted structured
  WorkOrder and calls local Core `workforce.search_candidates` with
  `sourceScope=network` to federate the three source CandidateSets. The response
  carries `selectionSessionId`. The host authors a Selection with that session
  ID and calls `workforce.validate_selection(workOrder, selection)`. Core
  restores the pinned federation result from the session. Do not echo the
  projected menu as `federationResult`. Call `workforce.prepare_execution` with
  the accepted `federatedSelection` and mandatory `projectDir`.
  Federation performs no scoring, reranking, or staffing decision. It may
  shadow the same `agentDefinitionId` by Local > Cloud > Hub only when every
  source proves the same lineage and exact immutable release; ambiguous or
  different-release collisions quarantine only that identity while unrelated
  candidates remain available. The host LLM makes the final exact-release
  selection from the merged content menu.
- A federated CandidateSet is a Core-owned session, not a Hub session. Validate
  it locally with its federation receipt. Preparation must use each selected
  row's pinned original source session/digest and exact release/package/content
  hashes; never send the merged CandidateSet to remote Hub validate/prepare.
  Do not run the legacy lexical router first.
- Agentlas Hub agents are BYOM bundles. Execute each prepared exact release in
  this host runtime while grounded in the current project. The Hub does not run
  a server-side LLM completion for you. A selection or prepared bundle is not
  proof that manager, workers, synthesis, or verifier ran.
- Hub calls are allowed only when the signed-in Agentlas account has entitlement
  and credits. If the server returns `insufficient_credits`, `owner_only`,
  `no_cloud_package`, or `agent_not_found`, report that exact refusal. For a
  general task, report the boundary before considering a different explicitly
  labelled surface; for an exact named remote agent, do not claim a local
  fallback ran that agent. Never replace a missing role with an unrelated agent.
- Never send raw local memory, private files, or secrets to Hub search. Hub
  discovery uses redacted work-order requirements; local project grounding
  stays local. Installs, ratings, invocation history, revenue, and local
  callability must not determine semantic fit.
- Report results by the workers that actually did the task, not by narrating
  the routing step that staffed them — say what agents/skills ran, the same
  way you would not narrate "invoking the Bash tool" for every shell command.
  This is a conciseness rule, not a secrecy one: if asked what `hep-network`
  or this routing block is, explain it plainly.
- When Network, Cloud, or a local agent selects concrete agents, list those
  agent names:
  - Korean contexts: `사용 에이전트: <agent names>. 이유: <short reason>.`
  - English contexts: `Agents used: <agent names>. Reason: <short reason>.`
- If the final fallback is local host skills, announce skills instead of agents:
  - Korean contexts: `사용 스킬: <skill names>. 이유: <short reason>.`
  - English contexts: `Skills used: <skill names>. Reason: <short reason>.`
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
