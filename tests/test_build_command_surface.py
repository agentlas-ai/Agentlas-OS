import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run(*args: str) -> str:
    env = os.environ.copy()
    env["HEPHAESTUS_UPDATE_CHECK"] = "0"
    completed = subprocess.run(
        [str(ROOT / "bin" / "hephaestus"), *args],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    return completed.stdout


def test_build_subcommands_point_to_hephaestus_build() -> None:
    for command in ("hephaestus-build", "build", "meta-agent"):
        output = _run(command, "create a customer support agent")
        assert "/hephaestus-build create a customer support agent" in output
        assert "Legacy alias:" in output


def test_standalone_build_wrapper_points_to_hephaestus_build() -> None:
    env = os.environ.copy()
    env["HEPHAESTUS_UPDATE_CHECK"] = "0"
    completed = subprocess.run(
        [str(ROOT / "bin" / "hephaestus-build"), "create a finance agent"],
        cwd=str(ROOT),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert "/hephaestus-build create a finance agent" in completed.stdout
