#!/usr/bin/env bash
# Canonical /hep-* command bodies stay readable, whole, and singly-sourced.
#
# WHY THIS EXISTS
#   Unifying ten hand-maintained host copies (2026-08-17) appended every
#   divergent line verbatim under "Rules carried from the other runtime copies"
#   instead of merging it. The safety net was never taken in: by 2026-09-13 it
#   was 326 bullets — 24% of the canonical command contracts, 48% of
#   hep-connect — and the harvester had split on backticks, leaving 16 lines
#   ending mid-sentence and several bash-snippet fragments masquerading as
#   rules. Every host LLM read all of it on every invocation.
#
#   All 326 were read before removal: compressed restatements, host mechanics
#   the renderer now owns, and bash fragments were dropped; the handful of real
#   rules the canonical body did not state were promoted into the step they
#   belong to. The per-line disposition is in the commit that removed them.
#   This gate keeps the block from coming back and catches the harvesting
#   mistake that produced it.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

GATE="[verify-command-body-hygiene]"

python3 - <<'PY'
import pathlib, sys

GATE = "[verify-command-body-hygiene]"
BODIES = pathlib.Path("contracts/commands")
CARRIED = "Rules carried from the other runtime copies"

def unclosed_backticks(text: str) -> list[tuple[int, str]]:
    """Prose units whose inline code span is never closed.

    Parity is counted per prose unit, not per line: an inline code span may
    legally wrap across a line break, so a line-by-line count flags ordinary
    wrapped prose. Each list item is its own unit, so two broken bullets in a
    row cannot cancel each other's parity out. Fenced code is exempt entirely —
    a shell line may carry any number of backticks.
    """
    found: list[tuple[int, str]] = []
    in_fence = False
    start = 0
    ticks = 0
    buffer = ""

    def close() -> None:
        nonlocal start, ticks, buffer
        if start and ticks % 2 == 1:
            found.append((start, buffer.strip()[-70:]))
        start, ticks, buffer = 0, 0, ""

    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            close()
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if not stripped:
            close()
            continue
        if stripped[:2] in ("- ", "* ") or (stripped[:1].isdigit() and ". " in stripped[:4]):
            close()
        if not start:
            start = number
        ticks += stripped.count("`")
        buffer += " " + stripped
    close()
    return found


failures: list[str] = []
checked = 0

bodies = sorted(BODIES.glob("*.body.md"))
if not bodies:
    print(f"{GATE} FAIL")
    print(f"  - no canonical bodies found under {BODIES} — this checkout is broken")
    sys.exit(1)

for body in bodies:
    text = body.read_text(encoding="utf-8")
    checked += 1

    if CARRIED in text:
        failures.append(
            f"{body}: the '{CARRIED}' block is back. Merge each genuinely new rule "
            "into the step it belongs to and record the disposition; do not append "
            "a second copy of the contract."
        )

    for number, snippet in unclosed_backticks(text):
        failures.append(
            f"{body}:{number}: unclosed backtick — a sentence was cut here: {snippet!r}"
        )

if failures:
    print(f"{GATE} FAIL — {len(failures)} problem(s), {checked} canonical body/bodies checked")
    for failure in failures:
        print(f"  - {failure}")
    sys.exit(1)

print(f"{GATE} canonical bodies clean — {checked} body/bodies checked")
PY

# A clean canonical body that never reached the hosts helps nobody.
python3 scripts/render-host-commands.py --check

echo "$GATE PASS"
