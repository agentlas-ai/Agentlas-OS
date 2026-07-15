#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def invoke(project: Path, payload: object) -> tuple[int, dict[str, object]]:
    with tempfile.TemporaryDirectory(prefix="agentlas-deporder-") as tmp:
        task = Path(tmp) / "task.json"
        result = Path(tmp) / "result.json"
        task.write_text(json.dumps(payload), encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(project / "deporder.py"), "--input", str(task), "--output", str(result)],
            cwd=project,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
        if not result.is_file():
            raise AssertionError(f"result.json missing; exit={completed.returncode}; stderr={completed.stderr}")
        return completed.returncode, json.loads(result.read_text(encoding="utf-8"))


def verify(project: Path) -> None:
    if not (project / "deporder.py").is_file():
        raise AssertionError("deporder.py is missing")

    code, result = invoke(
        project,
        {"tasks": {"deploy": ["test"], "test": ["build"], "build": [], "docs": []}},
    )
    assert code == 0, result
    assert result == {"status": "ok", "order": ["build", "docs", "test", "deploy"]}, result

    code, result = invoke(project, {"tasks": {"z": [], "a": [], "m": []}})
    assert code == 0, result
    assert result == {"status": "ok", "order": ["a", "m", "z"]}, result

    code, result = invoke(project, {"tasks": {"a": ["b"], "b": ["c"], "c": ["a"]}})
    assert code == 2, (code, result)
    assert result.get("status") == "error"
    assert result.get("error") == "cycle"
    assert set(result.get("nodes") or []) == {"a", "b", "c"}

    code, result = invoke(project, {"tasks": {"build": ["missing"]}})
    assert code == 3, (code, result)
    assert result == {"status": "error", "error": "missing_dependency", "task": "build", "dependency": "missing"}

    first = invoke(project, {"tasks": {"d": ["b", "c"], "c": ["a"], "b": ["a"], "a": []}})
    second = invoke(project, {"tasks": {"a": [], "b": ["a"], "c": ["a"], "d": ["c", "b"]}})
    assert first == second == (0, {"status": "ok", "order": ["a", "b", "c", "d"]})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    verify(args.project.resolve())
    print("dependency-cli verifier: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
