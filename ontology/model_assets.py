from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ASSET_FORMAT = "agentlas-model2vec-int8-v1"
DEFAULT_ASSET_NAME = "potion-multilingual-128M-int8"
LEGACY_ASSET_NAME = "potion-base-8M-int8"
MODEL_PATH_ENV = "AGENTLAS_MODEL2VEC_PATH"
RUNTIME_HOME_ENV = "AGENTLAS_RUNTIME_HOME"
EMBEDDING_PART_MAX_BYTES = 64 * 1024 * 1024
PINNED_EMBEDDING_PARTS = (
    "embeddings.i8.part-000",
    "embeddings.i8.part-001",
)
PINNED_SOURCE_MODEL = "minishlab/potion-multilingual-128M"
PINNED_SOURCE_REVISION = "73908c3438cf03b6a01bcb9611d62b23d0726f08"
PINNED_CONTENT_SHA256 = "aa806dbd4c6025f47b0242f8b92eb789109a0c612524980eb905fda3b5b73bde"
PINNED_SOURCE_FILES = {
    "config.json": {"sha256": "595e4cab2093732efd5dbe084fd5c1826b5eea693b73b4c1fd971672867d2e54", "size": 271},
    "tokenizer.json": {"sha256": "19f1909063da3cfe3bd83a782381f040dccea475f4816de11116444a73e1b6a1", "size": 18616131},
    "model.safetensors": {"sha256": "14b5eb39cb4ce5666da8ad1f3dc6be4346e9b2d601c073302fa0a31bf7943397", "size": 512361560},
    "README.md": {"sha256": "9505454b6a3efbb25257124de875cb73e02bd663a822528525a3c29b1c4d91ac", "size": 5575},
}

_UNIGRAM_TOKENIZER_CONTRACT = {
    "type": "Unigram",
    "normalizer": "NFKC + collapse whitespace",
    "preTokenizer": "Metaspace(replacement=U+2581,prepend_scheme=always)",
    "segmentation": "viterbi_max_log_prob",
    "unknownToken": "[UNK]",
    "addSpecialTokens": False,
}
_WORDPIECE_TOKENIZER_CONTRACT = {
    "type": "WordPiece",
    "normalizer": "BertNormalizer(lowercase=true,handle_chinese_chars=true)",
    "preTokenizer": "BertPreTokenizer",
    "continuingSubwordPrefix": "##",
    "unknownToken": "[UNK]",
    "addSpecialTokens": False,
}
_PINNED_PROFILE = {
    "assetName": DEFAULT_ASSET_NAME,
    "modelId": PINNED_SOURCE_MODEL,
    "revision": PINNED_SOURCE_REVISION,
    "sourceFiles": PINNED_SOURCE_FILES,
    "contentSha256": PINNED_CONTENT_SHA256,
    "dimensions": 256,
    "vocabSize": 500353,
    "tokenizerType": "Unigram",
    "tokenizer": _UNIGRAM_TOKENIZER_CONTRACT,
    "runtimeEngine": "agentlas_pure_python_unigram_v1",
    "embeddingParts": PINNED_EMBEDDING_PARTS,
}
# Exact legacy input remains verifiable only for explicit migration paths. It
# is never searched by auto mode and is not the runtime default.
_LEGACY_PROFILE = {
    "assetName": LEGACY_ASSET_NAME,
    "modelId": "minishlab/potion-base-8M",
    "revision": "bf8b056651a2c21b8d2565580b8569da283cab23",
    "sourceFiles": {
        "config.json": {"sha256": "2a6ac0e9aaa356a68a5688070db78fc3a464fefe85d2f06a1905ce3718687553", "size": 202},
        "tokenizer.json": {"sha256": "e67e803f624fb4d67dea1c730d06e1067e1b14d830e2c2202569e3ef0f70bb50", "size": 683666},
        "model.safetensors": {"sha256": "f65d0f325faadc1e121c319e2faa41170d3fa07d8c89abd48ca5358d9a223de2", "size": 30236760},
        "README.md": {"sha256": "de8ec91bf63c5f4c0e20751c227b2d049953e1cab5f8d5d44211c59a44795bdd", "size": 5203},
    },
    "contentSha256": "fe492f69607b750142aa48d47d579b53252b3288547c27d4d0e473d6af485e1e",
    "dimensions": 256,
    "vocabSize": 29528,
    "tokenizerType": "WordPiece",
    "tokenizer": _WORDPIECE_TOKENIZER_CONTRACT,
    "runtimeEngine": "agentlas_pure_python_wordpiece_v1",
    "embeddingParts": ("embeddings.i8",),
}
_PROFILES = {
    (str(_PINNED_PROFILE["modelId"]), str(_PINNED_PROFILE["revision"])): _PINNED_PROFILE,
    (str(_LEGACY_PROFILE["modelId"]), str(_LEGACY_PROFILE["revision"])): _LEGACY_PROFILE,
}
_PART_NAME_PATTERN = re.compile(r"embeddings\.i8\.part-(\d{3})\Z")


class ModelAssetError(RuntimeError):
    pass


@dataclass(frozen=True)
class VerifiedModelAsset:
    path: Path
    manifest: dict[str, Any]
    content_sha256: str
    dimensions: int
    vocab_size: int
    embedding_parts: tuple[str, ...]
    tokenizer_type: str

    @property
    def identity(self) -> str:
        source = self.manifest["source"]
        return (
            f"model2vec:{source['modelId']}:{source['revision']}:"
            f"{self.content_sha256}:{self.manifest['format']}"
        )


def candidate_model_paths(explicit_path: Path | str | None = None) -> list[Path]:
    candidates: list[Path] = []
    if explicit_path is not None:
        candidates.append(Path(explicit_path).expanduser())
    env_path = os.environ.get(MODEL_PATH_ENV, "").strip()
    if env_path:
        candidates.append(Path(env_path).expanduser())
    runtime_home = os.environ.get(RUNTIME_HOME_ENV, "").strip()
    if runtime_home:
        candidates.append(Path(runtime_home).expanduser() / "models" / "model2vec" / DEFAULT_ASSET_NAME)

    module_path = Path(__file__).resolve()
    for parent in module_path.parents:
        candidates.append(parent / "assets" / "model2vec" / DEFAULT_ASSET_NAME)
    candidates.append(Path.home() / ".agentlas" / "runtime" / "current" / "models" / "model2vec" / DEFAULT_ASSET_NAME)

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve(strict=False))
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def find_verified_model_asset(explicit_path: Path | str | None = None) -> VerifiedModelAsset | None:
    if explicit_path is not None:
        return verify_model_asset(Path(explicit_path).expanduser())
    env_path = os.environ.get(MODEL_PATH_ENV, "").strip()
    if env_path:
        return verify_model_asset(Path(env_path).expanduser())
    for path in candidate_model_paths():
        if not path.exists():
            continue
        try:
            return verify_model_asset(path)
        except ModelAssetError:
            # Auto mode may continue to another verified multilingual install
            # location. It never downloads, repairs, or selects the legacy
            # English-only asset implicitly.
            continue
    return None


# A process that asks for the verified asset again (the hook alone selects the adapter in four places: the router and hub_fallback modules at import,
# the memory recall, the ontology query) used to hash and parse the whole payload each time, ~0.3-0.5 s apiece. The result of a verification that
# passed is kept for this process only, against the size and modification time of every file in the asset folder: a file that changed, was added or
# removed gives a different signature and is verified again from scratch. Never written to disk; a failed verification is never kept.
_VERIFIED_IN_PROCESS: dict[str, tuple[tuple[Any, ...], "VerifiedModelAsset"]] = {}


def _folder_signature(root: Path) -> tuple[Any, ...] | None:
    try:
        with os.scandir(root) as entries:
            return tuple(sorted((entry.name, stat.st_size, stat.st_mtime_ns) for entry in entries for stat in [entry.stat()]))
    except OSError:
        return None


def verify_model_asset(path: Path | str) -> VerifiedModelAsset:
    root = Path(path).expanduser().resolve()
    signature = _folder_signature(root)
    cached = _VERIFIED_IN_PROCESS.get(str(root)) if signature is not None else None
    if cached is not None and cached[0] == signature:
        return cached[1]
    asset = _verify_model_asset_files(root)
    if signature is not None and _folder_signature(root) == signature:  # nothing moved while it was being read
        _VERIFIED_IN_PROCESS[str(root)] = (signature, asset)
    return asset


def _verify_model_asset_files(root: Path) -> VerifiedModelAsset:
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ModelAssetError(f"missing Model2Vec asset manifest: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelAssetError(f"invalid Model2Vec asset manifest: {manifest_path}") from exc
    if manifest.get("format") != ASSET_FORMAT:
        raise ModelAssetError(f"unsupported Model2Vec asset format: {manifest.get('format')!r}")

    source = manifest.get("source") or {}
    profile = _PROFILES.get((str(source.get("modelId") or ""), str(source.get("revision") or "")))
    if profile is None:
        raise ModelAssetError("Model2Vec asset source model or revision is not a pinned release input")
    if source.get("files") != profile["sourceFiles"]:
        raise ModelAssetError("Model2Vec asset upstream file provenance does not match pinned checksums")
    if manifest.get("modelName") != profile["assetName"]:
        raise ModelAssetError("Model2Vec asset modelName does not match its pinned source")
    if manifest.get("license", {}) != {"spdx": "MIT", "file": "LICENSE.model.txt"}:
        raise ModelAssetError("Model2Vec asset must carry its MIT license declaration")

    dimensions = _positive_int(manifest.get("dimensions"), "dimensions")
    vocab_size = _positive_int(manifest.get("vocabSize"), "vocabSize")
    if dimensions != profile["dimensions"] or vocab_size != profile["vocabSize"]:
        raise ModelAssetError("Model2Vec dimensions or vocabulary size do not match the pinned release")
    quantization = manifest.get("quantization") or {}
    if (
        quantization.get("scheme") != "symmetric_per_row_int8"
        or quantization.get("dtype") != "int8"
        or quantization.get("scaleDtype") != "float32le"
    ):
        raise ModelAssetError("unsupported Model2Vec quantization contract")
    runtime = manifest.get("runtime") or {}
    if runtime != {
        "engine": profile["runtimeEngine"],
        "networkRequired": False,
        "externalPackages": [],
    }:
        raise ModelAssetError("Model2Vec runtime contract is not the pinned offline engine")
    if manifest.get("tokenizer") != profile["tokenizer"]:
        raise ModelAssetError("Model2Vec tokenizer contract does not match the pinned release")

    embedding_parts = _embedding_parts(manifest, profile)
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ModelAssetError("manifest files must be an object")
    required = set(embedding_parts) | {"scales.f32le", "tokenizer.json", "LICENSE.model.txt"}
    if set(files) != required:
        raise ModelAssetError(f"manifest files must exactly match the verified payload: {sorted(required)}")
    for name in sorted(required):
        _verify_manifest_file(root, name, files[name])

    combined_embedding_bytes = 0
    for index, name in enumerate(embedding_parts):
        size = int(files[name]["size"])
        if size % dimensions != 0:
            raise ModelAssetError(f"embedding part is not row-aligned: {name}")
        if profile is _PINNED_PROFILE:
            if size > EMBEDDING_PART_MAX_BYTES:
                raise ModelAssetError(f"embedding part exceeds 64 MiB: {name}")
            if index < len(embedding_parts) - 1 and size != EMBEDDING_PART_MAX_BYTES:
                raise ModelAssetError(f"non-final embedding part must be exactly 64 MiB: {name}")
        combined_embedding_bytes += size
    if combined_embedding_bytes != vocab_size * dimensions:
        raise ModelAssetError("combined embedding part size does not match vocabSize * dimensions")
    if int(files["scales.f32le"]["size"]) != vocab_size * 4:
        raise ModelAssetError("scales.f32le size does not match vocabSize * float32")
    if profile is _PINNED_PROFILE and (root / "embeddings.i8").exists():
        raise ModelAssetError("multilingual asset must not contain an unsplit embeddings.i8 payload")

    try:
        tokenizer = json.loads((root / "tokenizer.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelAssetError("invalid tokenizer.json payload") from exc
    _verify_tokenizer(tokenizer, tokenizer_type=str(profile["tokenizerType"]), vocab_size=vocab_size)

    computed_content = content_identity(files, required)
    if manifest.get("contentSha256") != computed_content:
        raise ModelAssetError("asset contentSha256 does not match verified payload files")
    if computed_content != profile["contentSha256"]:
        raise ModelAssetError("asset payload does not match the pinned Agentlas release content SHA-256")
    return VerifiedModelAsset(
        path=root,
        manifest=manifest,
        content_sha256=computed_content,
        dimensions=dimensions,
        vocab_size=vocab_size,
        embedding_parts=embedding_parts,
        tokenizer_type=str(profile["tokenizerType"]),
    )


def content_identity(files: dict[str, Any], names: Iterable[str]) -> str:
    digest = hashlib.sha256()
    for name in sorted(names):
        record = files[name]
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(record["sha256"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(record["size"]).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _embedding_parts(manifest: dict[str, Any], profile: dict[str, Any]) -> tuple[str, ...]:
    expected = tuple(str(name) for name in profile["embeddingParts"])
    if profile is _LEGACY_PROFILE:
        declared = manifest.get("embeddingParts")
        if declared not in (None, []):
            raise ModelAssetError("legacy Model2Vec asset must use its single embeddings.i8 payload")
        return expected

    declared = manifest.get("embeddingParts")
    if not isinstance(declared, list) or any(not isinstance(name, str) for name in declared):
        raise ModelAssetError("multilingual Model2Vec asset must declare ordered embeddingParts")
    parts = tuple(declared)
    if parts != expected:
        raise ModelAssetError(f"embeddingParts must be the pinned ordered list: {list(expected)}")
    for index, name in enumerate(parts):
        match = _PART_NAME_PATTERN.fullmatch(name)
        if match is None or int(match.group(1)) != index:
            raise ModelAssetError("embeddingParts names must be contiguous and ordered from part-000")
    return parts


def _verify_tokenizer(tokenizer: Any, *, tokenizer_type: str, vocab_size: int) -> None:
    if not isinstance(tokenizer, dict):
        raise ModelAssetError("tokenizer payload must be an object")
    model = tokenizer.get("model") or {}
    vocab = model.get("vocab")
    if tokenizer_type == "WordPiece":
        if model.get("type") != "WordPiece" or not isinstance(vocab, dict) or len(vocab) != vocab_size:
            raise ModelAssetError("tokenizer WordPiece vocabulary does not match manifest")
        try:
            ids = sorted(int(value) for value in vocab.values())
        except (TypeError, ValueError) as exc:
            raise ModelAssetError("tokenizer WordPiece ids must be integers") from exc
        if ids != list(range(vocab_size)):
            raise ModelAssetError("tokenizer vocabulary ids must be contiguous and row-aligned")
        return

    if model.get("type") != "Unigram" or not isinstance(vocab, list) or len(vocab) != vocab_size:
        raise ModelAssetError("tokenizer Unigram vocabulary does not match manifest")
    if model.get("byte_fallback") is not False:
        raise ModelAssetError("tokenizer Unigram byte fallback must remain disabled")
    unknown_id = model.get("unk_id")
    if not isinstance(unknown_id, int) or isinstance(unknown_id, bool) or not 0 <= unknown_id < vocab_size:
        raise ModelAssetError("tokenizer Unigram unk_id is invalid")
    for token_id, entry in enumerate(vocab):
        if not isinstance(entry, list) or len(entry) != 2:
            raise ModelAssetError(f"tokenizer Unigram row {token_id} must be [token, logProbability]")
        token, score = entry
        if not isinstance(token, str) or not isinstance(score, (int, float)) or isinstance(score, bool):
            raise ModelAssetError(f"tokenizer Unigram row {token_id} has invalid token or score")
        if not math.isfinite(float(score)):
            raise ModelAssetError(f"tokenizer Unigram row {token_id} score must be finite")
    if vocab[unknown_id][0] not in {"[UNK]", "<unk>"}:
        raise ModelAssetError("tokenizer Unigram unk_id does not identify the unknown token row")


def _verify_manifest_file(root: Path, name: str, record: Any) -> None:
    if not isinstance(record, dict):
        raise ModelAssetError(f"invalid manifest record for {name}")
    target = (root / name).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ModelAssetError(f"asset file escapes root: {name}") from exc
    if not target.is_file() or target.is_symlink():
        raise ModelAssetError(f"missing regular asset file: {target}")
    expected_size = _positive_int(record.get("size"), f"files.{name}.size")
    if target.stat().st_size != expected_size:
        raise ModelAssetError(f"asset size mismatch: {name}")
    expected_sha = str(record.get("sha256") or "")
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None or sha256_file(target) != expected_sha:
        raise ModelAssetError(f"asset SHA-256 mismatch: {name}")


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ModelAssetError(f"{label} must be a positive integer")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify installed Agentlas Model2Vec assets")
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("path", nargs="?", default=None)
    locate = sub.add_parser("locate")
    locate.add_argument("--path")
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            asset = verify_model_asset(args.path) if args.path else find_verified_model_asset()
            if asset is None:
                raise ModelAssetError("no verified local Model2Vec asset found")
        else:
            asset = find_verified_model_asset(args.path)
            if asset is None:
                raise ModelAssetError("no verified local Model2Vec asset found")
    except ModelAssetError as exc:
        print(json.dumps({"status": "fail", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    print(
        json.dumps(
            {
                "status": "pass",
                "path": str(asset.path),
                "identity": asset.identity,
                "contentSha256": asset.content_sha256,
                "dimensions": asset.dimensions,
                "vocabSize": asset.vocab_size,
                "embeddingParts": list(asset.embedding_parts),
                "tokenizer": asset.tokenizer_type,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
