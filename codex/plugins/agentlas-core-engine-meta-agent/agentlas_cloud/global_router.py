"""Install Hephaestus global routing instructions into host prompt files."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

BEGIN = "<!-- HEPHAESTUS:GLOBAL-ROUTER:BEGIN -->"
END = "<!-- HEPHAESTUS:GLOBAL-ROUTER:END -->"
VERSION = "global-router.v6"


@dataclass(frozen=True)
class Target:
    id: str
    path: Path
    label: str


def default_targets(home: Path | None = None) -> dict[str, Target]:
    root = home or Path.home()
    return {
        "codex": Target("codex", root / ".codex" / "AGENTS.md", "Codex AGENTS.md"),
        "claude": Target("claude", root / ".claude" / "CLAUDE.md", "Claude CLAUDE.md"),
        "antigravity": Target("antigravity", root / ".gemini" / "GEMINI.md", "Antigravity GEMINI.md"),
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
            if backup and target.path.exists():
                backup_path = _backup(target.path)
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
            if backup and target.path.exists():
                backup_path = _backup(target.path)
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
    ids = targets or ["codex", "claude", "antigravity"]
    unknown = [item for item in ids if item not in available]
    if unknown:
        raise ValueError(f"unknown global router target(s): {', '.join(unknown)}")
    return [available[item] for item in ids]


def _router_block(target_id: str) -> str:
    if target_id == "codex":
        host = "Codex"
        browser_instruction = (
            "Ask for Agentlas Browser in plain language; Codex dispatches it through "
            "the typed MCP surface"
        )
        network_instruction = "Use `$hephaestus-network <request>`"
        scope_instruction = (
            "Use `$hephaestus-cloud <request>` for owner Cloud. Request exact Local "
            "or public Hub scope in plain language through typed Workforce MCP"
        )
        call_instruction = (
            "Request the exact named Cloud or Hub agents in plain language through typed MCP"
        )
        host_surface_note = """
- Codex 0.117 and later use installed `$hephaestus-build`,
  `$hephaestus-network`, `$hephaestus-cloud`, `$hephaestus-upload`,
  `$hephaestus-storm`, and `$hephaestus-graph` skills. Request Browser, Local,
  Hub, Search, and Call actions in plain language through typed MCP. Custom
  `/prompts:hep-*` commands are legacy surfaces limited to Codex versions before
  0.117; do not direct current Codex users to them."""
    elif target_id == "claude":
        host = "Claude Code"
        browser_instruction = "Use `/hep-browser <url-or-query>`"
        network_instruction = "Use `/hep-network <request>`"
        scope_instruction = "Use `/hep-local`, `/hep-cloud`, or `/hep-hub`"
        call_instruction = "Use `/hep-call <agent-slugs> <context>`"
        host_surface_note = ""
    else:
        host = "Antigravity"
        browser_instruction = "Use `/hep-browser <url-or-query>`"
        network_instruction = "Use `/hep-network <request>`"
        scope_instruction = "Use `/hep-local`, `/hep-cloud`, or `/hep-hub`"
        call_instruction = "Use `/hep-call <agent-slugs> <context>`"
        host_surface_note = """
- Antigravity is an independent runtime target, not a Gemini CLI mode. The two
  may read the same configuration path, but installation and runtime selection
  remain separate."""
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
- Announce final workers, not the router command. Never announce `hep-network`
  as a skill or agent.
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
        new_text = text[:start].rstrip() + "\n\n" + block.rstrip() + "\n" + text[end:].lstrip("\n")
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


def _backup(path: Path) -> Path:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{stamp}")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup
