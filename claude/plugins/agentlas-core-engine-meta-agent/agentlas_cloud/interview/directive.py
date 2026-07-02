"""Briefing-interview directive for the HOST runtime (BYOC — no model here).

Like the router escalation directive, the engine only names the procedure and
hands over structured instructions; the host model conducts the interview,
runs the scoring prompt after each round, and emits the final Work Brief JSON.
"""

from __future__ import annotations

from typing import Any

from .lenses import question_budget, render_lens_table, surface_profile
from .scorer import AMBIGUITY_THRESHOLD, build_scoring_prompt
from .schema import WORK_BRIEF_RELPATH, WORK_BRIEF_SCHEMA_VERSION


def interview_directive(
    surface: str,
    query: str,
    *,
    locale: str = "ko",
    context_hint: str | None = None,
) -> dict[str, Any]:
    """Build the host-executed briefing interview directive for one request."""
    profile = surface_profile(surface)
    budget = question_budget(surface)
    soft = profile.get("soft_threshold")
    soft_rule = (
        f"- After one batch, re-score; if ambiguity <= {soft}, STATE the remaining "
        "assumptions explicitly (labelled) and proceed without more questions.\n"
        if soft is not None
        else ""
    )
    directive = (
        "Run a briefing interview BEFORE executing. The goal is a frozen Work Brief, "
        "not a conversation.\n"
        f"BUDGET (hard): at most {budget['batch_max']} questions per batch, "
        f"{budget['batches_max']} batch(es), {budget['total_max']} total. "
        "If the request is already clear (ambiguity <= "
        f"{AMBIGUITY_THRESHOLD}), ask NOTHING and proceed.\n"
        "PROCEDURE:\n"
        "- Wave 1 basics (goal/constraints/done-signal), wave 2 edges/conflicts, wave 3 "
        "contradictions/assumptions — but if an answer reveals a contradiction, an "
        "avoidance or an unverified assumption, abandon the wave order and follow that thread.\n"
        "- Pick questions from the lens table below; batch them in ONE message "
        "(multiple ask blocks), each with 2-4 options plus a recommended default.\n"
        "- Auto-confirm answers you can settle from code/project context/memory — tag them "
        "[from-code]/[from-memory] and do NOT ask the user. After 3 consecutive auto-confirms, "
        "the next question MUST go to the user (the interviewee is the human, not the codebase).\n"
        "- If rich context already exists, INVERT: present your understanding as numbered, "
        "falsifiable statements and ask only which numbers are wrong.\n"
        "- 'decide later' is always a valid answer: record it under deferred, never re-ask.\n"
        + soft_rule
        + "- Every risk noted in an interim summary MUST become a concrete question in the "
        "next wave, or be recorded as deferred with a named reason.\n"
        "SCORING: after each round run the scoring instructions (below) and keep a per-round "
        "history. Stop gates: overall ambiguity <= "
        f"{AMBIGUITY_THRESHOLD} AND every dimension above its floor AND stable for "
        f"{profile['streak_required']} consecutive round(s).\n"
        "CLOSING: one coverage question ('anything I missed?'), then restate the goal as ONE "
        "sentence and confirm 'would someone reading only this line reach the same result?'. "
        f"Only then emit the Work Brief (schemaVersion {WORK_BRIEF_SCHEMA_VERSION}; on builds "
        f"write it to {WORK_BRIEF_RELPATH}). anti_scope must contain the user's own words about "
        "what NOT to do — it feeds routing-card anti_triggers verbatim."
    )
    return {
        "mode": "briefing_interview",
        "surface": surface,
        "locale": locale,
        "query": query,
        "context_hint": context_hint,
        "budget": budget,
        "lens_table": render_lens_table(surface, locale),
        "scoring_prompt": build_scoring_prompt(surface, locale),
        "directive": directive,
    }
