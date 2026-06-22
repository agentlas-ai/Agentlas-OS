"""Agentlas Hub invocation through the Hephaestus Network MCP surface.

Agentlas public agents are BYOM: the Hub returns a runtime bundle and this
runtime executes it. The Hub does not run an LLM completion server-side.
"""

from __future__ import annotations

import json
import re
import uuid
from pathlib import Path
from typing import Any

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
) -> dict[str, Any]:
    """Fetch and prepare a Hub agent runtime bundle, then write an execution receipt."""

    base = Path(home) if home else networking_home()
    local = _local_slug_audit(base)
    results = list(((hub_decision or {}).get("hub") or {}).get("results") or [])
    selected = _select_candidate(results, slug)
    if selected is None and slug:
        selected = _candidate_from_search(slug, slug, base)
    if selected is None:
        selected = _first_callable(results)
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

    selected_slug = str(selected.get("slug") or slug or "")
    selected_norm = _norm_slug(selected_slug)
    # Locally mirrored cards are NOT short-circuited. Every caller — including one
    # whose agent source is in a local private/restricted folder — goes
    # through the SAME server policy: Agentlas OAuth sign-in (handled by
    # call_hub_tool's auto re-auth) plus the server-side credit gate, where
    # calling your OWN cloud package is priced at OWN_CALL_CREDITS. The server is
    # the only authority on entitlement, so a local source copy must never fork
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
                    "detail": _bundle_failure_detail(bundle_response),
                    "hub_response": _bundle_response_summary(bundle_response),
                    "local_slug_audit": local,
                },
            )
        entry = bundle.get("entry") if isinstance(bundle.get("entry"), dict) else {}
        package_hash = bundle.get("packageHash") or (bundle_response.get("version") or {}).get("current")
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
                    "missing_fields": missing,
                    "hub_response": _bundle_response_summary(bundle_response),
                    "local_slug_audit": local,
                },
            )
        needs = _derive_plugin_needs(bundle)
        plugin_resolution = (
            call_hub_tool("agentlas.resolve_plugins", {"needs": needs, "localInventory": local_inventory or []}, home=base)
            if needs
            else {"skipped": "no plugin needs detected"}
        )
        # Every borrowed Hub agent gets its OWN persistent local memory store, so
        # it can reference what it learned on prior runs. Default to a per-agent
        # path under the networking home when the caller does not pin one.
        resolved_memory_root = (
            Path(memory_root).expanduser() if memory_root else _default_memory_root(base, selected_slug)
        )
        memory = _touch_agentlas_memory(
            memory_root=resolved_memory_root,
            slug=selected_slug,
            request=request,
            routing_receipt_id=(hub_decision or {}).get("receipt_id"),
            home=base,
        )
    except HubToolError as exc:
        return _record(
            base,
            {
                "action": "hub_invoke",
                "status": "hub_tool_error",
                "slug": selected_slug,
                "request_hash": _request_hash(request),
                "routing_receipt_id": (hub_decision or {}).get("receipt_id"),
                "detail": str(exc),
                "local_slug_audit": local,
            },
        )

    execution_id = uuid.uuid4().hex[:16]
    agent_id = _hub_agent_id(selected_slug)
    grounding = _grounding_directive(
        agent_id=agent_id,
        memory_root=resolved_memory_root,
        project_dir=Path(project_dir),
        request=request,
    )
    output = {
        "mode": "byom_runtime_bundle",
        "status": "bundle_ready",
        "agent": selected_slug,
        "agent_id": agent_id,
        "agent_name": selected.get("nameEn") or selected.get("name"),
        "package_hash": package_hash,
        "entry_path": entry.get("path"),
        "entry_excerpt": _compact(entry.get("content") or "", 700),
        "prompt_summary": _compact(request, 260),
        "grounding": grounding,
        "next_step": "Caller runtime executes the returned entry instructions with its own model; Agentlas Hub itself does not run an LLM completion. Follow `grounding.directive` to decide whether to consult this agent's local memory and the super ontology — do so only when the task needs grounding.",
    }
    record = {
        "action": "hub_invoke",
        "status": "prepared",
        "execution_id": execution_id,
        "slug": selected_slug,
        "agent_id": agent_id,
        "kind": selected.get("kind"),
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


def _first_callable(results: list[dict[str, Any]]) -> dict[str, Any] | None:
    for item in results:
        if isinstance(item, dict) and (item.get("callable") is True or item.get("kind") == "cloud-callable"):
            return item
    return None


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
_SURFACED_REFUSALS = {"insufficient_credits", "owner_only", "no_cloud_package", "agent_not_found"}


def _server_refusal(response: dict[str, Any]) -> dict[str, Any] | None:
    """Surface a server credit/entitlement refusal as a clean, named status.

    agentlas.get_runtime_bundle RETURNS (does not raise) refusal objects such as
    {"error": "insufficient_credits", "needed", "have", "upgrade", "message"} or
    {"error": "no_cloud_package" | "owner_only" | "agent_not_found" | ...,
     "message"}. Those carry no `bundle`, so without this mapping they would fall
    through to a generic `bundle_unavailable` and hide the real reason (top up /
    sign in / not published). Auth refusals are handled earlier by call_hub_tool's
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
            "fields": {
                "needed": response.get("needed"),
                "have": response.get("have"),
                "upgrade": response.get("upgrade") or "/pricing",
                "message": response.get("message")
                or "Not enough Agentlas credits to call this agent. Top up or upgrade to continue.",
            },
        }
    return {
        "status": error,
        "fields": {
            "server_error": error,
            "message": response.get("message") or error,
        },
    }


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


def _missing_runtime_bundle_fields(bundle: dict[str, Any], entry: dict[str, Any], package_hash: str | None) -> list[str]:
    missing: list[str] = []
    if not package_hash:
        missing.append("packageHash")
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


def _bundle_response_summary(response: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in ("error", "status", "message", "missingFields", "nextAction", "version"):
        if key in response:
            summary[key] = response[key]
    return summary


def _touch_agentlas_memory(
    *,
    memory_root: Path | None,
    slug: str,
    request: str,
    routing_receipt_id: str | None,
    home: Path,
) -> dict[str, Any]:
    if memory_root is None:
        return {"status": "skipped", "reason": "memory_root not provided"}
    memory_root.mkdir(parents=True, exist_ok=True)
    created = _ensure_agentlas_memory_files(memory_root)
    tool_errors: list[str] = []
    status = _optional_hub_memory_tool("agentlas.memory.status", {"memoryRoot": str(memory_root)}, home, tool_errors)
    wizard = _optional_hub_memory_tool(
        "agentlas.wizard.start",
        {"memoryRoot": str(memory_root), "scope": "global"},
        home,
        tool_errors,
    )
    soul = _optional_hub_memory_tool(
        "agentlas.soul.update",
        {
            "memoryRoot": str(memory_root),
            "field": "note",
            "content": f"Hub-only Hephaestus Network invocation prepared for {slug}; routing receipt {routing_receipt_id or 'none'}.",
        },
        home,
        tool_errors,
    )
    if soul:
        _apply_soul_append(memory_root, soul)
    else:
        with open(memory_root / "project-soul-memory.md", "a", encoding="utf-8") as handle:
            handle.write(
                f"\n### note\n- Hub-only Hephaestus Network invocation prepared for {slug}; routing receipt {routing_receipt_id or 'none'}.\n"
            )
    append_jsonl(
        memory_root / "invocation-ledger.jsonl",
        {
            "ts": utc_now(),
            "source": "hephaestus-network",
            "slug": slug,
            "routing_receipt_id": routing_receipt_id,
            "request_hash": _request_hash(request),
            "mode": "hub_byom_bundle",
        },
    )
    return {
        "status": "updated" if not tool_errors else "updated_with_warnings",
        "memory_root": str(memory_root),
        "created": created,
        "status_tool": status,
        "wizard": wizard,
        "soul_update": soul,
        "tool_errors": tool_errors,
    }


def _optional_hub_memory_tool(
    name: str,
    arguments: dict[str, Any],
    home: Path,
    tool_errors: list[str],
) -> dict[str, Any] | None:
    try:
        return call_hub_tool(name, arguments, home=home)
    except HubToolError as exc:
        tool_errors.append(str(exc))
        return None


def _ensure_agentlas_memory_files(root: Path) -> list[str]:
    defaults: dict[str, str] = {
        "memory-map.json": json.dumps(
            {
                "schemaVersion": "1.0",
                "scope": "global",
                "owner": "agentlas-memory",
                "rule": "missing-only bootstrap; no secrets or raw transcripts",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        "memory-tickets.jsonl": "",
        "curator-decisions.jsonl": "",
        "project-soul-memory.md": "# Agentlas Global Soul Memory\n\n",
        "invocation-ledger.jsonl": "",
        "vault-references.json": "{}\n",
    }
    created: list[str] = []
    for name, body in defaults.items():
        path = root / name
        if not path.exists():
            path.write_text(body, encoding="utf-8")
            created.append(str(path))
    return created


def _apply_soul_append(root: Path, soul: dict[str, Any]) -> None:
    rel = str(soul.get("write_to") or "")
    append = str(soul.get("append") or "")
    if not append:
        return
    target = root / "project-soul-memory.md"
    if rel.endswith("project-soul-memory.md"):
        current = target.read_text(encoding="utf-8") if target.exists() else ""
        if append not in current:
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(append)


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


def _default_memory_root(home: Path, slug: str) -> Path:
    return home / "hub-agents" / _norm_slug(slug) / "memory"


def _ontology_db_path(project_dir: Path) -> Path:
    # The project-local "super ontology" the Hephaestus runtime ingests into.
    return project_dir / ".agentlas" / "ontology-runtime.sqlite"


def _grounding_directive(
    *,
    agent_id: str,
    memory_root: Path,
    project_dir: Path,
    request: str,
) -> dict[str, Any]:
    """Tell the executing runtime HOW (and WHEN) to ground a borrowed agent.

    The borrowed agent must reference its own local memory and the super
    ontology ONLY when the task needs grounding (brand facts, prior decisions,
    domain knowledge) — never unconditionally. Retrieval is relevance-gated
    (ontology query returns nothing for unrelated tasks), and this directive
    makes the host LLM the judge of whether to consult at all.
    """

    ontology_db = _ontology_db_path(project_dir)
    return {
        "agent_id": agent_id,
        "memory_root": str(memory_root),
        "ontology_db": str(ontology_db),
        "policy": "selective",
        "directive": (
            "Decide if this task needs grounding (brand facts, prior decisions, domain context). "
            "If yes: (1) read this borrowed agent's local memory under memory_root "
            "(project-soul-memory.md, invocation-ledger.jsonl); (2) query the super ontology with "
            "`ontology_query` below. If the task is trivial or self-contained, skip both. "
            "Do not load all memory/ontology unconditionally — consult only when relevant."
        ),
        "commands": {
            "ontology_query": (
                f"python3 -m ontology query {_shell_quote(_compact(request, 160))} "
                f"--agent {agent_id} --db {_shell_quote(str(ontology_db))}"
            ),
            "memory_read": f"cat {_shell_quote(str(memory_root / 'project-soul-memory.md'))}",
            "working_memory_read": f"python3 -m ontology working-memory read --agent {agent_id} --db {_shell_quote(str(ontology_db))}",
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
