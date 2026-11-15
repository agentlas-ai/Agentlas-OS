"""Agentlas Hub invocation through the Hephaestus Network MCP surface.

Agentlas public agents are BYOM: the Hub returns a runtime bundle and this
runtime executes it. The Hub does not run an LLM completion server-side.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from .hub_prompt_composition import hub_next_step, hub_grounding_directive

from .bootstrap import append_jsonl, networking_home, utc_now
from .card_store import load_global_cards
from .hub_client import HubToolError, call_hub_tool


def invoke_hub_agent(
    request: str,
    *,
    slug: str | None = None,
    hub_decision: dict[str, Any] | None = None,
    project_dir: Path | str = ".",
    memory_root: Path | str | None = None,
    home: Path | str | None = None,
    version: str = "latest",
    local_inventory: list[str] | None = None,
    expected_entity_kind: str | None = None,
    source: str = "hub",
) -> dict[str, Any]:
    """Fetch an exact Hub agent bundle, or return candidates for host selection."""

    base = Path(home) if home else networking_home()
    local = _local_slug_audit(base)
    results = list(((hub_decision or {}).get("hub") or {}).get("results") or [])
    requested_slug = str(slug or "").strip()
    if not requested_slug:
        candidates = _callable_candidates(results)
        return _record(
            base,
            {
                "action": "hub_invoke",
                "status": "selection_required",
                "request_hash": _request_hash(request),
                "routing_receipt_id": (hub_decision or {}).get("receipt_id"),
                "candidates": candidates,
                "candidate_count": len(candidates),
                "reason": (
                    "Direct Hub invocation requires an exact agent slug selected "
                    "by the host. No candidate was selected and no runtime bundle "
                    "was requested."
                ),
            },
        )

    # (Agentlas 2.0, behind the 2.0 switch): an agent is used only after it is registered on this computer. This is the one funnel of
    # hephaestus_hub_invoke, hephaestus_call / `hephaestus call` / /hep-call, route --auto-run and the Stormbreaker runner.
    from ..agent_usability import agent_usability, refusal_fields

    usability = agent_usability(requested_slug, source=source)
    if not usability["usable"]:
        return {"action": "hub_invoke", "status": usability["code"], **refusal_fields(usability),
                "request_hash": _request_hash(request), "local_slug_audit": local}

    selected = _select_candidate(results, requested_slug)
    if selected is None:
        selected = _candidate_from_search(requested_slug, requested_slug, base)
    if selected is None:
        return _record(
            base,
            {
                "action": "hub_invoke",
                "status": "no_callable_candidate",
                "request_hash": _request_hash(request),
                "routing_receipt_id": (hub_decision or {}).get("receipt_id"),
                "reason": "Hub search returned no cloud-callable agent. Install-only agents require marketplace.get_manifest, not runtime invocation.",
            },
        )

    selected_slug = str(selected.get("slug") or requested_slug)
    selected_norm = _norm_slug(selected_slug)
    # Locally mirrored cards are NOT short-circuited. Every caller — including one
    # whose agent source is in a local private/restricted folder — goes
    # through the SAME server access policy: Agentlas OAuth sign-in (handled by
    # call_hub_tool's auto re-auth). The public Hub no longer sells calls;
    # a local source copy must never fork
    # behavior into a privileged path.

    try:
        bundle_response = call_hub_tool("agentlas.get_runtime_bundle", {"slug": selected_slug, "version": version}, home=base)
        refusal = _server_refusal(bundle_response)
        if refusal is not None:
            return _record(
                base,
                {
                    "action": "hub_invoke",
                    "status": refusal["status"],
                    "slug": selected_slug,
                    "request_hash": _request_hash(request),
                    "routing_receipt_id": (hub_decision or {}).get("receipt_id"),
                    "local_slug_audit": local,
                    "alternates": _alternates(results, selected_slug),
                    **refusal["fields"],
                },
            )
        bundle = bundle_response.get("bundle") if isinstance(bundle_response.get("bundle"), dict) else None
        if bundle is None:
            return _record(
                base,
                {
                    "action": "hub_invoke",
                    "status": "bundle_unavailable",
                    "slug": selected_slug,
                    "request_hash": _request_hash(request),
                    "routing_receipt_id": (hub_decision or {}).get("receipt_id"),
                    # Never bare: the audit measured one live refusal with no
                    # detail at all and none with a way out, while the MCP
                    # prepare surface says both. Same refusal, same words,
                    # every surface.
                    "detail": _bundle_failure_detail(bundle_response)
                    or "the Hub answered without a runnable bundle for this listing",
                    "remediation": (
                        "this listing has no runnable bundle right now — "
                        "call a different agent, or retry later; if it persists, "
                        "the listing itself needs repair on the Hub"
                    ),
                    "hub_response": _bundle_response_summary(bundle_response),
                    "local_slug_audit": local,
                    "alternates": _alternates(results, selected_slug),
                },
            )
        entry = bundle.get("entry") if isinstance(bundle.get("entry"), dict) else {}
        entity_kind = str(bundle.get("entityKind") or "").lower()
        if expected_entity_kind and entity_kind != expected_entity_kind:
            return _record(
                base,
                {
                    "action": "hub_invoke",
                    "status": "entity_kind_mismatch",
                    "slug": selected_slug,
                    "expected_entity_kind": expected_entity_kind,
                    "actual_entity_kind": entity_kind or "unproven",
                    "request_hash": _request_hash(request),
                },
            )
        execution_graph = bundle.get("executionGraph") if isinstance(bundle.get("executionGraph"), dict) else None
        if entity_kind == "team" and execution_graph is None:
            return _record(
                base,
                {
                    "action": "hub_invoke",
                    "status": "team_execution_graph_unavailable",
                    "slug": selected_slug,
                    "request_hash": _request_hash(request),
                },
            )
        package_hash = bundle.get("packageHash") or (bundle_response.get("version") or {}).get("current")
        agent_definition_id = str(
            bundle.get("agentDefinitionId") or bundle.get("agent_definition_id") or ""
        ).strip()
        agent_release_id = str(
            bundle.get("agentReleaseId") or bundle.get("agent_release_id") or ""
        ).strip()
        localized = _runtime_bundle_localized(bundle)
        missing = _missing_runtime_bundle_fields(bundle, entry, package_hash)
        if missing:
            return _record(
                base,
                {
                    "action": "hub_invoke",
                    "status": "bundle_unavailable",
                    "slug": selected_slug,
                    "request_hash": _request_hash(request),
                    "routing_receipt_id": (hub_decision or {}).get("receipt_id"),
                    "detail": "Hub returned an incomplete runtime bundle.",
                    "remediation": (
                        "this listing has no runnable bundle right now — "
                        "call a different agent, or retry later; if it persists, "
                        "the listing itself needs repair on the Hub"
                    ),
                    "missing_fields": missing,
                    "hub_response": _bundle_response_summary(bundle_response),
                    "local_slug_audit": local,
                    "alternates": _alternates(results, selected_slug),
                },
            )
        needs = _derive_plugin_needs(bundle)
        plugin_resolution = (
            call_hub_tool("agentlas.resolve_plugins", {"needs": needs, "localInventory": local_inventory or []}, home=base)
            if needs
            else {"skipped": "no plugin needs detected"}
        )
        # Preserve a legacy server lease receipt for reconciliation if an old
        # deployment still sends one. New free Hub calls create no lease.
        lease = _lease_from_response(bundle_response)
        if lease is not None:
            _cache_lease(base, selected_slug, lease)
        # a Hub agent that is only called (not downloaded) keeps no memory anywhere: no drawer folder, no
        # invocation ledger, no ticket, nothing for the hook to recall later. The `memory` key keeps its old
        # "skipped" shape so callers that read it see no change in structure.
        memory = {"status": "skipped", "reason": "hub_call_only", "feature": "memory-hooks",
            "memory_root": None, "created": [], "status_tool": None, "wizard": None,
            "memory_ticket": None, "tool_errors": []}
    except HubToolError as exc:
        if exc.code == "insufficient_credits":
            return _record(
                base,
                {
                    "action": "hub_invoke",
                    "status": "insufficient_credits",
                    "slug": selected_slug,
                    "request_hash": _request_hash(request),
                    "routing_receipt_id": (hub_decision or {}).get("receipt_id"),
                    "local_slug_audit": local,
                    **_free_hub_credit_refusal(),
                },
            )
        return _record(
            base,
            {
                "action": "hub_invoke",
                "status": "hub_tool_error",
                "slug": selected_slug,
                "request_hash": _request_hash(request),
                "routing_receipt_id": (hub_decision or {}).get("receipt_id"),
                "detail": str(exc),
                # The last neighbour that common rule 3 had not reached: a
                # transient server error (measured: HTTP 502 mid-audit) told
                # the caller what broke and nothing about what to do.
                "remediation": (
                    "the Hub could not complete this call — retry shortly; "
                    "if it persists, check `hephaestus doctor` and your network"
                ),
                "local_slug_audit": local,
            },
        )

    execution_id = uuid.uuid4().hex[:16]
    agent_id = _hub_agent_id(selected_slug)
    agent_display_name = selected.get("nameEn") or selected.get("name")
    from ..feature_preferences import feature_enabled
    # Project reading (code, project ontology) follows the owner's memory-hooks switch; agent memory is never on.
    project_ontology = feature_enabled("memory-hooks")
    if project_ontology:
        grounding = _grounding_project_only(agent_id=agent_id, project_dir=Path(project_dir), request=request)
    else:
        grounding = _grounding_without_memory(agent_id=agent_id, project_dir=Path(project_dir))
    next_step = hub_next_step(project_ontology=project_ontology, display_name=agent_display_name or selected_slug)

    # Composition order: fixed → variable (docs/PROMPT-COMPOSITION-POLICY.md, ledger os.hub.invocation.next-step-and-grounding).
    # The fixed instructions (next_step, grounding) precede the agent's versioned runtime_bundle.
    output = {
        "next_step": next_step,
        "grounding": grounding,
        "mode": "byom_runtime_bundle",
        "status": "bundle_ready",
        "agent": selected_slug,
        "agent_id": agent_id,
        "agent_name": agent_display_name,
        "entity_kind": entity_kind,
        "agent_definition_id": agent_definition_id,
        "agent_release_id": agent_release_id,
        "package_hash": package_hash,
        "localized": localized,
        "entry_path": entry.get("path"),
        "entry_excerpt": _compact(entry.get("content") or "", 700),
        # The executor needs the complete Hub instruction entry, not merely a
        # display excerpt.  This is still a BYOM package payload fetched from
        # the Hub; it contains no local prompt, memory, or project files.
        "runtime_bundle": {
            "agent": selected_slug,
            "entity_kind": entity_kind,
            "agentDefinitionId": agent_definition_id,
            "agentReleaseId": agent_release_id,
            "package_hash": package_hash,
            "localized": localized,
            "entry": {
                "path": entry.get("path"),
                "content": entry.get("content"),
            },
            "tool_permissions": bundle.get("toolPermissions") or {},
            **({"execution_graph": execution_graph} if execution_graph is not None else {}),
        },
        "prompt_summary": _compact(request, 260),
        "lease": lease,
    }
    record = {
        "action": "hub_invoke",
        "status": "prepared",
        "execution_id": execution_id,
        "slug": selected_slug,
        "agent_id": agent_id,
        "kind": selected.get("kind"),
        "entityKind": entity_kind,
        "agentDefinitionId": agent_definition_id,
        "agentReleaseId": agent_release_id,
        "packageHash": package_hash,
        "localized": localized,
        "callable": bool(selected.get("callable", selected.get("kind") == "cloud-callable")),
        "request_hash": _request_hash(request),
        "routing_receipt_id": (hub_decision or {}).get("receipt_id"),
        "routing_action": (hub_decision or {}).get("action"),
        "local_route_used": False,
        "local_slug_present": selected_norm in local["all"],
        "restricted_slug_present": selected_norm in local["restricted"],
        "private_slug_present": selected_norm in local["private"],
        "plugin_needs": needs,
        "plugin_resolution": plugin_resolution,
        "memory": memory,
        "lease": lease,
        "output": output,
    }
    return _record(base, record)


def _candidate_from_search(query: str, slug: str, home: Path) -> dict[str, Any] | None:
    payload = call_hub_tool("marketplace.search_agents", {"q": query}, home=home)
    for item in payload.get("results") or []:
        if isinstance(item, dict) and _norm_slug(str(item.get("slug") or "")) == _norm_slug(slug):
            return item
    return {"slug": slug, "kind": "cloud-callable", "callable": True}


def _select_candidate(results: list[dict[str, Any]], slug: str | None) -> dict[str, Any] | None:
    if not slug:
        return None
    norm = _norm_slug(slug)
    for item in results:
        if isinstance(item, dict) and _norm_slug(str(item.get("slug") or "")) == norm:
            return item
    return None


def _alternates(results: list[dict[str, Any]], failed_slug: str, limit: int = 3) -> list[dict[str, Any]]:
    """Other callable agents from the same search, so a refusal is not a dead end.

    The host chooses; nothing here substitutes an agent. Empty when the search
    that led here offered nothing else.
    """

    failed = _norm_slug(failed_slug)
    picked = [item for item in _callable_candidates(results) if _norm_slug(str(item.get("slug") or "")) != failed]
    return picked[:limit]


def _callable_candidates(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in results
        if isinstance(item, dict)
        and (item.get("callable") is True or item.get("kind") == "cloud-callable")
    ]


def _local_slug_audit(home: Path) -> dict[str, Any]:
    cards, _ = load_global_cards(home)
    buckets: dict[str, set[str]] = {
        "all": set(),
        "private": set(),
        "restricted": set(),
        "plugin": set(),
        "local": set(),
    }
    for card in cards:
        card_id = str(card.get("id") or "")
        tier, _, raw_slug = card_id.partition("/")
        slug = _norm_slug(raw_slug or card_id)
        buckets["all"].add(slug)
        if tier in buckets:
            buckets[tier].add(slug)
    return {key: sorted(value) for key, value in buckets.items()}


# Server errors that mean an entitlement / credit / availability refusal we want
# to surface as a clean, named status. Bundle-validity errors (manifest_invalid,
# version_mismatch) are intentionally NOT here — they keep falling through to the
# bundle_unavailable path with their detail/hub_response intact.
_SURFACED_REFUSALS = {"insufficient_credits", "owner_only", "no_cloud_package", "agent_not_found", "team_execution_graph_unavailable"}


def _free_hub_credit_refusal() -> dict[str, str]:
    """Fail closed on a stale charging server without forwarding its upsell."""
    return {
        "message": "This Hub server requires credits for a public agent call, but public Hub calls are free. The call was stopped.",
        "remediation": "The Hub service must enable free public calls before this agent can be invoked.",
    }


def _server_refusal(response: dict[str, Any]) -> dict[str, Any] | None:
    """Surface a server refusal as a clean, named status.

    agentlas.get_runtime_bundle RETURNS (does not raise) refusal objects such as
    {"error": "insufficient_credits", ...} or
    {"error": "no_cloud_package" | "owner_only" | "agent_not_found" | ...,
     "message"}. Those carry no `bundle`, so without this mapping they would fall
    through to a generic `bundle_unavailable` and hide the real reason. Credit
    refusals keep their machine code but never forward amounts, payment links,
    or stale server text. Auth refusals are handled earlier by call_hub_tool's
    auto re-auth, so they never reach here.
    """
    if not isinstance(response, dict):
        return None
    error = response.get("error")
    if not error:
        return None
    error = str(error)
    if error not in _SURFACED_REFUSALS:
        return None
    if error == "insufficient_credits":
        return {
            "status": "insufficient_credits",
            "fields": _free_hub_credit_refusal(),
        }
    # The server sentence is preserved verbatim (hep-call's contract: relay the
    # server's exact refusal, never substitute). The remedy is added beside it,
    # not instead of it — a statement of fact with no next move is where common
    # rule 3 and that contract only appear to conflict.
    local_remedies = {
        "agent_not_found": (
            "no listing with that slug — check the spelling, or find the right "
            "one with `hephaestus search \"<what you need>\"`"
        ),
        "no_cloud_package": (
            "this listing has no cloud package to call; install it locally, or "
            "ask the publisher to publish a callable release"
        ),
        "owner_only": (
            "this listing is private to its owner — sign in as that workspace, "
            "or pick a public listing"
        ),
        "team_execution_graph_unavailable": (
            "this team ships no execution graph, so it cannot be run as a team; "
            "call one of its agents directly, or ask the publisher to repair it"
        ),
    }
    fields = {
        "server_error": error,
        "message": response.get("message") or error,
    }
    if error in local_remedies:
        fields["remediation"] = local_remedies[error]
    return {"status": error, "fields": fields}


def _derive_plugin_needs(bundle: dict[str, Any]) -> list[str]:
    content = str(((bundle.get("entry") or {}).get("content")) or "").lower()
    permissions = bundle.get("toolPermissions") or {}
    needs: set[str] = set()
    for key, value in permissions.items():
        if value and value != "deny":
            needs.add(str(key))
    for keyword in ("github", "notion", "slack", "websearch", "web search", "analytics", "ga4", "spreadsheet"):
        if keyword in content:
            needs.add(keyword.replace(" ", ""))
    return sorted(needs)


def _runtime_bundle_localized(bundle: dict[str, Any]) -> dict[str, str]:
    raw = bundle.get("localized")
    if not isinstance(raw, dict):
        return {}
    return {
        key: str(raw.get(key) or "").strip()
        for key in ("titleEn", "titleKo", "descriptionEn", "descriptionKo")
    }


def _missing_runtime_bundle_fields(bundle: dict[str, Any], entry: dict[str, Any], package_hash: str | None) -> list[str]:
    missing: list[str] = []
    if not package_hash:
        missing.append("packageHash")
    if not str(bundle.get("agentDefinitionId") or bundle.get("agent_definition_id") or "").strip():
        missing.append("agentDefinitionId")
    if not str(bundle.get("agentReleaseId") or bundle.get("agent_release_id") or "").strip():
        missing.append("agentReleaseId")
    localized = _runtime_bundle_localized(bundle)
    for key in ("titleEn", "titleKo", "descriptionEn", "descriptionKo"):
        if not localized.get(key):
            missing.append(f"localized.{key}")
    if re.search(r"[\uac00-\ud7af]", localized.get("titleEn", "")):
        missing.append("localized.titleEn.validEnglish")
    if re.search(r"[\uac00-\ud7af]", localized.get("descriptionEn", "")):
        missing.append("localized.descriptionEn.validEnglish")
    if not entry.get("path"):
        missing.append("entry.path")
    if not entry.get("content"):
        missing.append("entry.content")
    if not isinstance(bundle.get("toolPermissions"), dict):
        missing.append("toolPermissions")
    return missing


def _bundle_failure_detail(response: dict[str, Any]) -> str:
    error = response.get("error")
    status = response.get("status")
    message = response.get("message")
    missing = response.get("missingFields")
    parts = [str(part) for part in (error, status, message) if part]
    if missing:
        parts.append(f"missingFields={missing}")
    return "; ".join(parts) or "Hub returned no runtime bundle."


def _lease_from_response(response: dict[str, Any]) -> dict[str, Any] | None:
    """Preserve a legacy lease block for reconciliation, if a stale server sends it."""
    lease = response.get("lease")
    if not isinstance(lease, dict):
        return None
    leased_until = lease.get("leasedUntil") or lease.get("leased_until")
    charged = lease.get("chargedCredits")
    if charged is None:
        charged = lease.get("charged")
    return {
        "active": bool(lease.get("active")),
        "leased_until": leased_until if isinstance(leased_until, str) else None,
        "charged_credits": charged if isinstance(charged, (int, float)) else None,
    }


def _cache_lease(base: Path, slug: str, lease: dict[str, Any]) -> None:
    """Best-effort legacy receipt cache; never used to authorize a new call."""
    try:
        path = base / "leases.json"
        data: dict[str, Any] = {}
        if path.is_file():
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        data[slug] = {**lease, "cached_at": utc_now()}
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception:
        # Never block an invocation over a display cache.
        pass


def _bundle_response_summary(response: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("error", "status", "message", "missingFields", "nextAction", "version"):
        if key in response:
            summary[key] = response[key]
    return summary


def _record(home: Path, record: dict[str, Any]) -> dict[str, Any]:
    record = {"ts": utc_now(), **record}
    append_jsonl(home / "ledgers" / "executions.jsonl", record)
    return record


def _request_hash(request: str) -> str:
    import hashlib

    return hashlib.sha256(request.encode("utf-8")).hexdigest()[:24]


def _norm_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _hub_agent_id(slug: str) -> str:
    # Stable per-agent id that also keys this borrowed agent's ontology working
    # memory, so memory persists across invocations of the same Hub agent.
    return f"hub:{_norm_slug(slug)}"


def _ontology_db_path(project_dir: Path) -> Path:
    # The project-local semantic ontology database the Hephaestus runtime ingests into.
    return project_dir / ".agentlas" / "ontology-runtime.sqlite"


def _attached_project(project_dir: Path | str) -> Path | None:
    """A working project the invocation may attach to, or None.

    The home folder and a filesystem root are where a host starts when no
    project is open; they are never a project, so no path, ontology or listing
    command for them is handed to the borrowed agent (E56).
    """
    try:
        project = Path(project_dir).expanduser().resolve()
    except (OSError, RuntimeError):
        return None
    if not project.is_dir() or project == Path(project.anchor):
        return None
    try:
        if project == Path.home().resolve():
            return None
    except (OSError, RuntimeError):
        pass
    return project


def _grounding_without_memory(*, agent_id: str, project_dir: Path) -> dict[str, Any]:
    """Memory-hooks switched off by the owner: no memory, no ontology, no Context Map state."""
    project = _attached_project(project_dir)
    return {
        "policy": "attach_codebase_when_relevant" if project else "no_project",
        "directive": hub_grounding_directive(project_ontology=False, project_attached=project is not None),
        "agent_id": agent_id, "project_dir": str(project) if project else None, "memory_root": None,
        "ontology_db": None, "experience_db": None,
        "commands": {"project_overview": f"ls -la {_shell_quote(str(project))}" if project else None,
                     "ontology_query": None, "experience_query": None, "memory_read": None,
                     "working_memory_read": None, "experience_record": None},
    }


def _grounding_project_only(*, agent_id: str, project_dir: Path, request: str) -> dict[str, Any]:
    """Grounding for a Hub agent that is only called.

    The agent keeps no memory of its own, so there is no drawer, no experience store and nothing to record into.
    What stays is reading the PROJECT: the live codebase and the project's semantic ontology (read-only query).
    """

    project = _attached_project(project_dir)
    ontology_db = _ontology_db_path(project) if project else None
    # The host can execute this from any project/CWD. Rely on the versioned runtime installed by Agentlas OS, never an
    # ambient PYTHONPATH or a source checkout that happens to make `python3 -m ontology` importable.
    from ..feature_preferences import _DESKTOP_HOSTS
    if os.environ.get("AGENTLAS_HOST_RUNTIME", "").strip().lower() in _DESKTOP_HOSTS:
        ontology_cli = '"${HOME}/.agentlas/runtime/current/bin/ontology"'
    else:
        ontology_cli = _shell_quote(str(Path(__file__).resolve().parents[2] / "bin" / "ontology"))
    return {
        "policy": "attach_codebase_when_relevant_then_project_ontology" if project else "no_project",
        "directive": hub_grounding_directive(project_ontology=True, project_attached=project is not None),
        "agent_id": agent_id,
        "project_dir": str(project) if project else None,
        "memory_root": None,
        "ontology_db": str(ontology_db) if ontology_db else None,
        "experience_db": None,
        "commands": {
            "project_overview": f"ls -la {_shell_quote(str(project))}" if project else None,
            "ontology_query": (
                f"{ontology_cli} --db {_shell_quote(str(ontology_db))} "
                f"query {_shell_quote(_compact(request, 160))}"
            ) if ontology_db else None,
            "experience_query": None, "memory_read": None, "working_memory_read": None, "experience_record": None,
        },
    }


def _shell_quote(value: str) -> str:
    if re.fullmatch(r"[A-Za-z0-9_./:@-]+", value or ""):
        return value
    return "'" + (value or "").replace("'", "'\\''") + "'"


def _compact(value: str, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"
