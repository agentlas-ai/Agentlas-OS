"""Exact product One aliases; original source and runtime identity stay intact.

Mirror shared/memory-actor-family.ts and shared/builtin-agent-ids.ts. Never
derive a family from a slug, model output, graph label, path or provider seat.
"""
from __future__ import annotations

MEMORY_ACTOR_FAMILY_SCHEMA = "agentlas.memory-actor-family.v1"
CORE_ONE_ACTOR_ID = "agentlas-one"
DESKTOP_ONE_ACTOR_ID = "builtin-agentlas-one"
ONE_MEMORY_ACTOR_IDS = (DESKTOP_ONE_ACTOR_ID, CORE_ONE_ACTOR_ID)


def is_one_memory_actor(actor: str | None) -> bool:
    return actor in ONE_MEMORY_ACTOR_IDS


def memory_actor_ids(actor: str | None) -> tuple[str | None, ...]:
    return ONE_MEMORY_ACTOR_IDS if is_one_memory_actor(actor) else (actor,)


def same_memory_actor(left: str | None, right: str | None) -> bool:
    return left == right or (is_one_memory_actor(left) and is_one_memory_actor(right))
