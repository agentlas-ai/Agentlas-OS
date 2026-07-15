#!/usr/bin/env python3
"""Run the same routed Stormbreaker pipeline against Terra or local Qwen."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SEEDER = HERE / "seed_dependency_cli.py"
EXECUTOR = HERE / "packet_executor.py"
VERIFIER = HERE / "verify_dependency_cli.py"
HEPHAESTUS = ROOT / "bin" / "hephaestus"
GOAL = (
    "Use the Hub packaged team product-development-hq to plan, implement, test, and "
    "independently verify a safe Python command-line tool "
    "that reads a JSON task graph, computes a deterministic dependency-respecting "
    "execution order, reports every node in a cycle, and reports missing dependencies. "
    "Use the existing project brief and finish only after the external verifier passes."
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=("codex", "openai"), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--api-base", default="http://127.0.0.1:11434/v1")
    parser.add_argument("--max-turns", type=int, default=12)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    project = args.project.resolve()
    seed = [sys.executable, str(SEEDER), str(project)]
    if args.force:
        seed.append("--force")
    subprocess.run(seed, check=True)

    run_env = os.environ.copy()
    run_env.update(
        {
            "AGENTLAS_PACKET_BACKEND": args.backend,
            "AGENTLAS_PACKET_MODEL": args.model,
            "AGENTLAS_PACKET_API_BASE": args.api_base,
            "AGENTLAS_PACKET_MAX_TURNS": str(args.max_turns),
            "AGENTLAS_PACKET_VERIFY_COMMAND": (
                f"{sys.executable} {VERIFIER} --project {project}"
            ),
            "PYTHONUTF8": "1",
        }
    )
    started_at = datetime.now(timezone.utc).isoformat()
    provider = "codex" if args.backend == "codex" else "ollama"
    session_inventory = [
        {
            "session_id": f"{provider}:{args.model}",
            "provider": provider,
            "model": args.model,
            "local": True,
            "capabilities": ["planning", "coding", "verification", "test"],
            "max_parallel": 1,
            "supports_tools": True,
        }
    ]
    command = [
        str(HEPHAESTUS),
        "hep-storm",
        GOAL,
        "--project",
        str(project),
        "--brief",
        str(project),
        "--session-inventory",
        json.dumps(session_inventory, separators=(",", ":")),
        "--executor-command",
        f"{sys.executable} {EXECUTOR}",
        "--max-workers",
        "1",
        "--max-replans",
        "1",
        "--timeout",
        str(args.timeout),
    ]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=run_env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)
    try:
        stormbreaker_result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        stormbreaker_result = {
            "status": "invalid_result",
            "stdout": completed.stdout[-20_000:],
            "stderr": completed.stderr[-20_000:],
        }
    (project / "stormbreaker-result.json").write_text(
        json.dumps(stormbreaker_result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {
        "schema": "agentlas.benchmark.core-run.v1",
        "startedAt": started_at,
        "finishedAt": datetime.now(timezone.utc).isoformat(),
        "backend": args.backend,
        "model": args.model,
        "project": str(project),
        "command": command,
        "exitCode": completed.returncode,
        "routeReceiptId": stormbreaker_result.get("route_receipt_id"),
        "pipelineId": stormbreaker_result.get("pipeline_id"),
        "finalGate": stormbreaker_result.get("final_gate"),
    }
    output = project / "benchmark-run.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
