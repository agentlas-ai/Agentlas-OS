"""Hephaestus Network 2.0 — Local + owner Cloud + public Hub federation.

Contract: docs/hephaestus-network-2.0.md.

The canonical path federates exact-source candidate menus and leaves
exact-release selection to the active host LLM.  Core validates and prepares
the accepted pinned roster.  The deterministic card router and local cards
under ~/.agentlas/networking/cards/ are legacy/debug surfaces only;
registry.sqlite is a rebuildable cache.
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
