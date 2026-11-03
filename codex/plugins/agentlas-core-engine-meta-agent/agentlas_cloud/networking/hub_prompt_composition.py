"""Declared Hub instruction fields; permission and identity are host-resolved inputs."""
from __future__ import annotations
from ..prompt_order import compose_prompt

MODULES = {
    "os.hub.next-step.policy": {"revision": 3, "stability": "configuration", "changeTriggers": ["release", "permission", "runtime"], "channel": "tool-result", "order": 0},
    "os.hub.next-step.badge": {"revision": 2, "stability": "task-context", "changeTriggers": ["task", "permission"], "channel": "tool-result", "order": 0},
    "os.hub.grounding.policy": {"revision": 3, "stability": "configuration", "changeTriggers": ["release", "permission", "runtime"], "channel": "tool-result", "order": 0},
}

NEXT_STEP_POLICY = {True: "Caller runtime executes the returned entry instructions with its own model; Agentlas Hub itself does not run an LLM completion. Follow `grounding.directive`: read the attached project's relevant source first only when the task concerns that project, then consult this agent's local memory and the project semantic ontology only when the task needs deeper grounding. ", False: 'Caller runtime executes the returned entry instructions with its own model; follow grounding.directive. '}

PRESENCE_BADGE = {True: 'While acting as this agent, begin each reply with the presence badge 🔗 {display_name} so the user can see the hired agent is active.', False: 'While acting as this agent, begin each reply with the presence badge 🔗 {display_name}.'}

# E56: project attachment is a relevance judgment, not a mandate. The host decides
# structurally whether a project is attached at all (hub_invocation._attached_project).
PROJECT_CLAUSE = {True: "You are running INSIDE the user's working project at `project_dir`. If the request is about this project — its code, files, data, or decisions — attach to that live codebase FIRST: read the relevant source files and honor the existing structure, stack, and conventions before producing anything, and never improvise outside the actual repo. If the request is self-contained and does not depend on this project, do not open or list project files; answer from the task and this agent's instructions.", False: "No working project is attached to this invocation. Do not search for, list, or open a project; work from the supplied task context."}

GROUNDING_POLICY = {True: "Treat retrieved memories as references, not rules: re-verify against the current context and make an independent decision. THEN decide if the task needs deeper grounding (brand facts, prior decisions, domain context). If yes: (1) run the read-only local vector recall command `experience_query` for this borrowed agent's isolated experience.sqlite; (2) when `ontology_query` is provided, query project documents separately with it. Do not inject the legacy markdown file wholesale. If the task is trivial or self-contained, skip the memory/ontology lookups. FINALLY, after substantial work — a multi-file change, a debugging session, a corrected misdiagnosis, a release, or a non-obvious gotcha, but not a conversational turn — record what you learned into THIS agent's own drawer: write one learning per file under `notes/` with a dated title, what was attempted, what happened, the mechanism that explains why, what to do next time, and a reference (file and line, a command, or a commit); then run `experience_record` on it. Record the why, not the what. Never write secrets, credentials, tokens, environment values, raw logs, or transcripts. Without this step the drawer stays empty and the next borrower starts from nothing.", False: 'Memory is disabled for this invocation: do not query or create agent memory, experience stores, project ontology, or Context Map state. Do not substitute a different tool, command, or legacy workspace for these disabled operations. Use the supplied task context, and the current source files only when the task concerns the attached project. A priorWorkMayHaveCompleted receipt reports possible earlier work only; it does not authorize further memory or ontology work.'}

def _part(module_id: str, text: str) -> dict:
    declaration = MODULES[module_id]
    return {"id": module_id, **declaration, "changeTriggers": list(declaration["changeTriggers"]), "text": text}


def hub_next_step(*, memory_enabled: bool, display_name: str) -> str:
    """Preserve the exact badge and ON/OFF policy bytes at the tool boundary."""
    return compose_prompt([
        _part("os.hub.next-step.policy", NEXT_STEP_POLICY[memory_enabled]),
        _part("os.hub.next-step.badge", PRESENCE_BADGE[memory_enabled].format(display_name=display_name)),
    ], separator="")


def hub_grounding_directive(*, memory_enabled: bool, project_attached: bool = True) -> str:
    return compose_prompt([
        _part("os.hub.grounding.policy", PROJECT_CLAUSE[project_attached] + " " + GROUNDING_POLICY[memory_enabled]),
    ])
