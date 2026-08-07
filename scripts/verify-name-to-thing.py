#!/usr/bin/env python3
"""Every name this product writes down must point at something that exists.

Five defects found separately over months turned out to be one shape:

    /hep-build named AGENTS.md, the mode map, the interview gate  -> not shipped
    the Python CLI exposed `contract`                             -> not in bin dispatch
    project bootstrap created context-map.json                    -> no code ever wrote it
    the contract required routing-benchmarks.jsonl (plural)       -> packages ship singular
    the contract required eval-judge                              -> packages ship eval-qa

In each case one side wrote a name and nothing checked the other side. Fixing
them one at a time produces a sixth next month, so this gate checks the shape.

    C1  a path a shipped command file names exists in the shipped engine
    C2  every Python CLI subcommand is reachable through bin/hephaestus, both ways
    C3  a required contract artifact's name is a name the engine's own code knows
    C4  a seed file the product creates actually gets filled when there is input
    C5  every runtime's /hep-build surface carries the same contract steps
    C6  an installed runtime and the adapters it installs are one generation
    C7  an agent invocation actually files a candidate memory ticket

Usage:
    python3 scripts/verify-name-to-thing.py            # human output
    python3 scripts/verify-name-to-thing.py --json
    python3 scripts/verify-name-to-thing.py --engine <dir>   # check an installed engine

Exit code is 1 on any failure. A check that cannot run is a failure, not a skip:
this repository has already shipped a gate that silently passed because its
input had moved.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# The adapters that a user actually installs. Anything a command file here names
# has to be present here too — that is the whole point of the check.
ENGINE_ROOTS = [
    "claude/plugins/agentlas-core-engine-meta-agent",
    "codex/plugins/agentlas-core-engine-meta-agent",
]

# Command surfaces, per engine root and repo-wide. `$ENGINE/...` and bare
# relative paths are both read against the engine root, because that is where
# the reader stands when the command runs.
COMMAND_GLOBS = [
    "commands/*.md",
    "prompts/*.md",
]

# Paths named in prose that are not files this engine owns.
NAME_ALLOWLIST = {
    "agentlas.json",  # written into the package under construction, not read from the engine
    ".agentlas/work-brief.json",
    ".agentlas/capability-eval-plan.json",
    ".agentlas/global-commands.json",
    ".agentlas/routing-card.json",
    ".agentlas/company-blueprint.json",
    "docs/builder-interview.md",
    "docs/research-sources.md",
    "docs/tool-selection.md",
    "docs/domain-expert-synthesis.md",
    "docs/prompt-performance-contract.md",
    "README_FOR_HUMANS.md",
    "CLAUDE.md",
    "AGENTS.md",  # checked explicitly below against the engine root
}

_PATH_IN_BACKTICKS = re.compile(r"`\$?(?:\{?ENGINE\}?/)?([A-Za-z0-9_.][A-Za-z0-9_./-]*\.(?:md|json|jsonl|sh|py|toml))`")

failures: list[str] = []
notes: list[str] = []


def fail(check: str, message: str) -> None:
    failures.append(f"{check}: {message}")


# ---------------------------------------------------------------- C1
def check_named_paths_exist(engine: Path, label: str) -> None:
    """A path a command file names must exist where the command will look."""

    files: list[Path] = []
    for pattern in COMMAND_GLOBS:
        files.extend(sorted(engine.glob(pattern)))
    # Codex keeps its command surface beside the plugin (`codex/prompts/`), not
    # inside it. The files still read against the engine root at run time, so
    # they belong to this check.
    for pattern in COMMAND_GLOBS:
        files.extend(sorted(engine.parent.parent.glob(pattern)))
    files = sorted(set(files))
    if not files:
        fail("C1", f"{label}: no command files found — a gate that cannot look must fail")
        return

    checked = 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as error:
            fail("C1", f"{label}: cannot read {path.name} ({error})")
            continue
        for match in _PATH_IN_BACKTICKS.finditer(text):
            named = match.group(1)
            if named in NAME_ALLOWLIST and named != "AGENTS.md":
                continue
            # Only engine-owned trees: everything else is the user's package.
            if not named.split("/")[0] in {"AGENTS.md", "docs", "modes", "schemas", "scripts", "skills", "templates", "bin", ".agentlas", "package-contract.json"}:
                continue
            if named in NAME_ALLOWLIST and named != "AGENTS.md":
                continue
            checked += 1
            if not (engine / named).exists():
                fail("C1", f"{label}: {path.name} names `{named}` but the engine does not ship it")
    notes.append(f"C1 {label}: {len(files)} command file(s), {checked} engine-owned path reference(s)")


# ---------------------------------------------------------------- C2
def check_cli_reachable(engine: Path, label: str) -> None:
    """Every Python subcommand reachable from bin, and every bin token real."""

    cli = engine / "agentlas_cloud" / "cli.py"
    launcher = engine / "bin" / "hephaestus"
    if not cli.exists() or not launcher.exists():
        fail("C2", f"{label}: cli.py or bin/hephaestus missing — cannot compare")
        return

    # Ask argparse, do not pattern-match the source. `add_parser` also matches
    # every nested sub-subcommand (`contract scaffold`, `research armory`, …),
    # and a check built on that list reports dozens of false failures — which is
    # its own way of being useless.
    helped = subprocess.run(
        [sys.executable, "-m", "agentlas_cloud.cli", "--help"],
        cwd=engine,
        capture_output=True,
        text=True,
    )
    listed = re.search(r"\{([a-z0-9,\-]+)\}", helped.stdout)
    if not listed:
        fail("C2", f"{label}: could not read the CLI's own subcommand list — cannot compare")
        return
    top_level = {name for name in listed.group(1).split(",") if name}

    # What the launcher can actually invoke is the set of module calls it makes,
    # not its top-level case labels. `bundle` and `read-agent-file` are reached
    # through `runtime bundle` and are perfectly callable; a check that only read
    # the outer labels called them broken. Read the calls instead of the shape.
    launcher_text = launcher.read_text(encoding="utf-8")
    if 'case "$command" in' not in launcher_text:
        fail("C2", f"{label}: bin/hephaestus has no command dispatch")
        return
    dispatch = set(re.findall(r'run_python_module agentlas_cloud "?([a-z][a-z0-9-]*)"?', launcher_text))
    dispatch.update(re.findall(r'run_python_module agentlas_cloud "\$command"', launcher_text) and
                    {token for label_line in re.findall(r"^\s*([A-Za-z][A-Za-z0-9_|.-]*)\)\s*$", launcher_text, re.M)
                     for token in label_line.split("|")} or set())

    unreachable = sorted(top_level - dispatch)
    for name in unreachable:
        fail(
            "C2",
            f"{label}: `{name}` exists in the Python CLI but bin/hephaestus never dispatches it — "
            "it falls through to the natural-language router, which rejects a package path as private",
        )
    notes.append(f"C2 {label}: {len(top_level)} CLI subcommand(s), {len(dispatch)} dispatch token(s)")


# ---------------------------------------------------------------- C3
def check_contract_names_are_known(engine: Path, label: str) -> None:
    """A required artifact's name must be a name the rest of the engine knows.

    Comparing the contract against `contract scaffold` alone proves nothing:
    scaffold reads the same contract, so it agrees by construction. The drift
    that actually shipped was contract-versus-generator — the contract asked for
    `routing-benchmarks.jsonl` while `cards migrate` wrote the singular, and
    every package failed a required artifact on the name alone while the file sat
    on disk. So check the name against the code that produces and consumes it.
    """

    contract_path = engine / "package-contract.json"
    if not contract_path.exists():
        fail("C3", f"{label}: package-contract.json missing")
        return
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    sources = list((engine / "agentlas_cloud").rglob("*.py")) + list((engine / "templates").glob("*"))
    if not sources:
        fail("C3", f"{label}: no engine sources to compare names against")
        return
    corpus = "\n".join(
        path.read_text(encoding="utf-8", errors="replace") for path in sources if path.is_file()
    ) + "\n".join(path.name for path in sources)

    unknown = 0
    for artifact in contract.get("artifacts", []):
        if not artifact.get("required"):
            continue
        path = str(artifact.get("path") or "")
        if not path or "*" in path:
            continue
        basename = path.split("/")[-1]
        if basename not in corpus:
            unknown += 1
            fail(
                "C3",
                f"{label}: the contract requires `{path}` but no engine source or template "
                f"mentions `{basename}` — nothing produces or reads that name",
            )
    notes.append(f"C3 {label}: {len(contract.get('artifacts', []))} artifact(s), {unknown} unknown name(s)")


def check_scaffold_runs(engine: Path, label: str) -> None:
    """Scaffold must still put templated artifacts on disk in both modes."""

    contract_path = engine / "package-contract.json"
    if not contract_path.exists():
        fail("C3", f"{label}: package-contract.json missing")
        return
    contract = json.loads(contract_path.read_text(encoding="utf-8"))

    for mode in ("single", "team"):
        # An artifact with no template is declared to come from somewhere else —
        # `.agentlas/work-brief.json` is the interview's own output and cannot be
        # copied from a stencil. Declaring that is fine; what is not fine is a
        # required artifact that claims a template and still never appears.
        required = {
            artifact["path"]
            for artifact in contract.get("artifacts", [])
            if artifact.get("required")
            and mode in (artifact.get("modes") or [])
            and artifact.get("template")
        }
        with tempfile.TemporaryDirectory() as workdir:
            result = subprocess.run(
                [sys.executable, "-m", "agentlas_cloud.cli", "contract", "scaffold", workdir, "--mode", mode],
                cwd=engine,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                fail("C3", f"{label}/{mode}: contract scaffold failed ({result.stderr.strip()[:120]})")
                continue
            produced = {
                str(path.relative_to(workdir))
                for path in Path(workdir).rglob("*")
                if path.is_file()
            }
        missing = sorted(
            path
            for path in required
            if "*" not in path and path not in produced
        )
        for path in missing:
            fail(
                "C3",
                f"{label}/{mode}: the contract requires `{path}` but `contract scaffold` never writes it — "
                "a build following the contract cannot satisfy it",
            )
        notes.append(f"C3 {label}/{mode}: {len(required)} required, {len(missing)} unproduced")


# ---------------------------------------------------------------- C4
def check_seed_files_get_filled(engine: Path, label: str) -> None:
    """A file the product creates empty must actually get filled — run it and look.

    context-map.json was born with `nodes: []` and a note asking a human to add
    goals and decisions. No surface offered that action, so it stayed empty on
    every machine while `context.slice` reported the project's goals from it.

    Grepping for a writer is not enough, and this gate proved it: a text search
    passed while the seed was still never filled, because a large module that
    mentions the file and writes some other file matches. So build a project that
    has something to derive from, run the derivation, and require growth.
    """

    probe = (
        "import json, tempfile\n"
        "from pathlib import Path\n"
        "from agentlas_cloud.context_map_authoring import refresh_declared_context\n"
        "with tempfile.TemporaryDirectory() as workdir:\n"
        "    root = Path(workdir)\n"
        "    learnings = root / '.agentlas' / 'pm' / 'learnings'\n"
        "    learnings.mkdir(parents=True)\n"
        "    (learnings / 'probe.md').write_text('# Probe\\n\\n## Decision - the seed must carry this\\n- evidence\\n', encoding='utf-8')\n"
        "    receipt = refresh_declared_context(root)\n"
        "    payload = json.loads((root / '.agentlas' / 'context-map.json').read_text(encoding='utf-8'))\n"
        "    print(json.dumps({'nodes': len(payload.get('nodes') or []), 'status': receipt.get('status')}))\n"
    )
    result = subprocess.run([sys.executable, "-c", probe], cwd=engine, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        fail("C4", f"{label}: context-map.json has no working writer ({detail[-1][:120] if detail else 'no output'})")
        return
    try:
        measured = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        fail("C4", f"{label}: the seed-fill probe produced no readable result")
        return
    if measured.get("nodes", 0) < 1:
        fail(
            "C4",
            f"{label}: a project with a recorded decision still produced an empty context map — "
            "the file is seeded and never filled, so context.slice reports boilerplate goals",
        )
    notes.append(f"C4 {label}: seed fill probe produced {measured.get('nodes')} node(s)")



# ---------------------------------------------------------------- C5
# Every surface that offers the same command must carry the same contract steps.
BUILD_SURFACES = [
    "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-build.md",
    "codex/prompts/hep-build.md",
    "antigravity/workflows/hep-build.md",
    "cursor/plugin/commands/hep-build.md",
    "opencode/commands/hep-build.md",
    "gemini/extension/commands/hep-build.toml",
    ".claude/commands/hep-build.md",
    ".agents/workflows/hep-build.md",
    ".gemini/commands/hep-build.toml",
]

# Steps without which a build cannot satisfy the package contract. These are not
# stylistic: measured 2026-08-07, a build that skipped scaffold shipped 5 of 18
# required artifacts and still reported success.
BUILD_REQUIRED_STEPS = {
    "contract scaffold": "lays every required artifact down before writing",
    "contract verify": "names the exact remaining hole before reporting",
}


def check_build_surfaces_agree(root: Path) -> None:
    present = [path for path in (root / surface for surface in BUILD_SURFACES) if path.exists()]
    if not present:
        fail("C5", "no /hep-build surface found — a gate that cannot look must fail")
        return
    for path in present:
        text = path.read_text(encoding="utf-8", errors="replace")
        for step, why in BUILD_REQUIRED_STEPS.items():
            if step not in text:
                fail(
                    "C5",
                    f"{path.relative_to(root)} never calls `{step}` — {why}. "
                    "A surface that offers /hep-build without it builds a package the contract rejects.",
                )
    notes.append(f"C5: {len(present)} /hep-build surface(s) checked")



# ---------------------------------------------------------------- C6
# Shared runtime code that a runtime carries twice must be the same code.
RUNTIME_MIRRORED = [
    "bin/hephaestus",
    "package-contract.json",
    "agentlas_cloud/cli.py",
    "agentlas_cloud/package_contract.py",
]


def check_runtime_and_adapters_agree(runtime_root: Path) -> None:
    """A runtime and the adapters it installs must be one generation.

    The installed runtime overwrites `~/.claude/plugins/cache/...` from its own
    `host_adapters/` bundle on first run. Measured 2026-08-07: a locally repaired
    plugin was reverted to the published bytes at first invocation (md5 of the
    plugin's bin/hephaestus matched the runtime's copy, not the repaired one).
    That is correct behaviour and it is also why a fix that lands only in an
    adapter never reaches anyone. If the two halves of one runtime disagree, the
    product runs one engine and tells the host about another.
    """

    bundle = runtime_root / "host_adapters"
    if not bundle.is_dir():
        fail("C6", f"{runtime_root.name}: no host_adapters bundle — this runtime installs no adapters")
        return
    adapters = sorted(bundle.glob("*/plugins/agentlas-core-engine-meta-agent"))
    if not adapters:
        fail("C6", f"{runtime_root.name}: host_adapters carries no plugin — a gate that cannot look must fail")
        return
    compared = 0
    for adapter in adapters:
        for relative in RUNTIME_MIRRORED:
            left, right = runtime_root / relative, adapter / relative
            if not left.exists() or not right.exists():
                continue
            compared += 1
            if left.read_bytes() != right.read_bytes():
                fail(
                    "C6",
                    f"{runtime_root.name}: `{relative}` differs between the runtime root and "
                    f"{adapter.parent.parent.name}'s adapter — the adapter this runtime installs "
                    "is not the engine this runtime runs",
                )
    notes.append(f"C6 {runtime_root.name}: {len(adapters)} adapter(s), {compared} mirrored file(s) compared")




def check_invocation_ledgers_get_written(engine: Path, label: str) -> None:
    """A borrowed agent's candidate-memory ledger must actually receive events.

    Measured on 60 borrowed agents on a host that had been running for months:
    `invocation-ledger.jsonl`, `memory-map.json`, `project-soul-memory.md` and
    `experience.sqlite` were written in every one, and `memory-tickets.jsonl` was
    empty in all 60. The Hub serves `agentlas.memory.ticket`; the invocation path
    created the ledger file and then called three other memory tools, never that
    one. The curator downstream was not broken, it was starved.
    """

    probe = (
        "import json, pathlib, tempfile\n"
        "from agentlas_cloud.networking.hub_invocation import _touch_agentlas_memory\n"
        "with tempfile.TemporaryDirectory() as d:\n"
        "    root = pathlib.Path(d) / 'mem'\n"
        "    home = pathlib.Path(d) / 'home'; home.mkdir()\n"
        "    _touch_agentlas_memory(memory_root=root, slug='probe', request='probe request text',\n"
        "                           routing_receipt_id='receipt:probe', home=home)\n"
        "    t = root / 'memory-tickets.jsonl'\n"
        "    body = t.read_text(encoding='utf-8') if t.exists() else ''\n"
        "    print(json.dumps({'bytes': len(body), 'leaks': 'probe request text' in body}))\n"
    )
    result = subprocess.run([sys.executable, "-c", probe], cwd=engine, capture_output=True, text=True)
    if result.returncode != 0:
        detail = (result.stderr or "").strip().splitlines()
        fail("C7", f"{label}: the invocation memory path did not run ({detail[-1][:120] if detail else 'no output'})")
        return
    try:
        measured = json.loads(result.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        fail("C7", f"{label}: the invocation ledger probe produced no readable result")
        return
    if measured.get("bytes", 0) < 1:
        fail(
            "C7",
            f"{label}: an invocation wrote no candidate memory ticket — the curator has nothing "
            "to promote, so agent-level memory never accumulates",
        )
    if measured.get("leaks"):
        fail("C7", f"{label}: the ticket ledger carried the raw request; it must carry a hash")
    notes.append(f"C7 {label}: invocation ticket ledger {measured.get('bytes')} byte(s), raw request withheld")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--engine", action="append", default=[])
    parser.add_argument("--runtime", action="append", default=[],
                        help="an installed runtime root to check for adapter/runtime drift")
    args = parser.parse_args()

    engines = [Path(value).resolve() for value in args.engine] or [ROOT / rel for rel in ENGINE_ROOTS]
    for engine in engines:
        label = engine.name if engine.name != "agentlas-core-engine-meta-agent" else engine.parent.parent.name
        if not engine.is_dir():
            fail("C0", f"{label}: engine root {engine} does not exist")
            continue
        check_named_paths_exist(engine, label)
        check_cli_reachable(engine, label)
        check_contract_names_are_known(engine, label)
        check_scaffold_runs(engine, label)
        check_seed_files_get_filled(engine, label)
        check_invocation_ledgers_get_written(engine, label)
    check_build_surfaces_agree(ROOT)
    for runtime in (Path(value).resolve() for value in args.runtime):
        if runtime.is_dir():
            check_runtime_and_adapters_agree(runtime)
        else:
            fail("C6", f"runtime root {runtime} does not exist")

    if args.json:
        print(json.dumps({"ok": not failures, "notes": notes, "failures": failures}, ensure_ascii=False, indent=2))
    else:
        for note in notes:
            print(f"  {note}")
        if failures:
            print("\nname-to-thing: FAIL", file=sys.stderr)
            for failure in failures:
                print(f"  {failure}", file=sys.stderr)
            print(
                "\n  Each of these is one side writing a name the other side does not answer to.\n"
                "  Fix the mismatch; do not relax the check.",
                file=sys.stderr,
            )
        else:
            print("\nname-to-thing: PASS (every name points at something that exists)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
