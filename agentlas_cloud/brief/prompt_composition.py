"""Declared explanatory text for deterministic brief provenance."""
from ..prompt_order import compose_prompt

REFUSAL_GAP_MODULE = {"id": "os.brief.refusal-gap-reason", "revision": 2,
    "stability": "fixed-policy", "changeTriggers": ["release"], "channel": "tool-result"}


def refusal_gap_reason() -> str:
    return compose_prompt([{**REFUSAL_GAP_MODULE,
        "text": "anti_triggers are not refusals without an explicit refusal reason"}])
