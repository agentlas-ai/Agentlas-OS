#!/usr/bin/env python3
"""Refresh the verbatimSkills snapshot in schemas/command-alias-manifest.json
from whatever is currently on disk under codex/plugins/.../skills/agentlas-<verb>.

Run this after hand-editing one of those SKILL.md files, then run
scripts/render-command-aliases.py --check to confirm the manifest and disk
agree again.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "schemas" / "command-alias-manifest.json"


def main() -> int:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    for entry in manifest.get("verbatimSkills", []):
        path = ROOT / entry["path"]
        entry["content"] = path.read_text(encoding="utf-8")
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"refreshed {len(manifest.get('verbatimSkills', []))} verbatim entries from disk.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
