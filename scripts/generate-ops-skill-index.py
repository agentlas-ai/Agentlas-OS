#!/usr/bin/env python3
"""Generate the Agentlas operations skill's capability INDEX from the live
tool registry (D9: hand-written surface lists rot — cargo's liveness could only
be confirmed by a real call, so the index is derived, never authored).

Source of truth: agentlas_cloud/mcp_stdio.py TOOLS (this repo's own MCP
declarations — the same list a session actually loads). Regenerate on release;
the SKILL.md procedures reference this file instead of naming tools inline.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OUT = ROOT / "skills" / "agentlas-operations" / "INDEX.md"


def main() -> int:
    from agentlas_cloud.mcp_stdio import TOOLS  # the live registry, not prose

    lines = [
        "# Agentlas 도구 색인 (자동 생성 — 손으로 편집 금지)",
        "",
        f"생성원: `agentlas_cloud/mcp_stdio.py` TOOLS ({len(TOOLS)}개). "
        "재생성: `python3 scripts/generate-ops-skill-index.py`.",
        "",
        "| 도구 | 요지 |",
        "|---|---|",
    ]
    for tool in TOOLS:
        name = str(tool.get("name", ""))
        desc = " ".join(str(tool.get("description", "")).split())
        first = re.split(r"(?<=[.!?])\s", desc, maxsplit=1)[0][:140]
        lines.append(f"| `{name}` | {first} |")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"generated {OUT.relative_to(ROOT)} — {len(TOOLS)} tools")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
