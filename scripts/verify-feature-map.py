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

The gate also runs against any activated project's map: pass
``--map <project>/.agentlas/feature-map.json`` and sibling repos resolve
relative to that map's parent workspace, exactly as they do for the engine's
own map in contracts/ (the workspace's own name resolves to itself).

Rules (same honest-skip discipline as sync-worker-memory-directive.sh):
  * A surface's repo resolves to the sibling checkout ../<repo> relative to
    the map's workspace (the workspace's own directory name — and, for the
    engine map, the canonical name "Agentlas-OS" — resolves to the workspace
    itself). An absent sibling checkout is a SKIP with the exact reason — CI
    may check out one repo alone. A present sibling with a missing file or
    identifier is a FAIL, never a skip.
  * Schema validation (schemas/feature-map.schema.json) runs when the optional
    ``jsonschema`` package is importable; when it is not, that single check is
    an honest SKIP with the reason — a missing optional dep must never FAIL,
    and must never be silently reported as a pass.
  * On FAIL, print the featureId, its intent, the missing identifier, AND the
    sibling surfaces that implement the same feature — the fixer must see the
    intent and its siblings, not just a broken string.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAP_PATH = ROOT / "contracts" / "feature-map.json"
SCHEMA_PATH = ROOT / "schemas" / "feature-map.schema.json"
GATE = "[verify-feature-map]"


def workspace_root(map_path: Path) -> Path:
    """The workspace a map belongs to: contracts/ and .agentlas/ maps live one
    level below their workspace root; a bare map sits in its workspace."""
    if map_path.parent.name in {"contracts", ".agentlas"}:
        return map_path.parent.parent
    return map_path.parent


def resolve_repo(repo: str, workspace: Path) -> Path:
    if repo == workspace.name:
        return workspace
    # The engine map may live in a checkout named something other than
    # Agentlas-OS; the canonical name still means "this workspace".
    if workspace == ROOT and repo == "Agentlas-OS":
        return workspace
    return workspace.parent / repo


def validate_schema(registry: object, skips: list[str], failures: list[str]) -> None:
    if not SCHEMA_PATH.is_file():
        failures.append(f"schema missing — {SCHEMA_PATH} (the gate ships with its schema; this checkout is broken)")
        return
    try:
        import jsonschema  # type: ignore[import-untyped]
    except ImportError as error:
        skips.append(
            f"SKIP (jsonschema not importable: {error}) — schema validation not performed; "
            "identifier checks below still ran"
        )
        return
    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        failures.append(f"unreadable schema {SCHEMA_PATH}: {error}")
        return
    validator = jsonschema.Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(registry), key=lambda e: list(e.absolute_path))
    for error in errors[:20]:
        where = "/".join(str(part) for part in error.absolute_path) or "<root>"
        failures.append(f"schema violation at {where}: {error.message}")
    if len(errors) > 20:
        failures.append(f"schema violation: …and {len(errors) - 20} more")


#: Copy that actually ships to a user or a host LLM. A retired alias may still
#: be written down in history (CHANGELOG, docs, this gate's own docstring) — it
#: may not be *taught*. Anything outside this list is history and is not scanned.
RETIRED_SCAN_SUFFIXES = (".md", ".py", ".json", ".txt", ".toml")
RETIRED_SCAN_EXCLUDE_PREFIXES = (
    "docs/",
    "tests/",
    "benchmarks/",
    "ledgers/",
    "cache/",
    "dist/",
    "assets/",
    "scripts/",
    "CHANGELOG.md",
)
RETIRED_SCAN_EXCLUDE_NAMES = ("feature-map.json",)


def tracked_copy_files(workspace: Path, skips: list[str]) -> list[Path] | None:
    """Tracked, user-facing text files, via git.

    git is the enumerator on purpose: it already knows what ships and what is a
    build artifact, so the scan cannot be fooled by a stale dist/ or an ignored
    scratch file. No git, no enumeration — an honest skip, never a silent pass.
    """
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(workspace), "ls-files", "-z"],
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as error:
        skips.append(
            f"SKIP (git could not list tracked files in {workspace}: {error}) — "
            "retired-alias copy scan not performed"
        )
        return None

    files: list[Path] = []
    for raw in out.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", errors="replace")
        name = rel.rsplit("/", 1)[-1]
        # An extension list alone has a hole exactly where the product talks
        # most: `bin/hephaestus` is the CLI a seller reads prices from and it
        # has no suffix, so it went unscanned and kept teaching the retired
        # 24-hour lease for a month after everything else was corrected.
        # Extensionless tracked files are text here (scripts, runners); a
        # binary is rejected by the NUL check at read time.
        if not (rel.endswith(RETIRED_SCAN_SUFFIXES) or "." not in name):
            continue
        if rel.startswith(RETIRED_SCAN_EXCLUDE_PREFIXES):
            continue
        if name in RETIRED_SCAN_EXCLUDE_NAMES:
            continue
        files.append(workspace / rel)
    return files


def check_retired_copy(
    features: list, workspace: Path, skips: list[str], failures: list[str]
) -> int:
    """A `retired` alias must not reappear in shipping copy.

    The map already said so in prose — "Retired 2026-08-18; must not reappear in
    new copy" — and nothing enforced it, so on 2026-09-13 the retired 24-hour
    lease was still being taught in 52 places across the host adapters. A rule
    written only in a note is a rule nobody runs.

    An alias may carry `allowedIn: ["<path substring>", ...]` for the places
    that legitimately explain the retirement rather than teach it.
    """
    retired: list[tuple[str, str, dict, list[str]]] = []
    for feature in features:
        feature_id = feature.get("featureId", "<missing featureId>")
        intent = feature.get("intent", {})
        for alias in feature.get("aliases", []) or []:
            if alias.get("status") != "retired":
                continue
            name = str(alias.get("name", "")).strip()
            if not name:
                failures.append(f"feature {feature_id}: retired alias with no name")
                continue
            allowed = [str(a) for a in (alias.get("allowedIn") or [])]
            retired.append((feature_id, name, intent, allowed))

    if not retired:
        return 0

    files = tracked_copy_files(workspace, skips)
    if files is None:
        return 0

    scanned = 0
    for path in files:
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:4096]:
            continue  # binary; an extensionless tracked file may still be one
        text = raw.decode("utf-8", errors="replace")
        scanned += 1
        rel = str(path.relative_to(workspace))
        for feature_id, name, intent, allowed in retired:
            if name not in text:
                continue
            if any(fragment in rel for fragment in allowed):
                continue
            line_no = next(
                (i for i, line in enumerate(text.splitlines(), 1) if name in line), 0
            )
            failures.append(
                "\n".join(
                    [
                        f"feature {feature_id}: RETIRED alias still taught — '{name}'",
                        f"    in file: {rel}:{line_no}",
                        f"    say instead (ko): {intent.get('ko', '<none>')}",
                        f"    say instead (en): {intent.get('en', '<none>')}",
                        "    (if this line explains the retirement rather than teaches it, "
                        "add the path to that alias's allowedIn)",
                    ]
                )
            )
    return scanned


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--map",
        dest="map_path",
        default=str(DEFAULT_MAP_PATH),
        help="Feature map to verify (default: the engine's contracts/feature-map.json; "
        "pass <project>/.agentlas/feature-map.json for a project map)",
    )
    args = parser.parse_args()
    map_path = Path(args.map_path).expanduser().resolve()
    is_default_map = map_path == DEFAULT_MAP_PATH
    workspace = workspace_root(map_path)

    if not map_path.exists():
        print(f"{GATE} FAIL")
        print(f"  - missing registry: {map_path}")
        return 1
    try:
        registry = json.loads(map_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        print(f"{GATE} FAIL")
        print(f"  - unparseable registry {map_path}: {error}")
        return 1

    checked = 0
    skips: list[str] = []
    failures: list[str] = []
    missing_repos: set[str] = set()

    validate_schema(registry, skips, failures)

    features = registry.get("features") if isinstance(registry, dict) else None
    if not isinstance(features, list) or (not features and is_default_map):
        # The engine's own map must never regress to empty; a freshly seeded
        # project map legitimately starts with zero features.
        print(f"{GATE} FAIL")
        for failure in failures:
            print(f"  - {failure}")
        print(f"  - registry has no features array: {map_path}")
        return 1

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

            repo_root = resolve_repo(repo, workspace)
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
                # 저장소 정책상 로컬 전용(gitignored)인 게이트/테스트 파일은 새
                # 체크아웃에 없는 것이 정상이다 — 거짓 FAIL 대신 사유 있는 SKIP.
                if surface.get("localOnly"):
                    skips.append(
                        f"feature {feature_id}: local-only file absent in this checkout — {target}"
                    )
                    continue
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

    copy_scanned = check_retired_copy(features, workspace, skips, failures)

    for line in skips:
        print(f"{GATE} {line}")

    if failures:
        print(f"{GATE} FAIL — {len(failures)} problem(s), {checked} surface(s) checked")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(
        f"{GATE} PASS — {checked} surface identifier(s) verified across "
        f"{len(features)} feature(s); {copy_scanned} shipping file(s) scanned for "
        f"retired copy; {len(skips)} skip(s); map: {map_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
