"""Hephaestus Network 2.0 — Hub-first public agent/plugin routing layer.

Contract: docs/hephaestus-network-2.0.md and docs/plans/hephaestus-network-2.0-plan.md.

Hub routing is the public default. Local cards under ~/.agentlas/networking/cards/
exist only for explicit operator/debug routing; registry.sqlite is a rebuildable
cache. The router is deterministic (no LLM) and never sends raw prompts or local
memory to the Hub.
"""

from .bootstrap import (
    SCHEMA_VERSION,
    add_source,
    init_networking,
    network_status,
    networking_home,
    remove_source,
)
from .card_lint import lint_card
from .card_migrate import migrate_tree
from .card_store import load_global_cards, reindex, save_card
from .goal_loop import GoalLoopConfig, GoalLoopResult, run_goal_loop
from .router import route_request
from .run_journal import RunJournal
from .search_call import call_agents, search_agents
from .stormbreaker_runner import run_stormbreaker_decision, run_stormbreaker_query
from .stormbreaker_harness import goal_ultracode_harness

__all__ = [
    "SCHEMA_VERSION",
    "add_source",
    "init_networking",
    "lint_card",
    "load_global_cards",
    "migrate_tree",
    "network_status",
    "networking_home",
    "reindex",
    "remove_source",
    "route_request",
    "run_stormbreaker_decision",
    "run_stormbreaker_query",
    "goal_ultracode_harness",
    "run_goal_loop",
    "GoalLoopConfig",
    "GoalLoopResult",
    "RunJournal",
    "call_agents",
    "search_agents",
    "save_card",
]
