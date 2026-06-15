"""Bilingual (ko/en) deterministic tokenizer for routing.

Korean handling follows the repo's existing CJK practice (ontology/embeddings.py):
whole words plus character bigrams, with josa/filler stripping, so Korean
queries can still match partially-localized cards.
"""

from __future__ import annotations

import re

TOKEN_RE = re.compile(r"[a-z0-9]+|[가-힣]+")
HANGUL_RE = re.compile(r"^[가-힣]+$")

EN_FILLERS = {
    "a", "an", "and", "are", "can", "do", "for", "from", "get", "give", "help",
    "i", "in", "is", "it", "let", "make", "me", "my", "need", "of", "on",
    "please", "set", "so", "some", "that", "the", "this", "to", "up", "us",
    "want", "we", "with", "you", "your",
}

KO_FILLERS = {
    "해줘", "해주세요", "해줄래", "해봐", "하기", "해라", "해야", "있는", "있게",
    "좀", "그냥", "부탁", "부탁해", "원해", "필요해", "싶어", "싶다", "주세요",
    "만들어줘", "만들어주세요", "해주라", "할래", "이거", "저거", "그거",
}

# Longest-first so 에서/으로 are stripped before 에/로.
KO_JOSA = (
    "에서", "으로", "이랑", "한테", "처럼", "보다", "까지", "부터", "에게",
    "을", "를", "이", "가", "은", "는", "에", "로", "와", "과", "도", "만", "의", "랑",
    # Sentence-ending politeness/filler particles commonly attach to the real
    # query word ("추천좀", "알려줘요"). Treat them like josa so they don't leak
    # into route scoring or Hub redacted queries.
    "좀", "요", "죠", "네", "까",
)

KO_VERB_TAILS = ("해줘", "해주세요", "해줄래", "하기", "해라", "하고", "해서", "했어", "할래")


def _strip_korean_word(word: str) -> str:
    for tail in KO_VERB_TAILS:
        if word.endswith(tail) and len(word) > len(tail) + 1:
            word = word[: -len(tail)]
            break
    for josa in KO_JOSA:
        if word.endswith(josa) and len(word) > len(josa) + 1:
            word = word[: -len(josa)]
            break
    return word


def _hangul_bigrams(word: str) -> list[str]:
    if len(word) < 3:
        return []
    return [word[i : i + 2] for i in range(len(word) - 1)]


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in TOKEN_RE.findall((text or "").lower()):
        if HANGUL_RE.match(raw):
            word = _strip_korean_word(raw)
            if len(word) < 2 or word in KO_FILLERS:
                continue
            tokens.append(word)
            tokens.extend(_hangul_bigrams(word))
        else:
            if len(raw) < 2 or raw in EN_FILLERS:
                continue
            tokens.append(raw)
    return tokens


def token_set(text: str) -> set[str]:
    return set(tokenize(text))


def word_token_set(text: str) -> set[str]:
    """Like token_set but without Hangul bigrams — used as the denominator
    when computing trigger coverage so bigrams add recall, not dilution."""
    tokens: set[str] = set()
    for raw in TOKEN_RE.findall((text or "").lower()):
        if HANGUL_RE.match(raw):
            word = _strip_korean_word(raw)
            if len(word) < 2 or word in KO_FILLERS:
                continue
            tokens.add(word)
        else:
            if len(raw) < 2 or raw in EN_FILLERS:
                continue
            tokens.add(raw)
    return tokens


def has_hangul(text: str) -> bool:
    return bool(re.search(r"[가-힣]", text or ""))


def snake_tokens(value: str) -> set[str]:
    return {part for part in re.split(r"[^a-z0-9가-힣]+", (value or "").lower()) if len(part) >= 2}
