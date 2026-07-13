import io
import hashlib
import json
import os
import shutil
import tarfile
import time
from pathlib import Path

import pytest

from agentlas_cloud.update import (
    _compare_semver,
    _release_status,
    _safe_extract,
    fetch_latest_release,
    install_latest_runtime,
    maybe_auto_update,
    run_update,
    sync_installed_runtime_adapters,
    write_python_shims,
)


def test_runtime_update_uses_semver_prerelease_precedence():
    precedence = [
        "1.0.0-alpha",
        "1.0.0-alpha.1",
        "1.0.0-alpha.beta",
        "1.0.0-beta",
        "1.0.0-beta.2",
        "1.0.0-beta.11",
        "1.0.0-rc.1",
        "1.0.0",
    ]
    for left, right in zip(precedence, precedence[1:]):
        assert _compare_semver(left, right) == -1
        assert _compare_semver(right, left) == 1

    assert _compare_semver("v2.3.4", "2.3.4") == 0
    assert _compare_semver("1.0.0+build.1", "1.0.0+build.99") == 0
    assert _compare_semver("1.0.0-1", "1.0.0-alpha") == -1
    assert _compare_semver("999999999999999999999.0.0", "2.0.0") == 1
    assert _compare_semver("1.0.0-01", "1.0.0") is None
    assert _compare_semver("01.0.0", "1.0.0") is None

    assert _release_status("v1.0.0-rc.1", "v1.0.0") == "update_available"
    assert _release_status("v1.0.0", "v1.0.0-rc.99") == "current"
    assert _release_status("v1.0.0+local", "v1.0.0+remote") == "current"
    assert _release_status("release-main", "v1.0.0") == "unknown"


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


def _write_runtime_source(source: Path) -> None:
    (source / "bin").mkdir(parents=True)
    (source / "agentlas_cloud").mkdir()
    (source / "ontology").mkdir()
    (source / "bin" / "hephaestus").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    for relative in (
        Path("agentlas_cloud") / "__init__.py",
        Path("agentlas_cloud") / "__main__.py",
        Path("agentlas_cloud") / "cli.py",
        Path("agentlas_cloud") / "update.py",
        Path("ontology") / "__init__.py",
    ):
        (source / relative).write_text("", encoding="utf-8")


def _write_runtime_archive(tmp_path: Path, name: str = "source.tar.gz") -> Path:
    source = tmp_path / f"{name}.source"
    _write_runtime_source(source)
    archive = tmp_path / name
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(source, arcname="Hephaestus-test")
    return archive


def _release_with_runtime_asset(tag: str, archive: Path, *, digest: str | None = None, size: int | None = None):
    name = f"hephaestus-runtime-{tag}.tar.gz"
    return {
        "tag_name": tag,
        # The updater must ignore GitHub's digest-less generated tarball.
        "tarball_url": f"https://api.github.com/repos/agentlas-ai/Agentlas-OS/tarball/{tag}",
        "assets": [
            {
                "name": name,
                "browser_download_url": f"https://github.com/agentlas-ai/Agentlas-OS/releases/download/{tag}/{name}",
                "digest": f"sha256:{digest or hashlib.sha256(archive.read_bytes()).hexdigest()}",
                "size": archive.stat().st_size if size is None else size,
            }
        ],
    }


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


def test_update_recovers_runtime_without_release_marker(tmp_path, monkeypatch):
    monkeypatch.setenv("HEPHAESTUS_RUNTIME_BASE", str(tmp_path / "runtime"))
    root = tmp_path / "stale-plugin-cache"
    root.mkdir()
    release = {"tag_name": "v9.9.9", "tarball_url": "https://example.test/source.tar.gz", "html_url": "https://example.test/v9.9.9"}
    calls = []

    monkeypatch.setattr("agentlas_cloud.update.fetch_latest_release", lambda force=True: release)
    monkeypatch.setattr(
        "agentlas_cloud.update.install_latest_runtime",
        lambda item: calls.append(item) or {"updated_to": item["tag_name"], "runtime_root": str(tmp_path / "runtime" / "9.9.9")},
    )

    result = run_update(check_only=False, root=root)

    assert calls == [release]
    assert result["status"] == "recovered_missing_release_marker"
    assert result["current"] is None
    assert result["latest"] == "v9.9.9"


def test_install_latest_runtime_flips_current_and_writes_shims(tmp_path, monkeypatch):
    monkeypatch.setenv("HEPHAESTUS_RUNTIME_BASE", str(tmp_path / "runtime"))
    archive = _write_runtime_archive(tmp_path)
    expected_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()

    def fake_download(url: str, path: Path):
        shutil.copyfile(archive, path)

    monkeypatch.setattr("agentlas_cloud.update._download", fake_download)
    result = install_latest_runtime(_release_with_runtime_asset("v0.7.5", archive))

    runtime_root = Path(result["runtime_root"])
    current = tmp_path / "runtime" / "current"
    assert (runtime_root / "RELEASE").read_text(encoding="utf-8").strip() == "v0.7.5"
    assert current.exists() or current.is_symlink()
    assert current.resolve() == runtime_root.resolve()
    assert (runtime_root / "bin" / "python3").exists()
    assert "PYTHONUTF8" in (runtime_root / "bin" / "hephaestus.cmd").read_text(encoding="utf-8")
    assert result["archive_digest"] == f"sha256:{expected_sha256}"
    assert result["digest_verified"] is True
    assert result["archive_asset"] == "hephaestus-runtime-v0.7.5.tar.gz"


def test_install_latest_runtime_rejects_digest_mismatch_before_activation(tmp_path, monkeypatch):
    runtime_base = tmp_path / "runtime"
    monkeypatch.setenv("HEPHAESTUS_RUNTIME_BASE", str(runtime_base))
    archive = _write_runtime_archive(tmp_path)

    def fake_download(url: str, path: Path):
        shutil.copyfile(archive, path)

    monkeypatch.setattr("agentlas_cloud.update._download", fake_download)

    with pytest.raises(ValueError, match="digest mismatch"):
        install_latest_runtime(_release_with_runtime_asset("v0.7.5", archive, digest="0" * 64))

    assert not (runtime_base / "0.7.5").exists()
    assert not (runtime_base / "current").exists()
    assert not (runtime_base / ".update.lock").exists()


def test_install_latest_runtime_requires_digest_bearing_tag_asset_before_download(tmp_path, monkeypatch):
    monkeypatch.setenv("HEPHAESTUS_RUNTIME_BASE", str(tmp_path / "runtime"))
    calls = []
    monkeypatch.setattr("agentlas_cloud.update._download", lambda url, path: calls.append(url))

    with pytest.raises(ValueError, match="missing verified runtime asset"):
        install_latest_runtime(
            {
                "tag_name": "v0.7.5",
                "tarball_url": "https://api.github.com/repos/agentlas-ai/Agentlas-OS/tarball/v0.7.5",
                "assets": [],
            }
        )
    with pytest.raises(ValueError, match="missing SHA-256 metadata"):
        install_latest_runtime(
            {
                "tag_name": "v0.7.5",
                "assets": [
                    {
                        "name": "hephaestus-runtime-v0.7.5.tar.gz",
                        "browser_download_url": "https://github.com/agentlas-ai/Agentlas-OS/releases/download/v0.7.5/hephaestus-runtime-v0.7.5.tar.gz",
                        "size": 123,
                    }
                ],
            }
        )
    assert calls == [], "unsafe release metadata must fail before network access"


@pytest.mark.parametrize("member_kind", ["traversal", "symlink", "hardlink"])
def test_safe_extract_rejects_path_and_link_escapes(tmp_path, member_kind):
    archive = tmp_path / f"{member_kind}.tar.gz"
    payload = b"blocked"
    with tarfile.open(archive, "w:gz") as tf:
        if member_kind == "traversal":
            member = tarfile.TarInfo("../outside.txt")
            member.size = len(payload)
            tf.addfile(member, io.BytesIO(payload))
        else:
            member = tarfile.TarInfo(f"root/{member_kind}")
            member.type = tarfile.SYMTYPE if member_kind == "symlink" else tarfile.LNKTYPE
            member.linkname = "../../outside.txt"
            tf.addfile(member)

    destination = tmp_path / "extract"
    destination.mkdir()
    with tarfile.open(archive, "r:gz") as tf, pytest.raises(ValueError, match="archive links|unsafe path"):
        _safe_extract(tf, destination)

    assert not (tmp_path / "outside.txt").exists()


def test_install_latest_runtime_rolls_back_current_when_post_switch_healthcheck_fails(tmp_path, monkeypatch):
    runtime_base = tmp_path / "runtime"
    old_runtime = runtime_base / "0.7.4"
    old_runtime.mkdir(parents=True)
    current = runtime_base / "current"
    current.symlink_to(old_runtime, target_is_directory=True)
    monkeypatch.setenv("HEPHAESTUS_RUNTIME_BASE", str(runtime_base))
    archive = _write_runtime_archive(tmp_path)
    sync_calls = []

    def fake_download(url: str, path: Path):
        shutil.copyfile(archive, path)

    def fail_after_switch(path: Path):
        if path.name == "current":
            raise RuntimeError("post-switch healthcheck failed")

    monkeypatch.setattr("agentlas_cloud.update._download", fake_download)
    monkeypatch.setattr("agentlas_cloud.update._healthcheck_runtime", fail_after_switch)
    monkeypatch.setattr("agentlas_cloud.update.sync_installed_runtime_adapters", lambda source: sync_calls.append(source) or {})

    with pytest.raises(RuntimeError, match="post-switch healthcheck failed"):
        install_latest_runtime(_release_with_runtime_asset("v0.7.5", archive))

    assert current.is_symlink()
    assert current.resolve() == old_runtime.resolve()
    assert not (runtime_base / "0.7.5").exists()
    assert not list(runtime_base.glob(".*.backup.*"))
    assert not (runtime_base / ".update.lock").exists()
    assert sync_calls == []


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


def test_maybe_auto_update_recovers_dead_lock_even_with_recent_start_marker(tmp_path, monkeypatch):
    runtime_base = tmp_path / "runtime"
    monkeypatch.setenv("HEPHAESTUS_RUNTIME_BASE", str(runtime_base))
    monkeypatch.delenv("HEPHAESTUS_AUTO_UPDATE", raising=False)
    monkeypatch.delenv("HEPHAESTUS_UPDATE_CHECK", raising=False)
    root = runtime_base / "0.7.5"
    root.mkdir(parents=True)
    (root / "RELEASE").write_text("v0.7.5\n", encoding="utf-8")
    lock = runtime_base / ".update.lock"
    # Older updater releases wrote only the PID, so stale recovery must remain
    # backward compatible with that lock format.
    lock.write_text("987654", encoding="utf-8")
    (runtime_base / "auto-update.json").write_text(
        json.dumps({"last_started_epoch": int(time.time())}),
        encoding="utf-8",
    )
    release = {"tag_name": "v0.7.6", "tarball_url": "https://example.test/source.tar.gz"}
    calls = []

    monkeypatch.setattr("agentlas_cloud.update._pid_is_running", lambda pid: False)
    monkeypatch.setattr("agentlas_cloud.update.reconcile_adapters", lambda: {"count": 0, "sanitized": []})
    monkeypatch.setattr("agentlas_cloud.update.fetch_latest_release", lambda force=False: release)
    monkeypatch.setattr("agentlas_cloud.update.install_latest_runtime", lambda item: calls.append(item) or {"updated_to": item["tag_name"]})

    maybe_auto_update(root=root, background=False)

    assert calls == [release]
    assert not lock.exists()


def test_maybe_auto_update_keeps_live_lock(tmp_path, monkeypatch):
    runtime_base = tmp_path / "runtime"
    monkeypatch.setenv("HEPHAESTUS_RUNTIME_BASE", str(runtime_base))
    monkeypatch.delenv("HEPHAESTUS_AUTO_UPDATE", raising=False)
    monkeypatch.delenv("HEPHAESTUS_UPDATE_CHECK", raising=False)
    root = runtime_base / "0.7.5"
    root.mkdir(parents=True)
    (root / "RELEASE").write_text("v0.7.5\n", encoding="utf-8")
    lock = runtime_base / ".update.lock"
    lock.write_text(
        json.dumps({"pid": os.getpid(), "created_epoch": int(time.time()), "token": "active"}),
        encoding="utf-8",
    )
    calls = []

    monkeypatch.setattr("agentlas_cloud.update.reconcile_adapters", lambda: {"count": 0, "sanitized": []})
    monkeypatch.setattr("agentlas_cloud.update.fetch_latest_release", lambda force=False: calls.append("fetch") or {})

    maybe_auto_update(root=root, background=False)

    assert calls == []
    assert lock.exists()


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


def test_sync_installed_runtime_adapters_replaces_existing_plugin_cache_dirs(tmp_path, monkeypatch):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    source = tmp_path / "source"
    home = tmp_path / "home"
    claude_src = source / "claude" / "plugins" / "agentlas-core-engine-meta-agent"
    codex_src = source / "codex" / "plugins" / "agentlas-core-engine-meta-agent"
    source.mkdir()
    (source / "manifest.json").write_text(json.dumps({"version": "9.9.9"}), encoding="utf-8")
    for src, marker in ((claude_src, "new claude plugin"), (codex_src, "new codex plugin")):
        (src / "bin").mkdir(parents=True)
        (src / "bin" / "hephaestus").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        (src / "plugin-marker.txt").write_text(marker, encoding="utf-8")

    claude_old = home / ".claude" / "plugins" / "cache" / "agentlas-core-engine" / "hephaestus" / "0.7.23"
    codex_old = home / ".codex" / "plugins" / "cache" / "agentlas-core-engine" / "hephaestus" / "0.7.23"
    untouched = home / ".claude" / "plugins" / "cache" / "agentlas-core-engine" / "hephaestus" / "notes"
    for dest in (claude_old, codex_old, untouched):
        (dest / "bin").mkdir(parents=True)
    (claude_old / "bin" / "hephaestus").write_text("old\n", encoding="utf-8")
    (codex_old / "bin" / "hephaestus").write_text("old\n", encoding="utf-8")
    (untouched / "README.md").write_text("not a plugin cache runtime\n", encoding="utf-8")

    result = sync_installed_runtime_adapters(source, home=home)

    assert (claude_old / "plugin-marker.txt").read_text(encoding="utf-8") == "new claude plugin"
    assert (codex_old / "plugin-marker.txt").read_text(encoding="utf-8") == "new codex plugin"
    assert (claude_old / "RELEASE").read_text(encoding="utf-8").strip() == "v9.9.9"
    assert (codex_old / "RELEASE").read_text(encoding="utf-8").strip() == "v9.9.9"
    assert (claude_old / "bin" / "python3").exists()
    assert (codex_old / "bin" / "python3").exists()
    assert (untouched / "README.md").read_text(encoding="utf-8") == "not a plugin cache runtime\n"
    assert str(claude_old) in result["updated"]
    assert str(codex_old) in result["updated"]


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
    assert "if defined HEPHAESTUS_PYTHON" in runner
    assert "|| python" not in runner
    assert "exit /b %ERRORLEVEL%" in runner
    assert "PYTHONUTF8=1" in env
