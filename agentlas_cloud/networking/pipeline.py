"""Pipeline routing (a Hephaestus Network 2.0 feature, not a new version).

Chains multiple teams into one deliverable — e.g. PRD team → dev HQ → QA —
via the produces/consumes artifact contracts on routing cards. The planner is
deterministic (no LLM) and returns a PLAN only; the calling runtime executes
stages one by one with its own execution permissions and records artifacts under
<project>/.agentlas/pipeline/<pipeline_id>/.

Over-decomposition guard: a pipeline is only planned when the request is
plan-anchored (a planning intent plus at least one more stage intent) or uses
an explicit end-to-end phrase. Single-intent requests never get decomposed.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from pathlib import Path

from .execution_fabric import build_execution_fabric
from ..interview.schema import brief_packet_context, brief_scope_text

_LOGGER = logging.getLogger(__name__)

# Canonical stage order. Each stage: (key, intent keywords, artifact kind).
STAGE_DEFS: list[tuple[str, set[str], str]] = [
    (
        "plan",
        {"기획", "요구사항", "요건", "스펙", "prd", "spec", "requirements", "plan", "product plan"},
        "prd",
    ),
    (
        "build",
        {"구현", "개발", "제작", "빌드", "코딩", "웹앱", "사이트", "build", "implement", "develop", "code it", "app", "website"},
        "codebase_change",
    ),
    (
        "verify",
        {"검증", "테스트", "점검", "검수", "qa", "test", "verify", "validate"},
        "qa_report",
    ),
]

TARGET_ARTIFACT_TERMS: list[tuple[str, set[str]]] = [
    ("release-bundle", {"release", "릴리즈", "배포", "publish", "ship", "출시"}),
    ("single-agent-package", {"agent", "에이전트", "worker", "single-agent"}),
    ("team-package", {"team", "팀", "multi-agent", "멀티"}),
]


def detect_stages(
    query: str,
    extra_text: str | None = None,
    scoped: bool = False,
) -> list[tuple[str, str]]:
    """Return [(stage_key, artifact_kind)] in canonical order for the query."""

    return detect_stages_with_source(query, extra_text=extra_text, scoped=scoped)[0]


def detect_stages_with_source(
    query: str,
    extra_text: str | None = None,
    scoped: bool = False,
) -> tuple[list[tuple[str, str]], str]:
    """Return ([(stage_key, artifact_kind)], source) in canonical order.

    The connected model decides BY MEANING which stages the request genuinely
    needs; the STAGE_DEFS keyword sets are reference hints only. There is no
    keyword pipeline verdict: with no judgment runner installed the request
    stays UNDECIDED — no decomposition (an empty stage list, routed as a single
    task) — labeled ``source="unavailable"``. A keyword match must never
    manufacture a multi-stage pipeline on its own.

    `extra_text` extends intent detection beyond the raw first message — a
    briefing interview's confirmed goal + acceptance criteria carry the user's
    real intent far better than the original prompt. `scoped=True` (a Work
    Brief exists) is forwarded to the judge as context.
    """
    text = " ".join(part for part in [(query or ""), (extra_text or "")] if part)
    try:
        from ..judgment import has_judgment_runner, judge_labels
    except Exception:  # pragma: no cover - judgment module is optional at import time
        return [], "unavailable"
    if not has_judgment_runner():
        # Detectable signal that a dormant judge could not reach a model.
        _LOGGER.debug(
            "pipeline stage judgment unavailable: no connected model; "
            "request left undecided (single task, no decomposition)"
        )
        return [], "unavailable"
    picked, source = judge_labels(
        kind="networking-pipeline-stages",
        question=(
            "Which pipeline stages does this request GENUINELY ask to be executed as "
            "separate deliverables: plan (write a PRD/spec), build (implement code), "
            "verify (test/QA the result)?"
        ),
        labels=tuple(key for key, _, _ in STAGE_DEFS),
        text=text,
        hints={key: sorted(keywords) for key, keywords, _ in STAGE_DEFS},
        guidance=(
            "Merely mentioning a word is NOT a stage need — a single task that mentions "
            "testing or planning vocabulary is not a pipeline. Return the stages the user "
            "wants performed; return an empty list for a single-intent request."
        ),
        fallback=(),
        multi=True,
    )
    if source != "model":
        return [], "unavailable"
    kind_by_key = {key: kind for key, _, kind in STAGE_DEFS}
    hits = [(key, kind_by_key[key]) for key, _, _ in STAGE_DEFS if key in picked]
    if len(hits) < 2:
        # One stage (or none) is a single task, never a pipeline.
        return [], "model"
    return hits, "model"


def _producers(cards: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    found = []
    for card in cards:
        for produced in card.get("produces") or []:
            if isinstance(produced, dict) and produced.get("kind") == kind:
                found.append(card)
                break
    return found


def _consumes_kind(card: dict[str, Any], kind: str) -> bool:
    return any(
        isinstance(entry, dict) and entry.get("kind") == kind
        for entry in card.get("consumes") or []
    )


def _target_artifact(query: str) -> str | None:
    lowered = (query or "").lower()
    for artifact, terms in TARGET_ARTIFACT_TERMS:
        if any(term in lowered for term in terms):
            return artifact
    return None


def _card_lookup(cards: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    lookup: dict[str, dict[str, Any]] = {}
    for card in cards:
        cid = str(card.get("id") or "")
        if cid:
            lookup[cid] = card
        tail = cid.split("/")[-1] if cid else ""
        if tail and tail not in lookup:
            lookup[tail] = card
    return lookup


def _plan_pipeline_from_ao(
    query: str,
    usable_cards: list[dict[str, Any]],
    project_dir: str | Path | None,
    max_stages: int,
) -> tuple[list[dict[str, Any]], list[dict[str, str]], str | None] | None:
    if project_dir is None:
        return None
    target = _target_artifact(query)
    if not target:
        return None
    try:
        from ..agent_graph import plan_pipeline_ao

        plan = plan_pipeline_ao(project_dir, target, max_stages=max_stages)
    except Exception:
        return None
    if not plan.get("found") or len(plan.get("stages") or []) < 2:
        return None

    cards_by_id = _card_lookup(usable_cards)
    chosen: list[dict[str, Any]] = []
    graph_path: list[dict[str, str]] = []
    for stage in plan.get("stages") or []:
        agent_id = str(stage.get("agent") or "")
        produced_id = str(stage.get("produces") or "")
        produced = produced_id.removeprefix("artifact:")
        consumed = [str(item).removeprefix("artifact:") for item in stage.get("consumes") or []]
        card = cards_by_id.get(agent_id) or cards_by_id.get(agent_id.split("/")[-1]) or {}
        chosen.append(
            {
                "order": len(chosen) + 1,
                "stage": _stage_for_artifact(produced),
                "card": card.get("id") or agent_id,
                "name": card.get("name") or stage.get("agent"),
                "canonical_command": (card.get("entrypoints") or {}).get("canonical_command"),
                "consumes": consumed,
                "produces": [produced],
                "ao_agent": agent_id,
            }
        )
        for item in consumed:
            graph_path.append({"from": agent_id, "to": f"artifact:{item}", "relation": "consumes"})
        graph_path.append({"from": agent_id, "to": produced_id, "relation": "produces"})

    return chosen, graph_path, target


def _stage_for_artifact(kind: str) -> str:
    if kind in {"agent-spec", "team-spec", "prd"}:
        return "plan"
    if kind in {"single-agent-package", "team-package", "codebase_change"}:
        return "build"
    if kind in {"release-bundle", "qa_report"}:
        return "verify"
    return "stage"


def plan_pipeline(
    query: str,
    usable_cards: list[dict[str, Any]],
    score_of: Callable[[dict[str, Any]], float],
    max_stages: int = 3,
    project_dir: str | Path | None = None,
    session_inventory: list[Any] | None = None,
    model_allocation_decisions: dict[str, dict[str, Any]] | None = None,
    model_allocation_policy: dict[str, Any] | None = None,
    brief: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Build a deterministic stage plan, or None when no valid chain exists.

    When a Work Brief is provided (briefing interview output), its confirmed
    goal/acceptance/constraints extend stage detection, and a compact brief
    view is attached to the plan so runners can inject it into every packet.
    """
    _graph_enabled = project_dir is not None
    stages_wanted, stage_detection = detect_stages_with_source(
        query,
        extra_text=brief_scope_text(brief) if brief else None,
        scoped=brief is not None,
    )
    stages_wanted = stages_wanted[:max_stages]
    if len(stages_wanted) < 2:
        return None

    ao_plan = _plan_pipeline_from_ao(query, usable_cards, project_dir, max_stages)
    if ao_plan is not None:
        chosen, graph_path, target = ao_plan
        pipeline_id = uuid.uuid4().hex[:12]
        handoff_dir = f".agentlas/pipeline/{pipeline_id}/"
        execution_fabric = build_execution_fabric(
            chosen,
            pipeline_id=pipeline_id,
            handoff_dir=handoff_dir,
            session_inventory=session_inventory,
            model_allocation_decisions=model_allocation_decisions,
            model_allocation_policy=model_allocation_policy,
        )
        return {
            "pipeline_id": pipeline_id,
            "stages": chosen,
            "handoff_dir": handoff_dir,
            "graph_path": graph_path,
            "match_reason": "agent_ontology_pipeline_graph",
            "allowed_by": ["ontology_graph_gate", "produces_consumes_path"],
            "blocked_by_axiom": [],
            "stage_detection": stage_detection,
            "target_artifact": target,
            "execution_fabric": execution_fabric,
            "runner_contract": _runner_contract(),
            **({"work_brief": brief_packet_context(brief)} if brief else {}),
        }

    chosen: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    previous_kind: str | None = None
    for stage_key, kind in stages_wanted:
        producers = [card for card in _producers(usable_cards, kind) if str(card.get("id")) not in used_ids]
        if not producers:
            continue
        # Rank: consumes the previous artifact first, then query score, then id
        # for determinism.
        producers.sort(
            key=lambda card: (
                -(1 if previous_kind and _consumes_kind(card, previous_kind) else 0),
                -score_of(card),
                str(card.get("id")),
            )
        )
        card = producers[0]
        used_ids.add(str(card.get("id")))
        chosen.append(
            {
                "order": len(chosen) + 1,
                "stage": stage_key,
                "card": card.get("id"),
                "name": card.get("name"),
                "canonical_command": (card.get("entrypoints") or {}).get("canonical_command"),
                "consumes": [previous_kind] if previous_kind and _consumes_kind(card, previous_kind) else [],
                "produces": [kind],
            }
        )
        previous_kind = kind

    if len(chosen) < 2:
        return None
    graph_path: list[dict[str, str]] = []
    for idx, stage in enumerate(chosen):
        card_id = str(stage["card"])
        produced = str(stage["produces"][0])
        produced_id = f"artifact:{produced}" if not produced.startswith("artifact:") else produced
        if stage.get("consumes"):
            previous = str(stage["consumes"][0])
            previous_id = f"artifact:{previous}" if not previous.startswith("artifact:") else previous
            graph_path.append({"from": card_id, "to": previous_id, "relation": "consumes"})
        graph_path.append({"from": card_id, "to": produced_id, "relation": "produces"})

    pipeline_id = uuid.uuid4().hex[:12]
    if not _graph_enabled:
        # preserve historical shape while still exposing stage-level intent traces
        # as a logical graph for downstream audit tooling.
        exposed_path = []
    else:
        exposed_path = graph_path

    handoff_dir = f".agentlas/pipeline/{pipeline_id}/"
    execution_fabric = build_execution_fabric(
        chosen,
        pipeline_id=pipeline_id,
        handoff_dir=handoff_dir,
        session_inventory=session_inventory,
        model_allocation_decisions=model_allocation_decisions,
        model_allocation_policy=model_allocation_policy,
    )

    return {
        "pipeline_id": pipeline_id,
        "stages": chosen,
        "handoff_dir": handoff_dir,
        "graph_path": exposed_path,
        "match_reason": "pipeline_graph_sequence" if _graph_enabled else "pipeline_legacy_sequence",
        # A pipeline only ever forms when the connected model judged >=2 stages
        # (a keyword match never manufactures one), so the gate is model_stage_judgment.
        "allowed_by": ["model_stage_judgment"] if chosen else [],
        "blocked_by_axiom": [],
        "stage_detection": stage_detection,
        "execution_fabric": execution_fabric,
        "runner_contract": _runner_contract(),
        **({"work_brief": brief_packet_context(brief)} if brief else {}),
    }


def _runner_contract() -> list[str]:
    return [
        "apply execution_fabric.execution_harness.system_prompt verbatim; adapters must not redefine Goal mode or UltraCode mode",
        "execute work packets using the host runtime's safety and permission model",
        "run packets in the same execution_fabric.parallel_group concurrently when host sessions are available",
        "record each stage's artifacts under handoff_dir/<order>-<kind>/ and pass paths to the next stage",
        "on failure: stop, report progress and the remaining plan — never retry silently",
        "do not report success until execution_fabric.required_packet_ids are all passing",
    ]
