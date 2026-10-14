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
    locale: str = "en",
    context_hint: str | None = None,
) -> dict[str, Any]:
    """Build the host-executed briefing interview directive for one request."""
    profile = surface_profile(surface)
    budget = question_budget(surface)
    soft = profile.get("soft_threshold")
    soft_rule = (
        f"soft_stop: after 1 batch re-score; ambiguity <= {soft} -> state assumptions (labelled), proceed\n"
        if soft is not None
        else ""
    )
    # Composition order: fixed → variable (docs/PROMPT-COMPOSITION-POLICY.md, ledger os.interview.directive).
    # Fixed protocol first; per-surface budget, soft-stop and close rules follow it.
    directive = (
        "task: briefing interview BEFORE executing; output = frozen Work Brief\n"
        f"clear_request: ambiguity <= {AMBIGUITY_THRESHOLD} -> ask nothing\n"
        "waves: 1 goal/constraints/done-signal, 2 edges/conflicts, 3 contradictions/assumptions; "
        "follow any contradiction/avoidance/unverified assumption first\n"
        "ask: from lens table, ONE message, 2-4 options + recommended default each\n"
        "auto_confirm: answerable from code/context/memory -> tag [from-code]/[from-memory], do not ask; "
        "after 3 in a row the next question goes to the user\n"
        "rich_context: state understanding as numbered falsifiable claims, ask which are wrong\n"
        "defer: 'decide later' is valid -> record as deferred, never re-ask\n"
        "risks: every interim-summary risk -> next-wave question or deferred with reason\n"
        "scoring: score after each round (instructions in scoring_prompt), keep history; "
        f"stop when ambiguity <= {AMBIGUITY_THRESHOLD}, every dimension above floor, "
        f"stable {profile['streak_required']} consecutive round(s)\n"
        f"BUDGET (hard): {budget['batch_max']} questions/batch, "
        f"{budget['batches_max']} batch(es), {budget['total_max']} total\n"
        + soft_rule
        + "close: ask 'anything missed?', restate goal in ONE sentence and confirm, "
        f"then emit Work Brief (schemaVersion {WORK_BRIEF_SCHEMA_VERSION}; builds: write to "
        f"{WORK_BRIEF_RELPATH}); anti_scope = user's own words on what NOT to do (feeds routing-card anti_triggers verbatim)"
    )
    return {
        "directive": directive,
        "scoring_prompt": build_scoring_prompt(surface, locale),
        "mode": "briefing_interview",
        "surface": surface,
        "locale": locale,
        "budget": budget,
        "lens_table": render_lens_table(surface, locale),
        "query": query,
        "context_hint": context_hint,
    }
