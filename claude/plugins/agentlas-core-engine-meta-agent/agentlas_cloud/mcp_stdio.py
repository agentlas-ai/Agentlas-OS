"""Local stdio MCP server for the Hephaestus Network router.

Exposes the Hub-first Hephaestus Network router as MCP tools so any MCP-capable
harness (OpenCode, Goose, Crush, Hermes Agent, Cursor, Codex, Gemini CLI, and
Ollama-launched harnesses running local models such as Gemma or DeepSeek) can
call routing without a runtime-specific command surface.

Transport: newline-delimited JSON-RPC 2.0 on stdin/stdout (MCP stdio). No
third-party dependencies. Public Network calls skip local private cards by
default; local routing requires the explicit `allow_local_routing` debug flag.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Mapping

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "hephaestus-network", "version": "1.1.38"}
MODEL_ALLOCATION_POLICY_ENV = "AGENTLAS_MODEL_ALLOCATION_POLICY_JSON"
_HOST_MODEL_POLICY_FIELDS = frozenset({
    "pinnedModelId",
    "maxTier",
    "maxEffort",
    "requiredCapabilities",
})


def _host_model_allocation_policy() -> dict[str, Any]:
    """Read operator cost guardrails from the MCP process boundary.

    Tool arguments are untrusted workload input. They may carry a parent-AI
    allocation decision, but they must never raise the host's model/effort
    ceiling or forge a user pin. Operators configure this JSON in the MCP
    server launch environment instead.
    """

    raw = os.environ.get(MODEL_ALLOCATION_POLICY_ENV, "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        raise ValueError("invalid host model allocation policy JSON") from None
    if not isinstance(parsed, Mapping):
        raise ValueError("host model allocation policy must be an object")
    policy = {key: parsed[key] for key in _HOST_MODEL_POLICY_FIELDS if key in parsed}
    if "pinnedModelId" in policy and (
        not isinstance(policy["pinnedModelId"], str)
        or not policy["pinnedModelId"].strip()
        or len(policy["pinnedModelId"]) > 255
    ):
        raise ValueError("host pinnedModelId is invalid")
    if policy.get("maxTier") not in {None, "economy", "balanced", "frontier"}:
        raise ValueError("host maxTier is invalid")
    if policy.get("maxEffort") not in {None, "none", "minimal", "low", "medium", "high", "xhigh", "max"}:
        raise ValueError("host maxEffort is invalid")
    capabilities = policy.get("requiredCapabilities")
    if capabilities is not None and (
        not isinstance(capabilities, list)
        or len(capabilities) > 32
        or any(not isinstance(item, str) or not item.strip() or len(item) > 80 for item in capabilities)
    ):
        raise ValueError("host requiredCapabilities is invalid")
    return policy

TOOLS: list[dict[str, Any]] = [
    {
        "name": "hephaestus_route",
        "description": (
            "Route a natural-language request through the Hephaestus Network "
            "Hub-first router. Returns a JSON decision (route, clarify, "
            "pipeline, hub_fallback, propose_new, or refuse) with a receipt_id. "
            "The router does not execute tools; the caller runtime owns execution safety."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "The natural-language request to route."},
                "project_dir": {"type": "string", "description": "Project directory for context (default: cwd)."},
                "approve_hub": {
                    "type": "boolean",
                    "description": "Backward-compatible no-op; Hub lookup already sends redacted keywords only.",
                },
                "hub_only": {
                    "type": "boolean",
                    "description": "Skip local routing cards and search Agentlas Hub only. This is the default unless allow_local_routing is true.",
                },
                "allow_local_routing": {
                    "type": "boolean",
                    "description": "Operator/debug escape hatch. When false or omitted, local private/plugin cards are ignored.",
                },
                "caller_id": {
                    "type": "string",
                    "description": "Optional caller agent id for Agent Ontology deny/require gating.",
                },
                "caller": {
                    "type": "string",
                    "description": "Alias for caller_id, matching the CLI --caller option.",
                },
                "session_inventory": {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {"type": "string"},
                            {
                                "type": "object",
                                "properties": {
                                    "session_id": {"type": "string"},
                                    "provider": {"type": "string"},
                                    "model": {"type": "string"},
                                    "trust": {"type": "string"},
                                    "capabilities": {"type": "array", "items": {"type": "string"}},
                                    "max_parallel": {"type": "integer"},
                                    "tier": {"type": "string"},
                                    "supported_efforts": {"type": "array", "items": {"type": "string"}},
                                    "context_window": {"type": "integer"},
                                    "supports_tools": {"type": "boolean"},
                                    "supports_multimodal": {"type": "boolean"},
                                },
                                "additionalProperties": True,
                            },
                        ]
                    },
                    "description": "Optional host-advertised active sessions (Codex, Claude, GLM, DeepSeek, local models) for Stormbreaker pipeline scheduling.",
                },
                "model_allocation_decisions": {
                    "type": "object",
                    "additionalProperties": {"type": "object"},
                    "description": "Parent/leader AI decisions keyed by packet id, phase, or stage order. Raw task text must not be included.",
                },
            },
            "required": ["request"],
        },
    },
    {
        "name": "hephaestus_cloud_search",
        "description": (
            "Search ONLY the signed-in user's OWN Agentlas cloud packages (보관함) "
            "and return a JSON decision with a receipt_id. This is the owner-scoped "
            "leg of the three-scope model: it skips local cards and the public "
            "marketplace, querying the Hub with the owner filter (cargo.*). The "
            "user's own cloud packages are restorable/owned by them and call-priced "
            "at a flat 1 credit. The router does not execute tools; the caller "
            "runtime owns execution safety."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "The natural-language request to match against the owner's own cloud packages."},
                "project_dir": {"type": "string", "description": "Project directory for context (default: cwd)."},
            },
            "required": ["request"],
        },
    },
    {
        "name": "hephaestus_search",
        "description": (
            "Power-user search: return top Agentlas Cloud (owner packages) and "
            "public Hub candidates side by side without invoking any agent. Use "
            "when the user asks to find agents and compare choices."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "Search request, for example: 시장 리포트 쓸 에이전트 찾아줘."},
                "project_dir": {"type": "string", "description": "Project directory for context (default: cwd)."},
                "limit": {"type": "integer", "description": "Candidates per section. Default 10."},
            },
            "required": ["request"],
        },
    },
    {
        "name": "hephaestus_call",
        "description": (
            "Prepare explicitly named Agentlas Hub/cloud agents. This fetches BYOM "
            "runtime bundles and writes receipts; the caller runtime still runs "
            "the actual LLM/tool work."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agents": {
                    "oneOf": [
                        {"type": "string"},
                        {"type": "array", "items": {"type": "string"}},
                    ],
                    "description": "Comma list or array of slugs. Prefix with cloud: for owner packages or hub: for public Hub.",
                },
                "context": {"type": "string", "description": "Task context passed to each named agent."},
                "project_dir": {"type": "string", "description": "Project directory for context (default: cwd)."},
                "version": {"type": "string", "description": "Hub package hash or latest."},
                "local_inventory": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Installed plugin slugs/names to pass to agentlas.resolve_plugins. Use [] to avoid local plugin matches.",
                },
            },
            "required": ["agents", "context"],
        },
    },
    {
        "name": "hephaestus_network_status",
        "description": "Report Hephaestus Network state: card counts, benchmark state, auto-routing gate.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "agentlas_authenticate",
        "description": (
            "Open the user's browser for a one-time Agentlas Google/sign-in flow, "
            "store the local signed-in state under ~/.agentlas/auth, and reuse it "
            "for Claude Code, Codex, Gemini, and other Hephaestus Hub calls."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "base_url": {"type": "string", "description": "Agentlas Hub base URL. Defaults to https://agentlas.cloud."},
                "open_browser": {
                    "type": "boolean",
                    "description": "Open the default browser automatically. Defaults to true.",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Seconds to wait for browser sign-in. Defaults to 180.",
                },
            },
        },
    },
    {
        "name": "agentlas_auth_status",
        "description": "Report whether this machine already has a reusable Agentlas sign-in for Hephaestus Hub calls.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "base_url": {"type": "string", "description": "Agentlas Hub base URL. Defaults to https://agentlas.cloud."}
            },
        },
    },
    {
        "name": "hephaestus_hub_invoke",
        "description": (
            "Invoke an Agentlas Hub public agent through the Hephaestus Network surface. "
            "This skips local routing, calls Hub MCP marketplace.search_agents and "
            "agentlas.get_runtime_bundle, resolves Hub plugins, touches Agentlas memory "
            "when memory_root is provided, and writes an execution receipt. Agentlas "
            "public agents are BYOM: the Hub returns a runtime bundle; it does not run an LLM."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "Prompt/task for the Hub agent."},
                "slug": {"type": "string", "description": "Optional exact Hub agent slug. If omitted, first callable Hub result is used."},
                "project_dir": {"type": "string", "description": "Project directory for context (default: cwd)."},
                "memory_root": {"type": "string", "description": "Optional Agentlas memory root to bootstrap/update missing-only."},
                "approve_hub": {
                    "type": "boolean",
                    "description": "Backward-compatible no-op; host runtimes gate actual execution.",
                },
                "version": {"type": "string", "description": "Hub package hash or latest."},
                "local_inventory": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Installed plugin slugs/names to pass to agentlas.resolve_plugins. Use [] to avoid local plugin matches.",
                },
            },
            "required": ["request"],
        },
    },
    {
        "name": "workforce.search_candidates",
        "description": (
            "Search the Hub Agent Workforce Ontology with a redacted structured work order. "
            "Returns a broad content-only eligible candidate set; it never selects a team. "
            "The calling top-level LLM must author the work order and make the staffing decision."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workOrder": {"type": "object", "description": "agentlas.workforce-work-order.v1"},
                "expandSlotIds": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["workOrder"],
        },
    },
    {
        "name": "workforce.validate_selection",
        "description": (
            "Validate a team selected by the calling host LLM against the exact Hub candidate set. "
            "This tool cannot select, rerank, or silently substitute agents."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workOrder": {"type": "object"},
                "candidateSet": {"type": "object"},
                "selection": {"type": "object", "description": "agentlas.workforce-selection.v1 authored by the host LLM"},
            },
            "required": ["workOrder", "candidateSet", "selection"],
        },
    },
    {
        "name": "workforce.prepare_execution",
        "description": (
            "Fetch BYOM runtime bundles only for an already accepted exact roster. "
            "Pins agentReleaseId, packageHash, and contentDigest and fails closed on drift; "
            "it never chooses replacements."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "workOrder": {"type": "object"},
                "candidateSet": {"type": "object"},
                "selection": {"type": "object"},
                "validationReceipt": {"type": "object"},
            },
            "required": ["workOrder", "candidateSet", "selection", "validationReceipt"],
        },
    },
]


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    from .networking import init_networking, network_status, route_request
    from .networking.bootstrap import networking_home

    host_model_policy: dict[str, Any] = {}
    if name == "hephaestus_route":
        try:
            host_model_policy = _host_model_allocation_policy()
        except ValueError:
            return {
                "action": "refuse",
                "status": "invalid_host_model_allocation_policy",
                "detail": f"Fix {MODEL_ALLOCATION_POLICY_ENV} in the MCP server launch environment.",
            }

    bootstrap: dict[str, Any] | None = None
    if name in {
        "hephaestus_route",
        "hephaestus_cloud_search",
        "hephaestus_search",
        "hephaestus_call",
        "hephaestus_hub_invoke",
    }:
        from .project_bootstrap import auto_bootstrap_enabled, maybe_ensure_project

        bootstrap = maybe_ensure_project(
            arguments.get("project_dir", "."),
            reason=f"mcp:{name}",
            enabled=auto_bootstrap_enabled(mcp=True),
            allow_unmarked_current_root=True,
        )

    if bootstrap is not None:
        status = bootstrap.get("status")
        safe_warning = (
            status == "privacy_warning"
            and bootstrap.get("privacyBlockInstalled") is True
            and bootstrap.get("privateModeCompliant") is True
            and int(bootstrap.get("missingCount") or 0) == 0
            and int(bootstrap.get("permissionIssueCount") or 0) == 0
        )
        if status != "active" and not safe_warning:
            detail = bootstrap.get("detail") or "project_bootstrap_incomplete"
            return {
                "action": "project_bootstrap",
                "status": "blocked",
                "detail": detail,
                "project_bootstrap": bootstrap,
            }

    def with_bootstrap(result: dict[str, Any]) -> dict[str, Any]:
        if bootstrap is not None:
            result["project_bootstrap"] = bootstrap
        return result

    init_networking(networking_home())
    if name in {
        "workforce.search_candidates",
        "workforce.validate_selection",
        "workforce.prepare_execution",
    }:
        from .networking.hub_client import call_hub_tool

        # The local MCP surface is a transparent authenticated bridge.  The
        # Hub owns catalog state; Core must not reconstruct a different team or
        # fall back to lexical cards if the workforce service refuses a call.
        return call_hub_tool(name, arguments)
    if name == "hephaestus_route":
        allow_local_routing = bool(arguments.get("allow_local_routing", False))
        hub_only = True if not allow_local_routing else bool(arguments.get("hub_only", False))
        if hub_only:
            from .networking.gui_shortcut import open_local_gui_shortcut

            shortcut = open_local_gui_shortcut(
                arguments["request"],
                no_open=os.environ.get("HEPHAESTUS_NETWORK_GUI_NO_OPEN") == "1",
            )
            if shortcut.get("action") != "no_local_gui_shortcut":
                return with_bootstrap(shortcut)
        return with_bootstrap(route_request(
            arguments["request"],
            project_dir=arguments.get("project_dir", "."),
            runtime="mcp",
            use_hub=True,
            hub_approved=bool(arguments.get("approve_hub", False)),
            hub_only=hub_only,
            caller_id=arguments.get("caller_id") or arguments.get("caller"),
            session_inventory=arguments.get("session_inventory") or None,
            model_allocation_decisions=arguments.get("model_allocation_decisions") or None,
            # Cost ceilings and pins are host policy, never caller-controlled
            # MCP arguments. Unknown legacy arguments are intentionally ignored.
            model_allocation_policy=host_model_policy or None,
        ))
    if name == "hephaestus_cloud_search":
        # Owner-scoped: scope="cloud" implies hub_only inside route_request and
        # queries only the signed-in user's OWN cloud packages (보관함).
        return with_bootstrap(route_request(
            arguments["request"],
            project_dir=arguments.get("project_dir", "."),
            runtime="mcp",
            use_hub=True,
            hub_approved=False,
            scope="cloud",
        ))
    if name == "hephaestus_search":
        from .networking import search_agents

        return with_bootstrap(search_agents(
            arguments["request"],
            project_dir=arguments.get("project_dir", "."),
            runtime="mcp",
            limit=int(arguments.get("limit") or 10),
        ))
    if name == "hephaestus_call":
        from .networking import call_agents

        return with_bootstrap(call_agents(
            arguments.get("agents") or [],
            str(arguments.get("context") or ""),
            project_dir=arguments.get("project_dir", "."),
            runtime="mcp",
            version=str(arguments.get("version") or "latest"),
            local_inventory=arguments.get("local_inventory") or [],
        ))
    if name == "hephaestus_hub_invoke":
        from .networking.hub_invocation import invoke_hub_agent

        decision = route_request(
            arguments["request"],
            project_dir=arguments.get("project_dir", "."),
            runtime="mcp",
            use_hub=True,
            hub_approved=bool(arguments.get("approve_hub", False)),
            hub_only=True,
        )
        if decision.get("action") != "hub_candidates" and not arguments.get("slug"):
            return with_bootstrap({
                "action": "hub_invoke",
                "status": "routing_not_ready",
                "routing_decision": decision,
                "detail": "Hub invocation requires a Hub-approved hub_only route that returns hub_candidates.",
            })
        return with_bootstrap(invoke_hub_agent(
            arguments["request"],
            slug=arguments.get("slug"),
            hub_decision=decision,
            project_dir=arguments.get("project_dir", "."),
            memory_root=arguments.get("memory_root"),
            version=str(arguments.get("version") or "latest"),
            local_inventory=arguments.get("local_inventory") or [],
        ))
    if name == "hephaestus_network_status":
        return network_status()
    if name == "agentlas_auth_status":
        from .auth import auth_status

        return auth_status(arguments.get("base_url"))
    if name == "agentlas_authenticate":
        from .auth import AgentlasAuthError, ensure_access_token, token_path

        base_url = arguments.get("base_url")
        try:
            token = ensure_access_token(
                str(base_url) if base_url else None,
                interactive=True,
                open_browser=arguments.get("open_browser", True) is not False,
                timeout_seconds=int(arguments.get("timeout_seconds") or 180),
            )
        except AgentlasAuthError as exc:
            return {
                "action": "agentlas_authenticate",
                "status": "error",
                "error": str(exc),
                "token_path": str(token_path(str(base_url) if base_url else None)),
            }
        return {
            "action": "agentlas_authenticate",
            "status": "authenticated" if token else "signed_out",
            "token_path": str(token_path(str(base_url) if base_url else None)),
        }
    raise KeyError(name)


def _handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method", "")
    msg_id = message.get("id")
    params = message.get("params") or {}

    if msg_id is None:
        return None  # notification (e.g. notifications/initialized) — no response

    if method == "initialize":
        return _result(
            msg_id,
            {
                "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        )
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments") or {}
        try:
            payload = _call_tool(name, arguments)
        except KeyError:
            return _error(msg_id, -32602, f"unknown tool: {name}")
        except Exception as exc:  # surfaced as a tool error, not a protocol error
            return _result(
                msg_id,
                {"content": [{"type": "text", "text": f"hephaestus tool failed: {exc}"}], "isError": True},
            )
        return _result(
            msg_id,
            {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, sort_keys=True)}]},
        )
    return _error(msg_id, -32601, f"method not found: {method}")


def _result(msg_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def serve(stdin=None, stdout=None) -> int:
    # Starting the local Agentlas MCP server is the host's explicit plugin
    # boundary. Default its project bootstrap gate on while preserving an
    # operator's explicit 0/false override. maybe_ensure_project still confines
    # writes to the MCP process workspace and refuses unsafe home/root targets.
    from .project_bootstrap import MCP_AUTO_BOOTSTRAP_ENV

    os.environ.setdefault(MCP_AUTO_BOOTSTRAP_ENV, "1")
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            response: dict[str, Any] | None = _error(None, -32700, "parse error")
        else:
            response = _handle(message)
        if response is not None:
            stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0
