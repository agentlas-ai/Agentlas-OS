"""Non-executing loadout recommendation for research requests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .engine import default_registry
from .planner import run_research_plan
from .profile import run_research_profile


SOCIAL_REDDIT_KEYWORDS = ("reddit", "레딧", "subreddit", "r/")
SOCIAL_THREADS_KEYWORDS = ("threads", "thread", "스레드", "쓰레드")
BROWSER_KEYWORDS = (
    "browser",
    "브라우저",
    "click",
    "클릭",
    "form",
    "폼",
    "render",
    "렌더",
    "javascript",
    "js-heavy",
    "동적",
    "interactive",
    "상호작용",
)
BLOCKED_WEB_KEYWORDS = ("403", "blocked", "waf", "captcha", "차단", "막힌", "안 열", "안읽", "못 읽", "못 열")
RESEARCH_KEYWORDS = ("search", "web search", "research", "찾아", "조사", "리서치", "웹서치", "웹 검색")
OFFICIAL_KEYWORDS = ("official", "docs", "documentation", "github", "공식", "문서", "깃헙", "깃허브")


def run_research_recommendation(
    *,
    query: str,
    source_hints: list[str] | None = None,
    home: Path | str | None = None,
) -> dict[str, Any]:
    """Recommend a detachable research loadout without running network work."""

    compact_query = " ".join(query.split()).strip()
    hints = [hint.strip() for hint in source_hints or [] if hint and hint.strip()]
    signals = _signals(compact_query, hints)
    recommendation = _recommend(signals, judge_text=" ".join([compact_query, *hints]).strip())
    preview_hints = hints or [f"search:auto:{compact_query}"] if compact_query else hints
    registry = default_registry(home=home)
    plan = run_research_plan(
        {
            "query": compact_query or "Research recommendation",
            "intent": "recommend",
            "source_hints": preview_hints,
            "loadout": recommendation["loadout"],
            "depth": recommendation["depth"],
            "follow_results": recommendation["follow_results"],
            "query_variants": recommendation["query_variants"],
            "max_cost": {"requests": recommendation["max_requests"]},
        },
        registry=registry,
    )
    profile = run_research_profile(
        loadout=recommendation["loadout"],
        source_hints=preview_hints,
        home=home,
        registry=registry,
    )["profiles"][0]
    return {
        "schema": "agentlas.research.recommendation.v0",
        "status": "ok" if compact_query or hints else "needs_query",
        "commands_will_run": False,
        "network_will_run": False,
        "credentials_exposed_to_model": False,
        "home": str(home or ""),
        "query": compact_query,
        "source_hints": hints,
        "signals": signals,
        "recommendation": recommendation,
        "plan_preview": {
            "source_hints_before_budget": plan.get("source_hints_before_budget", []),
            "source_hints_used": plan.get("source_hints_used", []),
            "mounted_modules": plan.get("mounted_modules", []),
            "ready_mounted_modules": plan.get("ready_mounted_modules", []),
            "unready_mounted_modules": plan.get("unready_mounted_modules", []),
            "policy": plan.get("policy", {}),
        },
        "footprint": profile.get("footprint", {}),
        "loadout_profile": {
            "mounted_modules": profile.get("mounted_modules", []),
            "boundaries": profile.get("boundaries", {}),
        },
        "boundaries": {
            "default_stays_light": True,
            "browser_modules_require_browser_or_full_loadout": True,
            "credentialed_social_is_opt_in": True,
            "recommended_avoids_social_api_tokens": True,
            "public_fallbacks_are_labeled_lower_confidence": True,
            "operator_can_escalate": _escalation_ladder(recommendation["loadout"]),
        },
    }


def _signals(query: str, source_hints: list[str]) -> dict[str, bool]:
    haystack = " ".join([query, *source_hints]).lower()
    url_hosts = [_host(hint) for hint in source_hints]
    return {
        "mentions_reddit": _contains_any(haystack, SOCIAL_REDDIT_KEYWORDS) or any("reddit.com" in host for host in url_hosts),
        "mentions_threads": _contains_any(haystack, SOCIAL_THREADS_KEYWORDS) or any("threads." in host for host in url_hosts),
        "needs_browser": _contains_any(haystack, BROWSER_KEYWORDS),
        "blocked_public_web": _contains_any(haystack, BLOCKED_WEB_KEYWORDS),
        "needs_search": _contains_any(haystack, RESEARCH_KEYWORDS) or not source_hints,
        "prefers_official_sources": _contains_any(haystack, OFFICIAL_KEYWORDS),
    }


# The recommender only ever auto-selects these; social/full stay operator
# escalations (see _escalation_ladder) and are never chosen automatically.
AUTO_SELECTABLE_LOADOUTS = ("safe", "public-web", "browser")


def _recommend(signals: dict[str, bool], judge_text: str = "") -> dict[str, Any]:
    """Pick the research loadout — the connected model decides by meaning.

    The keyword-derived ``signals`` are demoted to reference hints; when a
    judgment runner is connected, ``judge_labels`` selects the loadout among
    the auto-selectable option ids. With no runner the deterministic keyword
    pick below is used and labeled ``selection_source="fallback"`` — never
    silently presented as a semantic decision.
    """

    choice = _deterministic_choice(signals)
    selection_source = "fallback"
    judged = _judge_loadout(judge_text, fallback_loadout=choice["loadout"])
    if judged is not None:
        selection_source = "model"
        if judged != choice["loadout"]:
            choice = _rebase_choice(choice, judged, signals)
            choice["reasons"].append("loadout_selected_by_connected_model")

    loadout = choice["loadout"]
    reasons = choice["reasons"]
    return {
        "loadout": loadout,
        "depth": choice["depth"],
        "follow_results": choice["follow_results"],
        "max_requests": choice["max_requests"],
        "query_variants": _dedupe(choice["query_variants"]),
        "reasons": reasons,
        "selection_source": selection_source,
        "mount_decision": _mount_decision(
            loadout=loadout,
            signals=signals,
            reasons=reasons,
            selection_source=selection_source,
        ),
        "suggested_command": _suggested_command(
            loadout, choice["depth"], choice["follow_results"], choice["max_requests"], choice["query_variants"]
        ),
    }


def _deterministic_choice(signals: dict[str, bool]) -> dict[str, Any]:
    """Today's keyword pick — the labeled no-runner fallback."""

    reasons: list[str] = []
    query_variants: list[str] = []
    loadout = "safe"
    depth = "quick"
    follow_results = 2
    max_requests = 5

    if signals["mentions_reddit"] or signals["mentions_threads"]:
        loadout = "public-web"
        follow_results = 3
        max_requests = 7
        reasons.append("public_social_research_requested")
        reasons.append("official_social_apis_not_mounted_by_default")
        if signals["mentions_reddit"]:
            query_variants.append("reddit")
        if signals["mentions_threads"]:
            query_variants.append("threads")
    elif signals["blocked_public_web"]:
        loadout = "public-web"
        follow_results = 3
        max_requests = 6
        reasons.append("blocked_public_web_fallback_needed")
    elif signals["needs_search"]:
        loadout = "public-web"
        follow_results = 3
        max_requests = 6
        reasons.append("web_search_with_followup_needed")

    if signals["needs_browser"]:
        loadout = "browser"
        depth = "deep"
        follow_results = max(follow_results, 2)
        max_requests = max(max_requests, 6)
        reasons.append("agentlas_browser_hardpoint_auto_selected")
        if signals["blocked_public_web"]:
            reasons.append("browser_escalation_requested_for_blocked_or_dynamic_page")

    if signals["prefers_official_sources"]:
        query_variants.extend(["official", "docs", "github"])
        reasons.append("official_or_github_sources_preferred")

    if not reasons:
        reasons.append("light_default_sufficient")

    return {
        "loadout": loadout,
        "depth": depth,
        "follow_results": follow_results,
        "max_requests": max_requests,
        "query_variants": query_variants,
        "reasons": reasons,
    }


def _rebase_choice(choice: dict[str, Any], loadout: str, signals: dict[str, bool]) -> dict[str, Any]:
    """Re-derive loadout-dependent parameters for a model-chosen loadout."""

    updated = dict(choice, loadout=loadout, reasons=list(choice["reasons"]))
    if loadout == "browser":
        updated["depth"] = "deep"
        updated["follow_results"] = max(choice["follow_results"], 2)
        updated["max_requests"] = max(choice["max_requests"], 6)
        if signals["blocked_public_web"]:
            updated["reasons"].append("browser_escalation_requested_for_blocked_or_dynamic_page")
    elif loadout == "public-web":
        updated["depth"] = "quick"
        updated["follow_results"] = max(choice["follow_results"], 3)
        updated["max_requests"] = max(choice["max_requests"], 6)
    else:  # safe
        updated["depth"] = "quick"
        updated["follow_results"] = 2
        updated["max_requests"] = 5
    return updated


def _judge_loadout(judge_text: str, *, fallback_loadout: str) -> str | None:
    """Connected-model loadout selection; None keeps the deterministic pick."""

    if not judge_text.strip():
        return None
    try:
        from ..judgment import has_judgment_runner, judge_labels
    except Exception:  # pragma: no cover - judgment module is optional at import time
        return None
    if not has_judgment_runner():
        return None
    fallback = fallback_loadout if fallback_loadout in AUTO_SELECTABLE_LOADOUTS else "safe"
    picked, source = judge_labels(
        kind="research-loadout",
        question=(
            "Which research loadout does this request need: 'safe' (fast public search and "
            "static reads), 'public-web' (blocked public pages, feeds, social fallbacks, the "
            "adaptive public reader), or 'browser' (JS-heavy or interactive pages that need a "
            "real browser)?"
        ),
        labels=AUTO_SELECTABLE_LOADOUTS,
        text=judge_text,
        hints={
            "browser": list(BROWSER_KEYWORDS),
            "public-web": list(BLOCKED_WEB_KEYWORDS)
            + list(RESEARCH_KEYWORDS)
            + list(SOCIAL_REDDIT_KEYWORDS)
            + list(SOCIAL_THREADS_KEYWORDS),
        },
        guidance=(
            "Choose by what the task actually needs, not keyword presence. Prefer the "
            "lightest loadout that can produce the evidence; credentialed social APIs stay "
            "operator-approved and are never auto-selected."
        ),
        fallback=(fallback,),
        multi=False,
    )
    if source != "model" or not picked:
        return None
    return picked[0]


def _suggested_command(loadout: str, depth: str, follow_results: int, max_requests: int, variants: list[str]) -> str:
    if loadout == "browser":
        parts = [
            "bin/hep-browser '<query>'",
            "--depth",
            depth,
            "--follow-results",
            str(follow_results),
            "--max-requests",
            str(max_requests),
        ]
        for variant in _dedupe(variants):
            parts.extend(["--variant", variant])
        return " ".join(parts)
    parts = [
        "bin/hephaestus research gather '<query>'",
        "--loadout",
        loadout,
        "--depth",
        depth,
        "--follow-results",
        str(follow_results),
        "--max-requests",
        str(max_requests),
    ]
    for variant in _dedupe(variants):
        parts.extend(["--variant", variant])
    return " ".join(parts)


def _escalation_ladder(loadout: str) -> list[dict[str, object]]:
    ladder = [
        {"loadout": "safe", "use_when": "fast public search and static reads"},
        {"loadout": "public-web", "use_when": "blocked public pages, feeds, metadata, and adaptive public fallback"},
        {"loadout": "social", "use_when": "Operator-approved Reddit or Threads official API evidence"},
        {"loadout": "browser", "use_when": "JS-heavy pages or interactive browser snapshots"},
        {"loadout": "full", "use_when": "operator-approved external readers plus browser and social cartridges"},
    ]
    for item in ladder:
        item["selected"] = item["loadout"] == loadout
    return ladder


def _mount_decision(
    *,
    loadout: str,
    signals: dict[str, bool],
    reasons: list[str],
    selection_source: str = "fallback",
) -> dict[str, object]:
    return {
        "selected_loadout": loadout,
        "selection_source": selection_source,
        "mode": _decision_mode(loadout),
        "browser_hardpoints": "mounted" if loadout in {"browser", "full"} else "detached",
        "credentialed_social": "mounted" if loadout in {"social", "full"} else "detached",
        "public_social_fallbacks": "mounted" if loadout in {"safe", "public-web", "social", "full"} else "detached",
        "adaptive_public_reader": "mounted" if loadout in {"public-web", "social", "browser", "full"} else "detached",
        "operator_approval_recommended": loadout in {"browser", "full"},
        "next_escalation": _next_escalation(loadout),
        "signals_true": [key for key, value in signals.items() if value],
        "reasons": list(reasons),
        "core_boundary": "planner_policy_receipts_stay_in_core; heavy_readers_and_browsers_mount_by_loadout",
    }


def _decision_mode(loadout: str) -> str:
    if loadout == "safe":
        return "light_core_only"
    if loadout == "public-web":
        return "adaptive_public_reader_without_browser"
    if loadout == "social":
        return "social_cartridges_without_browser"
    if loadout == "browser":
        return "browser_hardpoint_required"
    if loadout == "full":
        return "operator_approved_full_mount"
    return "unknown"


def _next_escalation(loadout: str) -> str:
    order = ["safe", "public-web", "browser", "social", "full"]
    try:
        return order[order.index(loadout) + 1]
    except (ValueError, IndexError):
        return ""


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def _host(value: str) -> str:
    parsed = urlsplit(value)
    return (parsed.hostname or "").lower()


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
