from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import textwrap


ROOT = Path(__file__).resolve().parents[1]
PUBLISH = ROOT / "scripts" / "publish-runtime-release-assets.sh"
WORKFLOW = ROOT / ".github" / "workflows" / "release-runtime.yml"
TAG = "v1.1.36"


FAKE_GH = r'''#!/usr/bin/env python3
import hashlib
import json
import os
from pathlib import Path
import sys

state_path = Path(os.environ["FAKE_GH_STATE"])
log_path = Path(os.environ["FAKE_GH_LOG"])
state = json.loads(state_path.read_text(encoding="utf-8"))
args = sys.argv[1:]

def save():
    state_path.write_text(json.dumps(state), encoding="utf-8")

def log(kind, value):
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps([kind, value]) + "\n")

if args and args[0] == "api":
    if not state.get("exists"):
        print("gh: Not Found (HTTP 404)", file=sys.stderr)
        raise SystemExit(1)
    print(json.dumps({"assets": state.get("assets", [])}))
    raise SystemExit(0)

if args[:2] == ["release", "create"]:
    if state.get("exists"):
        print("release already exists", file=sys.stderr)
        raise SystemExit(1)
    state["exists"] = True
    state.setdefault("assets", [])
    paths = [Path(value) for value in args[3:] if not value.startswith("-") and Path(value).is_file()]
    partial = os.environ.get("FAKE_GH_CREATE_PARTIAL")
    for index, path in enumerate(paths):
        if partial and index > 0:
            break
        state["assets"].append(
            {
                "name": path.name,
                "digest": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    save()
    log("create", args[2])
    if partial:
        print("simulated partial release creation", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(0)

if args[:2] == ["release", "upload"]:
    path = Path(args[3])
    name = path.name
    digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
    if any(asset.get("name") == name for asset in state.get("assets", [])):
        print("asset already exists", file=sys.stderr)
        raise SystemExit(1)
    state.setdefault("assets", []).append({"name": name, "digest": digest})
    save()
    log("upload", name)
    if os.environ.get("FAKE_GH_RACE_ASSET") == name:
        print("simulated concurrent upload", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(0)

print("unsupported fake gh call: " + repr(args), file=sys.stderr)
raise SystemExit(2)
'''


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _asset(path: Path, digest: str | None = None) -> dict[str, str]:
    return {"name": path.name, "digest": digest or f"sha256:{_sha256(path)}"}


def _fixture(tmp_path: Path):
    archive = tmp_path / f"hephaestus-runtime-{TAG}.tar.gz"
    checksum = tmp_path / f"{archive.name}.sha256"
    archive.write_bytes(b"deterministic runtime archive\n")
    checksum.write_text(f"{_sha256(archive)}  {archive.name}\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_gh = fake_bin / "gh"
    fake_gh.write_text(textwrap.dedent(FAKE_GH), encoding="utf-8")
    fake_gh.chmod(0o755)

    state_path = tmp_path / "state.json"
    log_path = tmp_path / "calls.jsonl"
    log_path.write_text("", encoding="utf-8")
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{env['PATH']}",
            "GITHUB_REPOSITORY": "agentlas-ai/Agentlas-OS",
            "FAKE_GH_STATE": str(state_path),
            "FAKE_GH_LOG": str(log_path),
        }
    )
    return archive, checksum, state_path, log_path, env


def _run(archive: Path, checksum: Path, env: dict[str, str]):
    return subprocess.run(
        ["bash", str(PUBLISH), TAG, str(archive), str(checksum)],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _write_state(path: Path, *, exists: bool, assets: list[dict[str, str]]):
    path.write_text(json.dumps({"exists": exists, "assets": assets}), encoding="utf-8")


def _calls(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_new_release_uploads_both_assets_and_rerun_skips_identical_assets(tmp_path):
    archive, checksum, state_path, log_path, env = _fixture(tmp_path)
    _write_state(state_path, exists=False, assets=[])

    first = _run(archive, checksum, env)
    assert first.returncode == 0, first.stderr
    assert _calls(log_path) == [
        ["create", TAG],
    ]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert {asset["name"] for asset in state["assets"]} == {archive.name, checksum.name}

    before_rerun = list(_calls(log_path))
    second = _run(archive, checksum, env)
    assert second.returncode == 0, second.stderr
    assert _calls(log_path) == before_rerun
    assert second.stdout.count("already verified; skipping") == 2
    assert f"release {TAG} runtime assets are complete and digest-verified" in second.stdout


def test_partial_release_uploads_only_the_missing_asset(tmp_path):
    archive, checksum, state_path, log_path, env = _fixture(tmp_path)
    _write_state(state_path, exists=True, assets=[_asset(archive)])

    result = _run(archive, checksum, env)

    assert result.returncode == 0, result.stderr
    assert _calls(log_path) == [["upload", checksum.name]]
    assert f"skipping {archive.name}" in result.stdout
    assert f"uploading missing release asset {checksum.name}" in result.stdout


def test_partial_first_create_is_recovered_by_uploading_only_the_missing_asset(tmp_path):
    archive, checksum, state_path, log_path, env = _fixture(tmp_path)
    _write_state(state_path, exists=False, assets=[])
    env["FAKE_GH_CREATE_PARTIAL"] = "1"

    result = _run(archive, checksum, env)

    assert result.returncode == 0, result.stderr
    assert _calls(log_path) == [["create", TAG], ["upload", checksum.name]]
    assert f"skipping {archive.name}" in result.stdout
    assert "release creation was partial" in result.stdout


def test_digest_mismatch_fails_before_uploading_any_missing_asset(tmp_path):
    archive, checksum, state_path, log_path, env = _fixture(tmp_path)
    _write_state(
        state_path,
        exists=True,
        assets=[_asset(checksum, "sha256:" + "0" * 64)],
    )

    result = _run(archive, checksum, env)

    assert result.returncode == 1
    assert f"release asset digest mismatch for {checksum.name}" in result.stderr
    assert "expected=sha256:" in result.stderr
    assert "actual=sha256:" + "0" * 64 in result.stderr
    assert _calls(log_path) == []
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert [asset["name"] for asset in state["assets"]] == [checksum.name]


def test_existing_asset_without_github_digest_fails_closed(tmp_path):
    archive, checksum, state_path, log_path, env = _fixture(tmp_path)
    _write_state(state_path, exists=True, assets=[{"name": archive.name, "digest": ""}])

    result = _run(archive, checksum, env)

    assert result.returncode == 1
    assert "actual=missing" in result.stderr
    assert _calls(log_path) == []


def test_matching_concurrent_upload_is_accepted_after_failed_upload_command(tmp_path):
    archive, checksum, state_path, log_path, env = _fixture(tmp_path)
    _write_state(state_path, exists=True, assets=[_asset(archive)])
    env["FAKE_GH_RACE_ASSET"] = checksum.name

    result = _run(archive, checksum, env)

    assert result.returncode == 0, result.stderr
    assert _calls(log_path) == [["upload", checksum.name]]
    assert "uploaded concurrently; verified" in result.stdout


def test_workflow_uses_the_reconciler_and_runs_its_regression_gate():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts/publish-runtime-release-assets.sh" in workflow
    assert "tests/test_release_runtime_assets.py" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "gh release upload" not in workflow
