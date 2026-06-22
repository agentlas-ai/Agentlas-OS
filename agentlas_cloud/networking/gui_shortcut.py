"""Explicit GUI shortcuts for the Network surface.

The public `/hep-network` surface is Hub-only by default. Hub-registered GUI
shortcuts restore their cloud package and launch that packaged GUI even when
the operator machine also has a local `private` or `restricted` source folder.

Local GUI cards are an explicit operator/debug escape hatch only. They are not
consulted unless `allow_local=True`, `local_first=True`, or
`HEPHAESTUS_NETWORK_ALLOW_LOCAL_GUI_SHORTCUTS=1` is set.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import hashlib
from typing import Any

from .bootstrap import networking_home
from .card_lint import effective_status
from .card_store import load_global_cards
from .hub_client import HubToolError, call_hub_tool


HUB_GUI_SHORTCUTS = {
    "startup": "agentlas-startup-founder-studio",
    "startup founder studio": "agentlas-startup-founder-studio",
    "startup studio": "agentlas-startup-founder-studio",
    "스타트업": "agentlas-startup-founder-studio",
    "스타트업 스튜디오": "agentlas-startup-founder-studio",
    "창업 스튜디오": "agentlas-startup-founder-studio",
}


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
    detach: bool = False,
    allow_local: bool = False,
    local_first: bool = False,
) -> dict[str, Any]:
    base = Path(home) if home else networking_home()
    wanted = _norm(query)
    local_allowed = (
        allow_local
        or local_first
        or os.environ.get("HEPHAESTUS_NETWORK_ALLOW_LOCAL_GUI_SHORTCUTS") == "1"
    )

    if local_first:
        local_result, quarantined = _open_registered_local_gui_shortcut(
            base,
            wanted,
            no_open=no_open,
            detach=detach,
        )
        if local_result is not None:
            return local_result
    else:
        quarantined = 0

    hub_result = _open_hub_gui_shortcut(wanted, home=base, no_open=no_open, detach=detach)
    if hub_result is not None:
        return hub_result

    if local_allowed and not local_first:
        local_result, quarantined = _open_registered_local_gui_shortcut(
            base,
            wanted,
            no_open=no_open,
            detach=detach,
        )
        if local_result is not None:
            return local_result

    return {
        "action": "no_local_gui_shortcut",
        "status": "not_found",
        "query": wanted,
        "quarantined": quarantined,
        "local_routing": "enabled_for_operator_debug" if local_allowed else "disabled_by_default",
        "hub_routing": "no_registered_gui_shortcut",
    }


def _open_registered_local_gui_shortcut(
    base: Path,
    wanted: str,
    *,
    no_open: bool,
    detach: bool,
) -> tuple[dict[str, Any] | None, int]:
    cards, quarantined = load_global_cards(base)

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
            }, len(quarantined)
        if not launcher:
            return {
                "action": "open_gui",
                "status": "error",
                "error": "shortcut card has no gui_launcher entrypoint",
                "selected": selected,
            }, len(quarantined)

        launcher_path = (source / launcher).resolve()
        if not launcher_path.is_file():
            return {
                "action": "open_gui",
                "status": "error",
                "error": "gui_launcher file is missing",
                "selected": selected,
                "launcher": str(launcher_path),
            }, len(quarantined)

        launch = _launch_python_gui(launcher_path, source, no_open=no_open, detach=detach)
        return {
            "action": "open_gui",
            "status": launch["status"],
            "selected": selected,
            "matched_phrase": wanted,
            "gui": str((source / gui).resolve()) if gui else None,
            "launcher": str(launcher_path),
            "launcher_result": launch.get("launcher_result", {}),
            "stderr": launch.get("stderr", ""),
            "returncode": launch.get("returncode"),
            "pid": launch.get("pid"),
            "local_routing": "used_for_explicit_gui_shortcut",
            "hub_routing": "skipped",
        }, len(quarantined)

    return None, len(quarantined)


def _open_hub_gui_shortcut(
    wanted: str,
    *,
    home: Path,
    no_open: bool,
    detach: bool,
) -> dict[str, Any] | None:
    slug = HUB_GUI_SHORTCUTS.get(wanted)
    if not slug:
        return None
    try:
        listing = call_hub_tool(
            "marketplace.get_manifest",
            {"kind": "agent", "slug": slug},
            home=home,
            timeout=60,
        )
    except HubToolError as exc:
        return {
            "action": "open_gui",
            "status": "error",
            "source": "hub_cloud_package",
            "slug": slug,
            "error": str(exc),
        }
    package = listing.get("cloudPackage") if isinstance(listing, dict) else None
    files = package.get("files") if isinstance(package, dict) else None
    if not isinstance(files, list) or not files:
        return {
            "action": "open_gui",
            "status": "error",
            "source": "hub_cloud_package",
            "slug": slug,
            "error": "Hub listing has no downloadable cloud package. Re-publish the package with cloudPackage files.",
        }

    install_dir = _cloud_install_root() / slug
    try:
        _materialize_cloud_package(install_dir, files, package_hash=str(package.get("packageHash") or ""))
    except (OSError, ValueError) as exc:
        return {
            "action": "open_gui",
            "status": "error",
            "source": "hub_cloud_package",
            "slug": slug,
            "error": str(exc),
        }

    launcher = _hub_launcher_path(install_dir)
    if launcher is None:
        return {
            "action": "open_gui",
            "status": "error",
            "source": "hub_cloud_package",
            "slug": slug,
            "install_dir": str(install_dir),
            "error": "Installed package has no ui.launcher or scripts/open-studio-gui.py.",
        }
    launch = _launch_python_gui(launcher, install_dir, no_open=no_open, detach=detach)
    return {
        "action": "open_gui",
        "status": launch["status"],
        "source": "hub_cloud_package",
        "slug": slug,
        "name": listing.get("name") or listing.get("nameEn") or slug,
        "matched_phrase": wanted,
        "install_dir": str(install_dir),
        "launcher": str(launcher),
        "launcher_result": launch.get("launcher_result", {}),
        "stderr": launch.get("stderr", ""),
        "returncode": launch.get("returncode"),
        "pid": launch.get("pid"),
        "local_routing": "skipped",
        "hub_routing": "cloud_package_installed",
    }


def _launch_python_gui(launcher_path: Path, cwd: Path, *, no_open: bool, detach: bool) -> dict[str, Any]:
    cmd = [sys.executable, str(launcher_path)]
    if no_open:
        cmd.append("--no-open")
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    if detach:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            env=env,
            start_new_session=True,
        )
        return {"status": "opening", "pid": proc.pid, "launcher_result": {}}
    proc = subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=env, check=False)
    return {
        "status": "opened" if proc.returncode == 0 else "error",
        "launcher_result": _launcher_payload(proc.stdout),
        "stderr": proc.stderr.strip(),
        "returncode": proc.returncode,
    }


def _cloud_install_root() -> Path:
    configured = os.environ.get("AGENTLAS_CLOUD_INSTALL_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".agentlas" / "cloud-agent-installs"


def _materialize_cloud_package(root: Path, files: list[dict[str, Any]], *, package_hash: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    marker = root / ".agentlas-cloud-package.json"
    current_hash = None
    try:
        current_hash = json.loads(marker.read_text(encoding="utf-8")).get("packageHash")
    except (OSError, ValueError):
        current_hash = None
    overwrite = current_hash != package_hash
    for item in files:
        rel = str(item.get("path") or "")
        target = _safe_install_path(root, rel)
        raw = _decode_package_file(item)
        target.parent.mkdir(parents=True, exist_ok=True)
        if overwrite or not target.exists():
            target.write_bytes(raw)
    marker.write_text(
        json.dumps({"packageHash": package_hash, "installedAt": _now_iso()}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _decode_package_file(item: dict[str, Any]) -> bytes:
    import base64

    raw = base64.b64decode(str(item.get("contentBase64") or ""), validate=True)
    expected_bytes = int(item.get("bytes") or 0)
    expected_hash = str(item.get("sha256") or "").lower()
    if len(raw) != expected_bytes:
        raise ValueError(f"cloud package file size mismatch: {item.get('path')}")
    if hashlib.sha256(raw).hexdigest().lower() != expected_hash:
        raise ValueError(f"cloud package file integrity failed: {item.get('path')}")
    return raw


def _safe_install_path(root: Path, rel_path: str) -> Path:
    normalized = str(rel_path or "").replace("\\", "/")
    if not normalized or normalized.startswith("/") or "\0" in normalized:
        raise ValueError(f"unsafe cloud package path: {rel_path}")
    parts = [part for part in normalized.split("/") if part and part != "."]
    if not parts or any(part == ".." for part in parts):
        raise ValueError(f"unsafe cloud package path: {rel_path}")
    target = root.resolve().joinpath(*parts).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"cloud package path escapes install folder: {rel_path}") from exc
    return target


def _hub_launcher_path(root: Path) -> Path | None:
    for metadata_name in ("agentlas.json", "manifest.json"):
        metadata_path = root / metadata_name
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        ui = metadata.get("ui") or metadata.get("ui_surface") or {}
        if isinstance(ui, dict):
            launcher = ui.get("launcher") or ui.get("legacyLauncher") or ui.get("legacy_launcher")
            if launcher:
                candidate = _safe_install_path(root, str(launcher))
                if candidate.is_file():
                    return candidate
    fallback = root / "scripts" / "open-studio-gui.py"
    return fallback if fallback.is_file() else None


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
