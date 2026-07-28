"""Score an offer brief against a need brief.

Deterministic, no model, no index. Given the two sides of `agentlas.brief/1` this
returns a score, the evidence behind it, and the obligations the requester has
not met — so a caller can show *why* a package was ranked where it was rather
than asserting it was best.

Two properties are load-bearing and everything else is tuning:

1. **Only one thing can remove a candidate.** `need.authority.forbid` against an
   offer's positively declared `authority.performs`, and only when everything the
   method does is forbidden. An offer that declared no `performs` can never be
   excluded, so a publisher who wrote nothing is never punished for it. This is
   the exact inverse of the failure that took a three-candidate inventory to zero
   on 8 probes out of 8 — there, a vocabulary miss deleted the candidate; here,
   only the requester's own stated refusal does.

2. **Sentences are compared as sentences.** Nothing below tokenises a statement, a
   deliverable label or an obligation. Cutting the refusal sentence "Fix the CI
   runner out-of-memory" into the bare words `ci` and `runner` is what cut a
   correct agent's score to a quarter and moved it from rank 2 to rank 24 on a
   query describing its own job.

Unstated is not inferred. An offer that never declared a shape scores zero on
shape rather than borrowing one from its neighbours.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping, Sequence

__all__ = ["match_briefs", "MatchResult"]

# SHAPE AND EFFECT CONFIRM A MATCH; THEY NEVER CREATE ONE.
#
# A first version of this file gave `shape` the top weight and scored it on its
# own. Measured immediately on the real catalogue: 89 of 113 compiled
# deliverables are `ledger` and almost every one is `describe`, so a wedding
# planner and a flaky-test surgeon both scored 37 on "ledger + describe" and the
# correct agent — which had no contract yet, hence no shape — scored 0. That is
# the same mistake as `runtimes`, filled by 246 of 246 profiles and worth
# nothing: a field where four out of five rows share a value cannot carry the
# ranking, however principled it looks.
#
# So the topology fields are MULTIPLIERS on evidence that the two sides are
# talking about the same work, not independent points. Agreement on what the
# thing is called is what separates; agreement on its shape then raises
# confidence in that separation.
WEIGHT = {
    "deliverable_label": 40.0,
    "statement": 22.0,
    "obligation_met": 9.0,
    "verdict_value": 6.0,
}
# Applied to the label score of the SAME deliverable pair, never on their own.
CONFIRM_SHAPE = 0.45
CONFIRM_EFFECT = 0.25
# An obligation the requester cannot satisfy is a real cost, but never a removal:
# the requester may simply not have said yet that they have the thing.
UNMET_REQUIRED_PENALTY = 7.0


class MatchResult(dict):
    """Score plus the reasons for it. A dict so it crosses a wire unchanged."""


def _fold(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text)).casefold().strip()


def _content_words(text: str) -> set[str]:
    """Words for OVERLAP MEASUREMENT ONLY - never for filtering.

    Nothing is excluded from a candidate set on the strength of this. It answers
    "how much do these two sentences have in common", and a zero answer means the
    pair contributes nothing, not that the candidate is wrong.
    """
    folded = _fold(text)
    words = re.findall(r"[0-9a-z]+|[가-힣]+", folded)
    return {word for word in words if len(word) >= 2}


def _overlap(left: str, right: str) -> float:
    """Jaccard over content words, in [0, 1]."""
    a, b = _content_words(left), _content_words(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _best_overlap(text: str, candidates: Sequence[str]) -> float:
    return max((_overlap(text, item) for item in candidates), default=0.0)


def _deliverables(brief: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = brief.get("deliverables")
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _obligations(brief: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    value = brief.get("obligations")
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _performs(brief: Mapping[str, Any]) -> set[str]:
    authority = brief.get("authority")
    if not isinstance(authority, Mapping):
        return set()
    value = authority.get("performs")
    return {str(item) for item in value} if isinstance(value, list) else set()


def _forbid(brief: Mapping[str, Any]) -> set[str]:
    authority = brief.get("authority")
    if not isinstance(authority, Mapping):
        return set()
    value = authority.get("forbid")
    return {str(item) for item in value} if isinstance(value, list) else set()


def match_briefs(offer: Mapping[str, Any], need: Mapping[str, Any]) -> MatchResult:
    """Score `offer` against `need`."""
    evidence: list[str] = []
    unmet: list[str] = []
    score = 0.0

    # --- the only exclusion in the system -----------------------------------
    forbid = _forbid(need)
    performs = _performs(offer)
    if forbid and performs and performs <= forbid:
        return MatchResult(
            score=0.0,
            excluded=True,
            reason="every effect this method performs was forbidden by the request",
            evidence=[f"forbid:{effect}" for effect in sorted(performs & forbid)],
            unmet=[],
        )

    offer_deliverables = _deliverables(offer)
    need_deliverables = _deliverables(need)

    # --- what the requester ends up holding ---------------------------------
    for wanted in need_deliverables:
        wanted_label = str(wanted.get("label") or "")
        wanted_shape = wanted.get("shape")
        wanted_effect = wanted.get("effect")

        # Score the BEST-MATCHING PAIR, not the best of each field separately.
        # Scoring fields independently let an offer collect shape points from one
        # deliverable and effect points from another while agreeing with neither.
        best_pair = 0.0
        best_note: list[str] = []
        for offered in offer_deliverables:
            # Match against the label AND what the schema actually contains. The
            # title alone is usually the package's own name repeated; the
            # discriminating words are the property names inside it.
            surfaces = [str(offered.get("label") or "")]
            contains = offered.get("contains")
            if isinstance(contains, list):
                surfaces.extend(str(item) for item in contains)
            label_fit = _best_overlap(wanted_label, surfaces)
            if label_fit <= 0:
                continue
            confirm = 1.0
            note = [f"deliverable:{wanted_label[:40]}"]
            if wanted_shape and wanted_shape != "other" and offered.get("shape") == wanted_shape:
                confirm += CONFIRM_SHAPE
                note.append(f"shape:{wanted_shape}")
            if wanted_effect and wanted_effect != "other" and offered.get("effect") == wanted_effect:
                confirm += CONFIRM_EFFECT
                note.append(f"effect:{wanted_effect}")
            pair = WEIGHT["deliverable_label"] * label_fit * confirm
            if pair > best_pair:
                best_pair, best_note = pair, note
        if best_pair > 0:
            score += best_pair
            evidence.extend(best_note)

        wanted_values = wanted.get("verdictValues")
        if isinstance(wanted_values, list) and wanted_values:
            offered = {
                str(value).casefold()
                for item in offer_deliverables
                for value in (item.get("verdictValues") or [])
            }
            shared = {str(value).casefold() for value in wanted_values} & offered
            if shared:
                score += WEIGHT["verdict_value"] * min(1.0, len(shared) / len(wanted_values))
                evidence.append(f"verdict:{sorted(shared)[0]}")

    # --- what the method needs before it can start --------------------------
    # Only `request`-stage obligations participate. Anything the requester could
    # simply be asked for later is a question, not a mismatch: penalising it
    # would rank agents by how little they ask rather than by how well they fit.
    supplied = [str(item.get("about") or "") for item in _obligations(need)]
    for obligation in _obligations(offer):
        if obligation.get("stage") != "request":
            continue
        about = str(obligation.get("about") or "")
        if supplied and _best_overlap(about, supplied) > 0.15:
            score += WEIGHT["obligation_met"]
            evidence.append(f"obligation:{about[:40]}")
        elif obligation.get("required"):
            # A requester who listed nothing has said nothing about what they
            # hold — that is unknown, not empty. Deducting for it penalised every
            # offer equally and wiped out real matches: a package with four
            # required inputs lost 28 points before its deliverables were even
            # read, so the strongest candidate scored zero. The obligation is
            # still REPORTED, because the caller has to be able to say what the
            # requester will be asked for; it just does not move the ranking
            # until the requester has actually stated their side.
            unmet.append(about)
            if supplied:
                score -= UNMET_REQUIRED_PENALTY

    # --- prose, last and lightest -------------------------------------------
    statement_overlap = _overlap(str(offer.get("statement") or ""), str(need.get("statement") or ""))
    if statement_overlap > 0:
        score += WEIGHT["statement"] * statement_overlap
        evidence.append("statement")

    return MatchResult(
        score=round(max(score, 0.0), 4),
        excluded=False,
        reason=None,
        evidence=evidence[:12],
        unmet=unmet[:8],
    )
