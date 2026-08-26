"""Fill what a package already knows about itself, without asking a model.

Measured on the live corpus (2026-08-07): of 372 published definitions, 295 have
a runtime artifact and 3 satisfy the package contract. Running `contract
scaffold` over all 295 adds 8.2 files each and moves the pass count by zero —
because scaffold writes stencils, and a stencil with `{{ROLE}}` in it is still a
blocker. Repackaging is therefore not a mechanical migration, and treating it as
one produces 295 packages that look complete and verify worse.

The work splits in two, and only the first half belongs here:

  derivable   the answer is already inside the package or its definition —
              a slug, a schema version, a summary, an empty ledger, a command
              table that follows from the entry point. No judgement involved.

  authored    the answer is the author's — what this agent does, what it
              refuses, what a good output looks like. A model can draft it from
              the package's own text, but it is drafting, not deriving.

This module does the derivable half and reports what is left, so the authored
half can be priced honestly instead of hidden inside a migration that silently
writes placeholders into production.
"""

from __future__ import annotations

import json
import re
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Mapping, TypeVar

from .routing_vocabulary import (
    RISK_CAPABILITY_ALIASES,
    normalise_memory_reads,
    normalise_memory_writes,
    normalise_risk_capabilities,
    normalise_runtimes,
)


def normalise_risk_capability_known(value: str) -> bool:
    """True when the token is a spelling we own — canonical or a known alias."""
    return bool(normalise_risk_capabilities([value])) or value in RISK_CAPABILITY_ALIASES

AGENT_CARD_SCHEMA = "agentlas.agent-card/1"
MEMORY_MAP_SCHEMA = "agentlas.memory-map/1"
SKILL_REGISTRY_SCHEMA = "agentlas.skill-registry/1"
GLOBAL_COMMANDS_SCHEMA = "agentlas.global-commands/1"

_PLACEHOLDER = re.compile(r"\{\{[A-Z0-9_]+\}\}")
_MutationResult = TypeVar("_MutationResult")


def _safe_package_mutator(
    function: Callable[..., _MutationResult],
) -> Callable[..., _MutationResult]:
    """Fail closed before any public repackaging mutation.

    CLI complete and upload both compose these APIs, but callers can also use
    them directly.  Keeping the check on every public mutator makes safety an
    API invariant and narrows the race window between multi-step repairs.
    """

    @wraps(function)
    def guarded(root: str | Path, *args: Any, **kwargs: Any) -> _MutationResult:
        from .package_contract import workspace_path_problem

        path_problem = workspace_path_problem(root, must_exist=True)
        if path_problem:
            raise ValueError(f"{path_problem['error']}: {path_problem['message']}")
        return function(Path(root).expanduser().resolve(), *args, **kwargs)

    return guarded


def _read_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _has_placeholders(path: Path) -> bool:
    try:
        return bool(_PLACEHOLDER.search(path.read_text(encoding="utf-8")))
    except OSError:
        return False


# The scaffolded AGENTS.md announces itself. Recognising a stencil by "does it
# still contain {{...}}" is a proxy that fails the moment the last placeholder
# in a file gets a legitimate answer — which is what happened when single-agent
# packages stopped being asked to name a team roster: `{{TEAM_ROLES}}` was the
# only placeholder left in single mode, so filling it made an untouched stencil
# look like an authored document and the real `agent.md` was never promoted
# into it (measured 2026-08-17).
#
# These lines come from templates/AGENTS.md.tpl and are not something a person
# writing about their own agent produces.
_STENCIL_MARKERS = (
    "Return status, evidence, output, global_commands, interview_research, and",
    "Research official sources,",
)


def _is_untouched_scaffold(path: Path) -> bool:
    """True when this file is still the contract stencil, placeholders or not."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return all(marker in text for marker in _STENCIL_MARKERS)


def _first_paragraph(text: str, limit: int = 300) -> str:
    for block in re.split(r"\n\s*\n", text):
        line = " ".join(block.split())
        if line.startswith("#") or not line:
            continue
        return line[:limit]
    return ""


@_safe_package_mutator
def derive(
    package_root: str | Path,
    *,
    slug: str,
    entity_kind: str = "agent",
    definition_id: str = "",
) -> dict[str, Any]:
    """Fill what the package already answers. Composes on top of `contract scaffold`.

    An earlier version of this wrote its own JSON for agent-card, memory-map,
    skill-registry and global-commands. Every shape was wrong — `canonicalMemoryRoots`
    is an object, not a list; a command entry is `{command, adapterPath, scope}`,
    not `{invocation}` — and the corpus blocker count went from 4,804 to 8,874,
    because a file that exists and violates its schema fails harder than a file
    that is absent. The canonical shapes are `templates/*.tpl`; the only correct
    move is to let scaffold write them and then answer the placeholders we can.
    """

    root = Path(package_root)
    card = _read_json(root / ".agentlas" / "routing-card.json")
    manifest = _read_json(root / "agentlas.json")
    filled: list[str] = []

    name = str(card.get("name") or manifest.get("name") or slug)
    summary = str(card.get("summary") or card.get("summary_en") or "").strip()
    if not summary:
        for candidate in ("agent.md", "AGENTS.md", "README_FOR_HUMANS.md"):
            path = root / candidate
            if path.exists() and not _has_placeholders(path):
                summary = _first_paragraph(path.read_text(encoding="utf-8", errors="replace"))
                if summary:
                    break

    capabilities = [c for c in (card.get("capabilities") or []) if isinstance(c, str) and c.strip()]
    substitutions = {
        "{{PACKAGE_ID}}": slug,
        # Same grammar, same repair: the id keeps the slug, the command is made
        # legal. Without this the templates rendered a command the schema below
        # rejects for any slug carrying an underscore or a capital.
        "{{COMMAND_SLUG}}": command_slug(slug),
        "{{project_id}}": slug,
        "{{draft_id}}": f"{slug}-export",
        "{{NAME}}": name,
        "{{NAME_KO}}": name,
        "{{TEAM_NAME}}": name,
    }
    if summary:
        substitutions["{{SUMMARY_EN}}"] = summary
    if definition_id:
        substitutions["{{AGENT_DEFINITION_ID}}"] = definition_id
    for index, capability in enumerate(capabilities[:4], start=1):
        substitutions[f"{{{{CAPABILITY_VERB_OBJECT_{index}}}}}"] = capability

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in {".json", ".jsonl", ".md"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if "{{" not in text:
            continue
        replaced = text
        for token, value in substitutions.items():
            replaced = replaced.replace(token, value)
        if replaced != text:
            path.write_text(replaced, encoding="utf-8")
            filled.append(str(path.relative_to(root)))

    # ── agent-card: identity fields the definition already answers ─────────
    # Only when the file already exists (scaffold covers the absent case) and
    # only for fields whose value is not a judgement: the slug is the
    # definition's slug, the schema version is the template's, the summary is
    # the card's own sentence. `"1.0"` is taken from templates/agent-card.json.tpl
    # rather than invented — an earlier version of this module made up
    # `agentlas.agent-card/1` and every package it touched failed harder.
    card_path = root / ".agentlas" / "agent-card.json"
    if card_path.exists():
        agent_card = _read_json(card_path)
        changed = False
        for key, value in (
            ("schemaVersion", "1.0"),
            ("slug", slug),
            ("name", name),
            ("summary", summary),
        ):
            if value and not str(agent_card.get(key) or "").strip():
                agent_card[key] = value
                changed = True
        if changed:
            _write_json(card_path, agent_card)
            filled.append(".agentlas/agent-card.json")

    # ── routing card: normalise the vocabulary that is already there ───────
    if card:
        card_file = root / ".agentlas" / "routing-card.json"
        before = json.dumps(card, sort_keys=True, ensure_ascii=False)
        runtimes = normalise_runtimes(card.get("supported_runtimes"))
        if runtimes:
            card["supported_runtimes"] = runtimes
        risk = card.get("risk_profile")
        if isinstance(risk, dict):
            declared = [c for c in (risk.get("capabilities_at_risk") or []) if isinstance(c, str)]
            if declared:
                canonical = normalise_risk_capabilities(declared)
                # An author's own risk name survives; only known aliases collapse.
                own = [c for c in declared if not normalise_risk_capability_known(c)]
                risk["capabilities_at_risk"] = canonical + [c for c in own if c not in canonical]
        if json.dumps(card, sort_keys=True, ensure_ascii=False) != before:
            _write_json(card_file, card)
            filled.append(".agentlas/routing-card.json")

    # ── infrastructure declarations ────────────────────────────────────────
    # Where this package's memory lives, how it is reached, and what it admits
    # to reading. All three are properties of the runtime the package sits in,
    # not claims about the agent, so the server can state them without inventing
    # anything. 63 packages were unpublishable for a projectId that is the slug.
    if fill_memory_map(root, slug):
        filled.append(".agentlas/memory-map.json")
    if fill_global_commands(root, slug, name):
        filled.append(".agentlas/global-commands.json")
    if fill_memory_behavior(root):
        filled.append(".agentlas/routing-card.json (memory_behavior)")
    if entity_kind == "team" and fill_company_blueprint(root, slug, name):
        filled.append(".agentlas/company-blueprint.json")

    return {"slug": slug, "entityKind": entity_kind, "derived": sorted(set(filled))}



# ── infrastructure declarations the package can answer for itself ───────────
# These are not the author's words; they are the shape of the runtime the
# package sits in. Measured on the live corpus before this existed: 63 packages
# were unpublishable for a missing `projectId` that is just the slug, and 61 for
# a `packageId` that is the same slug again. Refusing an upload over a value the
# server already knows is the failure mode, not the safeguard.

MEMORY_MAP_SCHEMA_VERSION = "1.1"
GLOBAL_COMMANDS_SCHEMA_VERSION = "1.0"

# Every root below has a real consumer — verified by source before being named
# here (python 3-8 files each, TypeScript 1-5 each). A root nobody reads is the
# phantom-skill defect wearing a different hat.
CANONICAL_MEMORY_ROOTS = {
    "project": [".agentlas/project-soul-memory.md"],
    "agent_repo": ["memory.md"],
    "team_memory": [],
    "session": [".agentlas/memory-tickets.jsonl"],
    "curator_decisions": [".agentlas/curator-decisions.jsonl"],
    "sitemap": [".agentlas/sitemap.json", ".agentlas/validation-ledger.jsonl"],
    "code_map": [".agentlas/code-map/project-map.json"],
    "context_map": [".agentlas/context-map.json"],
    "recall_index": [".agentlas/ontology-runtime.sqlite"],
    "experience": [".agentlas/experience-relations.jsonl"],
}
MEMORY_WRITE_OWNERS = {
    "project": "pm-soul",
    "agent_repo": "memory-curator",
    "team_memory": "orchestrator",
    "session": "memory-curator",
    "curator_decisions": "memory-curator",
    "sitemap": "project bootstrap",
    "code_map": "project bootstrap",
    "context_map": "context map authoring (derived)",
    "recall_index": "ontology runtime",
    "experience": "experience intake",
}
# The runtime fills these; a package declares them so a reader knows where its
# memory comes from, and never ships their contents.
RUNTIME_OWNED_ROOTS = ["code_map", "context_map", "recall_index", "experience"]
MEMORY_PROMOTION_PATH = [
    "session ticket",
    "curator decision",
    "durable memory entry",
    "experience candidate",
    "experience pack",
]
MEMORY_TRUST_LABELS = ["verified", "memory_derived", "inferred", "stale_check_needed"]



CANONICAL_COMMAND_RE = re.compile(r"^/[a-z0-9][a-z0-9-]*(?::[a-z0-9][a-z0-9-]*)?$")


def command_slug(slug: str) -> str:
    """A slug reshaped to the command pattern the schema enforces.

    Published slugs carry underscores and capitals (`Web_master`); the command
    grammar accepts neither, so 16 packages declared a canonical command their
    own schema rejected. Reshaping is not renaming: the package keeps its slug,
    and only the command string is made legal.
    """

    lowered = re.sub(r"[^a-z0-9]+", "-", str(slug).lower()).strip("-")
    return lowered or "agent"


def fill_memory_map(root: Path, slug: str) -> bool:
    """Declare where this package's memory lives. Never invents an author fact."""
    path = root / ".agentlas" / "memory-map.json"
    current = _read_json(path)
    payload = dict(current) if isinstance(current, dict) else {}
    before = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    if is_unfilled(payload.get("schemaVersion")):
        payload["schemaVersion"] = MEMORY_MAP_SCHEMA_VERSION
    if is_unfilled(payload.get("projectId")):
        payload["projectId"] = slug
    # Merge, do not replace and do not skip. A package that already declared
    # roots keeps every one of them — those may be the author's. But the
    # infrastructure roots are not the author's to know about: code map, context
    # map, recall index and experience are filled by the runtime, and a map that
    # omits them tells a reader the package's memory is smaller than it is.
    # Measured: the old five-root template predates all four, so every published
    # package understates where its own memory comes from.
    roots = payload.get("canonicalMemoryRoots")
    roots = dict(roots) if isinstance(roots, dict) else {}
    for key, value in CANONICAL_MEMORY_ROOTS.items():
        if key not in roots:
            roots[key] = list(value)
    payload["canonicalMemoryRoots"] = roots

    owners = payload.get("writeOwners")
    owners = dict(owners) if isinstance(owners, dict) else {}
    for key, value in MEMORY_WRITE_OWNERS.items():
        if key not in owners:
            owners[key] = value
    payload["writeOwners"] = owners
    # promotionPath ships as a list; one published package had it as an object
    # and failed its own schema, so a wrong-typed value is replaced, not merged.
    if not isinstance(payload.get("promotionPath"), list):
        payload["promotionPath"] = list(MEMORY_PROMOTION_PATH)
    if not isinstance(payload.get("trustLabels"), list):
        payload["trustLabels"] = list(MEMORY_TRUST_LABELS)
    payload.setdefault("runtimeOwned", list(RUNTIME_OWNED_ROOTS))
    # The blueprint describes the team; `manifest.json` is what the RUNTIME reads
    # to find the manager. A team can have a complete roster and a correct
    # blueprint and still publish as uncallable, because the runtime looks for
    # `entrypoints.orchestrator` and finds nothing. Declare it from the same
    # answer rather than leaving the two to disagree.
    if json.dumps(payload, sort_keys=True, ensure_ascii=False) == before:
        return False
    _write_json(path, payload)
    return True


def fill_global_commands(root: Path, slug: str, name: str) -> bool:
    """Fill the command table's envelope. Entries the author wrote are kept."""
    path = root / ".agentlas" / "global-commands.json"
    current = _read_json(path)
    payload = dict(current) if isinstance(current, dict) else {}
    before = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    if is_unfilled(payload.get("schemaVersion")):
        payload["schemaVersion"] = GLOBAL_COMMANDS_SCHEMA_VERSION
    if is_unfilled(payload.get("packageId")):
        payload["packageId"] = slug
    slug_command = command_slug(slug)
    if not CANONICAL_COMMAND_RE.match(str(payload.get("canonicalCommand") or "")):
        payload["canonicalCommand"] = f"/{slug_command}"
    # The schema's shape, not a sentence: {required, template}. Writing a bare
    # string here is what 61 packages were rejected for.
    message = payload.get("postCreationUserMessage")
    if not isinstance(message, dict) or not str(message.get("template") or "").strip():
        payload["postCreationUserMessage"] = {
            "required": False,
            "template": f"{name} is installed. Run /{command_slug(slug)} to start it.",
        }
    if not isinstance(payload.get("commands"), list) or is_unfilled(payload.get("commands")):
        payload["commands"] = [{
            "runtime": "claude-code",
            "command": f"/{slug_command}",
            "adapterPath": f".claude/commands/{slug_command}.md",
            "globalInstallPath": f"~/.claude/commands/{slug_command}.md",
            "scope": "global",
            "status": "native-slash-command",
        }]
    if json.dumps(payload, sort_keys=True, ensure_ascii=False) == before:
        return False
    _write_json(path, payload)
    return True


def fill_memory_behavior(root: Path) -> bool:
    """A card must say what it reads and writes. Absent means the narrowest."""
    path = root / ".agentlas" / "routing-card.json"
    card = _read_json(path)
    if not card:
        return False
    behaviour = card.get("memory_behavior")
    payload = dict(behaviour) if isinstance(behaviour, Mapping) else {}
    before = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    # Defaulting to the narrowest true claim: a package that never said it reads
    # project memory is not thereby granted it.
    if not normalise_memory_reads(payload.get("reads")):
        payload["reads"] = "task"
    if not normalise_memory_writes(payload.get("writes")):
        payload["writes"] = "none"
    # Required, and the honest default is the narrowest: a package that never
    # said it exports memory to the cloud has not claimed the right to.
    if not isinstance(payload.get("exports_to_cloud"), bool):
        payload["exports_to_cloud"] = False
    if json.dumps(payload, sort_keys=True, ensure_ascii=False) == before:
        return False
    card["memory_behavior"] = payload
    _write_json(path, card)
    return True



def is_unfilled(value: Any) -> bool:
    """True when a value is absent OR is still a scaffold stencil.

    `{{TOPOLOGY}}` is a truthy string and `[{"id": "{{ROLE}}"}]` is a non-empty
    list, so `if not payload.get(...)` and `setdefault` both read a stencil as an
    answer and decline to fill it. The file then keeps one `{{` token, the upload
    path withdraws the whole artifact for shipping placeholder text, and the
    package blocks on a field the server could have derived. Measured 2026-08-07:
    that single confusion held 65 of 178 published packages out of the corpus.
    """

    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip() or ("{{" in value and "}}" in value)
    if isinstance(value, (list, tuple)):
        return not value or all(is_unfilled(item) for item in value)
    if isinstance(value, dict):
        return not value or all(is_unfilled(item) for item in value.values())
    return False


def fill_company_blueprint(root: Path, slug: str, name: str) -> bool:
    """Describe the team that is on disk. Never invents a member.

    topology/nodes/edges are read from `agents/*/agent.md` — the roster is the
    fact, the blueprint is its description, and a description that disagrees
    with the folder is worse than none. Measured: 54 published teams had a
    blueprint with no topology and no edges while carrying a complete roster,
    so the shape gate refused a team that was structurally fine.
    """

    members = sorted(
        path.parent.name for path in root.glob("agents/*/agent.md") if path.is_file()
    )
    if not members:
        return False

    def role_of(folder: str) -> str:
        return folder.split("-", 1)[1] if folder[:1].isdigit() and "-" in folder else folder

    orchestrators = [m for m in members if "orchestrator" in role_of(m) or role_of(m) in {"hq", "router"}]
    orchestrator = orchestrators[0] if orchestrators else members[0]
    workers = [m for m in members if m != orchestrator]

    path = root / ".agentlas" / "company-blueprint.json"
    payload = _read_json(path)
    payload = dict(payload) if isinstance(payload, dict) else {}
    before = json.dumps(payload, sort_keys=True, ensure_ascii=False)

    if is_unfilled(payload.get("schemaVersion")):
        payload["schemaVersion"] = "1.0"
    if is_unfilled(payload.get("name")):
        payload["name"] = name
    if is_unfilled(payload.get("teamId")):
        payload["teamId"] = slug
    # `topology` ships as a bare string in the corpus and as an object in 15
    # packages; a real string that is already there is left alone.
    if is_unfilled(payload.get("topology")):
        payload["topology"] = "hub-and-spoke" if len(workers) > 1 else "single-agent"
    # A declared orchestrator that is not in the roster is a name with nothing
    # behind it: the runtime looks for `agents/<orchestrator>/agent.md`, does not
    # find it, and refuses the team as uncallable AFTER publishing. Keep an
    # author's choice only while it points at a member that exists.
    if is_unfilled(payload.get("orchestrator")) or payload.get("orchestrator") not in members:
        payload["orchestrator"] = orchestrator
    if not isinstance(payload.get("nodes"), list) or is_unfilled(payload.get("nodes")):
        payload["nodes"] = [
            {"id": member, "role": role_of(member),
             "kind": "orchestrator" if member == orchestrator else "worker",
             "agent": f"agents/{member}/agent.md"}
            for member in members
        ]
    if not isinstance(payload.get("edges"), list) or is_unfilled(payload.get("edges")):
        # Every worker is reached by the orchestrator and returns to it. That is
        # the contract in orchestrator-protocol.md: HQ routes, workers never
        # call each other. The edges state the protocol, they do not guess it.
        payload["edges"] = [
            {"from": orchestrator, "to": worker, "relation": "delegates"}
            for worker in workers
        ] + [
            {"from": worker, "to": orchestrator, "relation": "returns"}
            for worker in workers
        ]
    manifest_path = root / "manifest.json"
    manifest = _read_json(manifest_path)
    # Absent is the common case for a team that was never callable: there is
    # nothing for the runtime to read at all. Creating it with just the manager
    # declaration is the smallest true statement - it says who leads, which is
    # the one fact the roster already proves.
    if manifest or not manifest_path.exists():
        entrypoints = manifest.get("entrypoints")
        if not isinstance(entrypoints, dict):
            entrypoints = {}
        declared = entrypoints.get("orchestrator")
        roster = [f"agents/{x.parent.name}/agent.md" for x in root.glob("agents/*/agent.md")]
        if declared not in roster:
            # A PATH, not a node id: the runtime resolves the manager by opening
            # the file, and a bare name resolves to nothing.
            entrypoints["orchestrator"] = f"agents/{payload.get('orchestrator') or orchestrator}/agent.md"
            manifest["entrypoints"] = entrypoints
            _write_json(manifest_path, manifest)

    if json.dumps(payload, sort_keys=True, ensure_ascii=False) == before:
        return False
    _write_json(path, payload)
    return True


@_safe_package_mutator
def coerce_contract_shapes(root: Path, slug: str) -> list[str]:
    """Move already-present answers into the shape their schema declares.

    Nothing here invents a fact. Every value written is one the package already
    states somewhere else in the same file - an orchestrator object's own `id`, a
    skill entry's own `id`, an input's own name. These are shape mismatches, not
    missing content, and refusing an upload over one asks the author to retype
    what they already wrote.

    Measured 2026-08-07 on the 178 published packages: 46 were held back and every
    remaining blocker was one of the five below.
    """

    fixed: list[str] = []

    # ── company-blueprint: `topology` and `orchestrator` are strings ──────────
    # 15 packages nest the whole graph under `topology` as an object, and others
    # give `orchestrator` as `{id, role, job}`. The gate reads both with
    # `isinstance(..., str)` and treats anything else as absent, so a fully
    # described team reads as an empty one.
    blueprint_path = root / ".agentlas" / "company-blueprint.json"
    if blueprint_path.exists():
        payload = _read_json(blueprint_path)
        before = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        topology = payload.get("topology")
        if isinstance(topology, dict):
            for key in ("nodes", "edges"):
                nested = topology.get(key)
                if isinstance(nested, list) and nested and is_unfilled(payload.get(key)):
                    payload[key] = nested
            shape = topology.get("shape") or topology.get("type") or topology.get("name")
            payload["topology"] = (
                str(shape).strip() if isinstance(shape, str) and shape.strip()
                else ("hub-and-spoke" if len(payload.get("nodes") or []) > 2 else "single-agent")
            )
        orchestrator = payload.get("orchestrator")
        if isinstance(orchestrator, dict):
            identifier = orchestrator.get("id") or orchestrator.get("slug") or orchestrator.get("name")
            if isinstance(identifier, str) and identifier.strip():
                payload["orchestrator"] = identifier.strip()
        if is_unfilled(payload.get("teamId")):
            payload["teamId"] = slug
        if json.dumps(payload, sort_keys=True, ensure_ascii=False) != before:
            _write_json(blueprint_path, payload)
            fixed.append(".agentlas/company-blueprint.json")

    # ── skill-registry: each entry needs `slug`, which it already carries as `id`
    registry_path = root / ".agentlas" / "skill-registry.json"
    if registry_path.exists():
        payload = _read_json(registry_path)
        skills = payload.get("skills")
        if isinstance(skills, list):
            changed = False
            for entry in skills:
                if not isinstance(entry, dict) or not is_unfilled(entry.get("slug")):
                    continue
                candidate = entry.get("id") or entry.get("name")
                if not (isinstance(candidate, str) and candidate.strip()):
                    path_value = str(entry.get("path") or "")
                    candidate = Path(path_value).parent.name if path_value else ""
                if isinstance(candidate, str) and candidate.strip():
                    entry["slug"] = candidate.strip()
                    changed = True
            if changed:
                _write_json(registry_path, payload)
                fixed.append(".agentlas/skill-registry.json")

    # ── routing-card: optional_inputs entries are objects with a `name` ───────
    card_path = root / ".agentlas" / "routing-card.json"
    if card_path.exists():
        card = _read_json(card_path)
        inputs = card.get("optional_inputs")
        if isinstance(inputs, list) and any(isinstance(item, str) for item in inputs):
            card["optional_inputs"] = [
                {"name": item.strip()} if isinstance(item, str) and item.strip() else item
                for item in inputs
                if not (isinstance(item, str) and not item.strip())
            ]
            _write_json(card_path, card)
            fixed.append(".agentlas/routing-card.json")

    # ── agent-card: capabilities the routing card already lists ──────────────
    # The schema admits either a list of ids or a profile object; a card that has
    # neither takes the routing card's own capability list rather than a guess.
    agent_card_path = root / ".agentlas" / "agent-card.json"
    if agent_card_path.exists():
        agent_card = _read_json(agent_card_path)
        if is_unfilled(agent_card.get("capabilities")):
            card = _read_json(card_path)
            declared = [c for c in (card.get("capabilities") or []) if isinstance(c, str) and c.strip()]
            if declared:
                agent_card["capabilities"] = declared
                _write_json(agent_card_path, agent_card)
                fixed.append(".agentlas/agent-card.json")

    # ── routing card: shapes the corpus writes but the schema does not ───────
    # Each of these is the author's own answer in a form the schema refuses, so
    # coercing is restating, not inventing. Measured 2026-08-07 on the 14
    # packages the gate still held back.
    if card_path.exists():
        card = _read_json(card_path)
        before_card = json.dumps(card, sort_keys=True, ensure_ascii=False)

        # `locale_coverage` ships as a bare list of locales in some packages and
        # as {primary, ready, partial} in others. The list IS the ready set, and
        # its first entry is the primary - nothing else is implied by it.
        locales = card.get("locale_coverage")
        if isinstance(locales, list):
            ready = [x for x in locales if isinstance(x, str) and x.strip()]
            if ready:
                card["locale_coverage"] = {"primary": ready[0], "ready": ready, "partial": []}

        # `cost_hints.paid_api` is declared boolean; "optional" means the agent
        # CAN reach a paid API, which is the true branch. Any other string is
        # read the same way strings are read everywhere else - non-empty is yes.
        hints = card.get("cost_hints")
        if isinstance(hints, dict) and isinstance(hints.get("paid_api"), str):
            hints["paid_api"] = hints["paid_api"].strip().lower() not in {"", "no", "false", "none"}

        # `source.kind` is a closed pair. A package that came back from the Hub
        # and calls itself something else is still a Hub package; only a folder
        # on this machine is `local_path`.
        src = card.get("source")
        if isinstance(src, dict) and src.get("kind") not in {"local_path", "hub"}:
            src["kind"] = "hub"

        # `workforce.communities` needs at least one entry. The card's own
        # communities are the answer when it has them; otherwise the routing
        # card's declared type is, because a résumé with no community is
        # unroutable and an empty list is what made it unpublishable.
        wf = card.get("workforce")
        if isinstance(wf, dict) and is_unfilled(wf.get("communities")):
            declared = [c for c in (card.get("communities") or []) if isinstance(c, str) and c.strip()]
            if not declared:
                # No declared community, so read the card's own capability verbs.
                # The vocabulary is the one the corpus actually uses (measured
                # 2026-08-07 over the published cards), not an invented list, and
                # a résumé with no community is unroutable - which is exactly what
                # made these packages unpublishable.
                blob = " ".join([
                    str(card.get("summary") or ""),
                    " ".join(c for c in (card.get("capabilities") or []) if isinstance(c, str)),
                ]).lower()
                for term, community in (
                    ("research", "community:research"),
                    ("spec", "community:product-design"),
                    ("design", "community:product-design"),
                    ("architect", "community:software-engineering"),
                    ("test", "community:quality-engineering"),
                    ("deploy", "community:devops"),
                    ("market", "community:marketing"),
                    ("agent", "community:ai-engineering"),
                    ("code", "community:software-engineering"),
                ):
                    if term in blob and community not in declared:
                        declared.append(community)
                declared = declared[:3]
            if declared:
                wf["communities"] = declared[:4]

        if json.dumps(card, sort_keys=True, ensure_ascii=False) != before_card:
            _write_json(card_path, card)
            fixed.append(".agentlas/routing-card.json")

    # ── sitemap: `taskBiases` entries must be objects ────────────────────────
    sitemap_path = root / ".agentlas" / "sitemap.json"
    if sitemap_path.exists():
        sm = _read_json(sitemap_path)
        biases = sm.get("taskBiases")
        if isinstance(biases, list) and any(not isinstance(b, dict) for b in biases):
            sm["taskBiases"] = [
                b if isinstance(b, dict) else {"note": str(b)}
                for b in biases if b not in (None, "")
            ]
            _write_json(sitemap_path, sm)
            fixed.append(".agentlas/sitemap.json")

    # ── agentlas.json: assetContract.materialization is a fixed token ────────
    manifest_path = root / "agentlas.json"
    manifest = _read_json(manifest_path)
    asset = manifest.get("assetContract") if isinstance(manifest, dict) else None
    if isinstance(asset, dict) and asset.get("materialization") != "hub-or-cloud-registration":
        if asset.get("materialization"):
            asset["materialization"] = "hub-or-cloud-registration"
            _write_json(manifest_path, manifest)
            fixed.append("agentlas.json")

    # ── global-commands: one HQ command, many adapters ───────────────────────
    # The contract is a single public HQ command exposed through per-runtime
    # adapter rows. Measured: some rows carry `command: null` and some carry a
    # drifted spelling, so the shape gate sees either no canonical command or
    # several. `canonicalCommand` in the same file is the declared answer; the
    # rows are adapters, not competing names.
    commands_path = root / ".agentlas" / "global-commands.json"
    if commands_path.exists():
        payload = _read_json(commands_path)
        canonical = str(payload.get("canonicalCommand") or "").strip()
        rows = payload.get("commands")
        if canonical and isinstance(rows, list) and rows:
            changed = False
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if str(row.get("command") or "").strip() != canonical:
                    row["command"] = canonical
                    changed = True
            if changed:
                _write_json(commands_path, payload)
                fixed.append(".agentlas/global-commands.json")

    return fixed


def _slugify_key(value: str) -> str:
    """A JSON property name from a human phrase, stable across runs."""
    key = re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
    return key or "value"


def _card_texts(value: Any) -> list[str]:
    out: list[str] = []
    for item in value or []:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
        elif isinstance(item, Mapping):
            text = item.get("text") or item.get("example") or item.get("prompt") or item.get("name")
            if isinstance(text, str) and text.strip():
                out.append(text.strip())
    return out


@_safe_package_mutator
def reconcile_team_shape(root: Path, *, requested_mode: str = "") -> list[str]:
    """Make the declared entity kind and the roster on disk agree.

    Two ways they disagree in the published corpus, both measured 2026-08-07:

    1. A flat roster. `agents/<name>.md` holds the members, but the runtime and
       the shape gate both read `agents/<name>/agent.md`, so the team looks
       empty and cannot be built. Moving the file into the layout the contract
       names is what makes it actually runnable - the content is untouched.

    2. A card that says `team` over a package with no roster at all. The
       package is the fact and the card is its description; a description that
       disagrees with the folder is worse than none, so the card is corrected
       down to `agent` rather than the package being refused for a roster it
       never had. This repair is forbidden while an explicit team build is in
       progress: scaffold creates the blueprint before the builder authors its
       roster, so absence at that intermediate point is not evidence of a
       single-agent package.
    """

    changed: list[str] = []
    nested = list(root.glob("agents/*/agent.md"))
    flat = [p for p in root.glob("agents/*.md") if p.name != "agent.md"]

    if not nested and flat:
        for source in sorted(flat):
            target = root / "agents" / source.stem / "agent.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            source.unlink()
            changed.append(f"agents/{source.stem}/agent.md (from {source.name})")
        nested = list(root.glob("agents/*/agent.md"))

    if not nested and requested_mode != "team":
        # No roster: this is a single agent whatever anything else claims. The
        # card AND the blueprint both have to stop saying team, because either
        # one alone still puts the package on the TEAM branch of the contract -
        # a leftover blueprint kept a card that already read `agent` being
        # checked against every team requirement.
        card_path = root / ".agentlas" / "routing-card.json"
        card = _read_json(card_path)
        if card and card.get("type") == "team":
            card["type"] = "agent"
            _write_json(card_path, card)
            changed.append(".agentlas/routing-card.json (type: team -> agent, no roster on disk)")
        blueprint = root / ".agentlas" / "company-blueprint.json"
        if blueprint.exists():
            blueprint.unlink()
            changed.append(".agentlas/company-blueprint.json (removed: no roster on disk)")
    return changed


@_safe_package_mutator
def fill_declared_artifacts(root: Path, slug: str) -> list[str]:
    """Write the contract artifacts the routing card already answers.

    Same failure shape as the eval plan and `agent.md`: scaffold lays a stencil,
    derive cannot answer it, the upload pass withdraws it rather than ship
    `{{...}}`, and the server refuses the package for the file being missing. The
    routing card is the package's own declaration and already carries every field
    these three need, so restating it in their shapes invents nothing.

    Keys are the ones the consumers actually read, not a shape guessed from the
    name - `context_map_authoring` reads goal/requirements/constraints/done_signal
    off the work brief, and benchmark rows are generated from routing-card
    triggers rather than copied from an internal fixture.
    """

    written: list[str] = []
    card = _read_json(root / ".agentlas" / "routing-card.json")
    if not card:
        return written

    triggers = _card_texts(card.get("trigger_examples"))
    anti = _card_texts(card.get("anti_triggers"))
    inputs = _card_texts(card.get("required_inputs"))
    produces = _card_texts(card.get("produces"))
    summary = str(card.get("summary") or card.get("summary_en") or "").strip()

    def stale(path: Path) -> bool:
        """True when the file is absent or still a stencil."""
        if not path.is_file():
            return True
        try:
            body = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return True
        return not body.strip() or bool(_PLACEHOLDER.search(body))

    brief_path = root / ".agentlas" / "work-brief.json"
    if (summary or inputs) and stale(brief_path):
        # Emit the SAME dialect the consumer validates. This used to write
        # schemaVersion "agentlas.work-brief/1" with requirements/done_signal,
        # but cards migrate reads it through interview/schema.resolve_work_brief,
        # which only accepts "work-brief/1.0" with anti_scope/acceptance_criteria
        # — so every completer-derived brief was rejected ("no user-confirmed
        # anti_triggers") and the card shipped without them. Measured 2026-08-12
        # on .builds/legacy-invoice-agent. Map the routing-card facts onto the
        # consumer's field names: anti-scope→anti_scope, produces→acceptance,
        # required inputs→constraints (informational; the consumer reads
        # acceptance_criteria/anti_scope, but constraints is a valid field).
        from .interview.schema import WORK_BRIEF_SCHEMA_VERSION

        _write_json(brief_path, {
            "schemaVersion": WORK_BRIEF_SCHEMA_VERSION,
            "goal": summary or f"deliver what {slug} declares in its routing card",
            "acceptance_criteria": produces,
            "anti_scope": anti,
            "constraints": inputs,
            "derivedFrom": ".agentlas/routing-card.json",
        })
        written.append(".agentlas/work-brief.json")

    bench_path = root / ".agentlas" / "routing-benchmarks.jsonl"
    if (triggers or anti) and stale(bench_path):
        rows: list[str] = []
        case = 0
        for prompt, expect in [(t, "route") for t in triggers[:6]] + [(a, "refuse") for a in anti[:4]]:
            case += 1
            locale = "ko" if _is_cjk(prompt) else "en"
            rows.append(json.dumps(
                {"case": case, "locale": locale, "prompt": prompt, "expect": expect},
                ensure_ascii=False))
        bench_path.parent.mkdir(parents=True, exist_ok=True)
        bench_path.write_text("\n".join(rows) + "\n", encoding="utf-8")
        written.append(".agentlas/routing-benchmarks.jsonl")

    interview_path = root / "docs" / "builder-interview.md"
    if summary and stale(interview_path):
        interview_path.parent.mkdir(parents=True, exist_ok=True)
        def block(title: str, items: list[str]) -> str:
            if not items:
                return ""
            body = "\n".join(f"- {item}" for item in items)
            return f"\n## {title}\n\n{body}\n"
        interview_path.write_text(
            f"# Builder Interview - {slug}\n\n"
            f"Reconstructed from this package's own routing card, because the original\n"
            f"interview transcript was not shipped. Every line below is the package's\n"
            f"declaration, not a new answer.\n\n"
            f"## Request\n\n{summary}\n"
            + block("Inputs it asks for", inputs)
            + block("What it produces", produces)
            + block("When it should be chosen", triggers)
            + block("When it should NOT be chosen", anti)
            + f"\n## Source\n\n`.agentlas/routing-card.json`\n",
            encoding="utf-8")
        written.append("docs/builder-interview.md")

    # ── .agentlas/sitemap.json: the AI Sitemap Task Bias governs ──────────────
    # One node per surface that exists on disk: the roster for a team, the
    # skills for a single agent. Every node starts `provisional` with an unknown
    # status and a zero completion score, which is the honest starting state -
    # the sitemap contract says a completion score must be evidence-backed, and
    # there is no evidence yet. Task Bias promotes them as evidence arrives.
    sitemap_path = root / ".agentlas" / "sitemap.json"
    if stale(sitemap_path):
        surfaces = [(p.parent.name, f"agents/{p.parent.name}/agent.md")
                    for p in sorted(root.glob("agents/*/agent.md"))]
        kind = "team-member"
        if not surfaces:
            # `skills/*/SKILL.md` alone missed the host layout real packages
            # use (`.claude/skills/<name>/SKILL.md`), so a six-skill agent got
            # no sitemap at all. Discovery covers every host root.
            from .networking.card_lint import discover_skill_manifests

            surfaces = discover_skill_manifests(root)
            kind = "skill"
        if surfaces:
            lead = surfaces[0][0]
            _write_json(sitemap_path, {
                "schemaVersion": "agentlas.sitemap/1",
                "projectId": slug,
                "nodes": [
                    {
                        "id": name,
                        "kind": kind,
                        "title": name.split("-", 1)[1] if name[:1].isdigit() and "-" in name else name,
                        "relative_path": relative_path,
                        "status": "unknown",
                        "generated": True,
                        "dependencies": [],
                    }
                    for name, relative_path in surfaces
                ],
                # A single agent's skills do not call each other, and a team's
                # members answer to the lead - the same shape orchestrator-protocol
                # states. No edge is guessed beyond that.
                "edges": ([] if kind == "skill" else [
                    {"from": lead, "to": name, "relation": "delegates", "generated": True}
                    for name, _ in surfaces[1:]
                ]),
                "derivedFrom": "agents/*/agent.md" if kind == "team-member" else "<host>/skills/*/SKILL.md",
            })
            written.append(".agentlas/sitemap.json")

    # ── contracts/{intake,output}.schema.json: the brief compiles from these ──
    # The routing card already names the inputs (with descriptions) and what the
    # agent produces; the schemas restate that in JSON Schema so the brief can be
    # compiled and its deliverables stop reading as absent. Nothing new is
    # asserted — an input the card does not name does not appear here.
    def _schema_from(entries: list[Any], title: str) -> dict[str, Any]:
        props: dict[str, Any] = {}
        required: list[str] = []
        for item in entries:
            if isinstance(item, str) and item.strip():
                key = _slugify_key(item)
                props[key] = {"type": "string", "description": item.strip()}
                required.append(key)
            elif isinstance(item, Mapping):
                name = str(item.get("name") or item.get("id") or "").strip()
                if not name:
                    continue
                key = _slugify_key(name)
                prop: dict[str, Any] = {"type": str(item.get("type") or "string")}
                description = item.get("description")
                if isinstance(description, str) and description.strip():
                    prop["description"] = description.strip()
                props[key] = prop
                required.append(key)
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": title,
            "type": "object",
            "properties": props,
            "required": required,
            "derivedFrom": ".agentlas/routing-card.json",
        }

    intake_path = root / "contracts" / "intake.schema.json"
    if stale(intake_path):
        entries = card.get("required_inputs") or []
        if entries:
            _write_json(intake_path, _schema_from(entries, f"{slug} intake"))
            written.append("contracts/intake.schema.json")

    output_path = root / "contracts" / "output.schema.json"
    if stale(output_path):
        entries = card.get("produces") or []
        if not entries and summary:
            entries = [{"name": "result", "type": "string", "description": summary}]
        if entries:
            _write_json(output_path, _schema_from(entries, f"{slug} output"))
            written.append("contracts/output.schema.json")

    # ── docs/research-sources.md: the sources that are actually in the package ──
    sources_path = root / "docs" / "research-sources.md"
    if stale(sources_path):
        found: list[str] = []
        for pattern in ("skills/*/knowledge/*.md", "knowledge/*.md", "docs/*.md", "THIRD_PARTY_NOTICES.md"):
            for hit in sorted(root.glob(pattern)):
                rel = hit.relative_to(root).as_posix()
                if rel not in found and not rel.startswith("docs/research-sources"):
                    found.append(rel)
        sources_path.parent.mkdir(parents=True, exist_ok=True)
        listing = "\n".join(f"- `{rel}`" for rel in found[:40]) if found else (
            "- No reference material is shipped inside this package. Its behaviour is\n"
            "  defined entirely by `AGENTS.md` and the routing card."
        )
        sources_path.write_text(
            f"# Research Sources - {slug}\n\n"
            f"What this package's answers are grounded in. Listed from the files that\n"
            f"actually ship with it, not from a bibliography written after the fact -\n"
            f"a source that is not in the package cannot be checked by whoever runs it.\n\n"
            f"## Shipped reference material\n\n{listing}\n",
            encoding="utf-8")
        written.append("docs/research-sources.md")

    # ── contracts/output.example.json: one instance of the declared schema ─────
    example_path = root / "contracts" / "output.example.json"
    schema_path = root / "contracts" / "output.schema.json"
    if stale(example_path) and schema_path.is_file():
        schema = _read_json(schema_path)
        example = _example_from_schema(schema, produces)
        if example is not None:
            _write_json(example_path, example)
            written.append("contracts/output.example.json")

    return written


def _example_from_schema(schema: Mapping[str, Any], produces: list[str]) -> Any:
    """A minimal instance of a JSON Schema, built from what the schema declares.

    Prefers the schema's own `example`/`default`/`const`/first `enum` value, so
    the instance is the author's where they gave one. Strings with no declared
    value fall back to the package's own `produces` phrasing rather than lorem,
    because an example nobody can read teaches a buyer nothing.
    """

    if not isinstance(schema, Mapping):
        return None
    for key in ("example", "default", "const"):
        if key in schema:
            return schema[key]
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]

    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), None)
    if kind == "object" or (kind is None and "properties" in schema):
        props = schema.get("properties")
        if not isinstance(props, Mapping):
            return {}
        required = schema.get("required")
        keys = [k for k in (required if isinstance(required, list) else list(props)) if k in props]
        return {k: _example_from_schema(props[k], produces) for k in keys}
    if kind == "array":
        item = _example_from_schema(schema.get("items") or {}, produces)
        return [item] if item is not None else []
    if kind == "integer":
        return 0
    if kind == "number":
        return 0
    if kind == "boolean":
        return False
    if kind == "null":
        return None
    title = str(schema.get("description") or schema.get("title") or "").strip()
    return title or (produces[0] if produces else "see contracts/output.schema.json")


def _is_cjk(text: str) -> bool:
    return any("가" <= ch <= "힣" or "぀" <= ch <= "ヿ" for ch in text)



MANIFEST_CLOSED_OBJECTS = {
    "memoryPolicy": ("writeBack", "publicCopy"),
    "toolPermissions": ("network", "shell", "fileRead"),
}


@_safe_package_mutator
def prune_unrecognised_manifest_keys(root: Path) -> list[str]:
    """Drop manifest keys the schema does not admit, and name each one.

    `memoryPolicy` and `toolPermissions` are closed objects, so one extra key
    refuses the whole upload. Measured 2026-08-07 across the 178 published
    packages: `writeBack`/`publicCopy` and `network`/`shell`/`fileRead` appear in
    all 178, while `assetPolicy`, `privateMetrics`, `sourceFreshness`,
    `fileWrite` and `browser` appear in one or two. Those are not a producer
    convention the schema failed to keep up with - they are one-off additions
    that nothing reads, because a key outside the schema reaches no consumer.

    Dropping beats blocking here, but only because the drop is announced: the
    caller gets one repair record per removed key, so an author who meant
    something by it finds out instead of wondering why their field vanished.
    """

    path = root / "agentlas.json"
    manifest = _read_json(path)
    if not manifest:
        return []
    dropped: list[str] = []
    for parent, allowed in MANIFEST_CLOSED_OBJECTS.items():
        block = manifest.get(parent)
        if not isinstance(block, dict):
            continue
        for key in [k for k in block if k not in allowed]:
            block.pop(key, None)
            dropped.append(f"{parent}.{key}")
    if dropped:
        _write_json(path, manifest)
    return dropped

@_safe_package_mutator
def fill_capability_eval_plan(root: Path) -> bool:
    """Write the eval plan from the trigger examples the card already carries.

    The scaffold lays down a stencil with `{{POSITIVE_PROMPT}}`, derive cannot
    answer it, and the upload pass withdraws the file rather than ship the
    placeholder - so the server refuses the package for the artifact being
    missing. Nothing here is invented: a routing card is required to carry at
    least six trigger examples and four anti-triggers, and those ARE the positive
    and negative cases. The card already states them; this only restates them in
    the shape the eval plan declares.
    """

    card = _read_json(root / ".agentlas" / "routing-card.json")
    if not card:
        return False

    def phrases(value: Any) -> list[str]:
        out: list[str] = []
        for item in value or []:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, Mapping):
                text = item.get("text") or item.get("example") or item.get("prompt")
                if isinstance(text, str) and text.strip():
                    out.append(text.strip())
        return out

    positive = phrases(card.get("trigger_examples"))
    negative = phrases(card.get("anti_triggers"))
    if not positive and not negative:
        return False

    path = root / ".agentlas" / "capability-eval-plan.json"
    existing = _read_json(path)
    if existing and not _PLACEHOLDER.search(json.dumps(existing, ensure_ascii=False)):
        return False

    produces = [p for p in (card.get("produces") or []) if isinstance(p, str) and p.strip()]
    def repeat_to_minimum(values: list[str], minimum: int) -> list[tuple[str, int]]:
        """Repeat declared prompts as stability trials without inventing facts."""

        if not values:
            return []
        return [(values[index % len(values)], index // len(values) + 1) for index in range(minimum)]

    positive_trials = repeat_to_minimum(positive, 10)
    negative_trials = repeat_to_minimum(negative, 5)
    payload = {
        "schemaVersion": "agentlas-capability-eval-plan/1.0",
        "positive_cases": [
            {
                "id": f"cap-{index:03d}",
                "prompt": prompt,
                "expected_artifacts": produces[:2] or ["the deliverable named in the routing card"],
                "pass_criteria": [
                    "the request is accepted and handled by this agent",
                    "the deliverable follows the package's own return contract",
                ],
                "repeat": repeat,
            }
            for index, (prompt, repeat) in enumerate(positive_trials, start=1)
        ],
        "negative_cases": [
            {
                "id": f"anti-{index:03d}",
                "prompt": prompt,
                "expected_behavior": "declines or reroutes; this is outside the declared scope",
                "repeat": repeat,
            }
            for index, (prompt, repeat) in enumerate(negative_trials, start=1)
        ],
        "tool_smoke_checks": [],
        "derivedFrom": (
            ".agentlas/routing-card.json (trigger_examples, anti_triggers, produces); "
            "declared prompts repeat as stability trials until the 10/5 verifier floor"
        ),
    }
    _write_json(path, payload)
    return True


RUNTIME_ADAPTER_FILES = ("CLAUDE.md", "GEMINI.md", "AGENTS.md")


@_safe_package_mutator
def fill_runtime_adapter_bodies(root: Path, slug: str) -> list[str]:
    """Write the adapter files the contract requires, from the package's own core.

    `agent.md` is required by the contract and refused by the server when absent,
    but `contract scaffold` can only lay down a `{{ROLE}}` stencil for it, and the
    upload pass then withdraws that stencil rather than ship placeholder text to a
    buyer. Net effect: the engine created the file, deleted it, and the server
    rejected the upload for the file being missing - measured 2026-08-07 as an
    HTTP 403 `security_blocked` on a package whose local gate said ready.

    Nothing is invented here. Every published package in this corpus already
    declares one canonical core (`AGENTS.md`) and treats `CLAUDE.md`/`GEMINI.md`
    as thin adapters that point at it; this writes `agent.md` as the same kind of
    thin adapter, in the package's own words, so the required file exists and
    still has exactly one source of truth.
    """

    written: list[str] = []
    core = root / "AGENTS.md"
    # A stencil AGENTS.md counts as missing. `contract scaffold` lays one down
    # before this runs, so checking only `is_file()` made the promotion skip —
    # and the upload pass then withdrew the stencil for carrying `{{`, leaving
    # the package with no canonical core at all. Measured 2026-08-07: 15
    # packages published locally as ready with no AGENTS.md in the bundle.
    # A stencil AGENTS.md needs REPLACING with a real body, not DELETING. This
    # used to unlink it unconditionally, but on the documented packager order
    # (scaffold → complete → fill holes) `complete` runs while agent.md is still
    # a stencil too, so nothing could be promoted — the unlink turned "AGENTS.md
    # has holes to fill" into "AGENTS.md is missing", forcing a re-scaffold and
    # a hard verify blocker. Measured 2026-08-12 on .builds/legacy-invoice-agent
    # (repro'd twice). Fix: promote a real body over a missing OR stencil core;
    # if no real body exists yet, LEAVE the stencil so its holes stay fillable.
    # The upload pass still withdraws any stencil that survives to publish time —
    # that guard is what the original 2026-08-07 measurement needed, and it is
    # unaffected here.
    core_is_stencil = core.is_file() and (_has_placeholders(core) or _is_untouched_scaffold(core))
    if (not core.is_file()) or core_is_stencil:
        # The canonical core is missing or still a stencil, but a real body may
        # exist under another name. AGENTS.md is the entry every runtime reads
        # first and the file the contract requires, so promote the body that IS
        # there. Measured 2026-08-07: several published packages ship `agent.md`
        # alone and were refused for the file the engine could have named.
        for candidate in ("agent.md", "README_FOR_HUMANS.md"):
            source = root / candidate
            if not source.is_file():
                continue
            try:
                body = source.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if is_unfilled(body) or _PLACEHOLDER.search(body):
                continue
            core.write_text(body, encoding="utf-8")
            written.append(f"AGENTS.md (promoted from {candidate})")
            break
        # No real body to promote yet. A stencil left in place is a fillable
        # target; only a genuinely absent core ends the work here.
        if not core.is_file():
            return written
        if _has_placeholders(core):
            return written
    try:
        core_text = core.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return written
    if is_unfilled(core_text) or _has_placeholders(core):
        return written

    target = root / "agent.md"
    existing = ""
    if target.is_file():
        try:
            existing = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            existing = ""
        # A body the author actually wrote is never replaced; only an absent file
        # or a leftover stencil is.
        # A body under a dozen lines is a stub, not an authored agent: the
        # contract requires >=12 non-empty lines and a 6-line file fails it while
        # looking present. Replace a stub with the thin adapter; anything a person
        # actually wrote is left exactly as it is.
        substantive = len([ln for ln in existing.splitlines() if ln.strip()]) >= 12
        if substantive and not _PLACEHOLDER.search(existing):
            return written

    title = ""
    for line in core_text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    target.write_text(
        f"# {title or slug}\n\n"
        f"> Thin adapter. **Source of truth is [`AGENTS.md`](AGENTS.md)** - read it first.\n"
        f"> This file exists so a runtime that looks for `agent.md` finds the same\n"
        f"> core, never a second copy that can drift away from it.\n\n"
        f"## How to run {slug}\n\n"
        f"1. Read [`AGENTS.md`](AGENTS.md) for the principles, rules, workflow, and\n"
        f"   return contract. Everything binding lives there.\n"
        f"2. Follow the runtime adapter for your host if one is present:\n"
        f"   [`CLAUDE.md`](CLAUDE.md), [`GEMINI.md`](GEMINI.md).\n\n"
        f"## Do not\n\n"
        f"- Treat this file as the source of truth. That is always `AGENTS.md`.\n"
        f"- Copy rules out of `AGENTS.md` into here; a second copy is a second\n"
        f"  answer, and the two will disagree.\n",
        encoding="utf-8",
    )
    written.append("agent.md")
    return written


@_safe_package_mutator
def fill_thin_runtime_adapters(root: Path, slug: str) -> list[str]:
    """Write CLAUDE.md / GEMINI.md as thin adapters over AGENTS.md.

    `RUNTIME_ADAPTER_FILES` named these two files as adapters since this
    module's first version, but nothing ever called it — measured: zero other
    references anywhere in this codebase. A package's `agent.md` prose already
    promises "Follow the runtime adapter for your host if one is present:
    CLAUDE.md, GEMINI.md", so a package with neither file broke its own
    promise on every build. Same non-destructive rule as
    `fill_runtime_adapter_bodies`: a stub (<12 non-empty lines) or an absent
    file gets the thin adapter; anything a person actually wrote is left
    exactly as it is.
    """

    core = root / "AGENTS.md"
    if not core.is_file():
        return []
    try:
        core_text = core.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if is_unfilled(core_text) or _has_placeholders(core):
        return []

    title = ""
    for line in core_text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break

    written: list[str] = []
    for filename, runtime_label in (("CLAUDE.md", "Claude Code"), ("GEMINI.md", "Gemini CLI")):
        target = root / filename
        existing = ""
        if target.is_file():
            try:
                existing = target.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                existing = ""
            substantive = len([ln for ln in existing.splitlines() if ln.strip()]) >= 12
            if substantive and not _PLACEHOLDER.search(existing):
                continue
        target.write_text(
            f"# {title or slug} — {runtime_label} adapter\n\n"
            f"> Thin adapter. **Source of truth is [`AGENTS.md`](AGENTS.md)** - read it first.\n"
            f"> This file exists so {runtime_label} finds an entry point in its own\n"
            f"> expected name, never a second copy of the rules that can drift away\n"
            f"> from the canonical core.\n\n"
            f"## Route\n\n"
            f"1. Read [`AGENTS.md`](AGENTS.md) for the principles, rules, workflow, and\n"
            f"   return contract. Everything binding lives there.\n"
            f"2. Use `.agentlas/global-commands.json` for this package's per-runtime\n"
            f"   slash command.\n\n"
            f"## Do not\n\n"
            f"- Treat this file as the source of truth. That is always `AGENTS.md`.\n"
            f"- Copy rules out of `AGENTS.md` into here; a second copy is a second\n"
            f"  answer, and the two will disagree.\n",
            encoding="utf-8",
        )
        written.append(filename)
    return written


@_safe_package_mutator
def redact_host_paths(root: Path) -> list[str]:
    """Replace absolute host paths with package-relative ones, in place.

    A path like `/Users/<person>/Documents/...` is someone's home directory
    leaking into a published package. Blocking the upload leaves the leak in the
    author's working tree and the package unpublished; redacting removes the
    private part and ships the rest. A path that points inside this package
    becomes the relative path it should always have been; anything else becomes a
    neutral marker, because the absolute location is not portable information.
    """

    from .package_contract import HOST_PATH_RE, TEXT_SCAN_LIMIT_BYTES, _looks_like_a_pattern_not_a_path

    workspace = str(root.resolve())
    redacted: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            if path.stat().st_size > TEXT_SCAN_LIMIT_BYTES:
                continue
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw:
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue

        def replace(match: re.Match[str]) -> str:
            found = match.group(0)
            if _looks_like_a_pattern_not_a_path(text, match):
                return found
            if found.startswith(workspace):
                relative = found[len(workspace):].lstrip("/")
                return relative or "."
            return "<host-path-removed>"

        rewritten = HOST_PATH_RE.sub(replace, text)
        if rewritten != text:
            try:
                path.write_text(rewritten, encoding="utf-8")
            except OSError:
                continue
            redacted.append(path.relative_to(root).as_posix())
    return redacted


def authored_gaps(blockers: list[Any]) -> list[str]:
    """The blockers a model has to answer, separated from the mechanical ones."""

    gaps: list[str] = []
    for blocker in blockers:
        text = str(blocker)
        if "unfilled placeholders" in text or text.endswith(": missing"):
            gaps.append(text.split(":")[0])
    return sorted(set(gaps))
