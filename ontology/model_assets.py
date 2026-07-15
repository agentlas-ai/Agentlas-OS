from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ASSET_FORMAT = "agentlas-model2vec-int8-v1"
DEFAULT_ASSET_NAME = "potion-base-8M-int8"
MODEL_PATH_ENV = "AGENTLAS_MODEL2VEC_PATH"
RUNTIME_HOME_ENV = "AGENTLAS_RUNTIME_HOME"
PINNED_SOURCE_MODEL = "minishlab/potion-base-8M"
PINNED_SOURCE_REVISION = "bf8b056651a2c21b8d2565580b8569da283cab23"
PINNED_CONTENT_SHA256 = "fe492f69607b750142aa48d47d579b53252b3288547c27d4d0e473d6af485e1e"
PINNED_SOURCE_FILES = {
    "config.json": {"sha256": "2a6ac0e9aaa356a68a5688070db78fc3a464fefe85d2f06a1905ce3718687553", "size": 202},
    "tokenizer.json": {"sha256": "e67e803f624fb4d67dea1c730d06e1067e1b14d830e2c2202569e3ef0f70bb50", "size": 683666},
    "model.safetensors": {"sha256": "f65d0f325faadc1e121c319e2faa41170d3fa07d8c89abd48ca5358d9a223de2", "size": 30236760},
    "README.md": {"sha256": "de8ec91bf63c5f4c0e20751c227b2d049953e1cab5f8d5d44211c59a44795bdd", "size": 5203},
}


class ModelAssetError(RuntimeError):
    pass


@dataclass(frozen=True)
class VerifiedModelAsset:
    path: Path
    manifest: dict[str, Any]
    content_sha256: str
    dimensions: int
    vocab_size: int

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
            # Auto mode may continue to another verified install location. It
            # never tries a remote model id or repairs an asset at runtime.
            continue
    return None


def verify_model_asset(path: Path | str) -> VerifiedModelAsset:
    root = Path(path).expanduser().resolve()
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
    if source.get("modelId") != PINNED_SOURCE_MODEL or source.get("revision") != PINNED_SOURCE_REVISION:
        raise ModelAssetError("Model2Vec asset source model or revision is not the pinned release input")
    if source.get("files") != PINNED_SOURCE_FILES:
        raise ModelAssetError("Model2Vec asset upstream file provenance does not match pinned checksums")
    if manifest.get("license", {}).get("spdx") != "MIT":
        raise ModelAssetError("Model2Vec asset must carry its MIT license declaration")
    dimensions = _positive_int(manifest.get("dimensions"), "dimensions")
    vocab_size = _positive_int(manifest.get("vocabSize"), "vocabSize")
    quantization = manifest.get("quantization") or {}
    if quantization.get("scheme") != "symmetric_per_row_int8" or quantization.get("scaleDtype") != "float32le":
        raise ModelAssetError("unsupported Model2Vec quantization contract")

    files = manifest.get("files")
    if not isinstance(files, dict):
        raise ModelAssetError("manifest files must be an object")
    required = {"embeddings.i8", "scales.f32le", "tokenizer.json", "LICENSE.model.txt"}
    if not required <= set(files):
        raise ModelAssetError(f"manifest missing required files: {sorted(required - set(files))}")
    for name in sorted(required):
        _verify_manifest_file(root, name, files[name])
    if int(files["embeddings.i8"]["size"]) != vocab_size * dimensions:
        raise ModelAssetError("embeddings.i8 size does not match vocabSize * dimensions")
    if int(files["scales.f32le"]["size"]) != vocab_size * 4:
        raise ModelAssetError("scales.f32le size does not match vocabSize * float32")

    tokenizer = json.loads((root / "tokenizer.json").read_text(encoding="utf-8"))
    model = tokenizer.get("model") or {}
    vocab = model.get("vocab")
    if model.get("type") != "WordPiece" or not isinstance(vocab, dict) or len(vocab) != vocab_size:
        raise ModelAssetError("tokenizer WordPiece vocabulary does not match manifest")
    ids = sorted(int(value) for value in vocab.values())
    if ids != list(range(vocab_size)):
        raise ModelAssetError("tokenizer vocabulary ids must be contiguous and row-aligned")

    computed_content = content_identity(files, required)
    if manifest.get("contentSha256") != computed_content:
        raise ModelAssetError("asset contentSha256 does not match verified payload files")
    if computed_content != PINNED_CONTENT_SHA256:
        raise ModelAssetError("asset payload does not match the pinned Agentlas release content SHA-256")
    return VerifiedModelAsset(
        path=root,
        manifest=manifest,
        content_sha256=computed_content,
        dimensions=dimensions,
        vocab_size=vocab_size,
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
    if len(expected_sha) != 64 or sha256_file(target) != expected_sha:
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
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
