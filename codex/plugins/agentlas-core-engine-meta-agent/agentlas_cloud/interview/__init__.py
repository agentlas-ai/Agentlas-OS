"""Briefing interview engine — measure ambiguity, ask only what's needed,
freeze the answers into a Work Brief that builders, the pipeline planner,
the stormbreaker runner and the router all consume."""

from .context_assessment import ContextAssessmentError, assess_build_context, validate_context_assessment
from .directive import interview_directive
from .lenses import LENS_GROUPS, question_budget, render_lens_table, surface_profile
from .schema import (
    WORK_BRIEF_RELPATH,
    WORK_BRIEF_SCHEMA_VERSION,
    WorkBriefResolution,
    brief_packet_context,
    brief_scope_text,
    load_work_brief,
    resolve_work_brief,
    work_brief_problem,
)
from .scorer import (
    AMBIGUITY_THRESHOLD,
    build_scoring_prompt,
    completion_check,
    compose_ambiguity,
    milestone_of,
)

__all__ = [
    "AMBIGUITY_THRESHOLD",
    "ContextAssessmentError",
    "LENS_GROUPS",
    "WORK_BRIEF_RELPATH",
    "WORK_BRIEF_SCHEMA_VERSION",
    "WorkBriefResolution",
    "assess_build_context",
    "brief_packet_context",
    "brief_scope_text",
    "build_scoring_prompt",
    "completion_check",
    "compose_ambiguity",
    "interview_directive",
    "load_work_brief",
    "milestone_of",
    "question_budget",
    "render_lens_table",
    "resolve_work_brief",
    "surface_profile",
    "validate_context_assessment",
    "work_brief_problem",
]
