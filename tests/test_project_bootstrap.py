from __future__ import annotations

import gc
import json
import os
import stat
import subprocess
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from agentlas_cloud import cli, mcp_stdio, project_bootstrap
from agentlas_cloud.project_bootstrap import ensure_project, generate_code_map, maybe_ensure_project, project_status


def make_project(tmp_path: Path) -> Path:
    project = tmp_path / "workspace"
    project.mkdir()
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    (project / "main.py").write_text("def hello_world():\n    return 1\n", encoding="utf-8")
    return project


def test_first_contact_creates_complete_private_project_architecture(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    result = ensure_project(project, reason="test-first-contact")

    assert result["status"] == "active"
    assert result["missing"] == []
    assert result["mergeOnly"] is True
    assert result["overwritten"] == []
    assert result["warnings"] == []
    assert result["codeMap"]["stats"]["codeFiles"] == 1
    assert (project / ".agentlas" / "project-soul-memory.md").is_file()
    assert (project / ".agentlas" / "code-map" / "project-map.json").is_file()
    assert (project / ".agentlas" / "ontology-runtime.sqlite").is_file()
    assert (project / ".agentlas" / "career-graph.sqlite").is_file()
    assert (project / "signing" / "README.md").is_file()
    assert (project / "credentials" / "README.md").is_file()

    ignored = subprocess.run(
        ["git", "-C", str(project), "check-ignore", "-q", ".agentlas/project-soul-memory.md"],
        check=False,
    )
    assert ignored.returncode == 0
    visible = subprocess.check_output(["git", "-C", str(project), "status", "--short"], text=True)
    assert ".agentlas/project-soul-memory.md" not in visible
    assert ".agentlas/code-map" not in visible
    env_example_ignored = subprocess.run(
        ["git", "-C", str(project), "check-ignore", "-q", ".env.example"],
        check=False,
    )
    assert env_example_ignored.returncode != 0

    project_map = json.loads((project / ".agentlas" / "code-map" / "project-map.json").read_text(encoding="utf-8"))
    assert project_map["schemaVersion"] == "agentlas.code-map.v1"
    assert project_map["entryPoints"][0]["path"] == "main.py"
    assert str(project) not in json.dumps(result)
    assert stat.S_IMODE((project / ".agentlas").stat().st_mode) == 0o700
    assert result["privateModeCompliant"] is True
    assert all(
        stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
        for path in (project / ".agentlas").rglob("*")
        if not path.is_symlink()
    )


def test_bootstrap_is_idempotent_and_never_overwrites_user_memory(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    ensure_project(project)
    soul = project / ".agentlas" / "project-soul-memory.md"
    soul.write_text("USER CONTENT MUST SURVIVE\n", encoding="utf-8")

    repeated = ensure_project(project, reason="test-repeat")

    assert repeated["status"] == "active"
    assert repeated["created"] == []
    assert repeated["gitignore"]["changed"] is False
    assert repeated["codeMap"]["status"] == "existing"
    assert soul.read_text(encoding="utf-8") == "USER CONTENT MUST SURVIVE\n"


def test_changed_source_refreshes_existing_code_map(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    ensure_project(project)
    (project / "main.py").write_text("def refreshed_symbol():\n    return 2\n", encoding="utf-8")

    refreshed = ensure_project(project)
    project_map = json.loads((project / ".agentlas" / "code-map" / "project-map.json").read_text(encoding="utf-8"))

    assert refreshed["codeMap"]["status"] == "refreshed"
    assert "refreshed_symbol" in json.dumps(project_map)


def test_ctime_detects_same_size_replacement_even_when_mtime_is_restored(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    source = project / "main.py"
    source.write_text("def alpha_name():\n    return 1\n", encoding="utf-8")
    ensure_project(project)
    before = source.stat()
    source.write_text("def bravo_name():\n    return 2\n", encoding="utf-8")
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))

    refreshed = ensure_project(project)

    assert refreshed["codeMap"]["status"] == "refreshed"
    raw = (project / ".agentlas" / "code-map" / "project-map.json").read_text(encoding="utf-8")
    assert "bravo_name" in raw
    assert "alpha_name" not in raw


def test_concurrent_first_contacts_converge_without_partial_files(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda index: ensure_project(project, reason=f"concurrent-{index}"), range(6)))

    assert all(result["status"] == "active" for result in results)
    assert project_status(project)["missing"] == []
    leftovers = [path for path in project.rglob("*") if ".tmp-" in path.name]
    assert leftovers == []
    assert stat.S_IMODE((project / ".agentlas" / ".project-bootstrap.lock").stat().st_mode) == 0o600


def test_existing_tracked_private_paths_are_reported_not_removed(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    private = project / ".agentlas" / "project-soul-memory.md"
    private.parent.mkdir()
    private.write_text("tracked before Agentlas privacy install\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(project), "add", ".agentlas/project-soul-memory.md"], check=True)

    result = ensure_project(project)

    assert ".agentlas/project-soul-memory.md" in result["trackedSensitivePaths"]
    staged = subprocess.check_output(["git", "-C", str(project), "diff", "--cached", "--name-only"], text=True)
    assert ".agentlas/project-soul-memory.md" in staged
    assert private.read_text(encoding="utf-8") == "tracked before Agentlas privacy install\n"
    assert result["status"] == "privacy_warning"
    assert cli._project_bootstrap_blocks_execution(result) is False


def test_status_is_read_only_and_redacts_absolute_root(tmp_path: Path) -> None:
    project = make_project(tmp_path)

    status = project_status(project)

    assert status["status"] == "incomplete"
    assert not (project / ".agentlas").exists()
    assert str(project) not in json.dumps(status)


def test_status_refuses_unsafe_gitignore_without_following_it(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    outside = tmp_path / "outside-status"
    outside.write_text("PRIVATE OUTSIDE CONTENT\n", encoding="utf-8")
    (project / ".gitignore").symlink_to(outside)

    status = project_status(project)

    assert status["privacyBlockInstalled"] is False
    assert "unsafe_gitignore_file" in status["privacyWarnings"]
    assert outside.read_text(encoding="utf-8") == "PRIVATE OUTSIDE CONTENT\n"


def test_private_mode_uses_posix_bits_only_on_posix_hosts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = make_project(tmp_path)
    ensure_project(project)
    state = project / ".agentlas"
    state.chmod(0o755)

    posix_status = project_status(project)
    assert ".agentlas:group_or_world_access" in posix_status["permissionIssues"]

    # Windows reports synthetic Unix mode bits even though access is governed
    # by account ACLs. Those bits must not turn a complete bootstrap into a
    # false privacy warning for Desktop and Terminal hosts.
    monkeypatch.setattr(project_bootstrap, "POSIX_PRIVATE_MODE_ENFORCEMENT", False)
    windows_semantics = project_status(project)
    assert windows_semantics["privateModeCompliant"] is True
    assert windows_semantics["permissionIssues"] == []


def test_tracked_sensitive_scan_is_byte_and_count_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = make_project(tmp_path)
    private = project / ".agentlas"
    private.mkdir(mode=0o700)
    for index in range(20):
        path = private / f"private-{index:02d}.json"
        path.write_text("{}\n", encoding="utf-8")
        path.chmod(0o600)
    subprocess.run(["git", "-C", str(project), "add", "-f", ".agentlas"], check=True)
    monkeypatch.setattr(project_bootstrap, "MAX_TRACKED_PATH_BYTES", 64)
    monkeypatch.setattr(project_bootstrap, "MAX_TRACKED_PATHS", 3)

    status = project_status(project)

    assert status["trackedSensitiveScanComplete"] is False
    assert len(status["trackedSensitivePaths"]) <= 3
    assert "tracked_sensitive_scan_incomplete" in status["privacyWarnings"]


def test_automatic_bootstrap_requires_host_opt_in_and_workspace_marker(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    disabled = maybe_ensure_project(project, reason="test", enabled=False)
    assert disabled["status"] == "disabled"
    assert disabled["writeAttempted"] is False
    assert not (project / ".agentlas").exists()

    one_off = tmp_path / "one-off"
    one_off.mkdir()
    skipped = maybe_ensure_project(one_off, reason="test", enabled=True, trusted_target=True)
    assert skipped["status"] == "skipped"
    assert skipped["detail"] == "workspace_marker_missing"
    assert not (one_off / ".agentlas").exists()

    enabled = maybe_ensure_project(project, reason="test", enabled=True, trusted_target=True)
    assert enabled["status"] == "active"
    assert enabled["writeAttempted"] is True


def test_cli_implicit_bootstrap_is_disabled_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = make_project(tmp_path)
    monkeypatch.delenv(project_bootstrap.AUTO_BOOTSTRAP_ENV, raising=False)

    receipt = cli._project_bootstrap_receipt(project, "cli-test")

    assert receipt["status"] == "disabled"
    assert not (project / ".agentlas").exists()


def test_trusted_plugin_contact_bootstraps_an_unmarked_current_project(tmp_path: Path) -> None:
    project = tmp_path / "unmarked-plugin-project"
    project.mkdir()
    (project / "main.py").write_text("def plugin_contact(): return True\n", encoding="utf-8")

    receipt = cli._project_bootstrap_receipt(
        project,
        "test-plugin-first-contact",
        trusted_contact=True,
    )

    assert receipt["status"] == "privacy_warning"
    assert receipt["trackedSensitivePaths"] == []
    assert receipt["privacyBlockInstalled"] is True
    assert cli._project_bootstrap_blocks_execution(receipt) is False
    assert (project / ".agentlas" / "project-soul-memory.md").is_file()
    assert (project / ".agentlas" / "code-map" / "project-map.json").is_file()
    assert (project / ".agentlas" / "ontology-runtime.sqlite").is_file()
    assert (project / ".agentlas" / "career-graph.sqlite").is_file()
    assert ".agentlas/" in (project / ".gitignore").read_text(encoding="utf-8")


def test_plugin_runtime_detection_is_dynamic_but_terminal_reads_stay_passive() -> None:
    for runtime in ("codex", "claude-code", "gemini", "cursor", "opencode", "mcp"):
        assert cli._plugin_contact_runtime(runtime) is True
    for runtime in (None, "", "terminal", "cli", "shell"):
        assert cli._plugin_contact_runtime(runtime) is False


@pytest.mark.parametrize(
    ("extra_args", "reason"),
    [
        (["--runtime", "codex"], "codex-network-contact"),
        (["--scope", "cloud"], "owner-cloud-contact"),
    ],
)
def test_network_and_cloud_cli_contacts_bootstrap_before_routing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra_args: list[str],
    reason: str,
) -> None:
    project = tmp_path / reason
    project.mkdir()
    (project / "main.py").write_text("def routed(): return True\n", encoding="utf-8")
    import agentlas_cloud.networking as networking
    import agentlas_cloud.networking.bootstrap as networking_bootstrap

    monkeypatch.setattr(cli, "maybe_auto_update", lambda: None)
    monkeypatch.setattr(networking, "init_networking", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(networking_bootstrap, "networking_home", lambda: tmp_path / "network")
    monkeypatch.setattr(
        networking,
        "route_request",
        lambda *_args, **_kwargs: {"action": "propose_new", "receipt_id": reason},
    )

    code = cli.main(["route", "test request", "--project", str(project), "--no-hub", *extra_args])
    result = json.loads(capsys.readouterr().out)

    assert code == 0
    assert result["receipt_id"] == reason
    assert result["project_bootstrap"]["status"] == "privacy_warning"
    assert result["project_bootstrap"]["trackedSensitivePaths"] == []
    assert (project / ".agentlas" / "project-soul-memory.md").is_file()
    assert ".agentlas/" in (project / ".gitignore").read_text(encoding="utf-8")


def test_mcp_bootstrap_uses_separate_host_gate_not_tool_arguments(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = make_project(tmp_path)
    import agentlas_cloud.networking as networking
    import agentlas_cloud.networking.bootstrap as networking_bootstrap

    monkeypatch.setattr(networking, "init_networking", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(networking_bootstrap, "networking_home", lambda: tmp_path / "network")
    monkeypatch.setattr(networking, "search_agents", lambda *_args, **_kwargs: {"action": "agent_search", "status": "ok"})
    monkeypatch.delenv(project_bootstrap.MCP_AUTO_BOOTSTRAP_ENV, raising=False)

    disabled = mcp_stdio._call_tool(
        "hephaestus_search",
        {"request": "test", "project_dir": str(project), "ensure_project": True},
    )
    assert disabled["project_bootstrap"]["status"] == "disabled"
    assert not (project / ".agentlas").exists()

    monkeypatch.setenv(project_bootstrap.MCP_AUTO_BOOTSTRAP_ENV, "1")
    monkeypatch.setenv(project_bootstrap.AUTO_ALLOWED_ROOTS_ENV, str(project))
    enabled = mcp_stdio._call_tool("hephaestus_search", {"request": "test", "project_dir": str(project)})
    assert enabled["project_bootstrap"]["status"] == "active"
    assert (project / ".agentlas").is_dir()
    assert str(project) not in json.dumps(enabled["project_bootstrap"])


def test_mcp_opt_in_still_cannot_write_outside_host_approved_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    approved = make_project(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    import agentlas_cloud.networking as networking
    import agentlas_cloud.networking.bootstrap as networking_bootstrap

    monkeypatch.setattr(networking, "init_networking", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(networking_bootstrap, "networking_home", lambda: tmp_path / "network")
    monkeypatch.setattr(networking, "search_agents", lambda *_args, **_kwargs: {"action": "agent_search", "status": "ok"})
    monkeypatch.setenv(project_bootstrap.MCP_AUTO_BOOTSTRAP_ENV, "1")
    monkeypatch.setenv(project_bootstrap.AUTO_ALLOWED_ROOTS_ENV, str(approved))

    result = mcp_stdio._call_tool("hephaestus_search", {"request": "test", "project_dir": str(other)})

    assert result["project_bootstrap"]["status"] == "skipped"
    assert result["project_bootstrap"]["detail"] == "outside_host_approved_roots"
    assert not (other / ".agentlas").exists()


def test_mcp_host_gate_can_bootstrap_only_its_exact_unmarked_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "mcp-current-project"
    project.mkdir()
    (project / "main.py").write_text("def mcp_contact(): return True\n", encoding="utf-8")
    sibling = tmp_path / "unmarked-sibling"
    sibling.mkdir()
    monkeypatch.chdir(project)

    current = maybe_ensure_project(
        project,
        reason="mcp-current-root",
        enabled=True,
        allow_unmarked_current_root=True,
    )
    outside = maybe_ensure_project(
        sibling,
        reason="mcp-outside-root",
        enabled=True,
        allow_unmarked_current_root=True,
    )

    assert current["status"] == "privacy_warning"
    assert current["trackedSensitivePathCount"] == 0
    assert (project / ".agentlas").is_dir()
    assert outside["status"] == "skipped"
    assert outside["detail"] == "workspace_marker_missing"
    assert not (sibling / ".agentlas").exists()


def test_code_map_obeys_total_read_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = make_project(tmp_path)
    (project / "other.py").write_text("def another_symbol():\n    return 2\n", encoding="utf-8")
    monkeypatch.setattr(project_bootstrap, "MAX_CODE_TOTAL_READ_BYTES", 8)

    result = generate_code_map(project)

    assert result["stats"]["bytesRead"] <= 8
    assert result["stats"]["budgetStop"] == "total_read_bytes"


def test_code_map_output_is_bounded_and_symlinks_are_not_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = make_project(tmp_path)
    many = "\n".join(f"def symbol_{index}(): return {index}" for index in range(1_000))
    (project / "many.py").write_text(many + "\n", encoding="utf-8")
    outside = tmp_path / "outside.py"
    outside.write_text("def private_secret_marker(): return 'secret'\n", encoding="utf-8")
    (project / "linked.py").symlink_to(outside)
    monkeypatch.setattr(project_bootstrap, "MAX_CODE_MAP_BYTES", 24_000)

    result = generate_code_map(project)
    raw = (project / ".agentlas" / "code-map" / "project-map.json").read_bytes()

    assert len(raw) <= 24_000
    assert result["stats"]["skippedUnsafe"] >= 1
    assert b"private_secret_marker" not in raw
    assert b"linked.py" not in raw


def test_git_file_listing_stops_at_streaming_byte_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = make_project(tmp_path)
    for index in range(100):
        (project / f"source-{index:03d}.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(project_bootstrap, "MAX_GIT_FILE_LIST_BYTES", 64)

    files, stop, _skipped = project_bootstrap._git_file_list(project, time.monotonic() + 2.0)

    assert files is not None
    assert stop == "file_list_bytes"
    assert sum(len(path.relative_to(project).as_posix().encode()) + 1 for path in files) <= 64


def test_gitignore_symlink_and_oversized_file_are_refused_without_reading_target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = make_project(tmp_path)
    outside = tmp_path / "outside-gitignore"
    outside.write_text("DO NOT TOUCH\n", encoding="utf-8")
    (project / ".gitignore").symlink_to(outside)

    with pytest.raises(ValueError, match="unsafe_gitignore_file"):
        ensure_project(project)
    assert outside.read_text(encoding="utf-8") == "DO NOT TOUCH\n"

    (project / ".gitignore").unlink()
    (project / ".gitignore").write_text("x" * 65, encoding="utf-8")
    monkeypatch.setattr(project_bootstrap, "MAX_GITIGNORE_BYTES", 64)
    with pytest.raises(ValueError, match="gitignore_too_large"):
        ensure_project(project)


def test_empty_or_relative_runtime_root_never_falls_back_to_cwd_templates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_module = tmp_path / "package" / "agentlas_cloud" / "project_bootstrap.py"
    fake_module.parent.mkdir(parents=True)
    cwd = tmp_path / "cwd"
    (cwd / "templates").mkdir(parents=True)
    runtime = tmp_path / "runtime"
    (runtime / "templates").mkdir(parents=True)
    monkeypatch.setattr(project_bootstrap, "__file__", str(fake_module))
    monkeypatch.chdir(cwd)

    monkeypatch.delenv("HEPHAESTUS_RUNTIME_ROOT", raising=False)
    assert project_bootstrap._template_root() is None
    monkeypatch.setenv("HEPHAESTUS_RUNTIME_ROOT", ".")
    assert project_bootstrap._template_root() is None
    monkeypatch.setenv("HEPHAESTUS_RUNTIME_ROOT", str(runtime))
    assert project_bootstrap._template_root() == runtime / "templates"


def test_live_lock_times_out_without_unlink_race(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    ready = threading.Event()
    release = threading.Event()

    def hold_lock() -> None:
        with project_bootstrap._project_lock(project, timeout_seconds=1.0):
            ready.set()
            release.wait(timeout=2.0)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert ready.wait(timeout=1.0)

    try:
        with pytest.raises(TimeoutError):
            with project_bootstrap._project_lock(project, timeout_seconds=0.1):
                pass
    finally:
        release.set()
        holder.join(timeout=2.0)
    assert not holder.is_alive()
    assert (project / ".agentlas" / ".project-bootstrap.lock").exists()


def test_stale_lock_file_is_reused_after_owner_process_exit(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    agentlas = project / ".agentlas"
    agentlas.mkdir(mode=0o700)
    lock = agentlas / ".project-bootstrap.lock"
    lock.write_text(json.dumps({"pid": 999_999_999, "token": "dead"}), encoding="utf-8")
    with project_bootstrap._project_lock(project, timeout_seconds=0.2):
        assert project_bootstrap._read_lock(lock)["token"] != "dead"
    assert lock.exists()
    assert stat.S_IMODE(lock.stat().st_mode) == 0o600


def test_first_contact_closes_graph_database_connections(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    gc.collect()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ResourceWarning)
        ensure_project(project, reason="connection-lifecycle-test")
        gc.collect()

    leaked = [
        warning
        for warning in caught
        if issubclass(warning.category, ResourceWarning)
        and "unclosed database" in str(warning.message)
    ]
    assert leaked == []
