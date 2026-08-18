#!/usr/bin/env python3
"""Feature-map drift gate — a rename alarm keyed on INTENT, not spelling.

Owner diagnosis 2026-08-18: alignment gates compared spellings, so the same
feature under different code names per surface (wire INGEST vs UI 장기대여 vs
retired 프로젝트 인제스트; workspaceId that actually means creator workspace;
hep-* bodies drifting across 10 runtimes) was treated as different features and
never aligned. contracts/feature-map.json binds every surface's exact current
identifier to one featureId + one intent. This gate checks only that each bound
identifier still exists where the map says it does — a grep-level rename alarm,
not a semantics proof.

Rules (same honest-skip discipline as sync-worker-memory-directive.sh):
  * A surface's repo resolves to the sibling checkout ../<repo> relative to
    this repo ("Agentlas-OS" resolves to this repo itself). An absent sibling
    checkout is a SKIP with the exact reason — CI may check out this repo
    alone. A present sibling with a missing file or identifier is a FAIL,
    never a skip.
  * On FAIL, print the featureId, its intent, the missing identifier, AND the
    sibling surfaces that implement the same feature — the fixer must see the
    intent and its siblings, not just a broken string.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAP_PATH = ROOT / "contracts" / "feature-map.json"
GATE = "[verify-feature-map]"


def resolve_repo(repo: str) -> Path:
    if repo == ROOT.name or repo == "Agentlas-OS":
        return ROOT
    return ROOT.parent / repo


def main() -> int:
    if not MAP_PATH.exists():
        print(f"{GATE} FAIL")
        print(f"  - missing registry: {MAP_PATH}")
        return 1
    try:
        registry = json.loads(MAP_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        print(f"{GATE} FAIL")
        print(f"  - unparseable registry {MAP_PATH}: {error}")
        return 1

    features = registry.get("features")
    if not isinstance(features, list) or not features:
        print(f"{GATE} FAIL")
        print(f"  - registry has no features array: {MAP_PATH}")
        return 1

    checked = 0
    skips: list[str] = []
    failures: list[str] = []
    missing_repos: set[str] = set()

    for feature in features:
        feature_id = feature.get("featureId", "<missing featureId>")
        intent = feature.get("intent", {})
        surfaces = feature.get("surfaces", [])
        if not isinstance(surfaces, list) or not surfaces:
            failures.append(f"feature {feature_id}: no surfaces declared")
            continue

        for surface in surfaces:
            repo = surface.get("repo", "")
            rel_path = surface.get("path", "")
            identifier = surface.get("identifier", "")
            if not repo or not rel_path or not identifier:
                failures.append(
                    f"feature {feature_id}: surface missing repo/path/identifier: {surface}"
                )
                continue

            repo_root = resolve_repo(repo)
            if not repo_root.is_dir():
                # Honest skip: the sibling checkout is not present at all.
                if repo not in missing_repos:
                    missing_repos.add(repo)
                    skips.append(
                        f"SKIP (sibling checkout not present): {repo_root} — "
                        f"every '{repo}' surface is unverifiable in this tree"
                    )
                continue

            target = repo_root / rel_path
            siblings = [
                f"      sibling: {s.get('repo')}:{s.get('path')} :: {s.get('identifier')}"
                for s in surfaces
                if s is not surface
            ]
            context = [
                f"    intent(ko): {intent.get('ko', '<none>')}",
                f"    intent(en): {intent.get('en', '<none>')}",
                "    sibling surfaces implementing the same feature:"
                if siblings
                else "    (no sibling surfaces declared)",
                *siblings,
            ]

            if not target.is_file():
                failures.append(
                    "\n".join(
                        [
                            f"feature {feature_id}: file missing — {target}",
                            f"    expected identifier: {identifier}",
                            *context,
                        ]
                    )
                )
                continue

            try:
                # errors="replace": a stray NUL/encoding artifact must not make a
                # present identifier invisible (the literal-NUL-hides-files trap).
                text = target.read_text(encoding="utf-8", errors="replace")
            except OSError as error:
                failures.append(
                    "\n".join(
                        [
                            f"feature {feature_id}: unreadable file — {target}: {error}",
                            *context,
                        ]
                    )
                )
                continue

            checked += 1
            if identifier not in text:
                failures.append(
                    "\n".join(
                        [
                            f"feature {feature_id}: identifier NOT FOUND — '{identifier}'",
                            f"    in file: {target}",
                            *context,
                        ]
                    )
                )

    for line in skips:
        print(f"{GATE} {line}")

    if failures:
        print(f"{GATE} FAIL — {len(failures)} problem(s), {checked} surface(s) checked")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(
        f"{GATE} PASS — {checked} surface identifier(s) verified across "
        f"{len(features)} feature(s); {len(skips)} repo skip(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
