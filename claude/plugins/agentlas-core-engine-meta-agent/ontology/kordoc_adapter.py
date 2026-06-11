"""kordoc-backed Korean document parsing adapter.

kordoc (https://github.com/chrisryugj/kordoc, MIT) parses Korean government /
office documents (HWP 3.x/5.x, HWPX, HWPML, PDF, XLS, XLSX, DOCX) into
markdown with table-structure fidelity that the built-in stdlib parsers cannot
match (HWPX text recall 99.998%, nested-table reproduction, Hancom PUA
mapping, johab decoding for HWP 3.x).

The full kordoc source is vendored at ``vendor/kordoc`` so the ontology owns
its parser supply chain. The runtime binary is resolved in this order:

1. ``KORDOC_BIN`` environment variable (explicit override)
2. ``vendor/kordoc/dist/cli.js`` via ``node`` (present once the vendored
   package has been built with ``npm install && npm run build``)
3. ``kordoc`` on PATH (global npm install)
4. ``npx -y kordoc`` only when ``KORDOC_ENABLE_NPX=1`` — opt-in because it
   downloads and runs code from npm at parse time

``KORDOC_DISABLE=1`` turns the adapter off entirely (stdlib parsers only);
the deterministic verify gates pin this so machine-local kordoc installs
cannot change their expected statuses.

This module deliberately has no imports from ``ontology.parsers`` so the
registry can import it without a cycle.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

# Formats kordoc handles better than (or instead of) the stdlib parsers.
KORDOC_SUFFIXES = {".hwp", ".hwpx", ".hml", ".pdf", ".docx", ".xls", ".xlsx"}

ADAPTER_NAME = "kordoc_adapter"

_TIMEOUT_SECONDS = 180
_HEADING_PATTERN = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*$")


class KordocUnavailableError(RuntimeError):
    """No way to run kordoc on this machine."""


class KordocParseError(RuntimeError):
    """kordoc ran but failed to parse the document."""


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resolve_kordoc_command() -> list[str] | None:
    """Resolution order: KORDOC_BIN > vendored dist > PATH binary > opt-in npx."""
    if os.environ.get("KORDOC_DISABLE") == "1":
        return None

    explicit = os.environ.get("KORDOC_BIN")
    if explicit:
        return [explicit]

    node = shutil.which("node")
    vendored_cli = repo_root() / "vendor" / "kordoc" / "dist" / "cli.js"
    if node and vendored_cli.exists():
        return [node, str(vendored_cli)]

    binary = shutil.which("kordoc")
    if binary:
        return [binary]

    if os.environ.get("KORDOC_ENABLE_NPX") == "1":
        npx = shutil.which("npx")
        if npx:
            return [npx, "-y", "kordoc"]

    return None


def kordoc_status() -> str:
    command = resolve_kordoc_command()
    if command is None:
        return "unavailable_missing_kordoc"
    runner = Path(command[0]).name
    if runner == "node":
        return "available_vendored_dist"
    if runner == "npx":
        return "available_via_npx"
    return "available"


def parse_to_markdown(path: Path) -> tuple[str, str]:
    """Run kordoc on *path*; return ``(markdown, runner_label)``.

    Raises KordocUnavailableError / KordocParseError.
    """
    command = resolve_kordoc_command()
    if command is None:
        raise KordocUnavailableError(
            "kordoc is not available — set KORDOC_BIN, build vendor/kordoc "
            "(npm install && npm run build), or install kordoc from npm"
        )
    try:
        completed = subprocess.run(
            [*command, str(path), "--silent"],
            text=True,
            capture_output=True,
            timeout=_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise KordocParseError(f"kordoc timed out after {_TIMEOUT_SECONDS}s") from exc
    except OSError as exc:
        raise KordocUnavailableError(str(exc)) from exc

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise KordocParseError(detail[-2000:] or f"kordoc exited with {completed.returncode}")

    markdown = completed.stdout.strip()
    if not markdown:
        raise KordocParseError("kordoc produced no output")
    return markdown, " ".join(Path(part).name for part in command)


def split_markdown_sections(markdown: str) -> list[dict[str, object]]:
    """Split kordoc markdown into heading-delimited sections.

    Each section dict carries ``text``, ``section`` (1-based), and the
    nearest ``heading`` so chunk spans stay citable. Content before the first
    heading becomes section 1 with an empty heading.
    """
    sections: list[dict[str, object]] = []
    current_lines: list[str] = []
    current_heading = ""

    def flush() -> None:
        text = "\n".join(current_lines).strip()
        if text:
            sections.append(
                {
                    "text": text,
                    "section": len(sections) + 1,
                    "heading": current_heading,
                }
            )

    for line in markdown.splitlines():
        match = _HEADING_PATTERN.match(line)
        if match:
            flush()
            current_lines = [line]
            current_heading = match.group("title")
        else:
            current_lines.append(line)
    flush()

    if not sections:
        sections.append({"text": markdown, "section": 1, "heading": ""})
    return sections
