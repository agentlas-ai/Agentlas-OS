from __future__ import annotations

import json
import math
import mmap
import re
import struct
import unicodedata
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
class Model2VecInt8HybridAdapter:
    """Dependency-free, verified Model2Vec int8 + hash96 hybrid.

    The first 256 dimensions reproduce the pinned potion-base-8M WordPiece
    mean from the local int8 asset. The final 96 dimensions preserve lexical
    and CJK recall. Both components use equal L2 weight, so output is always a
    fixed 352 dimensions and never switches identity by input language.
    """

    asset: VerifiedModelAsset | Path | str
    name: str = "model2vec_potion_base_8m_int8_hybrid"
    status: str = "available"
    dimensions: int = 352
    semantic_dimensions: int = 256
    hash_dimensions: int = 96
    max_tokens: int = 512
    _hash_adapter: LocalHashingVectorAdapter = field(
        default_factory=LocalHashingVectorAdapter,
        init=False,
        repr=False,
    )
    _vocab: dict[str, int] | None = field(default=None, init=False, repr=False)
    _unknown_id: int | None = field(default=None, init=False, repr=False)
    _embeddings_handle: Any = field(default=None, init=False, repr=False)
    _embeddings: mmap.mmap | None = field(default=None, init=False, repr=False)
    _scales: bytes | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.asset, VerifiedModelAsset):
            self.asset = verify_model_asset(self.asset)
        if self.asset.dimensions != self.semantic_dimensions:
            raise ValueError(
                f"expected {self.semantic_dimensions} Model2Vec dimensions, got {self.asset.dimensions}"
            )

    @property
    def identity(self) -> str:
        return f"{self.asset.identity}:hybrid-hash96-v1:{self.dimensions}"

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
            "semantic_dimensions": self.semantic_dimensions,
            "hash_dimensions": self.hash_dimensions,
            "hybrid": "equal_weight_l2_concat_v1",
        }

    def embed(self, text: str) -> list[float]:
        semantic = self._semantic_embed(text)
        lexical = self._hash_adapter.embed(text)
        weight = 1.0 / math.sqrt(2.0)
        combined = [value * weight for value in semantic] + [value * weight for value in lexical]
        norm = math.sqrt(sum(value * value for value in combined))
        if norm == 0.0:
            return combined
        return [round(value / norm, 6) for value in combined]

    def wordpiece_ids(self, text: str) -> list[int]:
        self._ensure_loaded()
        assert self._vocab is not None
        output: list[int] = []
        for token in _bert_basic_tokens(text):
            pieces = _wordpiece(token, self._vocab)
            if pieces is None:
                continue
            output.extend(self._vocab[piece] for piece in pieces)
            if len(output) >= self.max_tokens:
                return output[: self.max_tokens]
        return output

    def _semantic_embed(self, text: str) -> list[float]:
        ids = self.wordpiece_ids(text)
        if not ids:
            return [0.0] * self.semantic_dimensions
        assert self._embeddings is not None and self._scales is not None
        vector = [0.0] * self.semantic_dimensions
        for token_id in ids:
            scale = struct.unpack_from("<f", self._scales, token_id * 4)[0]
            row_offset = token_id * self.semantic_dimensions
            for index in range(self.semantic_dimensions):
                raw = self._embeddings[row_offset + index]
                signed = raw if raw < 128 else raw - 256
                vector[index] += signed * scale
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0.0:
            return [0.0] * self.semantic_dimensions
        return [value / norm for value in vector]

    def _ensure_loaded(self) -> None:
        if self._vocab is not None:
            return
        tokenizer = json.loads((self.asset.path / "tokenizer.json").read_text(encoding="utf-8"))
        vocab = tokenizer["model"]["vocab"]
        self._vocab = {str(token): int(token_id) for token, token_id in vocab.items()}
        self._unknown_id = self._vocab.get("[UNK]")
        self._embeddings_handle = open(self.asset.path / "embeddings.i8", "rb")
        self._embeddings = mmap.mmap(self._embeddings_handle.fileno(), 0, access=mmap.ACCESS_READ)
        self._scales = (self.asset.path / "scales.f32le").read_bytes()

    def close(self) -> None:
        if self._embeddings is not None:
            self._embeddings.close()
            self._embeddings = None
        if self._embeddings_handle is not None:
            self._embeddings_handle.close()
            self._embeddings_handle = None
        self._scales = None
        self._vocab = None
        self._unknown_id = None

    def __del__(self) -> None:  # pragma: no cover - best-effort process cleanup
        try:
            self.close()
        except Exception:
            pass


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
            return Model2VecInt8HybridAdapter(asset=asset)
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
        return Model2VecInt8HybridAdapter(asset=asset)
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
    dot = sum(a * b for a, b in zip(left_values, right_values))
    left_norm = math.sqrt(sum(a * a for a in left_values))
    right_norm = math.sqrt(sum(b * b for b in right_values))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
