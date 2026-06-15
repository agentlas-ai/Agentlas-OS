import io
import json
import shutil
import tarfile
from pathlib import Path

from agentlas_cloud.update import fetch_latest_release, install_latest_runtime, run_update, write_python_shims


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


def test_update_check_uses_ttl_cache_and_reports_newer_release(tmp_path, monkeypatch):
    monkeypatch.setenv("HEPHAESTUS_RUNTIME_BASE", str(tmp_path / "runtime"))
    calls = []
    release = {"tag_name": "v9.9.9", "tarball_url": "https://example.test/source.tar.gz", "html_url": "https://example.test/v9.9.9"}

    def fake_urlopen(request, timeout):
        calls.append((request.full_url, timeout))
        return FakeResponse(json.dumps(release).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    assert fetch_latest_release(force=False)["tag_name"] == "v9.9.9"
    assert fetch_latest_release(force=False)["tag_name"] == "v9.9.9"
    assert len(calls) == 1

    root = tmp_path / "runtime" / "0.5.0"
    root.mkdir(parents=True)
    (root / "RELEASE").write_text("v0.5.0\n", encoding="utf-8")
    monkeypatch.setattr("agentlas_cloud.update.fetch_latest_release", lambda force=True: release)
    result = run_update(check_only=True, root=root)

    assert result["status"] == "update_available"
    assert result["current"] == "v0.5.0"
    assert result["latest"] == "v9.9.9"


def test_install_latest_runtime_flips_current_and_writes_shims(tmp_path, monkeypatch):
    monkeypatch.setenv("HEPHAESTUS_RUNTIME_BASE", str(tmp_path / "runtime"))
    source = tmp_path / "source"
    (source / "bin").mkdir(parents=True)
    (source / "agentlas_cloud").mkdir()
    (source / "ontology").mkdir()
    (source / "bin" / "hephaestus").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (source / "agentlas_cloud" / "__init__.py").write_text("", encoding="utf-8")
    (source / "ontology" / "__init__.py").write_text("", encoding="utf-8")
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(source, arcname="Hephaestus-test")

    def fake_download(url: str, path: Path):
        shutil.copyfile(archive, path)

    monkeypatch.setattr("agentlas_cloud.update._download", fake_download)
    result = install_latest_runtime({"tag_name": "v0.5.0", "tarball_url": "https://example.test/source.tar.gz"})

    runtime_root = Path(result["runtime_root"])
    current = tmp_path / "runtime" / "current"
    assert (runtime_root / "RELEASE").read_text(encoding="utf-8").strip() == "v0.5.0"
    assert current.exists() or current.is_symlink()
    assert (runtime_root / "bin" / "python3").exists()
    assert "PYTHONUTF8" in (runtime_root / "bin" / "hephaestus.cmd").read_text(encoding="utf-8")


def test_write_python_shims_adds_windows_utf8_launchers(tmp_path):
    bin_dir = tmp_path / "bin"
    write_python_shims(bin_dir, "C:/Python312/python.exe")

    assert 'C:/Python312/python.exe' in (bin_dir / "python3").read_text(encoding="utf-8")
    assert 'C:/Python312/python.exe' in (bin_dir / "python3.cmd").read_text(encoding="utf-8")
    runner = (bin_dir / "hephaestus.cmd").read_text(encoding="utf-8")
    env = (bin_dir / "hephaestus-env.cmd").read_text(encoding="utf-8")
    assert "PYTHONUTF8=1" in runner
    assert "PYTHONIOENCODING=utf-8" in runner
    assert "-m agentlas_cloud" in runner
    assert "PYTHONUTF8=1" in env
