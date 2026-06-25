import io
import json
import shutil
import tarfile
from pathlib import Path

from agentlas_cloud.update import (
    fetch_latest_release,
    install_latest_runtime,
    maybe_auto_update,
    run_update,
    sync_installed_runtime_adapters,
    write_python_shims,
)


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

    root = tmp_path / "runtime" / "0.7.5"
    root.mkdir(parents=True)
    (root / "RELEASE").write_text("v0.7.5\n", encoding="utf-8")
    monkeypatch.setattr("agentlas_cloud.update.fetch_latest_release", lambda force=True: release)
    result = run_update(check_only=True, root=root)

    assert result["status"] == "update_available"
    assert result["current"] == "v0.7.5"
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
    result = install_latest_runtime({"tag_name": "v0.7.5", "tarball_url": "https://example.test/source.tar.gz"})

    runtime_root = Path(result["runtime_root"])
    current = tmp_path / "runtime" / "current"
    assert (runtime_root / "RELEASE").read_text(encoding="utf-8").strip() == "v0.7.5"
    assert current.exists() or current.is_symlink()
    assert (runtime_root / "bin" / "python3").exists()
    assert "PYTHONUTF8" in (runtime_root / "bin" / "hephaestus.cmd").read_text(encoding="utf-8")


def test_maybe_auto_update_defaults_on_and_installs_newer_release(tmp_path, monkeypatch):
    runtime_base = tmp_path / "runtime"
    monkeypatch.setenv("HEPHAESTUS_RUNTIME_BASE", str(runtime_base))
    monkeypatch.delenv("HEPHAESTUS_AUTO_UPDATE", raising=False)
    monkeypatch.delenv("HEPHAESTUS_UPDATE_CHECK", raising=False)
    root = runtime_base / "0.7.5"
    root.mkdir(parents=True)
    (root / "RELEASE").write_text("v0.7.5\n", encoding="utf-8")
    release = {"tag_name": "v0.7.6", "tarball_url": "https://example.test/source.tar.gz"}
    calls = []

    monkeypatch.setattr("agentlas_cloud.update.fetch_latest_release", lambda force=False: release)
    monkeypatch.setattr("agentlas_cloud.update.install_latest_runtime", lambda item: calls.append(item) or {"updated_to": item["tag_name"]})

    maybe_auto_update(root=root, background=False)

    assert calls == [release]


def test_maybe_auto_update_respects_auto_update_opt_out(tmp_path, monkeypatch):
    runtime_base = tmp_path / "runtime"
    monkeypatch.setenv("HEPHAESTUS_RUNTIME_BASE", str(runtime_base))
    monkeypatch.setenv("HEPHAESTUS_AUTO_UPDATE", "0")
    root = runtime_base / "0.7.5"
    root.mkdir(parents=True)
    (root / "RELEASE").write_text("v0.7.5\n", encoding="utf-8")
    calls = []

    monkeypatch.setattr("agentlas_cloud.update.fetch_latest_release", lambda force=False: {"tag_name": "v0.7.6"})
    monkeypatch.setattr("agentlas_cloud.update.install_latest_runtime", lambda item: calls.append(item) or {})

    maybe_auto_update(root=root, background=False)

    assert calls == []


def test_maybe_auto_update_is_fail_silent_when_fetch_fails(tmp_path, monkeypatch):
    runtime_base = tmp_path / "runtime"
    monkeypatch.setenv("HEPHAESTUS_RUNTIME_BASE", str(runtime_base))
    monkeypatch.delenv("HEPHAESTUS_AUTO_UPDATE", raising=False)
    monkeypatch.delenv("HEPHAESTUS_UPDATE_CHECK", raising=False)
    root = runtime_base / "0.7.5"
    root.mkdir(parents=True)
    (root / "RELEASE").write_text("v0.7.5\n", encoding="utf-8")

    def fail_fetch(force=False):
        raise OSError("offline")

    monkeypatch.setattr("agentlas_cloud.update.fetch_latest_release", fail_fetch)

    assert maybe_auto_update(root=root, background=False) is None


def test_sync_installed_runtime_adapters_overwrites_existing_paths_only(tmp_path):
    source = tmp_path / "source"
    home = tmp_path / "home"
    (source / ".claude" / "commands").mkdir(parents=True)
    (source / ".claude" / "commands" / "hep-build.md").write_text("new claude\n", encoding="utf-8")
    (source / ".claude" / "commands" / "hep-network.md").write_text("new missing claude\n", encoding="utf-8")
    (source / "codex" / "prompts").mkdir(parents=True)
    (source / "codex" / "prompts" / "hep-build.md").write_text("new codex\n", encoding="utf-8")
    (source / "skills" / "hephaestus-network").mkdir(parents=True)
    (source / "skills" / "hephaestus-network" / "SKILL.md").write_text("new skill\n", encoding="utf-8")
    (source / "skills" / "hephaestus-cloud").mkdir(parents=True)
    (source / "skills" / "hephaestus-cloud" / "SKILL.md").write_text("new cloud skill\n", encoding="utf-8")

    (home / ".claude" / "commands").mkdir(parents=True)
    (home / ".claude" / "commands" / "hep-build.md").write_text("old claude\n", encoding="utf-8")
    (home / ".codex" / "prompts").mkdir(parents=True)
    (home / ".agents" / "skills" / "hephaestus-network").mkdir(parents=True)
    (home / ".agents" / "skills" / "hephaestus-network" / "SKILL.md").write_text("old skill\n", encoding="utf-8")

    result = sync_installed_runtime_adapters(source, home=home)

    assert (home / ".claude" / "commands" / "hep-build.md").read_text(encoding="utf-8") == "new claude\n"
    assert not (home / ".claude" / "commands" / "hep-network.md").exists()
    assert not (home / ".codex" / "prompts" / "hep-build.md").exists()
    assert (home / ".agents" / "skills" / "hephaestus-network" / "SKILL.md").read_text(encoding="utf-8") == "new skill\n"
    assert not (home / ".agents" / "skills" / "hephaestus-cloud").exists()
    assert str(home / ".claude" / "commands" / "hep-build.md") in result["updated"]


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
