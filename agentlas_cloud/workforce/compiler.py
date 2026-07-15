"""Compile package metadata into an immutable workforce supply profile."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from .contracts import (
    canonical_digest,
    concept_ids,
    content_tokens,
    load_ontology,
    normalized_strings,
    stable_id,
)


COMPILER_VERSION = "awo-compiler:1.0.0"
LEVELS = {"declared", "checked", "demonstrated", "attested"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _assertion(concept: str, source: str, *, level: str = "declared", evidence: list[str] | None = None) -> dict[str, Any]:
    return {
        "concept": concept,
        "level": level if level in LEVELS else "declared",
        "source": source,
        "evidenceRefs": normalized_strings(evidence),
    }


def _unique_assertions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {"declared": 0, "checked": 1, "demonstrated": 2, "attested": 3}
    merged: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row.get("concept") or "")
        if not key:
            continue
        existing = merged.get(key)
        if existing is None or order.get(str(row.get("level")), 0) > order.get(str(existing.get("level")), 0):
            merged[key] = dict(row)
        elif existing:
            existing["evidenceRefs"] = normalized_strings(
                list(existing.get("evidenceRefs") or []) + list(row.get("evidenceRefs") or [])
            )
    return [merged[key] for key in sorted(merged)]


def _ontology_indexes(ontology: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    communities = {
        str(item["id"]): dict(item)
        for item in ontology.get("communities") or []
        if isinstance(item, Mapping) and item.get("id")
    }
    roles = {
        str(item["id"]): dict(item)
        for item in ontology.get("roles") or []
        if isinstance(item, Mapping) and item.get("id")
    }
    return communities, roles


def _infer_roles_and_communities(
    routing_card: Mapping[str, Any],
    manifest: Mapping[str, Any],
    ontology: Mapping[str, Any],
) -> tuple[list[str], list[str], list[str]]:
    communities, roles = _ontology_indexes(ontology)
    workforce = routing_card.get("workforce") if isinstance(routing_card.get("workforce"), Mapping) else {}
    role_ids = set(concept_ids(workforce.get("roles") or routing_card.get("roles"), "role"))
    community_ids = set(concept_ids(workforce.get("communities") or routing_card.get("communities"), "community"))
    capabilities = normalized_strings(routing_card.get("capabilities"))
    for capability in capabilities:
        role_ids.update(ontology.get("capabilityRoleHints", {}).get(capability, []))

    text_values = [
        routing_card.get("name"), routing_card.get("name_ko"), routing_card.get("summary"),
        routing_card.get("summary_ko"), routing_card.get("description"), capabilities,
        manifest.get("skills"),
    ]
    haystack = " ".join(str(value or "") for value in text_values).lower().replace("_", " ").replace("-", " ")
    tokens = content_tokens(*text_values)
    for community_id, community in communities.items():
        labels = [community.get("label"), *(community.get("aliases") or [])]
        if any(
            (
                bool(str(label or "").strip())
                and (
                    str(label).lower() in haystack
                    or bool(content_tokens(label)) and content_tokens(label) <= tokens
                )
            )
            for label in labels
        ):
            community_ids.add(community_id)

    for role_id in list(role_ids):
        role = roles.get(role_id)
        if role:
            community_ids.update(str(item) for item in role.get("communities") or [])
    # Include parents so community queries can start at any level.
    frontier = list(community_ids)
    while frontier:
        current = frontier.pop()
        for parent in communities.get(current, {}).get("parents") or []:
            parent = str(parent)
            if parent not in community_ids:
                community_ids.add(parent)
                frontier.append(parent)

    known = set(communities) | set(roles)
    unmapped = sorted((role_ids | community_ids) - known)
    return sorted(role_ids), sorted(community_ids), unmapped


def _skill_assertions(
    routing_card: Mapping[str, Any],
    manifest: Mapping[str, Any],
    qualification_assertions: list[Mapping[str, Any]],
    ontology: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    skill_aliases = ontology.get("skillAliases") or {}
    capability_rows: list[dict[str, Any]] = []
    skill_rows: list[dict[str, Any]] = []
    for capability in normalized_strings(routing_card.get("capabilities")):
        capability_rows.append(_assertion(stable_id("capability", capability), "routing_card"))
        skill_rows.append(_assertion(str(skill_aliases.get(capability) or stable_id("skill", capability)), "routing_card"))
    for skill in normalized_strings(manifest.get("skills")):
        normalized = str(skill_aliases.get(skill) or skill_aliases.get(skill.lower()) or stable_id("skill", skill))
        skill_rows.append(_assertion(normalized, "manifest"))
    for evidence in qualification_assertions:
        subject = str(evidence.get("subject") or "")
        level = str(evidence.get("level") or "checked")
        refs = normalized_strings(evidence.get("evidenceRefs"))
        if subject.startswith("skill:"):
            skill_rows.append(_assertion(subject, "eval", level=level, evidence=refs))
        elif subject.startswith("capability:"):
            capability_rows.append(_assertion(subject, "eval", level=level, evidence=refs))
    return _unique_assertions(capability_rows), _unique_assertions(skill_rows)


def _tool_assertions(
    routing_card: Mapping[str, Any],
    manifest: Mapping[str, Any],
    mcp_requirements: list[Mapping[str, Any]],
    qualification_assertions: list[Mapping[str, Any]],
    ontology: Mapping[str, Any],
) -> list[dict[str, Any]]:
    aliases = ontology.get("toolCapabilityAliases") or {}
    rows: list[dict[str, Any]] = []
    for requirement in mcp_requirements:
        catalog_id = str(requirement.get("catalogId") or "").strip() or None
        permissions = normalized_strings(requirement.get("permissions"))
        alternatives = concept_ids(requirement.get("alternatives"), "tool")
        for capability in normalized_strings(requirement.get("capabilities")):
            concept = str(aliases.get(capability) or stable_id("tool", capability))
            rows.append(
                {
                    "capability": concept,
                    "catalogId": catalog_id,
                    "required": bool(requirement.get("required")),
                    "permissions": permissions,
                    "alternatives": alternatives,
                    "source": "mcp",
                    "level": "checked" if catalog_id else "declared",
                    "evidenceRefs": normalized_strings(requirement.get("evidenceRefs")),
                }
            )
    for plugin in routing_card.get("required_plugins") or []:
        if not isinstance(plugin, Mapping) or not plugin.get("id"):
            continue
        rows.append(
            {
                "capability": stable_id("tool", plugin["id"]),
                "catalogId": str(plugin["id"]),
                "required": True,
                "permissions": normalized_strings(plugin.get("min_permissions")),
                "alternatives": [],
                "source": "routing_card",
                "level": "declared",
                "evidenceRefs": [],
            }
        )
    tool_permissions = manifest.get("toolPermissions") if isinstance(manifest.get("toolPermissions"), Mapping) else {}
    for capability, value in tool_permissions.items():
        if str(value).lower() == "deny":
            continue
        concept = str(aliases.get(capability) or stable_id("tool", capability))
        rows.append(
            {
                "capability": concept,
                "catalogId": None,
                "required": False,
                "permissions": [str(value)],
                "alternatives": [],
                "source": "manifest",
                "level": "declared",
                "evidenceRefs": [],
            }
        )
    for evidence in qualification_assertions:
        subject = str(evidence.get("subject") or "")
        if not subject.startswith("tool:"):
            continue
        rows.append(
            {
                "capability": subject,
                "catalogId": str(evidence.get("catalogId")) if evidence.get("catalogId") else None,
                "required": False,
                "permissions": normalized_strings(evidence.get("permissions")),
                "alternatives": [],
                "source": "eval",
                "level": str(evidence.get("level") or "checked"),
                "evidenceRefs": normalized_strings(evidence.get("evidenceRefs")),
            }
        )
    level_order = {"declared": 0, "checked": 1, "demonstrated": 2, "attested": 3}
    merged: dict[tuple[str, str | None], dict[str, Any]] = {}
    for row in rows:
        key = (row["capability"], row["catalogId"])
        if key not in merged:
            merged[key] = row
        else:
            merged[key]["required"] = merged[key]["required"] or row["required"]
            merged[key]["permissions"] = normalized_strings(merged[key]["permissions"] + row["permissions"])
            merged[key]["alternatives"] = sorted(set(merged[key]["alternatives"] + row["alternatives"]))
            merged[key]["evidenceRefs"] = normalized_strings(merged[key]["evidenceRefs"] + row["evidenceRefs"])
            if level_order.get(row["level"], 0) > level_order.get(merged[key]["level"], 0):
                merged[key]["level"] = row["level"]
                merged[key]["source"] = row["source"]
    return [merged[key] for key in sorted(merged, key=lambda item: (item[0], item[1] or ""))]


def _artifacts(rows: Any, *, produced: bool) -> list[str]:
    concepts: list[str] = []
    for row in rows or []:
        value = row.get("kind") if isinstance(row, Mapping) else row
        if value:
            concepts.append(stable_id("artifact", value))
    return sorted(set(concepts))


def _authorities(routing_card: Mapping[str, Any], manifest: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    allowed: set[str] = set()
    forbidden: set[str] = set()
    risk = routing_card.get("risk_profile") if isinstance(routing_card.get("risk_profile"), Mapping) else {}
    allowed.update(stable_id("authority", item) for item in normalized_strings(risk.get("capabilities_at_risk")))
    tool_permissions = manifest.get("toolPermissions") if isinstance(manifest.get("toolPermissions"), Mapping) else {}
    mapping = {"network": "network", "shell": "shell", "fileRead": "file-read"}
    for key, label in mapping.items():
        decision = str(tool_permissions.get(key) or "").lower()
        target = stable_id("authority", label)
        if decision == "deny":
            forbidden.add(target)
        elif decision in {"allow", "ask", "manifest-allowlist"}:
            allowed.add(target)
    workforce = routing_card.get("workforce") if isinstance(routing_card.get("workforce"), Mapping) else {}
    allowed.update(concept_ids(workforce.get("authorities"), "authority"))
    forbidden.update(concept_ids(workforce.get("forbiddenAuthorities"), "authority"))
    return sorted(allowed), sorted(forbidden)


def _qualification(
    routing_card: Mapping[str, Any],
    entity_kind: str,
    team_graph: Mapping[str, Any] | None,
    assertions: list[Mapping[str, Any]],
) -> dict[str, Any]:
    normalized: list[dict[str, Any]] = []
    for index, assertion in enumerate(assertions):
        subject = str(assertion.get("subject") or "").strip()
        if not subject:
            continue
        normalized.append(
            {
                "assertionId": str(assertion.get("assertionId") or stable_id("eval", f"{subject}-{index}")),
                "kind": str(assertion.get("kind") or "fixture"),
                "subject": subject,
                "level": str(assertion.get("level") or "checked"),
                "evidenceRefs": normalized_strings(assertion.get("evidenceRefs")),
                "evaluator": str(assertion.get("evaluator"))[:200] if assertion.get("evaluator") else None,
                "evaluatedAt": str(assertion.get("evaluatedAt")) if assertion.get("evaluatedAt") else None,
            }
        )
    required = bool(routing_card.get("id") and routing_card.get("name") and routing_card.get("capabilities"))
    if entity_kind == "team":
        required = required and bool(team_graph and team_graph.get("authoritative") and team_graph.get("manager"))
    return {
        "structuralStatus": "complete" if required else ("partial" if routing_card else "invalid"),
        "assertions": normalized,
    }


def compile_workforce_profile(
    *,
    agent_definition_id: str,
    agent_release_id: str,
    package_hash: str,
    release_version: str | None = None,
    routing_card: Mapping[str, Any],
    manifest: Mapping[str, Any] | None = None,
    mcp_requirements: list[Mapping[str, Any]] | None = None,
    team_graph: Mapping[str, Any] | None = None,
    qualification_assertions: list[Mapping[str, Any]] | None = None,
    operational: Mapping[str, Any] | None = None,
    performance_history: Mapping[str, Any] | None = None,
    ontology: Mapping[str, Any] | None = None,
    compiled_at: str | None = None,
) -> dict[str, Any]:
    """Build a reproducible content profile for one immutable release.

    Invocation history is accepted only as an observation field and is never
    read while compiling semantic membership or qualification.
    """

    manifest = dict(manifest or {})
    ontology = dict(ontology or load_ontology())
    requirements = [dict(item) for item in (mcp_requirements or [])]
    evals = [dict(item) for item in (qualification_assertions or [])]
    operational_input = dict(operational or {})
    entity_kind = str(routing_card.get("type") or "agent")
    if entity_kind not in {"agent", "team", "group"}:
        entity_kind = "agent"

    roles, communities, unmapped = _infer_roles_and_communities(routing_card, manifest, ontology)
    capabilities, skills = _skill_assertions(routing_card, manifest, evals, ontology)
    knowledge = [
        _assertion(concept, "routing_card")
        for concept in concept_ids(
            (routing_card.get("workforce") or {}).get("knowledge")
            if isinstance(routing_card.get("workforce"), Mapping)
            else [],
            "knowledge",
        )
    ]
    tools = _tool_assertions(routing_card, manifest, requirements, evals, ontology)
    authorities, forbidden_authorities = _authorities(routing_card, manifest)
    locale = routing_card.get("locale_coverage") if isinstance(routing_card.get("locale_coverage"), Mapping) else {}
    languages = normalized_strings([locale.get("primary"), *(locale.get("ready") or []), *(locale.get("partial") or [])])
    runtimes = normalized_strings(routing_card.get("supported_runtimes") or manifest.get("requiredRuntime"))
    modalities = normalized_strings((routing_card.get("workforce") or {}).get("modalities") if isinstance(routing_card.get("workforce"), Mapping) else [])
    team_pattern = None
    if team_graph:
        team_pattern = {
            "authoritative": bool(team_graph.get("authoritative")),
            "manager": str(team_graph.get("manager")) if team_graph.get("manager") else None,
            "workers": normalized_strings(team_graph.get("workers")),
            "edges": [
                {
                    "from": str(edge.get("from")),
                    "to": str(edge.get("to")),
                    "relation": str(edge.get("relation")),
                }
                for edge in team_graph.get("edges") or []
                if isinstance(edge, Mapping) and edge.get("from") and edge.get("to") and edge.get("relation")
            ],
        }

    qualification = _qualification(routing_card, entity_kind, team_graph, evals)
    routing_eligible = bool(operational_input.get("routingEligible", qualification["structuralStatus"] != "invalid"))
    semantic = {
        "names": normalized_strings([routing_card.get("name"), routing_card.get("name_ko"), *(routing_card.get("aliases") or [])]),
        "summaries": normalized_strings([routing_card.get("summary"), routing_card.get("summary_ko"), routing_card.get("description")]),
        "communities": communities,
        "roles": roles,
        "capabilities": capabilities,
        "skills": skills,
        "knowledge": _unique_assertions(knowledge),
        "toolCapabilities": tools,
        "consumes": _artifacts(routing_card.get("consumes"), produced=False),
        "produces": _artifacts(routing_card.get("produces"), produced=True),
        "authorities": authorities,
        "forbiddenAuthorities": forbidden_authorities,
        "runtimes": runtimes,
        "languages": languages,
        "modalities": modalities,
        "teamPattern": team_pattern,
        "unmappedConcepts": unmapped,
    }
    content_digest = canonical_digest({"semantic": semantic, "qualification": qualification})
    profile = {
        "schemaVersion": "agentlas.workforce-profile.v1",
        "profileId": stable_id("workforce-profile", agent_release_id),
        "agentDefinitionId": agent_definition_id,
        "agentReleaseId": agent_release_id,
        "releaseVersion": str(release_version or agent_release_id.rsplit(":", 1)[-1]),
        "packageHash": package_hash,
        "entityKind": entity_kind,
        "status": "active",
        "semantic": semantic,
        "qualification": qualification,
        "operational": {
            "callable": bool(operational_input.get("callable")),
            "installable": bool(operational_input.get("installable")),
            "routingEligible": routing_eligible,
            "unavailableReasons": normalized_strings(operational_input.get("unavailableReasons")),
        },
        "provenance": {
            "compilerVersion": COMPILER_VERSION,
            "ontologyVersion": str(ontology.get("ontologyVersion")),
            "sourceRefs": normalized_strings(
                operational_input.get("sourceRefs")
                or [".agentlas/routing-card.json", "agentlas.json", ".agentlas/mcp-policy.json"]
            ),
            "compiledAt": compiled_at or _now(),
            "contentDigest": content_digest,
        },
    }
    if performance_history is not None:
        profile["performanceHistory"] = dict(performance_history)
    return profile
