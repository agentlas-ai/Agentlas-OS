"""Legacy markdown → per-slug memory import (Phase 1b, hep surface).

Light parity with the Desktop/Terminal ``agentlas memory import``: ingests
substantive markdown sections into a member cell's per-slug experience store
(``~/.agentlas/networking/hub-agents/<slug>/memory/experience.sqlite``) so
legacy notes become recallable through the same hook. Dry-run by default;
``--apply`` writes. Idempotent via a stable per-section source id, and secrets
are redacted before anything is written.

Usage:
  python -m agentlas_cloud.memory_import <folder-or-file> --slug <slug> [--apply]
"""

from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path
from typing import Any

from ontology import OntologyRuntime, RuntimeConfig

from .memory_contract import member_cell_db_path, normalize_slug
from .memory_hook import _redact_secrets  # shared secret chokepoint

MAX_FILES = 400
MAX_SECTION_CHARS = 4000
MIN_SECTION_CHARS = 24
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_RISK_HINT = re.compile(r"(security|attack|vuln|bug|gotcha|incident|보안|취약|버그|사고)", re.IGNORECASE)


def _iter_markdown_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() in {".md", ".markdown", ".txt"} else []
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if len(files) >= MAX_FILES:
            break
        if path.is_file() and not path.is_symlink() and path.suffix.lower() in {".md", ".markdown", ".txt"}:
            files.append(path)
    return files


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split markdown into (heading, body) sections by ATX headings."""
    sections: list[tuple[str, str]] = []
    heading = ""
    body: list[str] = []
    for line in text.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            if heading or body:
                sections.append((heading, "\n".join(body).strip()))
            heading = match.group(2).strip()
            body = []
        else:
            body.append(line)
    if heading or body:
        sections.append((heading, "\n".join(body).strip()))
    return sections


def _kind_for(heading: str, body: str) -> str:
    return "risk" if _RISK_HINT.search(f"{heading}\n{body}") else "experience"


def _plan(files: list[Path], base: Path) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for file_path in files:
        try:
            raw = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for heading, body in _split_sections(raw):
            summary = _redact_secrets(" ".join(f"{heading} {body}".split()))[:MAX_SECTION_CHARS]
            if len(summary) < MIN_SECTION_CHARS:
                continue
            try:
                rel = str(file_path.relative_to(base))
            except ValueError:
                rel = file_path.name
            source_id = "md-import:" + hashlib.sha256(
                f"{rel}:{heading}:{summary}".encode("utf-8")
            ).hexdigest()[:24]
            plan.append(
                {
                    "file": rel,
                    "heading": heading or "(untitled)",
                    "kind": _kind_for(heading, body),
                    "chars": len(summary),
                    "summary": summary,
                    "source_id": source_id,
                }
            )
    return plan


def run_import(path: str, slug: str, *, apply: bool, out=print) -> int:
    normalized = normalize_slug(slug)
    if not normalized:
        out("error: --slug is required and must normalize to a non-empty slug")
        return 2
    root = Path(path).expanduser()
    if not root.exists():
        out(f"error: path not found: {root}")
        return 2
    base = root if root.is_dir() else root.parent
    files = _iter_markdown_files(root)
    plan = _plan(files, base)
    out(f"agent cell: hub:{normalized}")
    out(f"store: {member_cell_db_path(normalized)}")
    out(f"markdown files scanned: {len(files)}; importable sections: {len(plan)}")
    out("")
    out(f"{'kind':<11} {'chars':>6}  file :: heading")
    for item in plan:
        out(f"{item['kind']:<11} {item['chars']:>6}  {item['file']} :: {item['heading']}")
    if not apply:
        out("")
        out("dry-run — nothing written. Re-run with --apply to write to the per-slug store.")
        return 0
    if not plan:
        out("nothing to import.")
        return 0
    db_path = member_cell_db_path(normalized)
    runtime = OntologyRuntime(RuntimeConfig(db_path=db_path))
    agent_id = f"hub:{normalized}"
    written = 0
    for item in plan:
        try:
            runtime.ingest_experience(
                agent_id=agent_id,
                summary=item["summary"],
                tags=[item["kind"]],
                memory_kind=item["kind"],
                source_memory_id=item["source_id"],
                reason="Imported from legacy markdown via agentlas memory import.",
            )
            written += 1
        except (ValueError, OSError):
            continue
    out("")
    out(f"applied — {written} section(s) written to {db_path} (idempotent by source id).")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agentlas_cloud.memory_import",
        description="Import legacy markdown into a per-slug member cell (dry-run by default).",
    )
    parser.add_argument("path", help="markdown file or folder to import")
    parser.add_argument("--slug", required=True, help="member/agent slug (the cell id)")
    parser.add_argument("--apply", action="store_true", help="write to the per-slug store")
    args = parser.parse_args(argv)
    return run_import(args.path, args.slug, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
