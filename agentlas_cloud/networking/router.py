"""Deterministic local-first router (no LLM).

Pipeline (docs/hephaestus-network-2.0.md):
1. explicit command/alias match
2. project-local .agentlas/routing-overrides.json
3. score local routing cards (only routing_ready/trusted cards can auto-route)
4. risk / ambiguity / privacy gates
5. high confidence + low risk → route; medium → clarify; none → Hub fallback
6. Hub has no match → propose building a new agent (meta-agent modes)

Every decision writes a routing receipt. Raw prompts are never persisted and
never sent to the Hub.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .approvals import build_approval_request, consume_per_call_grants, missing_grants, required_approvals
from .bootstrap import default_routing_policy, networking_home, read_json
from .card_lint import effective_status, lint_card
from .card_store import load_global_cards
from .hub_fallback import search_hub
from .memory import load_profile, profile_adjustment, redact_tokens
from .pipeline import plan_pipeline
from .receipts import write_receipt
from .tokenize import has_hangul, snake_tokens, token_set, tokenize, word_token_set

RISK_KEYWORDS: dict[str, set[str]] = {
    "payment": {"결제", "지불", "환불", "청구", "구독결제", "payment", "refund", "billing", "checkout"},
    "delete": {"삭제", "지워", "지우", "전부삭제", "delete", "erase", "wipe"},
    "publish": {"배포", "공개", "발행", "출시", "올려", "업로드", "publish", "release", "deploy", "upload", "push"},
    "private_data_export": {"전송", "내보내", "유출", "보내", "공유", "export", "send", "share"},
}

PRIVATE_TERMS = {
    "메모리", "기억", "개인정보", "비밀", "프라이버시", "대화기록", "트랜스크립트",
    "memory", "memories", "private", "secret", "secrets", "transcript", "personal",
}

CLOUD_TERMS = {"클라우드", "cloud", "허브", "hub", "외부", "온라인", "online"}

# Tokens shared by >= this fraction of all cards carry no routing signal
# (e.g. "team", "평가", "pipeline" in an agent-engineering inventory).
COMMON_TOKEN_DF = 0.15

_LINT_CACHE: dict[str, str] = {}
_INDEX_CACHE: dict[str, dict[str, Any]] = {}


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
    df: dict[str, int] = {}
    for card in cards:
        index = _cached_index(card)
        seen: set[str] = set(index["name"]) | set(index["capabilities"]) | set(index["summary"])
        for trigger_tokens, _words in index["triggers"]:
            seen |= trigger_tokens
        for token in seen:
            df[token] = df.get(token, 0) + 1
    threshold = max(3, int(COMMON_TOKEN_DF * len(cards)))
    return {token for token, count in df.items() if count >= threshold}


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


def _risk_hits(query: str) -> list[str]:
    lowered = query.lower()
    hits: list[str] = []
    for capability, keywords in RISK_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            hits.append(capability)
    return hits


def _privacy_hit(query: str) -> bool:
    lowered = query.lower()
    for term in PRIVATE_TERMS:
        if has_hangul(term):
            if term in lowered:
                return True
        elif re.search(rf"\b{re.escape(term)}\b", lowered):
            return True
    return False


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

    risk_hits = _risk_hits(query)
    privacy = _privacy_hit(query)
    cloud_intent = any(term in query.lower() for term in CLOUD_TERMS)

    if hub_only:
        if privacy:
            return finish(
                {
                    "action": "refuse",
                    "selected": None,
                    "candidates": [],
                    "suggestions": [],
                    "local_routing": "skipped",
                    "approval_request": build_approval_request(
                        ["private_data_export"],
                        "agentlas-hub",
                        "Hub-only routing will not send local/private memory outside this machine without explicit export approval.",
                    ),
                    "reasons": ["hub_only_privacy_block"],
                },
                [],
                ["hub_only_privacy_block"],
            )
        if risk_hits:
            question = (
                f"Hub-only 요청에 고위험 동작({', '.join(risk_hits)})이 포함된 것 같습니다. Hub 검색 전에 대상과 범위를 명확히 해주세요."
                if locale == "ko"
                else f"The Hub-only request appears to include high-risk actions ({', '.join(risk_hits)}). Please clarify the target and scope before Hub search."
            )
            return finish(
                {"action": "clarify", "selected": None, "candidates": [], "suggestions": [], "local_routing": "skipped", "clarify_question": question, "reasons": ["hub_only_high_risk"]},
                [],
                ["hub_only_high_risk"] + risk_hits,
            )
        if use_hub:
            hub = search_hub(sorted(query_tokens), home=base, approved=hub_approved)
            if hub.get("status") == "ok" and hub.get("results"):
                hub_approvals = [] if hub_approved else missing_grants(["cloud_call"], "agentlas-hub", base)
                if not hub_approvals and not hub_approved:
                    consume_per_call_grants(["cloud_call"], "agentlas-hub", base)
                return finish(
                    {
                        "action": "hub_candidates",
                        "selected": None,
                        "candidates": [],
                        "hub": hub,
                        "suggestions": [],
                        "local_routing": "skipped",
                        "approval_request": build_approval_request(hub_approvals, "agentlas-hub", "Using or installing a Hub agent requires your approval before first remote use.")
                        if hub_approvals
                        else None,
                        "reasons": ["hub_only_results_found"],
                    },
                    [],
                    ["hub_only", "hub_results_found"],
                )
            if hub.get("status") == "approval_required":
                return finish(
                    {"action": "hub_fallback", "selected": None, "candidates": [], "hub": hub, "suggestions": [], "local_routing": "skipped", "approval_request": hub.get("approval_request"), "reasons": ["hub_only_requires_approval"]},
                    [],
                    ["hub_only", "hub_approval_required"],
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
        all_approvals = required_approvals(explicit)
        approvals = missing_grants(all_approvals, str(explicit.get("id")), base)
        if all_approvals and not approvals:
            consume_per_call_grants(all_approvals, str(explicit.get("id")), base)
        selected = _selected_payload(explicit, 99.0)
        result: dict[str, Any] = {
            "action": "route",
            "selected": selected,
            "approval_request": build_approval_request(approvals, str(explicit.get("id")), "card declares high-risk capabilities")
            if approvals
            else None,
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
            all_approvals = required_approvals(creator)
            approvals = missing_grants(all_approvals, str(creator.get("id")), base)
            if all_approvals and not approvals:
                consume_per_call_grants(all_approvals, str(creator.get("id")), base)
            return finish(
                {
                    "action": "route",
                    "selected": selected,
                    "approval_request": build_approval_request(approvals, str(creator.get("id")), "card declares high-risk capabilities")
                    if approvals
                    else None,
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

    # Private data + an outbound destination (export verb or cloud/hub/online
    # target) is never routable — explicit export approval comes first.
    # Publish intent alone stays routable behind its approval gate: sanitizing
    # private material BEFORE publishing is a legitimate local task.
    if privacy and ("private_data_export" in risk_hits or cloud_intent):
        return finish(
            {
                "action": "refuse",
                "selected": None,
                "approval_request": build_approval_request(
                    ["private_data_export"],
                    "external",
                    "The request would send local/private memory outside this machine; explicit export approval is required.",
                ),
                "reasons": ["privacy_export_block"],
            },
            [],
            ["privacy_export_block"],
        )

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
        eligible_by_id = {str(card.get("id")): card for card in ready_cards}
        stage_candidates = []
        for stage in plan["stages"]:
            stage_card = eligible_by_id.get(str(stage["card"]))
            all_stage_approvals = required_approvals(stage_card) if stage_card else []
            stage_approvals = missing_grants(all_stage_approvals, str(stage["card"]), base) if stage_card else []
            if all_stage_approvals and not stage_approvals:
                consume_per_call_grants(all_stage_approvals, str(stage["card"]), base)
            stage["approval_request"] = (
                build_approval_request(stage_approvals, str(stage["card"]), "stage capability requires user approval")
                if stage_approvals
                else None
            )
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
        approvals = set(required_approvals(top_card))
        if risk_hits:
            declared = approvals | set(((top_card.get("risk_profile") or {}).get("capabilities_at_risk")) or [])
            undeclared = [hit for hit in risk_hits if hit not in declared]
            if undeclared:
                question = (
                    f"요청에 고위험 동작({', '.join(risk_hits)})이 포함된 것 같지만 선택된 에이전트가 해당 능력을 선언하지 않았습니다. 의도를 명확히 해주세요."
                    if locale == "ko"
                    else f"The request implies high-risk actions ({', '.join(risk_hits)}) the matched agent does not declare. Please clarify the intent."
                )
                return finish(
                    {"action": "clarify", "selected": None, "candidates": candidates, "clarify_question": question, "reasons": ["high_risk_ambiguous"]},
                    candidates,
                    ["high_risk_ambiguous"] + risk_hits,
                )
            approvals |= set(risk_hits)
        if privacy and str(top_card.get("cloud_delegation_policy") or "never") != "never":
            approvals.add("private_data_export")
        selected = _selected_payload(top_card, top_score)
        all_approvals = sorted(approvals)
        pending_approvals = missing_grants(all_approvals, str(top_card.get("id")), base)
        if all_approvals and not pending_approvals:
            consume_per_call_grants(all_approvals, str(top_card.get("id")), base)
        result = {
            "action": "route",
            "selected": selected,
            "candidates": candidates,
            "approval_request": build_approval_request(pending_approvals, str(top_card.get("id")), "high-risk capabilities require user approval before execution")
            if pending_approvals
            else None,
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

    # Ambiguous high-risk request with no local match: clarify before anything
    # leaves the machine (never forward destructive-sounding queries to the Hub).
    if risk_hits:
        question = (
            f"고위험 동작({', '.join(risk_hits)})으로 보이는 요청인데 처리할 로컬 에이전트가 없습니다. 정확히 무엇을 대상으로 어떤 작업을 원하시나요?"
            if locale == "ko"
            else f"This looks like a high-risk request ({', '.join(risk_hits)}) and no local agent matched. What exactly should be affected?"
        )
        return finish(
            {"action": "clarify", "selected": None, "suggestions": suggestions, "clarify_question": question, "reasons": ["high_risk_no_local_match"]},
            [],
            ["high_risk_no_local_match"] + risk_hits,
        )

    # No usable local match → Hub fallback (privacy-gated), then propose-new.
    if privacy:
        return finish(
            {
                "action": "refuse",
                "selected": None,
                "suggestions": suggestions,
                "approval_request": build_approval_request(
                    ["private_data_export"],
                    "agentlas-hub",
                    "The request references local/private memory; it will not be sent to the Hub without explicit export approval.",
                ),
                "reasons": ["privacy_block_local_memory"],
            },
            [],
            ["privacy_block"],
        )

    if use_hub:
        hub = search_hub(sorted(query_tokens), home=base, approved=hub_approved)
        if hub.get("status") == "ok" and hub.get("results"):
            hub_approvals = [] if hub_approved else missing_grants(["cloud_call"], "agentlas-hub", base)
            if not hub_approvals and not hub_approved:
                consume_per_call_grants(["cloud_call"], "agentlas-hub", base)
            return finish(
                {
                    "action": "hub_candidates",
                    "selected": None,
                    "hub": hub,
                    "suggestions": suggestions,
                    "approval_request": build_approval_request(hub_approvals, "agentlas-hub", "Using or installing a Hub agent requires your approval before first remote use.")
                    if hub_approvals
                    else None,
                    "reasons": ["hub_results_found"],
                },
                [],
                ["hub_fallback"],
            )
        if hub.get("status") == "approval_required":
            return finish(
                {"action": "hub_fallback", "selected": None, "hub": hub, "suggestions": suggestions, "approval_request": hub.get("approval_request"), "reasons": ["hub_requires_approval"]},
                [],
                ["hub_approval_required"],
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
