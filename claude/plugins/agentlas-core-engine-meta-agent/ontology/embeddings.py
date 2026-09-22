from __future__ import annotations

import json
import math
import mmap
import re
import struct
import unicodedata
from array import array
from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol

from .model_assets import ModelAssetError, VerifiedModelAsset, find_verified_model_asset, verify_model_asset
from .utils import stable_hash


class VectorAdapter(Protocol):
    name: str
    status: str
    dimensions: int | None
    identity: str

    def embed(self, text: str) -> list[float]:
        ...


@dataclass
class LocalHashingVectorAdapter:
    """Deterministic local semantic fallback.

    This is not a mock: it is a stable hashed bag-of-words vector that works
    without provider keys and without sending source text to a remote service.
    """

    dimensions: int = 96
    name: str = "local_hashing"
    status: str = "available"
    fallback_reason: str | None = None

    @property
    def identity(self) -> str:
        return f"local_hashing:sha256-bow:v1:{self.dimensions}"

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for token in tokenize(text):
            digest = stable_hash(token, length=16)
            bucket = int(digest[:8], 16) % self.dimensions
            sign = 1.0 if int(digest[8:10], 16) % 2 == 0 else -1.0
            vector[bucket] += sign * (1.0 + min(len(token), 16) / 16.0)
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [round(value / norm, 6) for value in vector]


@dataclass
class Model2VecInt8Adapter:
    """Dependency-free, verified 256-dimensional Model2Vec adapter.

    The multilingual release uses an ordered Unigram vocabulary and Viterbi
    segmentation. Quantized embedding rows stay split on disk and are mapped
    independently, so neither a 128 MB joined file nor a hash96 compensation
    axis is introduced at runtime. Lexical evidence remains a separate
    retrieval rank; hash-96 is used only when no verified local asset exists.
    """

    asset: VerifiedModelAsset | Path | str
    name: str = "model2vec_potion_multilingual_128m_int8"
    status: str = "available"
    dimensions: int = 256
    max_wordpiece_tokens: int = 512
    _vocab: dict[str, int] | None = field(default=None, init=False, repr=False)
    _unigram_scores: array | None = field(default=None, init=False, repr=False)
    _unknown_id: int | None = field(default=None, init=False, repr=False)
    _tokenizer_type: str | None = field(default=None, init=False, repr=False)
    _embedding_handles: list[Any] = field(default_factory=list, init=False, repr=False)
    _embedding_maps: list[mmap.mmap] = field(default_factory=list, init=False, repr=False)
    _embedding_row_starts: list[int] = field(default_factory=list, init=False, repr=False)
    _scales: bytes | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.asset, VerifiedModelAsset):
            self.asset = verify_model_asset(self.asset)
        if self.asset.dimensions != self.dimensions:
            raise ValueError(f"expected {self.dimensions} Model2Vec dimensions, got {self.asset.dimensions}")
        if self.asset.tokenizer_type != "Unigram":
            self.name = "model2vec_potion_base_8m_int8_legacy"

    @property
    def identity(self) -> str:
        return f"{self.asset.identity}:semantic-v1:{self.dimensions}"

    @property
    def asset_metadata(self) -> dict[str, Any]:
        source = self.asset.manifest["source"]
        return {
            "format": self.asset.manifest["format"],
            "path": str(self.asset.path),
            "content_sha256": self.asset.content_sha256,
            "source_model": source["modelId"],
            "source_revision": source["revision"],
            "license": self.asset.manifest["license"]["spdx"],
            "quantization": self.asset.manifest["quantization"]["scheme"],
            "dimensions": self.dimensions,
            "tokenizer": self.asset.tokenizer_type,
            "embedding_parts": list(self.asset.embedding_parts),
        }

    def embed(self, text: str) -> list[float]:
        return [round(value, 6) for value in self._semantic_embed(text)]

    def token_ids(self, text: str) -> list[int]:
        self._ensure_loaded()
        if self._tokenizer_type == "Unigram":
            return self.unigram_ids(text)
        return self.wordpiece_ids(text)

    def wordpiece_ids(self, text: str) -> list[int]:
        self._ensure_loaded()
        assert self._vocab is not None
        output: list[int] = []
        for token in _bert_basic_tokens(text):
            pieces = _wordpiece(token, self._vocab)
            if pieces is None:
                continue
            for piece in pieces:
                token_id = self._vocab[piece]
                if token_id != self._unknown_id:
                    output.append(token_id)
                if len(output) >= self.max_wordpiece_tokens:
                    return output
        return output

    def unigram_ids(self, text: str) -> list[int]:
        self._ensure_loaded()
        assert self._vocab is not None and self._unigram_scores is not None
        characters = list(_unigram_normalize(text))
        length = len(characters)
        if length == 0:
            return []
        best_score = [float("-inf")] * (length + 1)
        best_start = [-1] * (length + 1)
        best_id = [-1] * (length + 1)
        best_score[0] = 0.0
        for start in range(length):
            if best_score[start] == float("-inf"):
                continue
            limit = min(length, start + UNIGRAM_MAX_PIECE_CHARS)
            for end in range(start + 1, limit + 1):
                token_id = self._vocab.get("".join(characters[start:end]))
                if token_id is None:
                    continue
                candidate = best_score[start] + self._unigram_scores[token_id]
                if candidate > best_score[end]:
                    best_score[end] = candidate
                    best_start[end] = start
                    best_id[end] = token_id
        if best_score[length] == float("-inf"):
            return []
        output: list[int] = []
        at = length
        while at > 0:
            start = best_start[at]
            if start < 0:
                return []
            if best_id[at] != self._unknown_id:
                output.append(best_id[at])
            at = start
        output.reverse()
        return output

    def _semantic_embed(self, text: str) -> list[float]:
        ids = self.token_ids(text)
        if not ids:
            return [0.0] * self.dimensions
        assert self._scales is not None
        vector = [0.0] * self.dimensions
        for token_id in ids:
            scale = struct.unpack_from("<f", self._scales, token_id * 4)[0]
            part_index = bisect_right(self._embedding_row_starts, token_id) - 1
            row_offset = (token_id - self._embedding_row_starts[part_index]) * self.dimensions
            embeddings = self._embedding_maps[part_index]
            for index in range(self.dimensions):
                raw = embeddings[row_offset + index]
                signed = raw if raw < 128 else raw - 256
                vector[index] += signed * scale
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return [0.0] * self.dimensions
        return [value / norm for value in vector]

    def _ensure_loaded(self) -> None:
        if self._vocab is not None:
            return
        tokenizer = json.loads((self.asset.path / "tokenizer.json").read_text(encoding="utf-8"))
        model = tokenizer["model"]
        self._tokenizer_type = self.asset.tokenizer_type
        if self._tokenizer_type == "Unigram":
            vocab: dict[str, int] = {}
            scores = array("d")
            for token_id, (token, score) in enumerate(model["vocab"]):
                if token not in vocab:
                    vocab[str(token)] = token_id
                scores.append(float(score))
            self._vocab = vocab
            self._unigram_scores = scores
            self._unknown_id = int(model["unk_id"])
        else:
            self._vocab = {str(token): int(token_id) for token, token_id in model["vocab"].items()}
            self._unknown_id = self._vocab.get("[UNK]")

        row_start = 0
        for name in self.asset.embedding_parts:
            handle = open(self.asset.path / name, "rb")
            mapped = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
            self._embedding_handles.append(handle)
            self._embedding_maps.append(mapped)
            self._embedding_row_starts.append(row_start)
            row_start += len(mapped) // self.dimensions
        self._scales = (self.asset.path / "scales.f32le").read_bytes()

    def close(self) -> None:
        for mapped in self._embedding_maps:
            mapped.close()
        for handle in self._embedding_handles:
            handle.close()
        self._embedding_maps.clear()
        self._embedding_handles.clear()
        self._embedding_row_starts.clear()
        self._scales = None
        self._vocab = None
        self._unigram_scores = None
        self._unknown_id = None
        self._tokenizer_type = None

    def __del__(self) -> None:  # pragma: no cover - best-effort process cleanup
        try:
            self.close()
        except Exception:
            pass


# Import compatibility for callers that used the old class name. The adapter
# itself is semantic-only; no hybrid/hash dimensions remain.
Model2VecInt8HybridAdapter = Model2VecInt8Adapter


def select_vector_adapter(
    adapter: str = "auto",
    *,
    model_path: Path | str | None = None,
    hashing_dimensions: int = 96,
) -> VectorAdapter:
    """Select a local-only vector adapter without remote fallbacks."""

    normalized = (adapter or "auto").strip().lower().replace("-", "_")
    if normalized == "auto":
        try:
            asset = find_verified_model_asset(model_path)
        except ModelAssetError as exc:
            raise ValueError(str(exc)) from exc
        if asset is not None:
            return Model2VecInt8Adapter(asset=asset)
        return LocalHashingVectorAdapter(
            dimensions=hashing_dimensions,
            status="degraded_fallback",
            fallback_reason="verified_local_model2vec_asset_not_found",
        )
    if normalized in {"hash", "hashing", "local_hashing"}:
        if model_path is not None:
            raise ValueError("model_path is only valid when adapter is 'auto' or 'model2vec'")
        return LocalHashingVectorAdapter(dimensions=hashing_dimensions)
    if normalized in {"model2vec", "model2vec_local"}:
        try:
            asset = find_verified_model_asset(model_path)
        except ModelAssetError as exc:
            raise ValueError(str(exc)) from exc
        if asset is None:
            raise ValueError("adapter='model2vec' requires a verified local Agentlas Model2Vec asset")
        return Model2VecInt8Adapter(asset=asset)
    raise ValueError(f"unsupported local vector adapter: {adapter}")


def vector_adapter_metadata(adapter: VectorAdapter) -> dict[str, Any]:
    metadata = {
        "name": adapter.name,
        "status": adapter.status,
        "identity": adapter.identity,
        "dimensions": adapter.dimensions,
        "local_only": True,
    }
    if isinstance(adapter, LocalHashingVectorAdapter) and adapter.fallback_reason:
        metadata["fallback_reason"] = adapter.fallback_reason
    asset_metadata = getattr(adapter, "asset_metadata", None)
    if asset_metadata:
        metadata["asset"] = asset_metadata
    return metadata


METASPACE = "\u2581"
UNIGRAM_MAX_PIECE_CHARS = 24


def _unigram_normalize(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    collapsed = " ".join(normalized.split())
    if not collapsed:
        return ""
    return METASPACE + collapsed.replace(" ", METASPACE)


def _bert_basic_tokens(text: str) -> list[str]:
    cleaned: list[str] = []
    for char in text:
        code = ord(char)
        category = unicodedata.category(char)
        if code in {0, 0xFFFD} or (category.startswith("C") and char not in "\t\n\r"):
            continue
        if char.isspace():
            cleaned.append(" ")
        elif _is_chinese_char(code):
            cleaned.extend((" ", char, " "))
        else:
            cleaned.append(char)
    normalized = unicodedata.normalize("NFD", "".join(cleaned).lower())
    normalized = "".join(char for char in normalized if unicodedata.category(char) != "Mn")
    tokens: list[str] = []
    for word in normalized.split():
        current: list[str] = []
        for char in word:
            if _is_punctuation(char):
                if current:
                    tokens.append("".join(current))
                    current = []
                tokens.append(char)
            else:
                current.append(char)
        if current:
            tokens.append("".join(current))
    return tokens


def _wordpiece(token: str, vocab: dict[str, int], max_characters: int = 100) -> list[str] | None:
    if not token or len(token) > max_characters:
        return None
    pieces: list[str] = []
    start = 0
    while start < len(token):
        end = len(token)
        selected: str | None = None
        while start < end:
            candidate = token[start:end]
            if start > 0:
                candidate = "##" + candidate
            if candidate in vocab:
                selected = candidate
                break
            end -= 1
        if selected is None:
            return None
        pieces.append(selected)
        start = end
    return pieces


def _is_punctuation(char: str) -> bool:
    code = ord(char)
    return 33 <= code <= 47 or 58 <= code <= 64 or 91 <= code <= 96 or 123 <= code <= 126 or unicodedata.category(char).startswith("P")


def _is_chinese_char(code: int) -> bool:
    return (
        0x4E00 <= code <= 0x9FFF
        or 0x3400 <= code <= 0x4DBF
        or 0x20000 <= code <= 0x2A6DF
        or 0x2A700 <= code <= 0x2B73F
        or 0x2B740 <= code <= 0x2B81F
        or 0x2B820 <= code <= 0x2CEAF
        or 0xF900 <= code <= 0xFAFF
        or 0x2F800 <= code <= 0x2FA1F
    )


LATIN_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{1,}")
CJK_RUN_PATTERN = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힣]+")


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    tokens = LATIN_TOKEN_PATTERN.findall(lowered)
    # CJK runs have no whitespace word boundary; character bigrams keep the
    # zero-install constraint (no morphological analyzer) while making Hangul,
    # kana, and ideograph text searchable.
    for run in CJK_RUN_PATTERN.findall(lowered):
        if len(run) == 1:
            tokens.append(run)
        else:
            tokens.extend(run[i : i + 2] for i in range(len(run) - 1))
    return tokens


def cosine_similarity(left: Iterable[float], right: Iterable[float]) -> float:
    left_values = list(left)
    right_values = list(right)
    if not left_values or not right_values:
        return 0.0
    # Different dimensions are different adapters. zip() would silently compare
    # only the shared prefix and return a fabricated score (the TS twins already
    # return 0 here; this one did not).
    if len(left_values) != len(right_values):
        return 0.0
    dot = sum(a * b for a, b in zip(left_values, right_values))
    left_norm = math.sqrt(sum(a * a for a in left_values))
    right_norm = math.sqrt(sum(b * b for b in right_values))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    score = dot / (left_norm * right_norm)
    # A NaN component would make every comparison NaN and the block unreachable.
    return score if math.isfinite(score) else 0.0


def encode_vector(vector: Iterable[float]) -> list[int] | list[float]:
    """Stored form of an embedding: int8 per dimension (-127..127).

    Cosine is scale-invariant, so each vector is scaled by its own max |x| and
    rounded; no per-vector scale needs storing and old float rows stay directly
    comparable. Measured on 2,068 durable blocks x 256d: storage 5.50MB (float
    JSON) -> 0.53MB (int8), recall@10 vs float 96.3%. Binary 1-bit was 33% at
    this dimension and is deliberately not used.

    Non-finite input is stored as all zeros (cosine 0) rather than NaN.
    """
    values = [float(x) for x in vector]
    if not values:
        return []
    if not all(math.isfinite(x) for x in values):
        return [0] * len(values)
    peak = max(abs(x) for x in values)
    if peak == 0:
        return [0] * len(values)
    return [int(round(x / peak * 127)) for x in values]
