#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


README = """# Dependency Order CLI Benchmark

Implement `deporder.py` using the Python standard library only.

The command is:

```text
python3 deporder.py --input task.json --output result.json
```

Input is `{"tasks":{"task-name":["dependency-name"]}}`.

- On success, exit 0 and write `{"status":"ok","order":[...]}`.
- The order must respect dependencies and use lexical order for every tie.
- On a cycle, exit 2 and write an error object with `error="cycle"` and the
  complete set of nodes participating in cycles under `nodes`.
- On a missing dependency, exit 3 and identify `task` and `dependency`.
- Output must be deterministic regardless of JSON object or dependency-list
  insertion order.
"""


BRIEF = {
    "schemaVersion": "work-brief/1.0",
    "goal": "Implement and independently verify a deterministic dependency-ordering CLI",
    "users": ["release engineer"],
    "acceptance_criteria": [
        "Produces a dependency-respecting lexical order",
        "Reports all cycle nodes with exit code 2",
        "Reports a missing dependency with exit code 3",
        "Produces deterministic result.json output",
    ],
    "constraints": ["Python standard library only", "No network access"],
    "anti_scope": ["No package installation", "No external service"],
    "risks": [{"risk": "non-deterministic graph traversal", "mitigation": "tie-order verifier cases"}],
    "exit_conditions": [{"name": "verifier", "criteria": "all hidden deterministic cases pass"}],
    "evidence": [{"claim": "benchmark fixture", "source": "local deterministic verifier"}],
    "metadata": {"ambiguity_score": 0.05},
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    target = args.target.resolve()
    if target.exists() and args.force:
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=False)
    (target / "README.md").write_text(README, encoding="utf-8")
    (target / "task.json").write_text(
        json.dumps({"tasks": {"deploy": ["test"], "test": ["build"], "build": []}}, indent=2) + "\n",
        encoding="utf-8",
    )
    agentlas = target / ".agentlas"
    agentlas.mkdir()
    (agentlas / "work-brief.json").write_text(json.dumps(BRIEF, indent=2) + "\n", encoding="utf-8")
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
