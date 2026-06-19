"""Explicit local GUI shortcuts for the Network surface.

The public `/hephaestus-network` surface is Hub-only by default. This module
adds a narrow escape hatch: a local routing card can opt in to a GUI shortcut
with `network_shortcut.enabled=true` and exact phrases. Nothing else is routed
locally from the Network command.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from .bootstrap import networking_home
from .card_lint import effective_status
from .card_store import load_global_cards


def _norm(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _selected_payload(card: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": card.get("id"),
        "type": card.get("type"),
        "name": card.get("name"),
        "name_ko": card.get("name_ko"),
        "routing_status": card.get("routing_status"),
        "entrypoints": card.get("entrypoints") or {},
        "source": (card.get("source") or {}).get("ref"),
    }


def _launcher_payload(stdout: str) -> dict[str, Any] | str:
    text = stdout.strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text
    return payload if isinstance(payload, dict) else text


def open_local_gui_shortcut(
    query: str,
    *,
    home: Path | str | None = None,
    no_open: bool = False,
) -> dict[str, Any]:
    base = Path(home) if home else networking_home()
    cards, quarantined = load_global_cards(base)
    wanted = _norm(query)

    for card in cards:
        if effective_status(card) not in {"routing_ready", "trusted"}:
            continue
        shortcut = card.get("network_shortcut") or {}
        if not isinstance(shortcut, dict) or shortcut.get("enabled") is not True:
            continue
        phrases = [_norm(str(item)) for item in shortcut.get("phrases") or []]
        if wanted not in phrases:
            continue

        source = Path(str((card.get("source") or {}).get("ref") or ""))
        entrypoints = card.get("entrypoints") or {}
        launcher = str(entrypoints.get("gui_launcher") or "")
        gui = str(entrypoints.get("gui") or "")
        selected = _selected_payload(card)

        if not source.is_dir():
            return {
                "action": "open_gui",
                "status": "error",
                "error": "shortcut source folder is missing",
                "selected": selected,
            }
        if not launcher:
            return {
                "action": "open_gui",
                "status": "error",
                "error": "shortcut card has no gui_launcher entrypoint",
                "selected": selected,
            }

        launcher_path = (source / launcher).resolve()
        if not launcher_path.is_file():
            return {
                "action": "open_gui",
                "status": "error",
                "error": "gui_launcher file is missing",
                "selected": selected,
                "launcher": str(launcher_path),
            }

        cmd = [sys.executable, str(launcher_path)]
        if no_open:
            cmd.append("--no-open")
        env = dict(os.environ)
        env.setdefault("PYTHONUTF8", "1")
        proc = subprocess.run(cmd, cwd=str(source), text=True, capture_output=True, env=env, check=False)
        return {
            "action": "open_gui",
            "status": "opened" if proc.returncode == 0 else "error",
            "selected": selected,
            "matched_phrase": wanted,
            "gui": str((source / gui).resolve()) if gui else None,
            "launcher": str(launcher_path),
            "launcher_result": _launcher_payload(proc.stdout),
            "stderr": proc.stderr.strip(),
            "returncode": proc.returncode,
            "local_routing": "used_for_explicit_gui_shortcut",
            "hub_routing": "skipped",
        }

    return {
        "action": "no_local_gui_shortcut",
        "status": "not_found",
        "query": wanted,
        "quarantined": len(quarantined),
    }
