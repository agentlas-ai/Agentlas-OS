"""Deterministic Hub-first/public router with explicit local debug mode (no LLM).

Pipeline (docs/hephaestus-network-2.0.md):
1. explicit command/alias match
2. project-local .agentlas/routing-overrides.json
3. public/default calls search Hub only; explicit local debug mode scores local routing cards
4. ambiguity / quality checks
5. high confidence → route; medium → clarify; none → Hub candidate/proposal
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
from .domains import classify_domains
from .hub_fallback import search_hub
from .memory import load_profile, profile_adjustment, redact_tokens
from .pipeline import detect_stages, plan_pipeline
from .playbooks import build_memory_playbook_context
from .policy import evaluate_local_operator_policy
from .receipts import write_receipt
from .router_agent_call import router_escalation
from .tokenize import has_hangul, snake_tokens, token_set, tokenize, word_token_set, word_tokens

# Optional semantic signal. The ontology ships a deterministic, offline hashed
# vector adapter (no provider key, Korean-aware bigrams). It's a recall enhancer
# layered on top of lexical scoring, not a replacement — and routing must keep
# working if it's ever unavailable, so the import degrades to None.
try:  # pragma: no cover - exercised indirectly
    from ontology.embeddings import LocalHashingVectorAdapter, cosine_similarity as _cosine_similarity

    _VECTOR_ADAPTER: Any = LocalHashingVectorAdapter()
except Exception:  # pragma: no cover
    _VECTOR_ADAPTER = None

    def _cosine_similarity(left: Any, right: Any) -> float:  # type: ignore[misc]
        return 0.0


# Tokens shared by >= this fraction of all cards carry no routing signal
# (e.g. "team", "평가", "pipeline" in an agent-engineering inventory).
COMMON_TOKEN_DF = 0.15

_LINT_CACHE: dict[str, str] = {}
_INDEX_CACHE: dict[str, dict[str, Any]] = {}
_COMMON_CACHE: dict[str, set[str]] = {}
_EMBED_CACHE: dict[str, list[float] | None] = {}


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


def _card_vector(card: dict[str, Any]) -> list[float] | None:
    """Cached semantic vector for a card (name + summary + capabilities), or
    None when the embedding adapter is unavailable."""
    if _VECTOR_ADAPTER is None:
        return None
    key = _card_key(card)
    if key not in _EMBED_CACHE:
        text = " ".join(
            [
                str(card.get("name") or ""),
                str(card.get("name_ko") or ""),
                str(card.get("summary") or ""),
                str(card.get("summary_ko") or ""),
                " ".join(str(c) for c in (card.get("capabilities") or [])),
            ]
        ).strip()
        try:
            _EMBED_CACHE[key] = _VECTOR_ADAPTER.embed(text) if text else None
        except Exception:  # pragma: no cover - never let embedding break routing
            _EMBED_CACHE[key] = None
    return _EMBED_CACHE[key]


def _embed_query(query: str) -> list[float] | None:
    if _VECTOR_ADAPTER is None or not query.strip():
        return None
    try:
        return _VECTOR_ADAPTER.embed(query)
    except Exception:  # pragma: no cover
        return None


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
    # Card domains: trust the explicit `domains` field when present (set by card
    # generation/backfill), else infer from the card's own text. Either way the
    # router treats it as a coarse semantic frame for the coherence guard.
    explicit = card.get("domains")
    if isinstance(explicit, list) and explicit:
        domains = {str(d) for d in explicit if str(d)}
    else:
        trigger_text = " ".join(
            str(entry.get("text") or "")
            for entry in (card.get("trigger_examples") or [])
            if isinstance(entry, dict)
        )
        domains = set(
            classify_domains(
                str(card.get("name") or ""),
                str(card.get("name_ko") or ""),
                str(card.get("summary") or ""),
                str(card.get("summary_ko") or ""),
                " ".join(str(c) for c in (card.get("capabilities") or [])),
                trigger_text,
            )
        )
    return {
        "name": name_tokens,
        "triggers": triggers,
        "antis": antis,
        "capabilities": capability_tokens,
        "summary": summary_tokens,
        "domains": domains,
    }


def _score_card(
    card: dict[str, Any],
    query_tokens: set[str],
    profile: dict[str, Any],
    query_is_korean: bool,
    t_high: float,
    common: set[str] | None = None,
    min_shared_words: int = 2,
    query_domains: set[str] | None = None,
    query_vector: list[float] | None = None,
    semantic_weight: float = 0.0,
    domain_boost: float = 1.5,
    domain_penalty: float = 6.0,
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

    # Domain coherence: when the query resolves to exactly ONE domain, a card in
    # that domain gets a small edge and a card living only in OTHER known domains
    # is penalized (the polysemy guard — keeps a finance team out of a game-asset
    # route). Ambiguous / domain-less queries and cards are untouched, so the
    # guard is purely additive and cannot regress existing routes.
    if query_domains:
        card_domains: set[str] = index.get("domains") or set()
        if card_domains:
            if card_domains & query_domains:
                score += domain_boost
                reasons.append("domain match")
            elif len(query_domains) == 1:
                # Demote a clear cross-domain card hard, but never let the
                # penalty ALONE drop a lexically-relevant card below the
                # eligibility gate (score > 0) — otherwise a single domain
                # misclassification would silently delete the correct card
                # instead of merely ranking it lower.
                penalized = score - domain_penalty
                score = penalized if penalized > 0 else (0.01 if score > 0 else penalized)
                reasons.append(
                    "cross-domain penalty (query="
                    + "/".join(sorted(query_domains))
                    + " vs card="
                    + "/".join(sorted(card_domains))
                    + ")"
                )

    # Semantic similarity (deterministic offline hashed vectors): a bounded
    # recall enhancer so a naturally-phrased query still reaches the right card
    # when it doesn't restate a trigger verbatim. Disabled when semantic_weight
    # is 0 or the embedding adapter is unavailable.
    if semantic_weight > 0 and query_vector is not None:
        card_vector = _card_vector(card)
        if card_vector:
            sim = _cosine_similarity(query_vector, card_vector)
            if sim > 0.15:
                score += min(semantic_weight * sim, semantic_weight)
                reasons.append(f"semantic match {sim:.2f}")

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


def _load_ao_context(project_dir: Path | str) -> dict[str, Any]:
    """Load AO graph only when it is available and valid enough to use."""

    from ..agent_graph import validate_graph

    context = validate_graph(project_dir)
    return {
        "valid": bool(context.get("valid", False)),
        "node_index": context.get("node_index", {}),
        "grammar": context.get("grammar", {}),
        "agent_count": context.get("counts", {}).get("agents", 0),
        "errors": context.get("errors", []),
        "warnings": context.get("warnings", []),
    }


def _filter_candidates_by_ao(
    cards: list[dict[str, Any]],
    project_dir: Path | str,
    caller_id: str | None = None,
    relation: str = "routes_to",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from ..agent_graph import edge_is_blocked, explain_edge_gate

    ao = _load_ao_context(project_dir)
    if not ao.get("node_index"):
        return cards, {"status": "missing"}

    node_index: dict[str, dict[str, Any]] = ao["node_index"]  # type: ignore[assignment]
    mapped = {str(card.get("id")) for card in cards if str(card.get("id") or "") in node_index}
    if not mapped:
        return cards, {"status": "available_but_unmapped", "available": ao["agent_count"]}

    candidates = [card for card in cards if str(card.get("id") or "") in mapped]
    blocked_targets: list[str] = []
    blocked_by_axiom: list[str] = []
    blocked_edge_samples: list[dict[str, Any]] = []
    if caller_id:
        filtered: list[dict[str, Any]] = []
        blocked = 0
        for card in candidates:
            edge = {"from": str(caller_id), "to": str(card.get("id") or ""), "relation": relation, "kind": relation}
            if edge_is_blocked(edge=edge, node_index=node_index, grammar=ao.get("grammar", None)):
                blocked += 1
                blocked_targets.append(str(card.get("id") or ""))
                gate = explain_edge_gate(edge=edge, node_index=node_index, grammar=ao.get("grammar", None))
                blocked_by_axiom.extend(gate.get("blocked_by") or [])
                blocked_by_axiom.extend(
                    [
                        f"requirement_violation: {violation.get('message')}"
                        for violation in (gate.get("requirement_violations") or [])
                        if isinstance(violation, dict) and violation.get("message")
                    ]
                )
                blocked_edge_samples.append({"from": str(edge.get("from")), "to": str(edge.get("to")), "relation": str(edge.get("relation"))})
                continue
            filtered.append(card)
        candidates = filtered
        return candidates, {
            "status": "caller_filtered",
            "mapped": len(candidates),
            "blocked": blocked,
            "caller_id": str(caller_id),
            "blocked_targets": blocked_targets,
            "blocked_by_axiom": blocked_by_axiom,
            "blocked_edges": blocked_edge_samples,
        }

    return candidates, {
        "status": "mapped_only",
        "mapped": len(candidates),
        "available": ao["agent_count"],
    }


def _compact_hub_result(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item.get(key)
        for key in ("slug", "name", "nameEn", "kind", "callable", "routingReady", "trustGrade", "evalPassRate", "rating")
        if item.get(key) is not None
    }


def _is_borrowable(item: dict[str, Any]) -> bool:
    return bool(
        isinstance(item, dict)
        and item.get("slug")
        and (item.get("callable") is True or item.get("kind") == "cloud-callable" or item.get("routingReady"))
    )


# 일반적인 빌드/기획 동사는 "이 에이전트를 지목했다"고 볼 만큼 특이하지 않으므로 제외 —
# 진짜 역할 단어("웹마스터", "카피라이터")로만 매칭한다.
_GENERIC_ROLE_TOKENS = {
    "기획", "제작", "개발", "구현", "빌드", "만들", "작업", "불러", "불러서", "해줘", "해",
    "팀", "웹", "앱", "사이트", "페이지", "랜딩", "랜딩페이지", "에이전트", "등",
    "agent", "team", "build", "make", "plan", "create", "page", "landing", "web", "app", "site",
}


def _explicitly_named_borrowables(
    query: str, borrowable: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The operator explicitly named these borrowable candidates in the request.

    The Hub ranks by lexical overlap and routinely mis-ranks (an off-domain agent
    can outscore a named one). But when a candidate's own name word appears in the
    request, the operator named it on purpose — borrow it regardless of Hub rank.
    Distinctive name words only (generic build/plan verbs excluded) so we do not
    over-borrow. Hub rank order is preserved.
    """
    q_tokens = word_token_set(query or "")
    if not q_tokens:
        return []
    named: list[dict[str, Any]] = []
    for item in borrowable:
        name_tokens = word_token_set(
            " ".join([str(item.get("name") or ""), str(item.get("nameEn") or "")])
        )
        name_tokens |= snake_tokens(str(item.get("slug") or ""))
        overlap = {
            t for t in (name_tokens & q_tokens) if len(t) >= 2 and t not in _GENERIC_ROLE_TOKENS
        }
        if overlap:
            named.append(item)
    return named


def _byom_execution_plan(
    *,
    project: Path,
    query: str = "",
    results: list[dict[str, Any]] | None = None,
    stages: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Turn Hub candidates into an actionable, context-attached execution plan.

    A `hub_candidates` decision must never dead-end at "here are options, you
    decide" — that is exactly what makes the network feel useless and pushes the
    operator to skip it and improvise locally. Instead we name the agent(s) to
    BORROW and instruct the runtime to execute them LOCALLY, grounded in the
    current project codebase + memory + ontology (the BYOM bundle path, where
    `hep-call` attaches `project_dir`). Returns None only when no candidate is
    borrowable.
    """

    recommended: list[dict[str, Any]] = []
    alternatives: list[dict[str, Any]] = []
    if stages:
        for stage in stages:
            stage_candidates = [c for c in (stage.get("hub_candidates") or []) if _is_borrowable(c)]
            if stage_candidates:
                recommended.append(
                    {
                        "stage": stage.get("stage"),
                        "agent": str(stage_candidates[0].get("slug")),
                        "alternatives": [str(c.get("slug")) for c in stage_candidates[1:4]],
                    }
                )
    else:
        borrowable = [item for item in (results or []) if _is_borrowable(item)]
        # 사용자가 에이전트를 명시적으로 지목했으면("웹마스터 카피라이터 불러서") 전부 빌려온다 —
        # 다중 역할 요청을 최상위 후보 1개로 축소하지 않는다(Hub가 오프도메인 에이전트를 명시된
        # 에이전트보다 높게 랭크할 수 있으므로 명시 지목을 우선).
        named = _explicitly_named_borrowables(query, borrowable)
        if named:
            for cand in named[:5]:
                recommended.append({"stage": "direct", "agent": str(cand.get("slug"))})
            named_slugs = {str(c.get("slug")) for c in named}
            alternatives = [
                str(c.get("slug")) for c in borrowable if str(c.get("slug")) not in named_slugs
            ][:5]
        elif borrowable:
            recommended.append({"stage": "direct", "agent": str(borrowable[0].get("slug"))})
            alternatives = [str(c.get("slug")) for c in borrowable[1:5]]
    if not recommended:
        return None

    primary = recommended[0]["agent"]
    # 명시 지목이 2개+면 이건 "여러 전문가가 협업하는 하나의 산출물" — 실행 모델이 임시
    # 오케스트레이터 역할(plan→dispatch→synthesize)을 맡도록 directive를 전환한다. CLI에는
    # 별도 오케스트레이터 세션이 없으므로(hep-storm --executor-command 없이는) 베이스 모델이
    # 매니저가 되는 게 현실적 경로다.
    multi = len(recommended) >= 2
    directive = (
        "Resolve this request by BORROWING the best-fit Hub agent(s) and running them "
        "LOCALLY, grounded in the current project. Start from `primary_agent`/"
        "`recommended_agents`, but if the top pick is clearly off-domain, choose a better "
        "one from `alternatives` (the Hub ranks by keyword relevance and can mis-rank a "
        "sparse query). Use `hep-call` (it fetches the BYOM runtime bundle and attaches "
        "project_dir). Each borrowed agent must attach to this repo's actual codebase + "
        "memory before producing output. Do NOT call agents context-less in the cloud, and "
        "do NOT skip the network to improvise a local answer yourself — run the borrowed "
        "specialist attached to this project."
    )
    if multi:
        directive += (
            " The operator NAMED MULTIPLE specialists, so YOU are their temporary "
            "orchestrator — do not just run each in isolation. (1) PLAN how this ONE "
            "deliverable splits across them (who owns what). (2) DISPATCH each named agent "
            "with `hep-call`, grounded in the project, feeding each the relevant slice plus "
            "any upstream specialist's output it needs. (3) SYNTHESIZE their outputs into ONE "
            "coherent deliverable — integrate and reconcile, do not just concatenate. Borrow "
            "EVERY named agent; none skipped."
        )
    return {
        "mode": "byom_local_grounded",
        # 다중 명시 지목이면 실행 모델이 매니저 역할을 맡는다는 신호.
        "formation": "temporary_orchestrator" if multi else "single_specialist",
        "primary_agent": primary,
        "recommended_agents": recommended,
        # The Hub ranks by its own keyword relevance and can mis-rank the #1 for a
        # sparse query, so the operator — who can see the actual task — gets the
        # ranked borrowable alternatives and is told to pick the best fit, not to
        # borrow #1 blindly.
        "alternatives": alternatives,
        "project_dir": str(project),
        "attach": ["project_codebase", "agentlas_memory", "super_ontology"],
        "borrow_command": f'hephaestus hep-call "{primary}" "<request>" --project {project}',
        "directive": directive,
    }


def _task_force_from_result(result: dict[str, Any]) -> dict[str, Any]:
    if isinstance(result.get("task_force"), dict):
        return result["task_force"]
    if result.get("action") == "pipeline":
        packets_by_order = {
            int(packet.get("stage_order") or 0): packet
            for packet in ((result.get("execution_fabric") or {}).get("packets") or [])
            if isinstance(packet, dict)
        }
        stages = []
        for stage in result.get("stages") or []:
            if not isinstance(stage, dict):
                continue
            packet = packets_by_order.get(int(stage.get("order") or 0), {})
            stages.append(
                {
                    "order": stage.get("order"),
                    "stage": stage.get("stage"),
                    "agent": stage.get("card"),
                    "ao_agent": stage.get("ao_agent"),
                    "produces": stage.get("produces") or [],
                    "consumes": stage.get("consumes") or [],
                    "session_hint": packet.get("session_hint") or {},
                    "memory_scope": "stage_artifacts_only",
                }
            )
        return {
            "mode": "agent_os_router",
            "formation": "stormbreaker_temporary_tf",
            "temporary_tf": True,
            "over_decomposition_guard": "single-intent requests stay single-route",
            "stages": stages,
        }
    if result.get("action") == "route" and result.get("selected"):
        return {
            "mode": "agent_os_router",
            "formation": "single_agent_route",
            "temporary_tf": False,
            "over_decomposition_guard": "single matched agent is enough",
            "stages": [
                {
                    "order": 1,
                    "stage": "direct",
                    "agent": (result.get("selected") or {}).get("id"),
                    "memory_scope": "local_runtime_scope",
                }
            ],
        }
    if result.get("action") == "hub_candidates":
        hub_results = ((result.get("hub") or {}).get("results") or [])[:5]
        return {
            "mode": "agent_os_router",
            "formation": "single_stage_hub_candidates",
            "temporary_tf": False,
            "over_decomposition_guard": "Hub TF only forms after stage decomposition",
            "stages": [
                {
                    "order": 1,
                    "stage": "direct",
                    "hub_candidates": [_compact_hub_result(item) for item in hub_results if isinstance(item, dict)],
                    "memory_scope": "public_playbook_or_redacted_summary",
                }
            ],
        }
    return {
        "mode": "agent_os_router",
        "formation": "none",
        "temporary_tf": False,
        "over_decomposition_guard": "no executable route selected",
        "stages": [],
    }


def _hub_task_force_plan(
    query: str,
    *,
    scope: str,
    search_hub_fn,
) -> dict[str, Any] | None:
    stages_wanted = detect_stages(query)
    if len(stages_wanted) < 2:
        return None

    stage_results: list[dict[str, Any]] = []
    combined: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    for order, (stage_key, artifact_kind) in enumerate(stages_wanted[:3], start=1):
        stage_query_tokens = word_tokens(f"{query} {stage_key} {artifact_kind}")
        hub = search_hub_fn(stage_query_tokens, search_scope=scope)
        results = [item for item in (hub.get("results") or []) if isinstance(item, dict)] if hub.get("status") == "ok" else []
        candidates = [_compact_hub_result(item) for item in results[:3]]
        for item in results:
            slug = str(item.get("slug") or "")
            if slug and slug not in seen_slugs:
                seen_slugs.add(slug)
                combined.append(item)
        stage_results.append(
            {
                "order": order,
                "stage": stage_key,
                "artifact": artifact_kind,
                "hub_status": hub.get("status"),
                "hub_scope": hub.get("scope") or scope,
                "attempted_scopes": hub.get("attemptedScopes") or [],
                "hub_query": hub.get("query"),
                "hub_candidates": candidates,
                "memory_scope": "public_playbook_or_redacted_summary",
            }
        )

    if not combined:
        return None

    return {
        "hub": {
            "status": "ok",
            "scope": scope,
            "query": "stagewise_task_force",
            "results": combined,
            "stage_results": stage_results,
        },
        "task_force": {
            "mode": "agent_os_router",
            "formation": "hub_stage_candidates",
            "temporary_tf": True,
            "over_decomposition_guard": "only plan-anchored composite requests form Hub TFs",
            "stages": stage_results,
        },
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
    scope: str = "network",
    caller_id: str | None = None,
    session_inventory: list[Any] | None = None,
) -> dict[str, Any]:
    # Three-scope command model (docs/hephaestus-network-2.0.md):
    #   scope="cloud"   -> /hep-cloud: search ONLY the signed-in user's
    #                     OWN cloud packages (보관함). Owner-scoped Hub query,
    #                     implies hub_only (skip local + public marketplace).
    #   scope="network" -> /hep-network: search Cloud > Bookmark > public Hub
    #                     in that order. Used with hub_only by the network command.
    #   operator debug route (hub_only=False, scope="network") → local +
    #                     own-cloud + Hub together, each priced by origin. Public
    #                     command/MCP surfaces default hub_only=True.
    cloud_only = scope == "cloud"
    if cloud_only:
        hub_only = True
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
    hub_query_tokens = word_tokens(query)
    chain = router_chain or ["hep-cloud" if cloud_only else "hep-network"]

    def _search_hub(query_tokens: list[str], *, search_scope: str) -> dict[str, Any]:
        if search_scope in {"cloud", "bookmark"}:
            try:
                return search_hub(query_tokens, home=base, approved=True, scope=search_scope)
            except TypeError as exc:
                if "scope" not in str(exc):
                    raise
                return {
                    "status": "unavailable",
                    "scope": search_scope,
                    "query": " ".join(query_tokens),
                    "results": [],
                    "note": "search_hub implementation does not support this scope",
                }
        return search_hub(query_tokens, home=base, approved=True)

    def _search_hub_ordered(query_tokens: list[str], *, search_scope: str) -> dict[str, Any]:
        if cloud_only or search_scope != "network":
            return _search_hub(query_tokens, search_scope=search_scope)
        attempted: list[str] = []
        last: dict[str, Any] = {}
        for candidate_scope in ["cloud", "bookmark", "network"]:
            hub = _search_hub(query_tokens, search_scope=candidate_scope)
            attempted.append(candidate_scope)
            hub["attemptedScopes"] = attempted.copy()
            last = hub
            if hub.get("status") == "ok" and hub.get("results"):
                return hub
            # Cloud/bookmark low-confidence should not block public Hub search.
            # Public Hub clarify is the final useful prompt to return.
            if candidate_scope == "network" and hub.get("status") == "clarify":
                return hub
        return last

    def finish(
        result: dict[str, Any],
        candidates: list[dict[str, Any]],
        reasons: list[str],
        *,
        match_reason: str | None = None,
        graph_path: list[dict[str, Any]] | None = None,
        allowed_by: list[str] | None = None,
        blocked_by_axiom: list[str] | None = None,
        fallback_scope: str | None = None,
    ) -> dict[str, Any]:
        task_force = _task_force_from_result(result)
        policy_decision = evaluate_local_operator_policy(
            sorted(query_tokens),
            action=str(result.get("action") or ""),
            hub_used=isinstance(result.get("hub"), dict),
            hub_only=hub_only or result.get("local_routing") == "skipped",
            scope=str(result.get("scope") or scope),
            pipeline=bool(result.get("action") == "pipeline" or task_force.get("temporary_tf")),
        )
        memory_playbook = build_memory_playbook_context(
            action=str(result.get("action") or ""),
            query_tokens=sorted(query_tokens),
            task_force=task_force,
            policy_decision=policy_decision,
        )
        # Cascade: a low-confidence (clarify/propose_new) decision can be handed
        # to the Router Agent for an LLM reasoning pass run by the HOST runtime.
        # The engine only attaches the directive (BYOC); confident routes and
        # pipelines are left untouched. Receipts store a redacted summary only.
        router_agent = router_escalation(
            result,
            query=query,
            locale=locale,
            policy=policy,
            query_tokens=sorted(query_tokens),
        )
        if router_agent:
            result["router_agent"] = router_agent
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
            match_reason=match_reason,
            graph_path=graph_path,
            allowed_by=allowed_by,
            blocked_by_axiom=blocked_by_axiom,
            fallback_scope=fallback_scope,
            task_force=task_force,
            policy_decision=policy_decision,
            memory_playbook=memory_playbook,
            router_agent=(
                {"mode": router_agent["mode"], "agent": router_agent["agent"], "reason": router_agent["reason"]}
                if router_agent
                else None
            ),
            home=base,
        )
        result["receipt_id"] = receipt_id
        result["locale"] = locale
        result["query_tokens"] = sorted(query_tokens)
        result["match_reason"] = match_reason
        result["graph_path"] = graph_path or []
        result["allowed_by"] = allowed_by or []
        result["blocked_by_axiom"] = blocked_by_axiom or []
        result["fallback_scope"] = fallback_scope
        result["agent_os_router"] = {
            "surface": chain[0] if chain else "hep-network",
            "command_model": "three_command",
            "commands": {
                "build": "hep-build",
                "network": "hep-network",
                "cloud": "hep-cloud",
                "search": "hep-search",
                "call": "hep-call",
                "upload": "hep-upload",
            },
            "router_version": "agent_os_router.v1",
            "local_operator_mode": True,
        }
        result["task_force"] = task_force
        result["policy_decision"] = policy_decision
        result["memory_playbook"] = memory_playbook
        return result

    if hop_count > max_hops:
        return finish(
            {"action": "refuse", "selected": None, "reasons": [f"router loop detected (hop_count={hop_count} > {max_hops})"]},
            [],
            ["loop_guard"],
            match_reason="loop_guard",
            graph_path=[],
            allowed_by=["loop_guard"],
            blocked_by_axiom=[],
            fallback_scope=None,
        )

    if hub_only:
        # The owner cloud (보관함) and the public marketplace share this
        # Hub-only flow; the only difference is the scope passed to the Hub and
        # the receipt/reason tag, so /hep-cloud and /hep-network
        # stay one code path with two scopes.
        scope_tag = "cloud_only" if cloud_only else "hub_only"
        if use_hub:
            stagewise = _hub_task_force_plan(query, scope=scope, search_hub_fn=_search_hub_ordered)
            if stagewise is not None:
                execution = _byom_execution_plan(
                    project=project, stages=(stagewise["task_force"].get("stages") or [])
                )
                return finish(
                    {
                        "action": "hub_candidates",
                        "selected": None,
                        "candidates": [],
                        "hub": stagewise["hub"],
                        "task_force": stagewise["task_force"],
                        "scope": scope,
                        "suggestions": [],
                        "local_routing": "skipped",
                        **({"execution": execution} if execution else {}),
                        "reasons": [f"{scope_tag}_task_force_results_found"],
                    },
                    [],
                    [scope_tag, "hub_task_force_results_found"],
                    match_reason=f"{scope_tag}_task_force_results",
                    graph_path=[],
                    allowed_by=["hub_results", scope_tag, "task_force_decomposition"],
                    blocked_by_axiom=[],
                    fallback_scope=None,
                )
            hub = _search_hub_ordered(hub_query_tokens, search_scope=scope)
            hub_scope = str(hub.get("scope") or scope)
            selected_reason = "hub_only_results_found" if not cloud_only and hub_scope == "network" else f"{scope_tag}_{hub_scope}_results_found"
            selected_match_reason = "hub_only_hub_results" if not cloud_only and hub_scope == "network" else f"{scope_tag}_{hub_scope}_results"
            if hub.get("status") == "clarify":
                return finish(
                    {
                        "action": "clarify",
                        "selected": None,
                        "candidates": [],
                        "hub": hub,
                        "scope": hub_scope,
                        "suggestions": hub.get("suggestions") or [],
                        "clarify_question": hub.get("questionKo") or hub.get("question"),
                        "local_routing": "skipped",
                        "reasons": [f"{scope_tag}_low_confidence"],
                    },
                    [],
                    [scope_tag, "hub_clarify"],
                    match_reason=f"{scope_tag}_hub_clarify",
                    graph_path=[],
                    allowed_by=["hub_search", scope_tag],
                    blocked_by_axiom=[],
                    fallback_scope=None,
                )
            if hub.get("status") == "ok" and hub.get("results"):
                execution = _byom_execution_plan(
                    project=project, query=query, results=hub.get("results") or []
                )
                return finish(
                    {
                        "action": "hub_candidates",
                        "selected": None,
                        "candidates": [],
                        "hub": hub,
                        "scope": hub_scope,
                        "suggestions": [],
                        "local_routing": "skipped",
                        **({"execution": execution} if execution else {}),
                        "reasons": [selected_reason],
                    },
                    [],
                    [scope_tag, f"{hub_scope}_results_found"],
                    match_reason=selected_match_reason,
                    graph_path=[],
                    allowed_by=["hub_results", scope_tag, "route_order:cloud_bookmark_hub", f"selected_scope:{hub_scope}"],
                    blocked_by_axiom=[],
                    fallback_scope=None,
                )
            return finish(
                {"action": "propose_new", "selected": None, "candidates": [], "hub": hub, "scope": scope, "suggestions": [], "local_routing": "skipped", "reasons": [f"{scope_tag}_no_match_or_unavailable"]},
                [],
                [scope_tag, "propose_new"],
                match_reason=f"{scope_tag}_no_match_or_unavailable",
                graph_path=[],
                allowed_by=["hub_search", scope_tag],
                blocked_by_axiom=[],
                fallback_scope="hub_no_match",
            )
        return finish(
            {"action": "propose_new", "selected": None, "candidates": [], "scope": scope, "suggestions": [], "local_routing": "skipped", "reasons": [f"{scope_tag}_requested_but_hub_disabled"]},
            [],
            [f"{scope_tag}_hub_disabled"],
            match_reason="hub_disabled",
            graph_path=[],
            allowed_by=["hub_disabled"],
            blocked_by_axiom=[],
            fallback_scope="hub_disabled",
        )

    cards, quarantined = load_global_cards(base)
    cards_by_id = {str(card.get("id")): card for card in cards}
    statuses = {str(card.get("id")): _cached_status(card) for card in cards}
    usable = [card for card in cards if statuses[str(card.get("id"))] not in ("quarantined", "stale")]
    # Plugins are tools an agent loads (required_plugins) — never a user-facing
    # route target. Exclude them from the agent route pool so a generic-vocabulary
    # lexical match can't recommend a plugin (e.g. plugin/shopify-dev) as an agent.
    usable = [
        card
        for card in usable
        if str(card.get("type") or "").lower() != "plugin"
        and not str(card.get("id") or "").startswith("plugin/")
    ]
    ao_filter_report: dict[str, Any] = {}
    usable, ao_filter_report = _filter_candidates_by_ao(usable, project, caller_id=caller_id)
    ao_allowed_by: list[str] = []
    ao_blocked_by_axiom: list[str] = []
    ao_fallback_scope: str | None = None
    if ao_filter_report.get("status") == "mapped_only":
        chain.append("ao:mapped-only")
        ao_allowed_by = ["agent_ontology_graph"]
    elif ao_filter_report.get("status") == "caller_filtered":
        chain.append("ao:caller-gated")
        ao_allowed_by = ["agent_ontology_graph", "caller_gate"]
        blocked = ao_filter_report.get("blocked_by_axiom") or []
        ao_blocked_by_axiom = list(dict.fromkeys([str(item) for item in blocked if isinstance(item, str)]))
        ao_fallback_scope = "local_graph_and_caller_gate"
    elif ao_filter_report.get("status") in ("missing", "available_but_unmapped"):
        # No project AO graph for these (global/network) cards — but the global
        # card store IS a graph: every card is an ExternalAgent node with
        # in_domain/has_capability edges (agent_graph.card_mapper). So routing is
        # ontology-backed (a routed card gets a real graph_path below), not blind
        # lexical fallback.
        chain.append("ao:card-derived")
        ao_allowed_by = ["agent_ontology_graph_cards"]
        ao_fallback_scope = "card_derived_ontology"

    query_domains = set(classify_domains(query))

    def _route_graph_path(card: dict[str, Any] | None) -> list[dict[str, Any]]:
        """A concrete AO edge (domain→agent) for a routed card under the
        card-derived ontology scope; empty for any other scope so non-card
        routes are unchanged. Used by every route branch so a routed card never
        reports the empty graph_path this feature was meant to eliminate."""
        if ao_fallback_scope != "card_derived_ontology" or not card:
            return []
        from ..agent_graph import card_route_path

        return card_route_path(
            str(card.get("id")),
            _cached_index(card).get("domains") or set(),
            query_domains,
        )

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
        return finish(
            result,
            [selected],
            ["explicit_match"],
            match_reason="explicit_match",
            graph_path=_route_graph_path(explicit),
            allowed_by=ao_allowed_by or ["explicit_match"],
            blocked_by_axiom=ao_blocked_by_axiom,
            fallback_scope=ao_fallback_scope,
        )

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
                match_reason="creation_intent",
                graph_path=_route_graph_path(creator),
                allowed_by=ao_allowed_by or ["creation_intent"],
                blocked_by_axiom=ao_blocked_by_axiom,
                fallback_scope=ao_fallback_scope,
            )

    profile = load_profile(base)
    common = _common_tokens(usable)
    # A one-content-word query ("웹사이트 만들어줘") can never share two words;
    # scale the trigger qualification down to the query's own word count.
    min_shared_words = min(2, max(1, len(word_token_set(query))))
    semantic_weight = float(policy.get("semantic_weight", 0.5))
    domain_boost = float(policy.get("domain_boost", 1.5))
    domain_penalty = float(policy.get("domain_penalty", 6.0))
    query_vector = _embed_query(query) if semantic_weight > 0 else None
    scored: list[tuple[float, list[str], dict[str, Any]]] = []
    for card in usable:
        score, reasons = _score_card(
            card,
            query_tokens,
            profile,
            locale == "ko",
            t_high,
            common=common,
            min_shared_words=min_shared_words,
            query_domains=query_domains,
            query_vector=query_vector,
            semantic_weight=semantic_weight,
            domain_boost=domain_boost,
            domain_penalty=domain_penalty,
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
    plan = plan_pipeline(
        query,
        ready_cards,
        lambda card: score_by_id.get(str(card.get("id")), 0.0),
        project_dir=project,
        session_inventory=session_inventory,
    )
    if plan is not None:
        stage_candidates = []
        for stage in plan["stages"]:
            stage_candidates.append({"id": stage["card"], "score": score_by_id.get(str(stage["card"]), 0.0)})
        chain = chain + [f"pipeline:{plan['pipeline_id']}"]
        return finish(
            {"action": "pipeline", "selected": None, **plan, "reasons": ["plan-anchored composite request → multi-team pipeline plan"]},
            stage_candidates,
            ["pipeline_plan"],
            match_reason=plan.get("match_reason"),
            graph_path=plan.get("graph_path"),
            allowed_by=plan.get("allowed_by") or ["pipeline_plan"],
            blocked_by_axiom=plan.get("blocked_by_axiom", []),
            fallback_scope=None,
        )

    top_score = auto_eligible[0][0] if auto_eligible else 0.0
    second_score = auto_eligible[1][0] if len(auto_eligible) > 1 else 0.0
    confident_local = bool(
        auto_eligible
        and top_score >= t_high
        and ((top_score - second_score) >= margin or second_score <= top_score * 0.7)
    )

    # Multi-routing (Network 2.0): explicit operator-debug mode can consult
    # the Hub so a better Hub agent for a not-installed capability is surfaced
    # next to local candidates — instead of clarifying on weak local matches or
    # missing the Hub entirely. The Hub call uses only redacted keywords, is TTL
    # cached, and is skipped for an overwhelmingly confident local route to keep
    # the common path cheap. Toggle with policy `multi_route` (default on).
    multi_route = bool(policy.get("multi_route", True))
    overwhelming_local = confident_local and top_score >= max(t_high * 1.5, t_high + margin + 2.0)
    hub: dict[str, Any] | None = None
    if use_hub and not (overwhelming_local and not multi_route):
        if multi_route or not confident_local:
            hub = search_hub(hub_query_tokens, home=base, approved=True)
    hub_ok = bool(hub and hub.get("status") == "ok" and hub.get("results"))
    hub_clarify = bool(hub and hub.get("status") == "clarify")

    # Confident local match in explicit debug mode → route locally, but attach Hub
    # alternatives when present so the caller can still pick a better Hub agent.
    if confident_local:
        top_card = auto_eligible[0][2]
        selected = _selected_payload(top_card, top_score)
        result: dict[str, Any] = {
            "action": "route",
            "selected": selected,
            "candidates": candidates,
            "reasons": auto_eligible[0][1],
        }
        chain_note = ["confident_local_match"]
        if hub_ok:
            result["hub"] = hub
            result["hub_alternatives"] = hub.get("results")
            chain_note.append("multi_route_hub_alternatives")
        if ao_filter_report.get("status") == "caller_filtered":
            chain_note.append("ao:caller-gated")
        route_graph_path = _route_graph_path(top_card)
        return finish(
            result,
            candidates,
            chain_note,
            match_reason="local_confident",
            graph_path=route_graph_path,
            allowed_by=(ao_allowed_by or ["local_keyword_score"]) + ["route_confident_threshold"],
            blocked_by_axiom=ao_blocked_by_axiom,
            fallback_scope=ao_fallback_scope,
        )

    # Not confident locally → multi-route: merge Hub candidates with local ones.
    if hub_clarify:
        return finish(
            {
                "action": "clarify",
                "selected": None,
                "candidates": candidates,
                "hub": hub,
                "suggestions": hub.get("suggestions") or (candidates + suggestions),
                "clarify_question": hub.get("questionKo") or hub.get("question"),
                "reasons": ["hub_low_confidence"],
            },
            candidates,
            ["multi_route", "hub_clarify"],
            match_reason="hub_clarify",
            graph_path=[],
            allowed_by=(ao_allowed_by or ["hub_low_confidence"]) + ["local_score"],
            blocked_by_axiom=ao_blocked_by_axiom,
            fallback_scope="local_hub_low_confidence",
        )
    if hub_ok:
        execution = _byom_execution_plan(
            project=project, query=query, results=(hub or {}).get("results") or []
        )
        return finish(
            {
                "action": "hub_candidates",
                "selected": None,
                "hub": hub,
                "candidates": candidates,
                "suggestions": (candidates + suggestions) or suggestions,
                **({"execution": execution} if execution else {}),
                "reasons": ["multi_route_local_plus_hub"],
            },
            candidates,
            ["multi_route", "hub_results_found"],
            match_reason="multi_route_hub_results",
            graph_path=[],
            allowed_by=(ao_allowed_by or ["hub_results"]) + ["local_score"],
            blocked_by_axiom=ao_blocked_by_axiom,
            fallback_scope=None,
        )

    # Hub offline/empty (or disabled) → fall back to local-only behavior.
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
            match_reason="low_confidence_threshold",
            graph_path=[],
            allowed_by=(ao_allowed_by or ["local_score"]) + ["low_confidence"],
            blocked_by_axiom=ao_blocked_by_axiom,
            fallback_scope="local_low_confidence",
        )

    return finish(
        {
            "action": "propose_new",
            "selected": None,
            **({"hub": hub} if hub is not None else {}),
            "suggestions": suggestions,
            "reasons": [
                "no local match; hub unavailable or empty - propose building a new agent via /hep-build"
                if use_hub
                else "no auto-eligible local match (hub disabled)"
            ],
        },
        [],
        ["propose_new"] if use_hub else ["local_only_no_match"],
        match_reason="no_local_match",
        graph_path=[],
        allowed_by=ao_allowed_by or ["no_local_match"],
        blocked_by_axiom=ao_blocked_by_axiom,
        fallback_scope=ao_fallback_scope or ("hub_available" if use_hub else "hub_disabled"),
    )
