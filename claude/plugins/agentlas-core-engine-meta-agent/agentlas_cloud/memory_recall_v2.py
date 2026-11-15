"""Agentlas 2.0: ``recall-v2``, one recall rule for every surface (ruleset 1.9.0). Pure functions: no store, no model, no clock.

Ruleset 1.9.0 ('): the fusion is the desktop's own rule, a calibrated late fusion (desktop electron/memory/local-embedding.ts
rankHybridLocal: ``lexical + 0.05 x (vector - floor)``), not reciprocal rank fusion; ties break on the two-column wording
(origin_class, certainty), then the newer line, then the id; contradiction picking is gone (a corrected or replaced line is not a
candidate); a line replaced because it was WRONG (``corrected``) is never shown, not even as a "was" note.

This is the engine's reference for contracts/test-vectors/memory-recall-v2-vectors.json. Nothing calls it yet: the engine hook and
tool and the desktop will, and both must give the SAME lines in the SAME order on the shared vectors. Embeddings are
not computed here: a vector score per line is GIVEN by the caller (the cosine of int8-quantised model2vec vectors), so two
implementations with slightly different embeddings still score, break ties and cut identically.

The values equal ``recall.*`` in system-agents/curator-ruleset.json (a test pins that).

Line fields (a dict): id, kind, text (English), text_native (original wording or None), vec / vec_native (given scores or None),
origin_class (user | observed | result | inferred | None), certainty (self_reported | run_verified | unverified | None),
prior (a given 0..1 weight of how sure the store is of the line, or None; the desktop passes its confidence prior, the engine None),
created_at (ISO text or None), store (a key the caller opens or not), project (the project a line is bound to, or None),
superseded / forgotten / disabled (booleans), superseded_why (changed | corrected | None: why a superseded line was replaced),
replaced ({text, at, why} for the newest line this one replaced, or None; why = changed | corrected, default changed).
Reader: {stores: [keys the conversation may read], project: key or None, history: bool}.
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

ALGORITHM = "recall-v2"
QUERY_USER_MAX = 2000
QUERY_USER_HEAD = 1000
QUERY_USER_TAIL = 1000
# Audit: the old rule kept the FIRST 2,000 characters, so a question written after a long paste (a log, a diff) was not in the query and
# a wrong line was recalled (6,057-character prompt, question at the end: not found). A text longer than QUERY_USER_MAX keeps its first 1,000 and its last
# 1,000 characters, joined by a newline (a token never spans the cut: a CJK run ends at a newline). Why 1,000/1,000: people put the ask first or last; a
# question in the middle 1,000-2,000 of a long prompt, which the old rule found, is no longer in the query (measured: evidence/ev1-engine/query_ht.json).
# When it is reached: only for a text over 2,000 characters; a shorter text is untouched, byte for byte.
QUERY_SUMMARY_MAX = 360
# EK4: the project's name is no longer part of the query (the previous summary is): measured on the EK3 set, 24 follow-ups, it adds nothing (R@8 0.958 -> 0.958, MRR 0.938 -> 0.904) and the
# desktop does not append it. The three surfaces build one query.
# The five values below are NOT measured choices (-11-13; evidence/set-values-audit/engine/sens40_result.json). The desktop's numbers were carried over.
# The 40-pair evaluation does not tell them apart: moving VECTOR_FLOOR 0 -> 0.40, VECTOR_FLOOR_CJK 0 -> 0.20 or VECTOR_RELATIVE_FLOOR 0 -> 1.0 changes R@8 of not one
# pair (0.925 every time). RESIDUAL_WEIGHT is the only one that moves anything (0.2 gives R@8 0.95 / MRR 0.91) and n=40 is too few to change it. "Basis: none"
# until the evaluation set is widened (Japanese, Chinese, paraphrase, long lines, several kinds, a real distribution of near-miss lines); do not retune before.
# When they are reached: a vector below the floor, or below 72% of the best one in the call, is not a candidate by meaning (words still count).
VECTOR_FLOOR = 0.15
VECTOR_FLOOR_CJK = 0.12
VECTOR_RELATIVE_FLOOR = 0.72
RESIDUAL_WEIGHT = 0.05
PRIOR_WEIGHT = 0.002
# PRIOR_WEIGHT is a dead value in this engine: every caller here passes prior=None (``contract_lines`` sets no "prior"), so the term is always 0. It is part of the
# shared contract because the desktop passes its confidence prior (context.ts); removing it would change the contract and the 181 shared vectors, so it stays.
MAX_LINES = 12
MAX_BYTES = 2400
SESSION_START_LINES = 8
HISTORY_WINDOW_DAYS = 90
HISTORY_OLD_CHARS = 80
TIER_ORDER = ("user", "run_verified", "unverified", "inferred", "none")

_VERSION = re.compile(r"v?[0-9]+(?:\.[0-9]+)+(?:-[a-z0-9.]+)?")
_LATIN = re.compile(r"[a-z0-9][a-z0-9_-]{1,}")
_CJK_RUN = re.compile("[぀-ヿ㐀-䶿一-鿿가-힣]+")
_CJK_ANY = re.compile("[぀-ヿ㐀-䶿一-鿿가-힣]")


def tokens(text: str) -> list[str]:
    """Version tokens, Latin words of two or more characters, and CJK/Hangul one-character runs or two-character windows."""
    lowered = text.lower()
    found: list[str] = []

    def take(match: "re.Match[str]") -> str:
        text = match.group(0)
        found.append(text[1:] if text.startswith("v") else text)
        return " "

    rest = _VERSION.sub(take, lowered)
    found.extend(_LATIN.findall(rest))
    for run in _CJK_RUN.findall(lowered):
        if len(run) == 1:
            found.append(run)
        else:
            found.extend(run[i:i + 2] for i in range(len(run) - 1))
    return found


def lexical(query_tokens: "set[str]", text: str, kind: str) -> float:
    """|Q and D| / sqrt(|Q| * |D|) over token sets; D is the tokens of text + one space + kind."""
    doc = set(tokens(text + " " + kind))
    if not query_tokens or not doc:
        return 0.0
    overlap = len(query_tokens & doc)
    return overlap / math.sqrt(len(query_tokens) * len(doc)) if overlap else 0.0


def assemble_query(user_text: Any, previous_summary: Any = None, project_name: Any = None) -> str | None:
    """Q = user text (a text over 2,000 characters keeps its first 1,000 and last 1,000), then the previous turn's English summary, joined by a newline. None = no-query mode.
    ``project_name`` is accepted and ignored (EK4: an older caller that still passes it does not break; the query never carries it)."""
    def part(value: Any, limit: int) -> str:
        return value.strip()[:limit] if isinstance(value, str) else ""

    user = part(user_text, 10 ** 9)
    if len(user) > QUERY_USER_MAX:
        user = user[:QUERY_USER_HEAD] + "\n" + user[-QUERY_USER_TAIL:]
    if not user:
        return None
    return "\n".join(piece for piece in (user, part(previous_summary, QUERY_SUMMARY_MAX)) if piece)


def tier(line: dict[str, Any]) -> int:
    """The tie tier of a line, 0 = best: user, run_verified, unverified, inferred, none (the two-column wording).

    user: origin_class user, or certainty self_reported. run_verified: certainty run_verified. inferred: origin_class inferred.
    unverified: certainty unverified, or origin_class observed / result. none: no origin and no certainty (an old or imported
    line). The order of the checks is the order of the rule: a line that is both user and unverified is a user line."""
    origin, certainty = line.get("origin_class"), line.get("certainty")
    if origin == "user" or certainty == "self_reported":
        return 0
    if certainty == "run_verified":
        return 1
    if origin == "inferred":
        return 3
    if certainty == "unverified" or origin in ("observed", "result"):
        return 2
    return 4


def _created(line: dict[str, Any]) -> str:
    return line.get("created_at") or ""


def _tie_key(line: dict[str, Any]) -> tuple:
    return (tier(line), _neg_text(_created(line)), line["id"])


def _neg_text(value: str) -> tuple:
    return tuple(-ord(char) for char in value) + (1,)   # a longer text of the same start is newer-or-equal: sorts first


def _visible(line: dict[str, Any], reader: dict[str, Any]) -> str | None:
    """None when the line may be read, else the reason it may not."""
    if line.get("forgotten"):
        return "forgotten"
    if line.get("disabled"):
        return "disabled"
    if line.get("superseded"):
        if line.get("superseded_why") == "corrected":
            return "corrected"          # a wrong line is gone for good: not a candidate, not even in the history
        if not reader.get("history"):
            return "superseded"
    if line.get("store") not in set(reader.get("stores") or []):
        return "store"
    if line.get("project") is not None and line.get("project") != reader.get("project"):
        return "project"
    return None


def _given_vector(line: dict[str, Any]) -> float | None:
    given = [value for value in (line.get("vec"), line.get("vec_native")) if value is not None]
    return max(given) if given else None


def score(lexical_score: float, vector: float | None, floor: float, best: float, prior: Any = None) -> tuple[bool, float]:
    """(semantically eligible, score): lexical + 0.05 x (vector - floor) when eligible + 0.002 x prior.

    eligible = a vector was given and vector >= floor and vector >= 0.72 x best; best = the largest given vector of the lines
    in this call, never below 0. The sum is added left to right: (lexical + semantic) + priorTerm."""
    eligible = vector is not None and vector >= floor and vector >= best * VECTOR_RELATIVE_FLOOR
    semantic = max(0.0, vector - floor) * RESIDUAL_WEIGHT if eligible else 0.0
    prior_term = max(0.0, float(prior)) * PRIOR_WEIGHT if isinstance(prior, (int, float)) and not isinstance(prior, bool) and math.isfinite(prior) else 0.0
    return eligible, lexical_score + semantic + prior_term


def rank(query: str, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The scored order of the lines that pass the gate: [{id, semantic, score}].

    A line is a candidate when its lexical score is above 0, or when it is semantically eligible."""
    query_tokens = set(tokens(query))
    floor = VECTOR_FLOOR_CJK if _CJK_ANY.search(query) else VECTOR_FLOOR
    measured = []
    for line in lines:
        lexical_score = lexical(query_tokens, line["text"], line["kind"])
        if line.get("text_native"):
            lexical_score = max(lexical_score, lexical(query_tokens, line["text_native"], line["kind"]))
        measured.append((line, lexical_score, _given_vector(line)))
    best = max([0.0] + [vector for _, _, vector in measured if vector is not None])
    out = []
    for line, lexical_score, vector in measured:
        eligible, total = score(lexical_score, vector, floor, best, line.get("prior"))
        if lexical_score > 0 or eligible:
            out.append({"id": line["id"], "semantic": eligible, "score": total, "_line": line})
    out.sort(key=lambda row: (-row["score"],) + _tie_key(row["_line"]))
    for row in out:
        del row["_line"]
    return out


def _cost(line: dict[str, Any], suffix: str) -> int:
    return len(("- [" + line["kind"] + "] " + line["text"] + suffix).encode("utf-8")) + 1


def _when(value: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _history_suffix(line: dict[str, Any], now: str | None) -> str:
    old = line.get("replaced")
    if not isinstance(old, dict) or not now or old.get("why") == "corrected":
        return ""
    at, current = _when(str(old.get("at") or "")), _when(now)
    if at is None or current is None or current - at > timedelta(days=HISTORY_WINDOW_DAYS):
        return ""
    return " (was: " + str(old.get("text") or "")[:HISTORY_OLD_CHARS].rstrip() + ", changed " + at.astimezone(timezone.utc).strftime("%Y-%m-%d") + ")"


def recall(query_parts: dict[str, Any], lines: list[dict[str, Any]], reader: dict[str, Any], *,
           options: dict[str, Any] | None = None) -> dict[str, Any]:
    """One recall. query_parts: {user_text, previous_summary} (a project_name key is read and ignored). options: {now, history_notes, max_lines, max_bytes}.

    Returns {mode: ranked | latest, query, ranked: [{id, semantic}], selected: [{id, suffix}], bytes, skipped_over_budget,
    excluded: [{id, reason}]}. A line is never dropped for disagreeing with another line: two lines that say different things
    both load, and the caller (the model) reads the newer one first only where the order says so."""
    opts = options or {}
    max_bytes = opts.get("max_bytes", MAX_BYTES)
    query = assemble_query(query_parts.get("user_text"), query_parts.get("previous_summary"), query_parts.get("project_name"))
    excluded, usable = [], []
    for line in sorted(lines, key=lambda row: row["id"]):
        reason = _visible(line, reader)
        (excluded.append({"id": line["id"], "reason": reason}) if reason else usable.append(line))
    by_id = {line["id"]: line for line in usable}
    if query is None:
        mode, max_lines = "latest", opts.get("max_lines", SESSION_START_LINES)
        order = sorted(usable, key=lambda row: (_neg_text(_created(row)), row["id"]))
        ranked = [{"id": row["id"], "semantic": None} for row in order]
    else:
        mode, max_lines = "ranked", opts.get("max_lines", MAX_LINES)
        ranked = [{"id": row["id"], "semantic": row["semantic"]} for row in rank(query, usable)]
    selected: list[dict[str, Any]] = []
    used, skipped = 0, []
    for row in ranked:
        if len(selected) >= max_lines:
            break
        line = by_id[row["id"]]
        suffix = _history_suffix(line, opts.get("now")) if opts.get("history_notes") else ""
        cost = _cost(line, suffix)
        if used + cost > max_bytes:
            skipped.append(line["id"])
            continue
        selected.append({"id": line["id"], "suffix": suffix})
        used += cost
    return {"mode": mode, "query": query, "ranked": ranked, "selected": selected, "bytes": used,
            "skipped_over_budget": skipped, "excluded": excluded}
