from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Protocol

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
class Model2VecLocalAdapter:
    """Optional in-process Model2Vec adapter backed by an existing local model.

    ``model_path`` must already exist on disk. The adapter deliberately never
    accepts a Hub model id and never downloads model files; importing
    ``model2vec`` and loading the model are deferred until the first embed.
    """

    model_path: Path | str
    name: str = "model2vec"
    status: str = "configured_local"
    _model: Any = field(default=None, init=False, repr=False)
    _dimensions: int | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        path = Path(self.model_path).expanduser()
        if not path.exists():
            raise ValueError(f"Model2Vec local model path does not exist: {path}")
        self.model_path = path.resolve()

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    @property
    def identity(self) -> str:
        path = Path(self.model_path)
        path_key = stable_hash(str(path), length=12)
        return f"model2vec:local:{path.name}:{path_key}"

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        try:
            from model2vec import StaticModel
        except ImportError as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError(
                "Model2Vec is configured but the optional 'model2vec' package is not installed"
            ) from exc
        # The existence check in __post_init__ is the network boundary: only a
        # filesystem path reaches Model2Vec, never a remote model identifier.
        self._model = StaticModel.from_pretrained(str(self.model_path))
        self.status = "available"
        return self._model

    def embed(self, text: str) -> list[float]:
        model = self._load()
        encoded = model.encode([text])
        first = encoded[0]
        raw = first.tolist() if hasattr(first, "tolist") else list(first)
        vector = [float(value) for value in raw]
        self._dimensions = len(vector)
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [round(value / norm, 6) for value in vector]


def select_vector_adapter(
    adapter: str = "hash",
    *,
    model_path: Path | str | None = None,
    hashing_dimensions: int = 96,
) -> VectorAdapter:
    """Select a local-only vector adapter without remote fallbacks."""

    normalized = (adapter or "hash").strip().lower().replace("-", "_")
    if normalized in {"hash", "hashing", "local_hashing"}:
        if model_path is not None:
            raise ValueError("model_path is only valid when adapter='model2vec'")
        return LocalHashingVectorAdapter(dimensions=hashing_dimensions)
    if normalized in {"model2vec", "model2vec_local"}:
        if model_path is None:
            raise ValueError("adapter='model2vec' requires an existing local model_path")
        return Model2VecLocalAdapter(model_path=model_path)
    raise ValueError(f"unsupported local vector adapter: {adapter}")


def vector_adapter_metadata(adapter: VectorAdapter) -> dict[str, Any]:
    return {
        "name": adapter.name,
        "status": adapter.status,
        "identity": adapter.identity,
        "dimensions": adapter.dimensions,
        "local_only": True,
    }


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
