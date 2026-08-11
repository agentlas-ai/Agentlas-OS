#!/usr/bin/env python3
"""Curator conformance gate — runs the shared fixtures against the OS executor.

Every Memory Curator executor (Desktop curator.ts, this repo's one_workspace.py)
must pass the same curator-fixtures/cases.json. A check that cannot run must
fail, not skip. Exit 0 only when every case matches.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agentlas_cloud import one_workspace as ow  # noqa: E402

FIXTURES = ROOT / ".internal" / "curator-fixtures" / "cases.json"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    raise SystemExit(1)


def main() -> int:
    if not FIXTURES.is_file():
        fail(f"fixtures missing: {FIXTURES}")
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))
    ruleset, sha = ow.load_ruleset()
    if sha == "embedded":
        fail("canonical curator-ruleset.json did not load — executor is on embedded fallback")
    passed = 0

    # 1) classify cases -----------------------------------------------------
    for case in cases.get("classify", []):
        durable = set()
        marker = case.get("durableContains")
        if marker:
            durable.add(ow._content_hash(marker))
        action, reason = ow._classify(dict(case["candidate"]), durable)
        if [action, reason] != [case["expect"]["action"], case["expect"]["reason"]]:
            fail(f"classify/{case['id']}: got ({action},{reason}) want "
                 f"({case['expect']['action']},{case['expect']['reason']})")
        passed += 1

    # 1b) shared secret-shape cases (server/desktop compat) -----------------
    for case in cases.get("secretShapes", []):
        content = case["content"]
        hit = bool(ow._rule_re("secretKeyValue").search(content)
                   or ow._rule_re("secretValueShapes").search(content))
        if hit != bool(case["expectSecret"]):
            fail(f"secretShapes/{case['id']}: matched={hit} want {case['expectSecret']}")
        passed += 1

    # (teamLayer / projectSpecifics sections are desktop-executor conformance;
    #  the OS executor gains the projectSpecifics guard with the P2 slug work.)

    # 2) emitter cases — exercised through the real curate() path ----------
    for case in cases.get("emitter", []):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "one"
            ow.seed(root, name="Fixture")
            ticket = {
                "schemaVersion": ow.SCHEMA_VERSION,
                "ticketId": "one-tkt-fixture",
                "agentId": ow.ONE_AGENT_ID,
                "state": "queued",
                "candidate": case["ticket"]["candidate"],
                "createdAt": ow._now(),
            }
            if "emitter" in case["ticket"]:
                ticket["emitter"] = case["ticket"]["emitter"]
            meta = root / ow.META_DIR
            with (meta / ow.MEMORY_TICKETS_FILE).open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(ticket, ensure_ascii=False) + "\n")
            ow.curate(root)
            decisions = [json.loads(line) for line in
                         (meta / ow.CURATOR_DECISIONS_FILE).read_text(encoding="utf-8").splitlines()
                         if line.strip()]
            row = next((d for d in decisions if d.get("ticketId") == "one-tkt-fixture"), None)
            if row is None:
                fail(f"emitter/{case['id']}: no decision recorded")
            if [row["action"], row["reason"]] != [case["expect"]["action"], case["expect"]["reason"]]:
                fail(f"emitter/{case['id']}: got ({row['action']},{row['reason']}) want "
                     f"({case['expect']['action']},{case['expect']['reason']})")
            if row.get("rulesetSha256") != sha:
                fail(f"emitter/{case['id']}: decision missing rulesetSha256 {sha}")
        passed += 1

    # 3) G6 dedupe cases — duplicate emits converge to a single ticket ------
    for case in cases.get("emitDedupe", []):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "one"
            ow.seed(root, name="Fixture")
            first = ow.emit_ticket(root, content=case["content"], kind=case["kind"],
                                   evidence=case["evidence"], emitter="one-cli")
            second = ow.emit_ticket(root, content=case["content"], kind=case["kind"],
                                    evidence=case["evidence"], emitter="one-cli")
            rows = (root / ow.META_DIR / ow.MEMORY_TICKETS_FILE).read_text(encoding="utf-8")
            count = sum(1 for line in rows.splitlines() if line.strip())
            if first is None:
                fail(f"emitDedupe/{case['id']}: first emit unexpectedly refused")
            if case.get("emitTwice") and second is not None:
                fail(f"emitDedupe/{case['id']}: duplicate emit returned a ticket")
            if count != case["expect"]["tickets"]:
                fail(f"emitDedupe/{case['id']}: {count} tickets, want {case['expect']['tickets']}")
        passed += 1

    # 4) desktop mirror parity — the shipped copies must be byte-equal to the
    #    canonical files. Field-name comparison misses drift; bytes cannot.
    # A standalone clone of this repo has no Desktop beside it, so absence is an
    # environment fact rather than a defect. A wrong path is a defect, though:
    # when AGENTLAS_DESKTOP_CHECKOUT names somewhere that is not a checkout, the
    # gate fails instead of quietly reporting a skip.
    override = os.environ.get("AGENTLAS_DESKTOP_CHECKOUT", "").strip()
    if override:
        desktop = Path(override).expanduser()
        if not desktop.is_dir():
            fail(f"AGENTLAS_DESKTOP_CHECKOUT does not exist: {desktop}")
    else:
        desktop = ROOT.parent / "agentlas_desktop"
    if desktop.is_dir():
        pairs = [
            (ROOT / "system-agents" / "curator-ruleset.json",
             desktop / "electron" / "memory" / "curator-ruleset.json"),
            (FIXTURES, desktop / ".internal" / "curator-fixtures" / "cases.json"),
        ]
        for canonical, mirror in pairs:
            if not mirror.is_file():
                fail(f"mirror missing: {mirror}")
            if canonical.read_bytes() != mirror.read_bytes():
                fail(f"mirror drift: {mirror} != {canonical}")
            passed += 1
    else:
        print("mirror-check: skipped (no agentlas_desktop sibling checkout)")

    print(f"PASS: {passed} curator fixture cases (ruleset {ruleset.get('rulesetVersion')} sha {sha})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
