"""Deterministic local-first router (no LLM).

Pipeline (docs/hephaestus-network-2.0.md):
1. explicit command/alias match
2. project-local .agentlas/routing-overrides.json
3. score local routing cards (only routing_ready/trusted cards can auto-route)
4. ambiguity / quality checks
5. high confidence → route; medium → clarify; none → Hub fallback
6. Hub has no match → propose building a new agent (meta-agent modes)

Every decision writes a routing receipt. Raw prompts are never persisted and
never sent to the Hub.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .bootstrap import default_routing_policy, networking_home, read_json
from .card_lint import effective_status, lint_card
from .card_store import load_global_cards
from .hub_fallback import search_hub
from .memory import load_profile, profile_adjustment, redact_tokens
from .pipeline import plan_pipeline
from .receipts import write_receipt
from .tokenize import has_hangul, snake_tokens, token_set, tokenize, word_token_set

# Tokens shared by >= this fraction of all cards carry no routing signal
# (e.g. "team", "평가", "pipeline" in an agent-engineering inventory).
COMMON_TOKEN_DF = 0.15

_LINT_CACHE: dict[str, str] = {}
_INDEX_CACHE: dict[str, dict[str, Any]] = {}
_COMMON_CACHE: dict[str, set[str]] = {}


def _card_key(card: dict[str, Any]) -> str:
    return f"{card.get('id')}::{(card.get('integrity') or {}).get('content_hash')}::{card.get('stale')}"


def _cached_status(card: dict[str, Any]) -> str:
    key = _card_key(card)
    if key not in _LINT_CACHE:
        _LINT_CACHE[key] = effective_status(card)
    return _LINT_CACHE[key]


def _cached_index(card: dict[str, Any]) -> dict[str, Any]:
    key = _card_key(card)
    if key not in _INDEX_CACHE:
        _INDEX_CACHE[key] = _card_index(card)
    return _INDEX_CACHE[key]


def _common_tokens(cards: list[dict[str, Any]]) -> set[str]:
    signature = "|".join(sorted(_card_key(card) for card in cards))
    if signature in _COMMON_CACHE:
        return _COMMON_CACHE[signature]
    df: dict[str, int] = {}
    for card in cards:
        index = _cached_index(card)
        seen: set[str] = set(index["name"]) | set(index["capabilities"]) | set(index["summary"])
        for trigger_tokens, _words in index["triggers"]:
            seen |= trigger_tokens
        for token in seen:
            df[token] = df.get(token, 0) + 1
    threshold = max(3, int(COMMON_TOKEN_DF * len(cards)))
    common = {token for token, count in df.items() if count >= threshold}
    _COMMON_CACHE[signature] = common
    return common


def _card_index(card: dict[str, Any]) -> dict[str, Any]:
    # Name matching is word-level only — bigram fuzz on names triples a single
    # shared word ("파이프라인") into a near-route score.
    name_tokens = word_token_set(
        " ".join(
            [str(card.get("name") or ""), str(card.get("name_ko") or ""), " ".join(card.get("aliases") or [])]
        )
    )
    tail = str(card.get("id") or "").split("/")[-1]
    name_tokens |= snake_tokens(tail)
    # Each trigger keeps (all tokens incl. bigrams, word count). Bigrams add
    # fuzzy recall to the numerator; the denominator stays word-based so
    # Korean coverage is not diluted by its own bigrams.
    triggers = []
    for entry in card.get("trigger_examples") or []:
        if isinstance(entry, dict) and entry.get("text"):
            tokens = token_set(str(entry["text"]))
            words = word_token_set(str(entry["text"]))
            if tokens:
                triggers.append((tokens, words))
    antis = []
    for entry in card.get("anti_triggers") or []:
        if isinstance(entry, dict) and entry.get("text"):
            tokens = token_set(str(entry["text"]))
            words = word_token_set(str(entry["text"]))
            if tokens:
                antis.append((tokens, max(1, len(words))))
    capability_tokens: set[str] = set()
    for capability in card.get("capabilities") or []:
        capability_tokens |= snake_tokens(str(capability))
    summary_tokens = token_set(f"{card.get('summary') or ''} {card.get('summary_ko') or ''}")
    return {
        "name": name_tokens,
        "triggers": triggers,
        "antis": antis,
        "capabilities": capability_tokens,
        "summary": summary_tokens,
    }


def _score_card(
    card: dict[str, Any],
    query_tokens: set[str],
    profile: dict[str, Any],
    query_is_korean: bool,
    t_high: float,
    common: set[str] | None = None,
    min_shared_words: int = 2,
) -> tuple[float, list[str]]:
    index = _cached_index(card)
    common = common or set()
    distinctive = query_tokens - common
    reasons: list[str] = []
    score = 0.0

    # Only distinctive tokens (rare across the card inventory) carry signal in
    # name/capability/summary matching — a token like "team" or "평가" that
    # appears on dozens of cards must not accumulate into a route.
    name_hits = len(distinctive & index["name"])
    if name_hits == 1:
        score += 1.5
        reasons.append("name match x1 (weak)")
    elif name_hits:
        score += min(3.0 * name_hits, 9.0)
        reasons.append(f"name match x{name_hits}")

    # Trigger scoring: substantive overlap only (two shared tokens or half the
    # trigger covered). Overlap made of inventory-common tokens is damped to
    # 40% — unless the query nearly restates the trigger verbatim (ratio >=
    # 0.9), which is a strong signal even with common words.
    # Eligibility counts WHOLE WORDS only — a single shared word inflated by
    # its own bigrams ("파이프라인" → 5 tokens) must not qualify a trigger.
    # Bigrams still contribute to the coverage ratio once a trigger qualifies.
    weighted: list[float] = []
    for trigger_tokens, trigger_word_set in index["triggers"]:
        shared = query_tokens & trigger_tokens
        shared_words = query_tokens & trigger_word_set
        word_count = max(1, len(trigger_word_set))
        ratio = min(1.0, len(shared) / word_count)
        if len(shared_words) < min_shared_words:
            continue
        distinct_fraction = len(shared - common) / len(shared) if shared else 0.0
        damp = 1.0 if ratio >= 0.9 else (0.4 + 0.6 * distinct_fraction)
        weighted.append(ratio * damp)
    weighted.sort(reverse=True)
    if weighted and weighted[0] > 0:
        score += 10.0 * weighted[0]
        if len(weighted) > 1 and weighted[1] > 0:
            score += 5.0 * weighted[1]
        reasons.append(f"trigger overlap {weighted[0]:.2f}")

    capability_hits = len(distinctive & index["capabilities"])
    if capability_hits:
        score += min(2.0 * capability_hits, 4.0)
        reasons.append(f"capability match x{capability_hits}")

    summary_hits = len(distinctive & index["summary"])
    if summary_hits:
        score += min(1.0 * summary_hits, 2.0)

    anti_penalty = 0.0
    for anti_tokens, anti_words in index["antis"]:
        shared = query_tokens & anti_tokens
        ratio = min(1.0, len(shared) / anti_words)
        if (len(shared - common) >= 1 and ratio >= 0.6) or len(shared - common) >= 3:
            anti_penalty -= 8.0
    if anti_penalty:
        anti_penalty = max(anti_penalty, -16.0)
        score += anti_penalty
        reasons.append("anti-trigger hit")

    capability_count = len(card.get("capabilities") or [])
    if capability_count > 20:
        score -= 4.0
        reasons.append("breadth penalty (>20 capabilities)")
    elif capability_count > 12:
        score -= 2.0
        reasons.append("breadth penalty (>12 capabilities)")

    adjustment = profile_adjustment(profile, str(card.get("id")))
    if adjustment:
        score += adjustment
        reasons.append(f"user profile adjustment {adjustment:+.1f}")

    locale_ready = ((card.get("locale_coverage") or {}).get("ready")) or ["en"]
    if query_is_korean and "ko" not in locale_ready:
        capped = min(score, t_high - 0.01)
        if capped < score:
            score = capped
            reasons.append("locale cap: card not ko-ready, forcing clarify ceiling")

    return round(score, 3), reasons


def _explicit_match(query: str, cards: list[dict[str, Any]]) -> dict[str, Any] | None:
    stripped = query.strip()
    lowered = stripped.lower()
    for card in cards:
        command = str(((card.get("entrypoints") or {}).get("canonical_command")) or "").lower()
        aliases = [str(alias).lower() for alias in card.get("aliases") or []]
        candidates = [alias for alias in [command, *aliases] if alias]
        for alias in candidates:
            if lowered == alias or lowered.startswith(alias + " "):
                return card
    return None


def _project_override(query: str, project_dir: Path, cards_by_id: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    overrides_path = project_dir / ".agentlas" / "routing-overrides.json"
    payload = read_json(overrides_path, default=None)
    if not isinstance(payload, dict):
        return None
    lowered = query.lower()
    for entry in payload.get("overrides") or []:
        if not isinstance(entry, dict):
            continue
        needle = str(entry.get("contains") or "").lower()
        card_id = str(entry.get("card_id") or "")
        if needle and needle in lowered and card_id in cards_by_id:
            return cards_by_id[card_id]
    return None


def _selected_payload(card: dict[str, Any], score: float) -> dict[str, Any]:
    return {
        "id": card.get("id"),
        "type": card.get("type"),
        "name": card.get("name"),
        "name_ko": card.get("name_ko"),
        "score": score,
        "routing_status": card.get("routing_status"),
        "entrypoints": card.get("entrypoints") or {},
        "required_plugins": card.get("required_plugins") or [],
        "risk_profile": card.get("risk_profile") or {},
        "source": (card.get("source") or {}).get("ref"),
    }


def route_request(
    query: str,
    home: Path | str | None = None,
    project_dir: Path | str = ".",
    runtime: str | None = None,
    use_hub: bool = True,
    hub_approved: bool = False,
    hub_only: bool = False,
    hop_count: int = 0,
    router_chain: list[str] | None = None,
) -> dict[str, Any]:
    base = Path(home) if home else networking_home()
    project = Path(project_dir)
    policy = read_json(base / "policies" / "routing-policy.json", default=default_routing_policy()) or default_routing_policy()
    t_high = float(policy.get("t_high", 6.0))
    t_low = float(policy.get("t_low", 2.0))
    margin = float(policy.get("margin", 1.5))
    max_hops = int(policy.get("max_hops", 2))
    locale = "ko" if has_hangul(query) else "en"
    raw_tokens = tokenize(query)
    query_tokens = set(redact_tokens(raw_tokens)) - {"[redacted]"}
    chain = router_chain or ["hephaestus-network"]

    def finish(result: dict[str, Any], candidates: list[dict[str, Any]], reasons: list[str]) -> dict[str, Any]:
        receipt_id = write_receipt(
            action=result["action"],
            query_tokens=sorted(query_tokens),
            candidates=candidates,
            selected=(result.get("selected") or {}).get("id"),
            reasons=reasons,
            locale=locale,
            runtime=runtime,
            hop_count=hop_count,
            router_chain=chain,
            home=base,
        )
        result["receipt_id"] = receipt_id
        result["locale"] = locale
        result["query_tokens"] = sorted(query_tokens)
        return result

    if hop_count > max_hops:
        return finish(
            {"action": "refuse", "selected": None, "reasons": [f"router loop detected (hop_count={hop_count} > {max_hops})"]},
            [],
            ["loop_guard"],
        )

    if hub_only:
        if use_hub:
            hub = search_hub(sorted(query_tokens), home=base, approved=True)
            if hub.get("status") == "clarify":
                return finish(
                    {
                        "action": "clarify",
                        "selected": None,
                        "candidates": [],
                        "hub": hub,
                        "suggestions": hub.get("suggestions") or [],
                        "clarify_question": hub.get("questionKo") or hub.get("question"),
                        "local_routing": "skipped",
                        "reasons": ["hub_only_low_confidence"],
                    },
                    [],
                    ["hub_only", "hub_clarify"],
                )
            if hub.get("status") == "ok" and hub.get("results"):
                return finish(
                    {
                        "action": "hub_candidates",
                        "selected": None,
                        "candidates": [],
                        "hub": hub,
                        "suggestions": [],
                        "local_routing": "skipped",
                        "reasons": ["hub_only_results_found"],
                    },
                    [],
                    ["hub_only", "hub_results_found"],
                )
            return finish(
                {"action": "propose_new", "selected": None, "candidates": [], "hub": hub, "suggestions": [], "local_routing": "skipped", "reasons": ["hub_only_no_match_or_unavailable"]},
                [],
                ["hub_only", "propose_new"],
            )
        return finish(
            {"action": "propose_new", "selected": None, "candidates": [], "suggestions": [], "local_routing": "skipped", "reasons": ["hub_only_requested_but_hub_disabled"]},
            [],
            ["hub_only_hub_disabled"],
        )

    cards, quarantined = load_global_cards(base)
    cards_by_id = {str(card.get("id")): card for card in cards}
    statuses = {str(card.get("id")): _cached_status(card) for card in cards}
    usable = [card for card in cards if statuses[str(card.get("id"))] not in ("quarantined", "stale")]

    explicit = _explicit_match(query, usable)
    if explicit is None:
        explicit = _project_override(query, project, cards_by_id)
        if explicit is not None and statuses.get(str(explicit.get("id"))) in ("quarantined", "stale"):
            explicit = None
    if explicit is not None:
        selected = _selected_payload(explicit, 99.0)
        result: dict[str, Any] = {
            "action": "route",
            "selected": selected,
            "reasons": ["explicit command/alias or project override match"],
        }
        return finish(result, [selected], ["explicit_match"])

    # Short, generic creation requests ("새 에이전트 만들어줘") belong to the
    # meta-agent creator — deterministic intent rule, ahead of card scoring.
    create_words = {"만들", "생성", "새로", "create", "build", "make"}
    agent_words = {"에이전트", "agent", "팀", "team", "플러그인", "plugin"}
    lowered_query = query.lower()
    query_words = word_token_set(query)
    if (
        len(query_words) <= 3
        and any(word in lowered_query for word in create_words)
        and (query_words & agent_words or "에이전트" in lowered_query)
    ):
        creator = next(
            (
                card
                for card in usable
                if "create_single_agent" in (card.get("capabilities") or [])
                or "/hephaestus" in (card.get("aliases") or [])
            ),
            None,
        )
        if creator is not None:
            selected = _selected_payload(creator, 98.0)
            return finish(
                {
                    "action": "route",
                    "selected": selected,
                    "reasons": ["creation intent → meta-agent creator"],
                },
                [selected],
                ["creation_intent"],
            )

    profile = load_profile(base)
    common = _common_tokens(usable)
    # A one-content-word query ("웹사이트 만들어줘") can never share two words;
    # scale the trigger qualification down to the query's own word count.
    min_shared_words = min(2, max(1, len(word_token_set(query))))
    scored: list[tuple[float, list[str], dict[str, Any]]] = []
    for card in usable:
        score, reasons = _score_card(
            card, query_tokens, profile, locale == "ko", t_high, common=common, min_shared_words=min_shared_words
        )
        if score > 0:
            scored.append((score, reasons, card))
    scored.sort(key=lambda item: item[0], reverse=True)

    auto_eligible = [item for item in scored if statuses[str(item[2].get("id"))] in ("routing_ready", "trusted")]
    suggestions = [
        {"id": item[2].get("id"), "name": item[2].get("name"), "score": item[0], "status": statuses[str(item[2].get("id"))]}
        for item in scored[:5]
        if statuses[str(item[2].get("id"))] not in ("routing_ready", "trusted")
    ]
    candidates = [
        {"id": item[2].get("id"), "name": item[2].get("name"), "score": item[0], "status": statuses[str(item[2].get("id"))]}
        for item in auto_eligible[: max(3, int(policy.get("clarify_max_candidates", 3)))]
    ]

    # Pipeline routing (Network 2.0 feature): a plan-anchored composite request
    # ("기획부터 구현, QA까지") becomes a multi-team stage plan chained by the
    # cards' produces/consumes artifact contracts. Takes precedence over a
    # single route; single-intent requests are never decomposed.
    # Stage producers don't need to match the query text themselves — any
    # routing_ready card with the right artifact contract is a candidate.
    ready_cards = [card for card in usable if statuses[str(card.get("id"))] in ("routing_ready", "trusted")]
    score_by_id = {str(item[2].get("id")): item[0] for item in auto_eligible}
    plan = plan_pipeline(query, ready_cards, lambda card: score_by_id.get(str(card.get("id")), 0.0))
    if plan is not None:
        stage_candidates = []
        for stage in plan["stages"]:
            stage_candidates.append({"id": stage["card"], "score": score_by_id.get(str(stage["card"]), 0.0)})
        chain = chain + [f"pipeline:{plan['pipeline_id']}"]
        return finish(
            {"action": "pipeline", "selected": None, **plan, "reasons": ["plan-anchored composite request → multi-team pipeline plan"]},
            stage_candidates,
            ["pipeline_plan"],
        )

    top_score = auto_eligible[0][0] if auto_eligible else 0.0
    second_score = auto_eligible[1][0] if len(auto_eligible) > 1 else 0.0

    # Route when confident: clear absolute score, and either a clear margin or
    # a second candidate that is mere noise relative to the winner.
    if auto_eligible and top_score >= t_high and (
        (top_score - second_score) >= margin or second_score <= top_score * 0.7
    ):
        top_card = auto_eligible[0][2]
        selected = _selected_payload(top_card, top_score)
        result = {
            "action": "route",
            "selected": selected,
            "candidates": candidates,
            "reasons": auto_eligible[0][1],
        }
        return finish(result, candidates, ["confident_local_match"])

    if auto_eligible and top_score >= t_low:
        names = ", ".join(str(item["id"]) for item in candidates)
        question = (
            f"어느 에이전트를 쓸까요? 후보: {names}"
            if locale == "ko"
            else f"Which agent should handle this? Candidates: {names}"
        )
        return finish(
            {"action": "clarify", "selected": None, "candidates": candidates, "suggestions": suggestions, "clarify_question": question, "reasons": ["low_confidence_margin"]},
            candidates,
            ["clarify_threshold"],
        )

    # No usable local match → Hub fallback, then propose-new.
    if use_hub:
        hub = search_hub(sorted(query_tokens), home=base, approved=True)
        if hub.get("status") == "clarify":
            return finish(
                {
                    "action": "clarify",
                    "selected": None,
                    "hub": hub,
                    "suggestions": hub.get("suggestions") or suggestions,
                    "clarify_question": hub.get("questionKo") or hub.get("question"),
                    "reasons": ["hub_low_confidence"],
                },
                [],
                ["hub_fallback", "hub_clarify"],
            )
        if hub.get("status") == "ok" and hub.get("results"):
            return finish(
                {
                    "action": "hub_candidates",
                    "selected": None,
                    "hub": hub,
                    "suggestions": suggestions,
                    "reasons": ["hub_results_found"],
                },
                [],
                ["hub_fallback"],
            )
        return finish(
            {"action": "propose_new", "selected": None, "hub": hub, "suggestions": suggestions, "reasons": ["no local match; hub unavailable or empty — propose building a new agent via /hephaestus"]},
            [],
            ["propose_new"],
        )

    return finish(
        {"action": "propose_new", "selected": None, "suggestions": suggestions, "reasons": ["no auto-eligible local match (hub disabled)"]},
        [],
        ["local_only_no_match"],
    )
