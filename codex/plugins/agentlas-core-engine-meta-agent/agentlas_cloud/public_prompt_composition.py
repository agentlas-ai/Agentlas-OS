"""Registered descriptions for public MCP parameter schemas."""
from .prompt_order import compose_prompt

DESCRIPTIONS = {'prepare-projection': 'Host LLMs should pass false: executionRoster rows then carry identifiers and digests, with directiveBundle/executionGraph shipped once per contentDigest in bundleContents (projection prepare.v2 — a same-agent-two-slots roster otherwise repeats them byte-identically). Omitted or true returns the legacy self-contained rows — the compatible default, because machine verifiers recompute bundleDigest over whole rows and update independently of this runtime.', 'shortlist': 'Default true: the response carries summary cards (ordinal, name, entityKind, communities, one summary, callable, missingMandatory) instead of full dossiers. Narrow to the candidates worth a closer look, then call workforce.expand_candidates for their full cards and decide from those. Nothing is discarded: the session store keeps the complete menu. Ignored when fullDossier is true. Set false only when a legacy caller needs menu.v2.'}

MODULES = {key: {"id": "os.mcp." + key + "-description", "revision": 2, "stability": "versioned-content", "changeTriggers": ["release", "output-schema"], "channel": "output-schema"} for key in DESCRIPTIONS}

def tool_schema_description(key: str) -> str:
    return compose_prompt([{**MODULES[key], "text": DESCRIPTIONS[key]}])
