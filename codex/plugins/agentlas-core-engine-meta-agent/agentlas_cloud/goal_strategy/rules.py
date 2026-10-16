"""The rules table (contracts/goal-rules.json), loaded once and read-only."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_RELATIVE = Path("contracts") / "goal-rules.json"


class RulesError(RuntimeError):
    pass


def _candidates() -> list[Path]:
    here = Path(__file__).resolve()
    return [here.parents[2] / _RELATIVE, here.parents[1] / _RELATIVE]


@lru_cache(maxsize=1)
def load_rules() -> dict[str, Any]:
    for path in _candidates():
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("schema") != "agentlas.goal-rules.v1":
                raise RulesError(f"unexpected rules schema in {path}")
            return data
    raise RulesError("contracts/goal-rules.json is missing; the goal engine has no rules and refuses to guess them")


def limits() -> dict[str, Any]:
    return load_rules()["limits"]
