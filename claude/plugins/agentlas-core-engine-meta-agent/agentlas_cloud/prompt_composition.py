"""Declared OS prompt modules, composed from host-resolved feature state.

Feature state is configuration, not evidence of a completed side effect.
"""
from __future__ import annotations
from .prompt_order import compose_prompt

MEMORY_EVENT_EXAMPLE = '{"schema_version":"agentlas.memory-ticket.v1","turn_summary":"one safe sentence in English"}'

WORKFORCE = (
    "Agentlas Workforce continuity is mandatory, not an optional goal mode. "
    "At the start of every nontrivial project turn call workforce.goal_context "
    "for the current project. Reuse an active exact roster plus local skills "
    "when sufficient; recruit only a real gap. workforce.prepare_execution "
    "requires projectDir and automatically binds every successful preparation, "
    "even when the user never said goal. Keep the roster until explicit whole-goal "
    "completion/cancellation through workforce.complete_goal. Free Hub calls do not "
    "need a paid lease; expiry of a legacy lease never ends the binding."
)

CONTEXT_PRIVACY = (
    "Work that changes no source code (reports, posts, notes, data files, browsing, "
    "publishing) does not use the Context Map. Context Map source paths and contents "
    "stay project-local and must never be sent in Network or Cloud discovery requests."
)

ACCESS_NOTICE_MENU = (
    "Before telling the user a capability is unavailable, call agentlas_resolve_plugins "
    "with the capability you need: the Agentlas Hub catalog covers integrations that are "
    "not installed on this machine yet, and a tool missing from this session is not the "
    "same as a tool that does not exist."
)

STANDALONE_ACCESS_MENU = (
    "Integration discovery is optional in standalone sessions. When the user asks to "
    "explore or find an integration, you may call agentlas_resolve_plugins with that "
    "requested capability. Do not automatically query the Hub catalog during ordinary "
    "work or solely before explaining a missing session tool. Describe observed session "
    "availability narrowly: not installed here does not mean no such integration exists. "
    "Do not claim that you searched the catalog unless you actually called the tool."
)

ACCESS_FINAL = (
    "Never install or enable a tool on your own — show the slug, what it will be allowed "
    "to do, and whether it needs credentials, then let the user decide. If nothing covers "
    "the need, say so plainly; do not describe a tool call you did not make."
)

ONE_IDENTITY = """# {name} — Agentlas One enabled

`agentlas-one on` owns this block and `off` removes it. Do not edit it directly.

## Identity
You are the owner's persistent personal agent operating the Agentlas engine, not a generic chat assistant.
Keep the same identity across sessions, projects, and hosts. Do not repeat introductions.
Begin user-facing answers with `**[{name}]**`; omit the prefix from intermediate tool updates."""

ONE_OPERATING = """## Operating rules
1. **Reuse the roster first.** Reuse the bound roster before recruiting; recruitment is additive.
2. **Prevent dead ends.**
   1. Use machine-readable markers for causes; never infer a cause by parsing prose.
   2. Keep terminal actions unconditional; close, stop, and cancel must not depend on another state.
   3. Re-read state after acting. If evidence is unchanged, say so explicitly.
3. **Never claim an uncalled tool was called.** Query before claiming that something is absent.
4. Before irreversible actions such as deletion, sending, payment, or publication, prefer live measurement over memory. Ask when verification is unavailable.
5. When memories conflict, expose the conflict instead of silently choosing one.
6. When blocked, exhaust remaining means in order. If all fail, report exactly where and why using machine evidence."""

ONE_COMMUNICATION = """## Communication
Lead with the outcome. State what is unknown, and support limitations with evidence. Use plain but precise language without presenting inference as fact."""

CONTEXT_ON = (
    "When a task changes source code, call context.slice once the task is "
    "resolved, context.impact before editing a source file, and context.verify "
    "before declaring completion, accounting for every affected file."
)

# Stable registry also supports private ledger validation before every branch runs.
MODULES = {
    "os.mcp.workforce-continuity": ("fixed-policy", ("release",), "system"),
    "os.mcp.workforce-entry": ("configuration", ("runtime", "profile"), "system"),
    "os.mcp.context-map-locality": ("fixed-policy", ("release",), "system"),
    "os.mcp.context-map-menu": ("configuration", ("runtime", "permission", "capability-inventory"), "system"),
    "os.mcp.capability-access-notice": ("fixed-policy", ("release",), "system"),
    "os.mcp.standalone-capability-access-menu": ("configuration", ("release", "runtime", "permission", "capability-inventory"), "system"),
    "os.mcp.final-tool-boundary": ("final-boundary", ("release", "permission"), "system"),
    "os.mcp.failure.continuity": ("fixed-policy", ("release",), "tool-result"),
    "os.mcp.failure.updater-state": ("configuration", ("runtime", "permission"), "tool-result"),
    "os.mcp.failure.diagnostic": ("turn-context", ("validation-result",), "tool-result"),
    "os.one.frame": ("fixed-policy", ("release",), "system"),
    "os.one.operating-rules": ("fixed-policy", ("release",), "system"),
    "os.one.communication": ("fixed-policy", ("release",), "system"),
    "os.one.identity": ("configuration", ("release", "owner-profile", "runtime"), "system"),
    "os.one.capability-menu": ("configuration", ("runtime", "permission", "capability-inventory"), "system"),
    "os.one.memory-output-contract": ("configuration", ("runtime", "permission"), "system"),
    "os.one.frame-end": ("final-boundary", ("release",), "system"),
}


def _part(module_id: str, text: str, order: int = 0) -> dict:
    stability, triggers, channel = MODULES[module_id]
    return {"id": module_id, "revision": 2 if module_id == "os.one.capability-menu" else 1, "stability": stability,
            "changeTriggers": list(triggers), "channel": channel, "order": order, "text": text}


def mcp_initialize_instructions(*, context_map_enabled: bool, desktop_runtime: bool = False) -> str:
    entry = (
        "Agentlas Workforce continuity is mandatory, not an optional goal mode. "
        "At the start of every nontrivial project turn call workforce.goal_context for the current project."
        if desktop_runtime else
        "workforce-entry: For explicitly requested Network/Goal work or an existing active bound goal, "
        "call workforce.goal_context and preserve Workforce continuity. Ordinary standalone turns do not "
        "automatically initiate Network/Goal work, recruit a roster, or create project state. "
        "A not_initialized context result means no local binding store was opened; it is not goal completion or evidence of executed work. "
        "Explicit Network/Goal requests retain the full goal, roster, tree, and agent execution workflow."
    )
    parts = [
        _part("os.mcp.workforce-continuity", WORKFORCE[WORKFORCE.index("Reuse an active"):]),
        _part("os.mcp.workforce-entry", entry),
        _part("os.mcp.context-map-locality", CONTEXT_PRIVACY, 10),
        (_part("os.mcp.capability-access-notice", ACCESS_NOTICE_MENU, 20) if desktop_runtime else
         _part("os.mcp.standalone-capability-access-menu", STANDALONE_ACCESS_MENU, 20)),
    ]
    if context_map_enabled:
        parts.append(_part("os.mcp.context-map-menu", CONTEXT_ON))
    parts.append(_part("os.mcp.final-tool-boundary", ACCESS_FINAL))
    return compose_prompt(parts)


def mcp_initialize_instructions_for_runtime(home=None) -> str:
    from .feature_preferences import feature_enabled
    import os
    from .feature_preferences import _DESKTOP_HOSTS
    return mcp_initialize_instructions(
        context_map_enabled=feature_enabled("context-map", home=home, mcp=True),
        desktop_runtime=os.environ.get("AGENTLAS_HOST_RUNTIME", "").strip().lower() in _DESKTOP_HOSTS,
    )


def tool_failure_text(*, name: str, exc: BaseException, auto_update_enabled: bool) -> str:
    parts = []
    missing = getattr(exc, "name", None) if isinstance(exc, ModuleNotFoundError) else None
    if isinstance(missing, str) and (missing == "agentlas_cloud" or missing.startswith("agentlas_cloud.")):
        parts.append(_part("os.mcp.failure.continuity",
            "runtime: This is an incomplete Agentlas runtime install. A missing module affects tools that depend on it; "
            "this failure alone does not establish that other tools or Workforce are unavailable. Continue using unaffected tools."))
        if auto_update_enabled:
            state = ("auto-update: enabled; update execution, scheduling, and completion status: unknown. "
                     "This failure provides no accepted or completed update receipt. "
                     "Enabled is permission, not a job receipt. Whether an update will happen is unknown: "
                     "do not claim either that it will happen or that it will not happen.")
        else:
            state = ("auto-update: disabled. No automatic update is authorized by this host setting. "
                     "An owner-initiated update or reinstall can repair an incomplete runtime; this failure did not perform either action.")
        parts.append(_part("os.mcp.failure.updater-state", state))
    parts.append(_part("os.mcp.failure.diagnostic", f"hephaestus tool {name} failed: {type(exc).__name__}: {exc}"))
    return compose_prompt(parts)


def one_directive(*, name: str, memory_enabled: bool, context_map_enabled: bool, standalone_runtime: bool = False) -> str:
    capabilities = [
        "## Available capabilities — inspect these before claiming a limitation",
        "| Need | Capability |", "|---|---|",
        "| Expertise | `workforce.goal_context` -> reuse -> search only genuine gaps -> validate -> prepare |",
        "| Public experts | `marketplace.search_agents`, `hephaestus_hub_invoke`, `/hep-hub` |",
        "| Owner assets | `cargo.*`, `/hep-cloud` |",
        "| Apparently missing tool | `agentlas_resolve_plugins`; uninstalled does not mean nonexistent, and installation is the user's decision |",
        "| Browser work | `/hep-browser` |",
        "| New capability | `/hep-build` -> `/hep-upload` |",
    ]
    if context_map_enabled:
        capabilities.append("| Code location and impact | `context_locate`, `context_slice`, `context_impact`, `context_verify` |")
    if memory_enabled:
        capabilities.append("| Memory | `agentlas_memory_preflight`, `agentlas_memory_ticket`; never write durable memory directly |")
    if standalone_runtime:
        capabilities = [line.replace(", `/hep-hub`", "").replace(", `/hep-cloud`", "")
                        for line in capabilities
                        if "| Browser work |" not in line and "| New capability |" not in line]
        capabilities.extend(["", "Use the connected tools' descriptions and operating skills actually exposed in this session.",
            "One preference alone does not connect the core tools or install an operations skill. Verify availability before use.",
            "Do not load legacy One workspace procedures or assume slash aliases are registered."])
    else:
        capabilities.extend(["", "Operating procedures for these capabilities live in `~/.agentlas/one/skills/agentlas-operations/SKILL.md`",
            "(tool index: `INDEX.md` beside it, generated from the live registry). Follow it for staffing, automation,",
            "asset" + (", and memory work" if memory_enabled else " work") + " instead of improvising."])
    if memory_enabled:
        memory = (
            "## Memory events\nEnd every normal answer with `## Memory Events` and one fenced JSON block, nothing else:\n`" +
            MEMORY_EVENT_EXAMPLE + "`\nWrite `turn_summary` in English whatever language the conversation uses. "
            "Never include secrets, credentials, raw transcripts, or host-absolute paths.\n"
            "receipt: Emitting an envelope requests processing; it is not proof of storage. "
            "Only an actual host acceptance receipt supports a claim that memory was saved or recorded."
        )
    else:
        memory = (
            "## Memory events\nmemory: disabled for this host. Do not emit a Memory Events envelope or invoke memory tools. "
            "A request to remember something cannot be saved while this setting is disabled. "
            "Do not promise to remember or persist it."
        )
    return compose_prompt([
        _part("os.one.frame", "<!-- AGENTLAS-ONE:BEGIN -->", -100),
        _part("os.one.operating-rules", ONE_OPERATING),
        _part("os.one.communication", ONE_COMMUNICATION, 10),
        _part("os.one.identity", ONE_IDENTITY.format(name=name)),
        _part("os.one.capability-menu", "\n".join(capabilities), 10),
        _part("os.one.memory-output-contract", memory, 20),
        _part("os.one.frame-end", "<!-- AGENTLAS-ONE:END -->"),
    ], separator="\n\n") + "\n"


def one_directive_for_runtime(*, name: str, home=None) -> str:
    import os
    from .feature_preferences import feature_enabled, _DESKTOP_HOSTS
    return one_directive(name=name,
        standalone_runtime=os.environ.get("AGENTLAS_HOST_RUNTIME", "").strip().lower() not in _DESKTOP_HOSTS,
        memory_enabled=feature_enabled("memory-hooks", home=home),
        context_map_enabled=feature_enabled("context-map", home=home, mcp=True))
