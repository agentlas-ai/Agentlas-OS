from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ontology.model_assets import ModelAssetError, find_verified_model_asset, verify_model_asset


class Model2VecReleaseAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo = Path(__file__).resolve().parents[1]
        cls.asset_path = cls.repo / "assets" / "model2vec" / "potion-base-8M-int8"

    def test_tracked_asset_manifest_and_payload_are_verified(self):
        asset = verify_model_asset(self.asset_path)
        self.assertEqual(asset.dimensions, 256)
        self.assertEqual(asset.vocab_size, 29528)
        self.assertEqual(
            asset.content_sha256,
            "fe492f69607b750142aa48d47d579b53252b3288547c27d4d0e473d6af485e1e",
        )
        manifest = asset.manifest
        self.assertEqual(manifest["source"]["revision"], "bf8b056651a2c21b8d2565580b8569da283cab23")
        self.assertEqual(manifest["license"]["spdx"], "MIT")
        self.assertEqual(manifest["quantization"]["scheme"], "symmetric_per_row_int8")
        self.assertEqual(manifest["runtime"]["networkRequired"], False)
        self.assertEqual(manifest["runtime"]["externalPackages"], [])

    def test_same_path_payload_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "potion-base-8M-int8"
            shutil.copytree(self.asset_path, copied)
            embeddings = copied / "embeddings.i8"
            with open(embeddings, "r+b") as handle:
                first = handle.read(1)
                handle.seek(0)
                handle.write(bytes([first[0] ^ 1]))
            with self.assertRaisesRegex(ModelAssetError, "SHA-256 mismatch"):
                verify_model_asset(copied)

    def test_manifest_cannot_relabel_pinned_upstream_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "potion-base-8M-int8"
            shutil.copytree(self.asset_path, copied)
            manifest_path = copied / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["source"]["revision"] = "0" * 40
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(ModelAssetError, "pinned release input"):
                verify_model_asset(copied)

    def test_explicit_env_asset_path_is_verified_not_downloaded(self):
        with mock.patch.dict(os.environ, {"AGENTLAS_MODEL2VEC_PATH": str(self.asset_path)}, clear=False):
            asset = find_verified_model_asset()
        self.assertIsNotNone(asset)
        self.assertEqual(asset.path, self.asset_path.resolve())

    def test_build_check_and_installed_verify_cli_are_offline(self):
        check = subprocess.run(
            [sys.executable, "scripts/build-model2vec-asset.py", "--check"],
            cwd=self.repo,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(json.loads(check.stdout)["status"], "pass")
        verify = subprocess.run(
            [sys.executable, "-m", "ontology.model_assets", "verify", str(self.asset_path)],
            cwd=self.repo,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(json.loads(verify.stdout)["status"], "pass")


if __name__ == "__main__":
    unittest.main()
