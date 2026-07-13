"""Phase-0 Agentlas Research Engine."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agentlas_cloud.networking.bootstrap import networking_home

from .adapters import (
    AgentBrowserCliAdapter,
    BrowserOSBrowserAdapter,
    BrowserUseAdapter,
    DuckDuckGoHtmlSearchAdapter,
    GitHubReposSearchAdapter,
    HyperAgentBrowserAdapter,
    HttpReaderAdapter,
    InsaneFetchAdapter,
    JinaReaderAdapter,
    JinaSearchAdapter,
    NewsRssSearchAdapter,
    PlaywrightMcpAdapter,
    StagehandBrowserAdapter,
    SteelBrowserAdapter,
)
from .contracts import ResearchAttempt, ResearchRequest, ResearchResult
from .evidence_coverage import analyze_evidence_coverage
from .evidence_quality import analyze_evidence_quality
from .loadouts import apply_loadout, loadout_policy
from .policy import module_allowed, weight_allowed
from .platforms import RedditOAuthAdapter, RedditPublicAdapter, ThreadsPublicWebAdapter, ThreadsSearchAdapter
from .query_variants import expand_query_variants
from .receipts import write_research_receipt
from .redaction import redacted_exception_reason
from .registry import AdapterRegistry
from .search_ranker import analyze_search_candidates


class ResearchEngine:
    """Small orchestrator for research modules.

    The first phase reads explicit URL hints only. Search, browser, and platform
    modules can be registered later without changing this core contract.
    """

    def __init__(self, *, registry: AdapterRegistry | None = None, home: Path | str | None = None):
        self.home = Path(home) if home else None
        self.registry = registry or default_registry(home=self.home)

    def run(self, request_value: ResearchRequest | dict[str, Any] | str) -> dict[str, Any]:
        request = apply_loadout(ResearchRequest.from_value(request_value))
        expanded_source_hints = _expand_source_hints(request)
        source_hints = _apply_source_hint_budget(request, expanded_source_hints)
        source_hints_dropped = _source_hints_dropped(expanded_source_hints, source_hints)
        attempts: list[ResearchAttempt] = []
        results: list[ResearchResult] = []
        module_chain: list[str] = []

        if not source_hints:
            attempts.append(
                ResearchAttempt(
                    module="research.core",
                    status="needs_source",
                    reason="phase0_requires_url_source_hints",
                )
            )
        for source_hint in source_hints:
            source_results = self._read_source_hint(
                source_hint,
                request,
                attempts=attempts,
                module_chain=module_chain,
            )
            results.extend(source_results)

        followup_limit = _followup_limit(request, source_hints)
        candidate_report = analyze_search_candidates(
            results,
            query=request.query,
            limit=_candidate_report_limit(results, followup_limit),
        )
        followup_candidates = candidate_report.candidates[:followup_limit]
        followup_urls = [candidate.url for candidate in followup_candidates]
        for url in followup_urls:
            source_results = self._read_source_hint(
                url,
                request,
                attempts=attempts,
                module_chain=module_chain,
                reason_prefix="followup",
            )
            results.extend(source_results)

        browser_execution = _browser_execution(request, attempts)
        mounted_module_ids = _dedupe(module_chain)
        escalation_advice = _escalation_advice(
            request,
            attempts=attempts,
            results=results,
            browser_execution=browser_execution,
            search_candidate_total=candidate_report.total_candidates,
        )
        evidence_quality = analyze_evidence_quality(results, attempts=attempts)
        evidence_coverage = analyze_evidence_coverage(
            results,
            attempts=attempts,
            browser_execution=browser_execution,
        )
        capability_summary = _capability_summary(
            request,
            attempts=attempts,
            results=results,
            mounted_module_ids=mounted_module_ids,
            mounted_module_slots=_module_slots(self.registry, mounted_module_ids),
            registry=self.registry,
            browser_execution=browser_execution,
            evidence_coverage=evidence_coverage,
        )
        policy = {
            "private_hosts_blocked": True,
            "credentials_exposed_to_model": False,
            "browser_used": browser_execution["succeeded"],
            "browser_execution": browser_execution,
            "evidence_quality": evidence_quality,
            "evidence_coverage": evidence_coverage,
            "capability_summary": capability_summary,
            "escalation_advice": escalation_advice,
            "optional_modules_required": any(attempt.status == "module_unavailable" for attempt in attempts),
            "follow_results": request.follow_results,
            "followup_count": len(followup_urls),
            "query_variants": list(request.query_variants),
            "followup_ranker": "score_v3_social_diverse",
            "followup_candidates": [candidate.to_dict() for candidate in followup_candidates],
            "search_candidate_report": candidate_report.to_dict(),
            "max_cost_requests": _max_cost_requests(request),
            "source_hint_count_before_budget": len(expanded_source_hints),
            "source_hint_count_after_budget": len(source_hints),
            "source_hint_budget_limited": bool(source_hints_dropped),
            "source_hints_dropped_by_budget": source_hints_dropped,
            "followup_requested": request.follow_results,
            "followup_budget_limited": _followup_budget_limited(request, source_hints, followup_limit),
            "request_budget": _request_budget_report(
                request,
                expanded_source_hints=expanded_source_hints,
                source_hints=source_hints,
                source_hints_dropped=source_hints_dropped,
                followup_limit=followup_limit,
                followup_count=len(followup_urls),
            ),
            "max_weight": request.max_weight,
            "read_strategy": _read_strategy(request, attempts),
            "source_hints_used": source_hints,
            "auto_search_modules": _auto_search_modules(request),
            "loadout": loadout_policy(request.loadout),
            "registered_module_count": len(self.registry.adapters),
            "mounted_module_ids": mounted_module_ids,
            "mounted_module_slots": capability_summary["mounted_slots"],
            "module_manifests": _module_manifests_for(self.registry, mounted_module_ids),
        }
        receipt = write_research_receipt(
            request,
            attempts=attempts,
            module_chain=mounted_module_ids,
            policy=policy,
            home=self.home,
        )
        for result in results:
            result.receipt_id = receipt.receipt_id
        return {
            "schema": "agentlas.research.v0",
            "status": "ok" if any(r.confidence != "blocked" for r in results) else "partial",
            "request": request.to_dict(),
            "capability_summary": capability_summary,
            "results": [result.to_dict() for result in results],
            "receipt": receipt.to_dict(),
        }

    def _read_source_hint(
        self,
        source_hint: str,
        request: ResearchRequest,
        *,
        attempts: list[ResearchAttempt],
        module_chain: list[str],
        reason_prefix: str = "",
    ) -> list[ResearchResult]:
        handled = False
        fallback_blocked_result: ResearchResult | None = None
        collected: list[ResearchResult] = []
        deep_read = _deep_read_enabled(request, source_hint)
        for adapter in self.registry.candidates(source_hint, request):
            if deep_read and collected and not _adapter_is_browser(adapter):
                continue
            allowed, reason = module_allowed(
                adapter.module_id,
                request.allowed_modules,
                request.forbidden_modules,
            )
            if not allowed:
                if _unmounted_browser_candidate(adapter, reason):
                    continue
                attempts.append(
                    ResearchAttempt(adapter.module_id, "module_unavailable", reason, source_hint, weight=adapter.weight)
                )
                continue
            allowed, reason = weight_allowed(adapter.weight, request.max_weight)
            if not allowed:
                attempts.append(
                    ResearchAttempt(adapter.module_id, "module_unavailable", reason, source_hint, weight=adapter.weight)
                )
                continue
            handled = True
            module_chain.append(adapter.module_id)
            try:
                result, attempt = adapter.read(source_hint, request)
            except Exception as exc:
                result = None
                attempt = ResearchAttempt(
                    adapter.module_id,
                    "error",
                    redacted_exception_reason(exc, max_length=160),
                    source_hint,
                    weight=adapter.weight,
                )
            if reason_prefix:
                attempt.reason = f"{reason_prefix}:{attempt.reason}" if attempt.reason else reason_prefix
            attempts.append(attempt)
            if result is not None and result.confidence != "blocked":
                if reason_prefix:
                    result.limits = _dedupe(result.limits + [f"{reason_prefix}_read"])
                if not deep_read:
                    return [result]
                if _result_is_browser(result, adapter):
                    collected.append(result)
                    return collected
                if not collected:
                    collected.append(result)
                continue
            if result is not None:
                fallback_blocked_result = result
        if not handled:
            attempts.append(
                ResearchAttempt(
                    module="research.core",
                    status="module_unavailable",
                    reason=f"{reason_prefix}:no_adapter_for_source_hint" if reason_prefix else "no_adapter_for_source_hint",
                    url=source_hint,
                )
            )
        if collected:
            return collected
        return [fallback_blocked_result] if fallback_blocked_result is not None else []


def default_registry(*, home: Path | str | None = None) -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(RedditOAuthAdapter())
    registry.register(RedditPublicAdapter())
    registry.register(ThreadsSearchAdapter())
    registry.register(ThreadsPublicWebAdapter())
    registry.register(DuckDuckGoHtmlSearchAdapter())
    registry.register(NewsRssSearchAdapter())
    registry.register(GitHubReposSearchAdapter())
    registry.register(JinaSearchAdapter())
    registry.register(HttpReaderAdapter())
    registry.register(InsaneFetchAdapter())
    registry.register(JinaReaderAdapter())
    registry.register(AgentBrowserCliAdapter(home=home))
    registry.register(PlaywrightMcpAdapter())
    registry.register(BrowserUseAdapter())
    registry.register(StagehandBrowserAdapter())
    registry.register(SteelBrowserAdapter())
    registry.register(HyperAgentBrowserAdapter())
    registry.register(BrowserOSBrowserAdapter())
    return registry


def run_research(
    request_value: ResearchRequest | dict[str, Any] | str,
    *,
    home: Path | str | None = None,
) -> dict[str, Any]:
    base = Path(home) if home else networking_home()
    return ResearchEngine(home=base).run(request_value)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _module_manifests_for(registry: AdapterRegistry, module_ids: list[str]) -> list[dict[str, Any]]:
    wanted = set(module_ids)
    return [
        adapter.manifest.to_dict()
        for adapter in registry.adapters
        if adapter.module_id in wanted
    ]


def _module_slots(registry: AdapterRegistry, module_ids: list[str]) -> dict[str, list[str]]:
    wanted = set(module_ids)
    slots: dict[str, list[str]] = {}
    for adapter in registry.adapters:
        if adapter.module_id not in wanted:
            continue
        slots.setdefault(adapter.manifest.slot, []).append(adapter.module_id)
    return {slot: ids for slot, ids in sorted(slots.items())}


def _module_weights(registry: AdapterRegistry, module_ids: list[str]) -> dict[str, str]:
    wanted = set(module_ids)
    return {
        adapter.module_id: str(adapter.weight)
        for adapter in registry.adapters
        if adapter.module_id in wanted
    }


def _capability_summary(
    request: ResearchRequest,
    *,
    attempts: list[ResearchAttempt],
    results: list[ResearchResult],
    mounted_module_ids: list[str],
    mounted_module_slots: dict[str, list[str]],
    registry: AdapterRegistry,
    browser_execution: dict[str, object],
    evidence_coverage: dict[str, Any],
) -> dict[str, Any]:
    usable = [result for result in results if result.confidence != "blocked"]
    weights = _module_weights(registry, mounted_module_ids)
    heavy_weights = {"adaptive_medium", "credentialed_medium", "browser_heavy"}
    heavy_modules = [
        {"id": module_id, "weight": weights.get(module_id, "")}
        for module_id in mounted_module_ids
        if weights.get(module_id, "") in heavy_weights
    ]
    social_missing = _dedupe_strings(_string_list(evidence_coverage.get("official_social_modules_missing")))
    missing_proofs = _dedupe_strings(_string_list(evidence_coverage.get("completion_blockers")))
    warnings = _dedupe_strings(_string_list(evidence_coverage.get("warnings")))
    browser_status = str(browser_execution.get("status") or "not_requested")
    trust_status = _capability_trust_status(
        usable_count=len(usable),
        browser_status=browser_status,
        social_missing=social_missing,
        public_social=bool(evidence_coverage.get("public_social_fallback_evidence")),
        missing_proofs=missing_proofs,
    )
    return {
        "schema": "agentlas.research.capability_summary.v0",
        "status": trust_status,
        "loadout": request.loadout,
        "max_weight": request.max_weight,
        "depth": request.depth,
        "mounted_modules": list(mounted_module_ids),
        "mounted_slots": mounted_module_slots,
        "heavy_modules_mounted": heavy_modules,
        "browser": {
            "requested": bool(browser_execution.get("requested")),
            "attempted": bool(browser_execution.get("attempted")),
            "used": bool(browser_execution.get("succeeded")),
            "status": browser_status,
            "modules": _dedupe_strings(_string_list(browser_execution.get("modules"))),
            "evidence": bool(evidence_coverage.get("browser_evidence")),
        },
        "social": {
            "requested": request.loadout in {"social", "full"} or any(_is_social_source_hint(hint) for hint in request.source_hints),
            "official_evidence": bool(evidence_coverage.get("official_social_evidence")),
            "public_fallback_evidence": bool(evidence_coverage.get("public_social_fallback_evidence")),
            "public_fallback_platforms": _dedupe_strings(_string_list(evidence_coverage.get("public_social_fallback_platforms"))),
            "official_missing_modules": social_missing,
            "missing_credentials": _dedupe_strings(_string_list(evidence_coverage.get("missing_credentials"))),
            "missing_proofs": missing_proofs,
        },
        "web": {
            "search_evidence": bool(evidence_coverage.get("search_evidence")),
            "direct_read_evidence": bool(evidence_coverage.get("direct_read_evidence")),
            "search_only": bool(evidence_coverage.get("search_only")),
        },
        "trust": {
            "usable_result_count": len(usable),
            "warnings": warnings,
            "missing_proofs": missing_proofs,
            "official_social_required_for_completion": bool(social_missing),
            "browser_required_for_completion": browser_status in {"unavailable", "blocked_by_policy", "failed"},
            "can_use_for_build_context": bool(usable),
        },
    }


def _capability_trust_status(
    *,
    usable_count: int,
    browser_status: str,
    social_missing: list[str],
    public_social: bool,
    missing_proofs: list[str],
) -> str:
    if usable_count <= 0 and browser_status not in {"used"}:
        return "missing_evidence"
    if browser_status in {"unavailable", "blocked_by_policy", "failed"}:
        return "needs_browser_config"
    if social_missing and public_social:
        return "partial_public_social_fallback"
    if missing_proofs:
        return "partial_needs_proof"
    return "ready"


def _is_social_source_hint(source_hint: str) -> bool:
    lowered = source_hint.lower()
    return lowered.startswith(("reddit:", "threads:")) or "reddit.com/" in lowered or "threads.net/" in lowered or "threads.com/" in lowered


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [str(value)]
    try:
        return [str(item) for item in value]
    except TypeError:
        return [str(value)]


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


SEARCH_MODULE_HINTS = {
    "search.ddg_html": "ddg_html",
    "search.news_rss": "news_rss",
    "search.github_repos": "github",
    "search.jina": "jina",
}
GITHUB_SEARCH_MODULE = "search.github_repos"
GITHUB_SEARCH_KEYWORDS = ("github", "깃헙", "깃허브", "repo:", "repository", "repositories", "open source", "오픈소스")


def _expand_source_hints(request: ResearchRequest) -> list[str]:
    expanded: list[str] = []
    for source_hint in request.source_hints:
        lowered = source_hint.lower()
        if lowered.startswith("search:auto:"):
            query = source_hint.split(":", 2)[2].strip()
            query_variants = expand_query_variants(query, request.query_variants)
            modules = _auto_search_modules(request)
            social_hints = _social_platform_hints(query, request)
            if not modules:
                expanded.extend(social_hints or [source_hint])
                continue
            base_query = query_variants[0] if query_variants else query
            for module in modules:
                provider = SEARCH_MODULE_HINTS.get(module)
                if provider:
                    expanded.append(f"search:{provider}:{base_query}")
            for hint in social_hints:
                _append_source_hint_with_public_fallback(expanded, hint, request)
            for module in modules:
                provider = SEARCH_MODULE_HINTS.get(module)
                if provider:
                    for variant_query in query_variants[1:]:
                        expanded.append(f"search:{provider}:{variant_query}")
            continue
        if lowered.startswith("search:"):
            parts = source_hint.split(":", 2)
            if len(parts) == 3 and parts[1] in set(SEARCH_MODULE_HINTS.values()):
                provider = parts[1]
                for variant_query in expand_query_variants(parts[2].strip(), request.query_variants):
                    expanded.append(f"search:{provider}:{variant_query}")
                continue
        platform_fallbacks = _public_platform_search_fallbacks(source_hint, request)
        if platform_fallbacks:
            if _should_keep_platform_source_hint(source_hint, request):
                expanded.append(source_hint)
            expanded.extend(platform_fallbacks)
            continue
        expanded.append(source_hint)
    return _dedupe(expanded)


def _auto_search_modules(request: ResearchRequest) -> list[str]:
    allowed = set(request.allowed_modules)
    forbidden = set(request.forbidden_modules)
    if not allowed:
        return ["search.news_rss"] if "search.news_rss" not in forbidden else []
    github_requested = _github_search_requested(request)
    return [
        module
        for module in SEARCH_MODULE_HINTS
        if module in allowed and module not in forbidden
        and (module != GITHUB_SEARCH_MODULE or github_requested)
    ]


def _github_search_requested(request: ResearchRequest) -> bool:
    haystack = " ".join([request.query, *request.source_hints, *request.query_variants]).lower()
    return any(keyword in haystack for keyword in GITHUB_SEARCH_KEYWORDS)


def _social_platform_hints(query: str, request: ResearchRequest) -> list[str]:
    if request.loadout not in {"social", "full"}:
        return []
    allowed = set(request.allowed_modules)
    forbidden = set(request.forbidden_modules)
    compact = " ".join(query.split())[:180]
    if not compact:
        return []
    hints: list[str] = []
    if _any_allowed_not_forbidden(("platform.reddit.oauth", "platform.reddit"), allowed, forbidden):
        hints.append(f"reddit:search:{compact}")
    if _any_allowed_not_forbidden(("platform.threads", "platform.threads.public"), allowed, forbidden):
        hints.append(f"threads:keyword:{compact}")
    return hints


def _any_allowed_not_forbidden(module_ids: tuple[str, ...], allowed: set[str], forbidden: set[str]) -> bool:
    return any(module_id in allowed and module_id not in forbidden for module_id in module_ids)


def _module_allowed_by_request(module_id: str, allowed: set[str], forbidden: set[str]) -> bool:
    return module_id in allowed and module_id not in forbidden


def _append_source_hint_with_public_fallback(expanded: list[str], source_hint: str, request: ResearchRequest) -> None:
    expanded.append(source_hint)
    expanded.extend(_public_platform_search_fallbacks(source_hint, request))


def _public_platform_search_fallbacks(source_hint: str, request: ResearchRequest) -> list[str]:
    allowed = set(request.allowed_modules)
    forbidden = set(request.forbidden_modules)
    query = _threads_keyword_query(source_hint)
    fallback_query = ""
    if query and (not _module_allowed_by_request("platform.threads", allowed, forbidden) or not _threads_token_configured()):
        fallback_query = f"{query} Threads site:threads.com"
    reddit_query = _reddit_search_query(source_hint)
    if reddit_query and (not _module_allowed_by_request("platform.reddit.oauth", allowed, forbidden) or not _reddit_token_configured()):
        fallback_query = f"{reddit_query} Reddit site:reddit.com"
    if not fallback_query:
        return []
    if query and not _any_allowed_not_forbidden(("platform.threads", "platform.threads.public"), allowed, forbidden):
        return []
    if reddit_query and not _any_allowed_not_forbidden(("platform.reddit.oauth", "platform.reddit"), allowed, forbidden):
        return []
    modules = _auto_search_modules(request)
    if not modules:
        return []
    return [
        f"search:{provider}:{fallback_query}"
        for module in modules
        if (provider := SEARCH_MODULE_HINTS.get(module))
    ]


def _should_keep_platform_source_hint(source_hint: str, request: ResearchRequest) -> bool:
    allowed = set(request.allowed_modules)
    if _threads_keyword_query(source_hint) and "platform.threads" not in allowed:
        return False
    return True


def _threads_keyword_query(source_hint: str) -> str:
    lowered = source_hint.lower()
    if lowered.startswith("threads:keyword:") or lowered.startswith("threads:tag:"):
        return source_hint.split(":", 2)[2].strip()
    return ""


def _reddit_search_query(source_hint: str) -> str:
    lowered = source_hint.lower()
    if lowered.startswith("reddit:search:"):
        return source_hint.split(":", 2)[2].strip()
    return ""


def _threads_token_configured() -> bool:
    return bool(os.environ.get("AGENTLAS_THREADS_ACCESS_TOKEN") or os.environ.get("THREADS_ACCESS_TOKEN"))


def _reddit_token_configured() -> bool:
    if os.environ.get("AGENTLAS_REDDIT_BEARER_TOKEN") or os.environ.get("REDDIT_BEARER_TOKEN"):
        return True
    return bool(
        (os.environ.get("AGENTLAS_REDDIT_CLIENT_ID") and os.environ.get("AGENTLAS_REDDIT_CLIENT_SECRET"))
        or (os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET"))
    )


def _followup_limit(request: ResearchRequest, source_hints: list[str]) -> int:
    limit = request.follow_results
    max_requests = _max_cost_requests(request)
    if max_requests <= 0:
        return limit
    remaining = max(0, max_requests - len(source_hints))
    return min(limit, remaining)


def _followup_budget_limited(request: ResearchRequest, source_hints: list[str], followup_limit: int) -> bool:
    return _max_cost_requests(request) > 0 and request.follow_results > followup_limit


def _request_budget_report(
    request: ResearchRequest,
    *,
    expanded_source_hints: list[str],
    source_hints: list[str],
    source_hints_dropped: list[str],
    followup_limit: int,
    followup_count: int,
) -> dict[str, object]:
    max_requests = _max_cost_requests(request)
    return {
        "max_requests": max_requests,
        "source_hint_count_before_budget": len(expanded_source_hints),
        "source_hint_count_after_budget": len(source_hints),
        "source_hint_budget_limited": bool(source_hints_dropped),
        "source_hints_dropped_by_budget": source_hints_dropped,
        "followup_requested": request.follow_results,
        "followup_limit_after_budget": followup_limit,
        "followup_count": followup_count,
        "followup_budget_limited": _followup_budget_limited(request, source_hints, followup_limit),
    }


def _apply_source_hint_budget(request: ResearchRequest, source_hints: list[str]) -> list[str]:
    source_hint_limit = _source_hint_budget_limit(request, source_hints)
    if source_hint_limit <= 0:
        return source_hints
    if len(source_hints) <= source_hint_limit:
        return source_hints
    if request.loadout in {"social", "full"}:
        selected = _social_diverse_source_hints(source_hints, source_hint_limit)
        if selected:
            return selected
    return source_hints[:source_hint_limit]


def _source_hint_budget_limit(request: ResearchRequest, source_hints: list[str]) -> int:
    max_requests = _max_cost_requests(request)
    if max_requests <= 0:
        return len(source_hints)
    if request.follow_results <= 0 or max_requests <= 1:
        return max_requests

    reserve_for_followups = min(request.follow_results, max_requests - 1)
    source_hint_limit = max_requests - reserve_for_followups
    if request.loadout in {"social", "full"}:
        source_hint_limit = max(source_hint_limit, _social_source_hint_floor(source_hints, max_requests))
    return max(1, min(max_requests, source_hint_limit))


def _social_source_hint_floor(source_hints: list[str], max_requests: int) -> int:
    floor = 0
    if any(_is_generic_search_hint(source_hint) for source_hint in source_hints):
        floor += 1
    if any(_is_reddit_source_hint(source_hint) for source_hint in source_hints):
        floor += 1
    if any(_is_threads_platform_hint(source_hint) for source_hint in source_hints):
        floor += 1
    if any(_is_threads_public_search_fallback(source_hint) for source_hint in source_hints):
        floor += 1
    return min(max_requests, max(1, floor))


def _source_hints_dropped(source_hints: list[str], selected: list[str]) -> list[str]:
    selected_set = set(selected)
    return [source_hint for source_hint in source_hints if source_hint not in selected_set]


def _social_diverse_source_hints(source_hints: list[str], max_requests: int) -> list[str]:
    selected: set[str] = set()
    has_reddit = any(_is_reddit_source_hint(source_hint) for source_hint in source_hints)
    has_threads = any(_is_threads_platform_hint(source_hint) for source_hint in source_hints)
    has_threads_fallback = any(_is_threads_public_search_fallback(source_hint) for source_hint in source_hints)

    if has_reddit and has_threads and max_requests >= 4:
        priorities = (
            _is_generic_search_hint,
            _is_reddit_source_hint,
            _is_threads_platform_hint,
            _is_threads_public_search_fallback,
        )
    elif has_reddit and has_threads and has_threads_fallback and max_requests >= 3:
        priorities = (
            _is_reddit_source_hint,
            _is_threads_platform_hint,
            _is_threads_public_search_fallback,
        )
    elif has_reddit and has_threads:
        priorities = (
            _is_generic_search_hint,
            _is_reddit_source_hint,
            _is_threads_platform_hint,
        )
    elif has_threads and has_threads_fallback and max_requests >= 2:
        priorities = (
            _is_threads_platform_hint,
            _is_threads_public_search_fallback,
            _is_generic_search_hint,
        )
    else:
        return source_hints[:max_requests]

    for predicate in priorities:
        _select_first_source_hint(source_hints, selected, predicate, max_requests)
    for source_hint in source_hints:
        if len(selected) >= max_requests:
            break
        selected.add(source_hint)
    return [source_hint for source_hint in source_hints if source_hint in selected][:max_requests]


def _select_first_source_hint(source_hints: list[str], selected: set[str], predicate, max_requests: int) -> None:
    if len(selected) >= max_requests:
        return
    for source_hint in source_hints:
        if source_hint in selected:
            continue
        if predicate(source_hint):
            selected.add(source_hint)
            return


def _is_reddit_source_hint(source_hint: str) -> bool:
    lowered = source_hint.lower()
    return lowered.startswith("reddit:") or "reddit.com/" in lowered


def _is_threads_platform_hint(source_hint: str) -> bool:
    return source_hint.lower().startswith("threads:")


def _is_threads_public_search_fallback(source_hint: str) -> bool:
    if _threads_token_configured():
        return False
    lowered = source_hint.lower()
    return lowered.startswith("search:") and " threads site:threads.com" in lowered


def _is_generic_search_hint(source_hint: str) -> bool:
    return source_hint.lower().startswith("search:") and not _is_threads_public_search_fallback(source_hint)


def _candidate_report_limit(results: list[ResearchResult], followup_limit: int) -> int:
    if not any(result.platform == "web_search" for result in results):
        return 0
    return max(10, followup_limit)


def _max_cost_requests(request: ResearchRequest) -> int:
    try:
        return int((request.max_cost or {}).get("requests") or 0)
    except (TypeError, ValueError):
        return 0


def _read_strategy(request: ResearchRequest, attempts: list[ResearchAttempt]) -> str:
    if str(request.depth).lower() == "deep" and any(
        attempt.module.startswith("browser.") and attempt.status == "ok"
        for attempt in attempts
    ):
        return "deep_static_plus_browser"
    return "first_success"


def _browser_execution(request: ResearchRequest, attempts: list[ResearchAttempt]) -> dict[str, object]:
    browser_attempts = [attempt for attempt in attempts if attempt.module.startswith("browser.")]
    succeeded = any(attempt.status == "ok" for attempt in browser_attempts)
    requested = any(module.startswith("browser.") for module in request.allowed_modules)
    unavailable = [attempt for attempt in browser_attempts if attempt.status == "module_unavailable"]
    failed = [attempt for attempt in browser_attempts if attempt.status in {"blocked", "error"}]
    status = "not_requested"
    if succeeded:
        status = "used"
    elif unavailable:
        status = "blocked_by_policy" if any(_browser_policy_blocked(attempt.reason) for attempt in unavailable) else "unavailable"
    elif failed:
        status = "failed"
    elif requested:
        status = "not_applicable"
    return {
        "requested": requested,
        "attempted": bool(browser_attempts),
        "succeeded": succeeded,
        "status": status,
        "attempt_count": len(browser_attempts),
        "unavailable_count": len(unavailable),
        "failed_count": len(failed),
        "modules": _dedupe([attempt.module for attempt in browser_attempts]),
        "reasons": _dedupe([attempt.reason for attempt in browser_attempts if attempt.reason])[:5],
    }


def _browser_policy_blocked(reason: str) -> bool:
    return (
        reason in {"forbidden_module", "not_in_allowed_modules"}
        or reason.startswith("weight_exceeds_max:")
        or reason.startswith("ssrf_blocked:")
    )


def _escalation_advice(
    request: ResearchRequest,
    *,
    attempts: list[ResearchAttempt],
    results: list[ResearchResult],
    browser_execution: dict[str, object],
    search_candidate_total: int,
) -> dict[str, object]:
    suggestions: list[dict[str, object]] = []
    allowed = set(request.allowed_modules)
    has_usable_result = any(result.confidence != "blocked" for result in results)
    attempt_reasons = " ".join(attempt.reason for attempt in attempts)

    if _has_http_block(attempts) and "read.insane_fetch" not in allowed:
        suggestions.append(
            _suggestion(
                action="try_loadout",
                reason="static_http_blocked",
                loadout="public-web",
                modules=["read.insane_fetch"],
                weight="adaptive_medium",
                note="Use the adaptive public-route reader for blocked public pages; it still stops at login/paywall boundaries.",
            )
        )

    if _needs_search_sources(request, search_candidate_total) and "search.ddg_html" not in allowed:
        suggestions.append(
            _suggestion(
                action="allow_module",
                reason="search_candidates_empty",
                loadout="safe",
                modules=["search.ddg_html"],
                weight="light",
                note="Add the no-key general web search cartridge before escalating to external search.",
            )
        )

    if _needs_search_sources(request, search_candidate_total) and "search.jina" not in allowed:
        suggestions.append(
            _suggestion(
                action="consider_external_search",
                reason="search_candidates_empty",
                loadout="full",
                modules=["search.jina"],
                weight="external_light",
                note="Jina search can broaden recall, but the query is sent to an external service and requires a configured API key.",
            )
        )

    browser_status = str(browser_execution.get("status") or "")
    if browser_status == "unavailable":
        suggestions.append(
            _suggestion(
                action="configure_module",
                reason="browser_hardpoint_unavailable",
                loadout="browser",
                modules=list(browser_execution.get("modules") or []),
                weight="browser_heavy",
                note="A browser loadout was requested, but the local snapshot command or binary is not configured.",
            )
        )
    elif browser_status == "blocked_by_policy" and not has_usable_result:
        suggestions.append(
            _suggestion(
                action="operator_approval_required",
                reason="browser_blocked_by_policy",
                loadout="browser",
                modules=[module for module in request.allowed_modules if module.startswith("browser.")],
                weight="browser_heavy",
                note="Raise max_weight to browser_heavy or choose the browser/full loadout only when heavy browser evidence is acceptable.",
            )
        )
    elif browser_status == "not_requested" and not has_usable_result and _public_routes_stopped_at_wall(attempts):
        suggestions.append(
            _suggestion(
                action="operator_approval_required",
                reason="browser_loadout_available_after_public_routes_blocked",
                loadout="browser",
                modules=[],
                weight="browser_heavy",
                note="Public readers stopped at an auth, rate-limit, or anti-bot boundary; choose a browser loadout only when heavier browser evidence is acceptable.",
            )
        )

    if (
        "platform.reddit.oauth" in [attempt.module for attempt in attempts]
        and (
            "REDDIT_BEARER_TOKEN not configured" in attempt_reasons
            or "reddit_oauth_credentials_not_configured" in attempt_reasons
        )
    ) or any(attempt.module == "platform.reddit" and attempt.status in {"blocked", "error"} for attempt in attempts):
        suggestions.append(
            _suggestion(
                action="configure_credentials",
                reason="reddit_oauth_missing",
                loadout="social",
                modules=["platform.reddit.oauth"],
                weight="credentialed_medium",
                note="Configure a Reddit bearer token or app-only client id/secret pair for durable Reddit reads; public fallback may still work.",
            )
        )

    if (
        "platform.threads" in [attempt.module for attempt in attempts]
        and "THREADS_ACCESS_TOKEN not configured" in attempt_reasons
    ) or any(attempt.module == "platform.threads.public" and attempt.status in {"blocked", "error"} for attempt in attempts):
        suggestions.append(
            _suggestion(
                action="configure_credentials",
                reason="threads_token_missing",
                loadout="social",
                modules=["platform.threads"],
                weight="credentialed_medium",
                note="Configure AGENTLAS_THREADS_ACCESS_TOKEN or THREADS_ACCESS_TOKEN for official Threads Graph API reads.",
            )
        )

    if "AGENTLAS_JINA_API_KEY or JINA_API_KEY not configured" in attempt_reasons:
        suggestions.append(
            _suggestion(
                action="configure_credentials",
                reason="jina_key_missing",
                loadout="full",
                modules=["search.jina"],
                weight="external_light",
                note="Configure AGENTLAS_JINA_API_KEY or JINA_API_KEY only when external search disclosure is acceptable.",
            )
        )

    suggestions = _dedupe_suggestions(suggestions)
    return {
        "status": "suggested" if suggestions else "none",
        "auto_escalated": False,
        "suggestions": suggestions,
    }


def _suggestion(
    *,
    action: str,
    reason: str,
    loadout: str,
    modules: list[str],
    weight: str,
    note: str,
) -> dict[str, object]:
    modules = _dedupe([module for module in modules if module])
    return {
        "action": action,
        "reason": reason,
        "loadout": loadout,
        "modules": modules,
        "max_weight": weight,
        "request_patch": _request_patch(loadout=loadout, modules=modules, weight=weight),
        "approval_required": _approval_required(action=action, modules=modules),
        "run_after_config": action in {"try_loadout", "allow_module"},
        "auto_apply": False,
        "safety_boundary": "advisory_only",
        "note": note,
    }


def _request_patch(*, loadout: str, modules: list[str], weight: str) -> dict[str, object]:
    patch: dict[str, object] = {
        "loadout": loadout,
        "allowed_modules": modules,
        "max_weight": weight,
    }
    if any(module.startswith("browser.") for module in modules) or weight == "browser_heavy":
        patch["depth"] = "deep"
    return patch


def _approval_required(*, action: str, modules: list[str]) -> bool:
    return action in {"consider_external_search", "operator_approval_required"} or any(
        module.startswith("browser.") for module in modules
    )


def _has_http_block(attempts: list[ResearchAttempt]) -> bool:
    for attempt in attempts:
        if attempt.module != "read.http" or attempt.status != "blocked":
            continue
        if attempt.reason.startswith(("blocked:", "auth_required:", "rate_limited:")):
            return True
    return False


def _public_routes_stopped_at_wall(attempts: list[ResearchAttempt]) -> bool:
    public_modules = {
        "platform.reddit",
        "platform.threads.public",
        "read.http",
        "read.insane_fetch",
        "read.jina",
    }
    boundary_prefixes = (
        "auth_required",
        "blocked",
        "rate_limited",
        "unsupported_threads_public_lookup",
        "public_fetch_failed",
    )
    for attempt in attempts:
        if attempt.module not in public_modules or attempt.status not in {"blocked", "error"}:
            continue
        if attempt.reason.startswith(boundary_prefixes):
            return True
    return False


def _needs_search_sources(request: ResearchRequest, search_candidate_total: int) -> bool:
    return request.intent in {"search", "gather"} and search_candidate_total == 0


def _dedupe_suggestions(suggestions: list[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict[str, object]] = []
    for suggestion in suggestions:
        modules = ",".join(str(module) for module in suggestion.get("modules", []))
        key = (str(suggestion.get("action", "")), str(suggestion.get("reason", "")), modules)
        if key in seen:
            continue
        seen.add(key)
        out.append(suggestion)
    return out


def _deep_read_enabled(request: ResearchRequest, source_hint: str) -> bool:
    if str(request.depth).lower() != "deep":
        return False
    if not any(module.startswith("browser.") for module in request.allowed_modules):
        return False
    parsed = urlsplit(source_hint)
    return parsed.scheme.lower() in {"http", "https"}


def _adapter_is_browser(adapter: Any) -> bool:
    manifest = getattr(adapter, "manifest", None)
    return str(getattr(manifest, "slot", "") or "").lower() == "browser" or str(getattr(adapter, "module_id", "")).startswith("browser.")


def _unmounted_browser_candidate(adapter: Any, reason: str) -> bool:
    return _adapter_is_browser(adapter) and reason == "not_in_allowed_modules"


def _result_is_browser(result: ResearchResult, adapter: Any) -> bool:
    return result.platform == "browser" or _adapter_is_browser(adapter)
