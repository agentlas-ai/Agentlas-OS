"""Named module loadouts for the Agentlas Research Engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .contracts import ResearchRequest


AUTO_PUBLIC_WEB_MODULES = (
    "search.ddg_html",
    "search.news_rss",
    "read.http",
    "platform.reddit",
)
AUTO_REDDIT_MODULES = ("platform.reddit",)
AUTO_THREADS_MODULES = ("platform.threads.public",)
AUTO_GITHUB_MODULES = ("search.github_repos",)
AUTO_EXTERNAL_HINT_MODULES = {
    "search:jina:": "search.jina",
    "jina:": "read.jina",
}
GITHUB_SEARCH_KEYWORDS = ("github", "깃헙", "깃허브", "repo:", "repository", "repositories", "open source", "오픈소스")


@dataclass(frozen=True)
class ResearchLoadout:
    name: str
    description: str
    allowed_modules: tuple[str, ...] = field(default_factory=tuple)
    max_weight: str = "light"
    use_when: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "allowed_modules": list(self.allowed_modules),
            "max_weight": self.max_weight,
            "use_when": self.use_when,
            "notes": list(self.notes),
        }


LOADOUTS: dict[str, ResearchLoadout] = {
    "auto": ResearchLoadout(
        name="auto",
        description="Source-aware default: public web by default, public social fallbacks for social hints, never browser or social APIs by default.",
        allowed_modules=(),
        max_weight="source_aware",
        use_when="Default SDK/CLI behavior when the caller has not selected a heavier loadout.",
        notes=(
            "Explicit allowed_modules keep caller policy unchanged.",
            "The adaptive public-route fetch chain requires public-web/social/browser/full or explicit allow.",
            "Official social APIs require social/full loadout or explicit module allow.",
            "Browser modules require browser/full loadout or explicit allow.",
        ),
    ),
    "safe": ResearchLoadout(
        name="safe",
        description="Light public search and static reads only.",
        allowed_modules=("search.ddg_html", "search.news_rss", "read.http", "platform.reddit"),
        max_weight="adaptive_medium",
        use_when="Fast evidence for Stormbreaker or normal web reads.",
        notes=("Reddit is public fallback only; OAuth remains opt-in through social/full or explicit allow.",),
    ),
    "public-web": ResearchLoadout(
        name="public-web",
        description="Safe readers plus the adaptive public-route fetch chain.",
        allowed_modules=(
            "search.ddg_html",
            "search.news_rss",
            "search.github_repos",
            "read.http",
            "platform.reddit",
            "platform.threads.public",
            "read.insane_fetch",
        ),
        max_weight="adaptive_medium",
        use_when="Blocked public pages, feeds, metadata, and RSS fallbacks.",
        notes=("The adaptive chain stops at login and paywall boundaries.", "GitHub search only auto-fans out when GitHub hints are present."),
    ),
    "social": ResearchLoadout(
        name="social",
        description="Public web plus first-class social platform cartridges.",
        allowed_modules=(
            "search.ddg_html",
            "search.news_rss",
            "search.github_repos",
            "platform.reddit.oauth",
            "platform.reddit",
            "platform.threads",
            "platform.threads.public",
            "read.insane_fetch",
        ),
        max_weight="credentialed_medium",
        use_when="Operator-approved Reddit or Threads research where official platform APIs are explicitly allowed.",
        notes=("Reddit OAuth and Threads Graph API use configured tokens; public fallbacks stay available.",),
    ),
    "browser": ResearchLoadout(
        name="browser",
        description="Public readers plus local browser hardpoints for JS-heavy pages.",
        allowed_modules=(
            "search.news_rss",
            "search.ddg_html",
            "search.github_repos",
            "read.http",
            "read.insane_fetch",
            "read.jina",
            "browser.playwright_mcp",
            "browser.browser_use",
            "browser.stagehand",
            "browser.steel",
            "browser.hyperagent",
            "browser.agent_cli",
            "browser.browseros",
        ),
        max_weight="browser_heavy",
        use_when="Pages that need a real browser snapshot or external markdown reader.",
        notes=("Browser modules are optional and report module_unavailable when missing.",),
    ),
    "full": ResearchLoadout(
        name="full",
        description="All built-in cartridges, including external and browser modules.",
        allowed_modules=(
            "search.news_rss",
            "search.ddg_html",
            "search.github_repos",
            "search.jina",
            "read.http",
            "read.insane_fetch",
            "read.jina",
            "platform.reddit.oauth",
            "platform.reddit",
            "platform.threads",
            "platform.threads.public",
            "browser.playwright_mcp",
            "browser.browser_use",
            "browser.stagehand",
            "browser.steel",
            "browser.hyperagent",
            "browser.agent_cli",
            "browser.browseros",
        ),
        max_weight="browser_heavy",
        use_when="Operator-approved deep research where external services and browser modules are acceptable.",
        notes=("Configured credentials and installed binaries are still required per module.",),
    ),
}


def apply_loadout(request: ResearchRequest) -> ResearchRequest:
    loadout = LOADOUTS.get(request.loadout)
    if loadout is None:
        return request
    if request.loadout == "auto":
        return _apply_auto_loadout(request)
    merged_allowed = _dedupe(list(loadout.allowed_modules) + list(request.allowed_modules))
    merged_forbidden = _dedupe(list(request.forbidden_modules))
    max_weight = request.max_weight or loadout.max_weight
    return ResearchRequest(
        query=request.query,
        intent=request.intent,
        source_hints=list(request.source_hints),
        loadout=request.loadout,
        freshness=request.freshness,
        depth=request.depth,
        follow_results=request.follow_results,
        query_variants=list(request.query_variants),
        allowed_modules=merged_allowed,
        forbidden_modules=merged_forbidden,
        privacy_scope=request.privacy_scope,
        max_weight=max_weight,
        max_cost=dict(request.max_cost),
    )


def loadout_catalog() -> list[dict[str, object]]:
    return [loadout_policy(name) for name in ("auto", "safe", "public-web", "social", "browser", "full")]


def loadout_policy(loadout_name: str) -> dict[str, object]:
    loadout = LOADOUTS.get(loadout_name)
    if loadout is None:
        return {"name": loadout_name, "status": "unknown", "allowed_modules": []}
    payload = loadout.to_dict()
    payload["status"] = "active" if loadout_name != "auto" else "source_aware_default"
    return payload


def loadout_names() -> list[str]:
    return list(LOADOUTS)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _apply_auto_loadout(request: ResearchRequest) -> ResearchRequest:
    if request.allowed_modules:
        return request
    allowed_modules = _auto_allowed_modules(request)
    allowed_modules = [module for module in allowed_modules if module not in set(request.forbidden_modules)]
    return ResearchRequest(
        query=request.query,
        intent=request.intent,
        source_hints=list(request.source_hints),
        loadout=request.loadout,
        freshness=request.freshness,
        depth=request.depth,
        follow_results=request.follow_results,
        query_variants=list(request.query_variants),
        allowed_modules=allowed_modules,
        forbidden_modules=list(request.forbidden_modules),
        privacy_scope=request.privacy_scope,
        max_weight=request.max_weight or _auto_max_weight(request, allowed_modules),
        max_cost=dict(request.max_cost),
    )


def _auto_allowed_modules(request: ResearchRequest) -> list[str]:
    modules = list(AUTO_PUBLIC_WEB_MODULES)
    if _is_github_hint(request.query.lower()):
        modules.extend(AUTO_GITHUB_MODULES)
    for source_hint in request.source_hints:
        lowered = source_hint.lower().strip()
        if _is_reddit_hint(lowered):
            modules.extend(AUTO_REDDIT_MODULES)
        if _is_threads_hint(lowered):
            modules.extend(AUTO_THREADS_MODULES)
        if _is_github_hint(lowered):
            modules.extend(AUTO_GITHUB_MODULES)
        for prefix, module in AUTO_EXTERNAL_HINT_MODULES.items():
            if lowered.startswith(prefix):
                modules.append(module)
    return _dedupe(modules)


def _auto_max_weight(request: ResearchRequest, allowed_modules: list[str]) -> str:
    if any(module in allowed_modules for module in ("platform.reddit.oauth", "platform.threads")):
        return "credentialed_medium"
    if "read.insane_fetch" in allowed_modules:
        return "adaptive_medium"
    if _has_public_social_hint(request) and any(module in allowed_modules for module in ("platform.reddit", "platform.threads.public")):
        return "adaptive_medium"
    if any(module in allowed_modules for module in ("search.jina", "read.jina")):
        return "external_light"
    return "light"


def _has_public_social_hint(request: ResearchRequest) -> bool:
    return any(_is_reddit_hint(hint.lower().strip()) or _is_threads_hint(hint.lower().strip()) for hint in request.source_hints)


def _is_github_hint(value: str) -> bool:
    return any(keyword in value for keyword in GITHUB_SEARCH_KEYWORDS)


def _is_threads_hint(source_hint: str) -> bool:
    return source_hint.startswith("threads:")


def _is_reddit_hint(source_hint: str) -> bool:
    if source_hint.startswith("reddit:"):
        return True
    host = (urlsplit(source_hint).hostname or "").lower()
    host = host[4:] if host.startswith("www.") else host
    return host in {"reddit.com", "old.reddit.com"} or host.endswith(".reddit.com")
