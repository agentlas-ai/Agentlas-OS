"""One owner for the words a routing card is allowed to use.

Measured on the live corpus (399 published routing cards, 2026-08-07):

    supported_runtimes    codex-cli 102, agentlas-hub 5   — not in the schema enum
    capabilities_at_risk  shell_execution 22, shell_exec 19, network_access 19,
                          network_fetch 8                  — same concepts, two spellings each
    required_inputs       object 255, string 110           — schema allowed object only
    produces              string 91, object 30             — schema allowed object only

None of those packages is wrong. They were published, they work, and they are
what the generators actually write. What was wrong is a closed enum that had
never been reconciled with the corpus it judges: 295 published packages were
measured against the package contract and 3 passed, and the top blockers were
these four rules rejecting real data.

So the vocabulary lives here, in one place, with three rules:

1. Every concept has ONE canonical spelling.
2. A spelling that is already in the corpus is an ALIAS, never an error. Deleting
   it would silently unpublish work that was accepted at the time.
3. Consumers normalise before comparing. Generators write canonical.

The schemas list canonical ∪ aliases so old cards validate; a gate asserts the
two lists agree, because a vocabulary kept in two places is how this drift
started.
"""

from __future__ import annotations

from typing import Any, Mapping

# ── runtimes ────────────────────────────────────────────────────────────────
CANONICAL_RUNTIMES: tuple[str, ...] = (
    "claude-code",
    "codex",
    "gemini-cli",
    "antigravity",
    "cursor",
    "terminal",
    "agents-md",
    "agentlas-desktop",
    "agentlas-web",
)

RUNTIME_ALIASES: dict[str, str] = {
    # The Codex CLI is the same runtime under the name its own installer uses.
    "codex-cli": "codex",
    "claude-code-cli": "claude-code",
    "gemini": "gemini-cli",
    # The Hub is a distribution surface that packages legitimately declare.
    "agentlas-hub": "agentlas-web",
    "hub": "agentlas-web",
    "desktop": "agentlas-desktop",
    "agentlas-terminal": "terminal",
    # Display names a generator wrote instead of ids. Measured in the corpus.
    "agents.md": "agents-md",
    "claude_code": "claude-code",
    "gemini_cli": "gemini-cli",
}

# ── capabilities a reader should be warned about ────────────────────────────
CANONICAL_RISK_CAPABILITIES: tuple[str, ...] = (
    "file_read",
    "file_write",
    "shell_execution",
    "network_access",
    "cloud_call",
    "external_tool",
    "payment",
    "publish",
    "delete",
    "private_data_export",
)

RISK_CAPABILITY_ALIASES: dict[str, str] = {
    "shell_exec": "shell_execution",
    "shell": "shell_execution",
    "command_execution": "shell_execution",
    "network_fetch": "network_access",
    "network": "network_access",
    "network_call": "network_access",
    "network_egress": "network_access",
    "network_read": "network_access",
    "http_request": "network_access",
    "file_delete": "delete",
    "data_export": "private_data_export",
    "personal_data_exposure": "private_data_export",
    "public_publish": "publish",
    "external_publication": "publish",
    "payment_workflow": "payment",
}

# `capabilities_at_risk` is an OPEN vocabulary, and the corpus settles it: 716
# published cards use about 170 distinct values, most of them domain-specific
# risks their author named — `supplier_confidentiality`, `app_store_connect_write`,
# `deforestation_verification_claims`. An enum can never be right for that, and
# the one that was there rejected 228 cards while telling the reader nothing.
#
# The shape that works is the one Chrome settled on for extension permissions: a
# small closed set the product itself acts on, beside an open namespace anyone
# may write into. CANONICAL_RISK_CAPABILITIES above is the closed part —
# everything the runtime actually gates. Anything else is the author telling a
# reader something true that we simply do not act on, and it is kept verbatim.
RISK_CAPABILITY_PATTERN = r"^[a-z][a-z0-9_]*$|^[A-Za-z][A-Za-z0-9_]*$"


def is_wellformed_risk_capability(value: object) -> bool:
    """True for any token an author may declare, canonical or their own."""
    import re as _re

    return isinstance(value, str) and bool(_re.match(RISK_CAPABILITY_PATTERN, value.strip()))


# ── what a card says it reads and writes ────────────────────────────────────
# Measured across 709 published cards: reads = project 523, "task input only" 12,
# none 10, package 4; writes = project 517, none 22, redacted_preferences_only 5,
# local_ledger_only 4, project_with_approval 1. The schema admitted `project` and
# `none` only, so 26 published cards failed a rule they were published under —
# and a card that says "task input only" is stating something narrower and safer
# than either allowed value, which is the opposite of a defect.
CANONICAL_MEMORY_READS: tuple[str, ...] = ("project", "package", "task", "none")
MEMORY_READS_ALIASES: dict[str, str] = {
    "task_input_only": "task",
    "task_input": "task",
    "input_only": "task",
    "package_only": "package",
}

CANONICAL_MEMORY_WRITES: tuple[str, ...] = (
    "project",
    "project_with_approval",
    "local_ledger_only",
    "redacted_preferences_only",
    "none",
)
MEMORY_WRITES_ALIASES: dict[str, str] = {
    "local_only": "local_ledger_only",
    "preferences_only": "redacted_preferences_only",
    "project_on_approval": "project_with_approval",
}


def normalise_memory_reads(value: Any) -> str | None:
    return _normalise(value, CANONICAL_MEMORY_READS, MEMORY_READS_ALIASES)


def normalise_memory_writes(value: Any) -> str | None:
    return _normalise(value, CANONICAL_MEMORY_WRITES, MEMORY_WRITES_ALIASES)


def schema_memory_reads_values() -> list[str]:
    return sorted({*CANONICAL_MEMORY_READS, *MEMORY_READS_ALIASES})


def schema_memory_writes_values() -> list[str]:
    return sorted({*CANONICAL_MEMORY_WRITES, *MEMORY_WRITES_ALIASES})


def _normalise(value: Any, canonical: tuple[str, ...], aliases: Mapping[str, str]) -> str | None:
    if not isinstance(value, str):
        return None
    token = value.strip().lower().replace(" ", "_")
    token = aliases.get(token, token)
    return token if token in canonical else None


def normalise_runtime(value: Any) -> str | None:
    """Canonical runtime id, or None when the word means nothing here."""
    return _normalise(value, CANONICAL_RUNTIMES, RUNTIME_ALIASES)


def normalise_risk_capability(value: Any) -> str | None:
    return _normalise(value, CANONICAL_RISK_CAPABILITIES, RISK_CAPABILITY_ALIASES)


def normalise_runtimes(values: Any) -> list[str]:
    seen: list[str] = []
    for value in values or []:
        token = normalise_runtime(value)
        if token and token not in seen:
            seen.append(token)
    return seen


def normalise_risk_capabilities(values: Any) -> list[str]:
    seen: list[str] = []
    for value in values or []:
        token = normalise_risk_capability(value)
        if token and token not in seen:
            seen.append(token)
    return seen


# ── card entries that are written either as a phrase or as a record ─────────
def entry_text(entry: Any) -> str:
    """The human phrase of a `required_inputs` / `produces` entry.

    Both shapes ship and both are legitimate: a bare string is the phrase, an
    object carries the phrase plus structure. Anything reading these must accept
    either — a reader that assumed the object shape crashed the market gate on
    exactly the packages a fresh build produces.
    """

    if isinstance(entry, Mapping):
        for key in ("description", "text", "name", "kind", "label"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""
    return str(entry or "").strip()


def schema_runtime_values() -> list[str]:
    """Canonical ∪ aliases, sorted — what the schema enum must contain."""
    return sorted({*CANONICAL_RUNTIMES, *RUNTIME_ALIASES})


def schema_risk_capability_values() -> list[str]:
    return sorted({*CANONICAL_RISK_CAPABILITIES, *RISK_CAPABILITY_ALIASES})
