"""Phase 5: cross-runtime consumption + Knowledge Catalog path.

The OKF bundle is the vendor-neutral, cross-runtime artifact. This module emits
a Knowledge-Catalog-ingestible descriptor over an OKF export and declares the
runtimes that can consume the pack, so the Agent OS participates as a pack
*producer* in a multi-agent mesh (Claude Code / Codex / Gemini CLI / any
OKF-aware agent) without proprietary coupling. Every export stays value-free
(redaction-safe) per the kernel's public-export invariant.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .agentos import build_pack
from .okf import FORMAT as OKF_FORMAT
from .okf import to_okf_bundle

SUPPORTED_RUNTIMES = ["claude-code", "codex", "gemini-cli", "antigravity", "agents-md", "okf-aware"]


def knowledge_catalog_descriptor(
    project_root: str | Path = ".",
    okf_dir: str | Path | None = None,
    export: bool = True,
) -> dict[str, Any]:
    """Produce a Knowledge-Catalog descriptor over an OKF export of the AO pack."""

    pack = build_pack(project_root)
    out = Path(okf_dir) if okf_dir else (Path(project_root) / ".agentlas" / "okf-export")
    if export:
        bundle = to_okf_bundle(project_root, out)
    else:
        bundle = {"format": OKF_FORMAT, "out_dir": str(out), "files": None, "nodes": None}

    return {
        "format": "knowledge-catalog-descriptor-v1",
        "pack_format": pack["format"],
        "content_hash": pack["content_hash"],
        "bundle": {
            "format": bundle.get("format"),
            "path": bundle.get("out_dir"),
            "files": bundle.get("files"),
            "nodes": bundle.get("nodes"),
            "index": "index.md",
        },
        "discovery": {"a2a_well_known": "/.well-known/agent-card.json", "okf_index": "index.md"},
        "supported_runtimes": SUPPORTED_RUNTIMES,
        "ingestion": {
            "google_cloud_knowledge_catalog": "okf-bundle",
            "method": "serve the OKF bundle directory; consumers parse YAML frontmatter + Markdown links",
        },
        "kernel_enforced": pack["kernel"]["all_enforced"],
        "value_free_export": True,
    }
