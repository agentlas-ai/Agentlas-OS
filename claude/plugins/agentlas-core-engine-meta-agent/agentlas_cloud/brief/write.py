"""Write `.agentlas/brief.json` into a package, and say what it could not fill.

This is the call that was missing. The compiler, the shape derivation and the
schema all existed and were all correct; an audit of the shipped tree found
`.agentlas/brief.json` on 0 of 186 packages, because nothing in any build or
upload path ever invoked them. A resume nobody generates is a resume nobody has.

Two rules govern what happens here, and both come from the same measured lesson:

- **Writing the brief never fails an upload.** It reads only files the package
  already ships and it invents nothing, so the worst case is a thin brief. A thin
  brief costs rank and says so; refusing the upload would cost the publisher their
  listing over a field the server could have simply left absent.
- **A gap is reported, not filled.** Every absent field is named in the returned
  findings at `advice` severity, so the author can see exactly which part of their
  package the routing layer could not read. Filling those quietly with something
  plausible is how `capabilities` came to equal
  `snake_case(agent.md ## Responsibilities)` in 130 of 130 packages — always full,
  never informative.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .compile import compile_offer

__all__ = ["write_offer_brief", "BRIEF_PATH"]

BRIEF_PATH = ".agentlas/brief.json"

# What a routing layer loses when each is absent. Written for the author, not for
# a log: a field name alone tells them nothing about why it matters.
_GAP_MEANING = {
    "deliverables": (
        "no output contract, so nothing describes what a requester ends up holding — "
        "the strongest signal in matching"
    ),
    "obligations": (
        "nothing states what a requester must supply first, so the work looks like it "
        "starts from nothing"
    ),
    "host": (
        "nothing states what the machine must be able to do, so a host cannot tell in "
        "advance whether this method will run there"
    ),
    "authority": (
        "nothing states what this method does to the requester's world, so a request that "
        "forbids an effect cannot tell whether this package is safe to run"
    ),
}


def write_offer_brief(root: str | Path) -> list[dict[str, Any]]:
    """Compile and write the offer brief. Returns findings, never raises."""
    base = Path(root)
    try:
        brief = compile_offer(base)
    except Exception as error:  # noqa: BLE001 - a resume must not break a publish
        return [{
            "id": "brief-compile-failed",
            "severity": "advice",
            "category": "routing",
            "message": f"Could not compile the routing brief: {error}",
            "file": BRIEF_PATH,
            "remediation": "The package still publishes; it will rank on its card alone.",
        }]

    target = base / BRIEF_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(brief, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        return [{
            "id": "brief-write-failed",
            "severity": "advice",
            "category": "routing",
            "message": f"Could not write {BRIEF_PATH}: {error}",
            "file": BRIEF_PATH,
        }]

    findings: list[dict[str, Any]] = []
    for field, meaning in _GAP_MEANING.items():
        if brief.get(field):
            continue
        findings.append({
            "id": f"brief-absent-{field}",
            "severity": "advice",
            "category": "routing",
            "message": f"Routing brief has no {field}: {meaning}.",
            "file": BRIEF_PATH,
            "remediation": (
                "Add contracts/output.schema.json and contracts/intake.schema.json; the brief is "
                "compiled from them, so nothing has to be written twice."
            ),
        })
    return findings
