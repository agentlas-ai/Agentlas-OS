#!/usr/bin/env python3
"""Prove that every platform and packaged adapter sees one harness byte string."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
HARNESS_SOURCE = ROOT / "agentlas_cloud" / "networking" / "stormbreaker_harness.py"
MIRRORED_HARNESS_SOURCES = (
    ROOT / "claude" / "plugins" / "agentlas-core-engine-meta-agent" / "agentlas_cloud" / "networking" / "stormbreaker_harness.py",
    ROOT / "codex" / "plugins" / "agentlas-core-engine-meta-agent" / "agentlas_cloud" / "networking" / "stormbreaker_harness.py",
)
ADAPTERS = (
    ROOT / "skills" / "hephaestus-storm" / "SKILL.md",
    ROOT / ".agents" / "skills" / "hephaestus-storm" / "SKILL.md",
    ROOT / "codex" / "prompts" / "hep-storm.md",
    ROOT / "codex" / "plugins" / "agentlas-core-engine-meta-agent" / "skills" / "hephaestus-storm" / "SKILL.md",
    ROOT / "claude" / "plugins" / "agentlas-core-engine-meta-agent" / "commands" / "hep-storm.md",
    ROOT / ".claude" / "commands" / "hep-storm.md",
    ROOT / "gemini" / "extension" / "commands" / "hep-storm.toml",
    ROOT / "antigravity" / "workflows" / "hep-storm.md",
    ROOT / "opencode" / "commands" / "hep-storm.md",
    ROOT / "cursor" / "plugin" / "commands" / "hep-storm.md",
    ROOT / "openclaw" / "skills" / "hephaestus-storm" / "SKILL.md",
    ROOT / "hermes" / "skills" / "hephaestus-storm" / "SKILL.md",
)


def _run_json(command: list[str], *, env: dict[str, str] | None = None) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return json.loads(completed.stdout)


def _validate_harness(value: dict[str, Any]) -> None:
    assert value["schema_version"] == "agentlas.stormbreaker.goal-ultracode-harness.v1"
    assert value["harness_id"] == "agentlas-core/stormbreaker-goal-ultracode"
    assert value["mode"] == "stormbreaker-goal-ultracode"
    prompt = value["system_prompt"]
    assert isinstance(prompt, str) and prompt
    assert prompt.count("GOAL MODE:") == 1
    assert prompt.count("ULTRACODE MODE:") == 1
    assert hashlib.sha256(prompt.encode("utf-8")).hexdigest() == value["prompt_sha256"]


def _wrapper_command() -> list[str]:
    if os.name == "nt":
        wrapper = ROOT / "bin" / "hephaestus.cmd"
        return [
            os.environ.get("COMSPEC", "cmd.exe"),
            "/d",
            "/c",
            "call",
            str(wrapper),
            "stormbreaker",
            "harness",
        ]
    return [str(ROOT / "bin" / "hephaestus"), "stormbreaker", "harness"]


def build_proof() -> dict[str, Any]:
    from agentlas_cloud.networking.stormbreaker_harness import goal_ultracode_harness

    canonical = goal_ultracode_harness()
    direct = _run_json([sys.executable, "-m", "agentlas_cloud", "stormbreaker", "harness"])
    wrapper_env = os.environ.copy()
    wrapper_env["HEPHAESTUS_PYTHON"] = sys.executable
    wrapper = _run_json(_wrapper_command(), env=wrapper_env)
    for candidate in (canonical, direct, wrapper):
        _validate_harness(candidate)
        assert candidate == canonical

    canonical_source = HARNESS_SOURCE.read_bytes()
    for mirror in MIRRORED_HARNESS_SOURCES:
        assert mirror.read_bytes() == canonical_source, f"Core harness mirror drift: {mirror}"

    for adapter in ADAPTERS:
        text = adapter.read_text(encoding="utf-8")
        assert "execution_harness.system_prompt" in text, adapter
        assert "GOAL MODE:" not in text, adapter
        assert "ULTRACODE MODE:" not in text, adapter

    prompt_bytes = canonical["system_prompt"].encode("utf-8")
    return {
        "schema": "agentlas.cross-platform-harness-proof.v1",
        "platform": platform.system(),
        "platform_release": platform.release(),
        "python": platform.python_version(),
        "harness_id": canonical["harness_id"],
        "mode": canonical["mode"],
        "prompt_sha256": canonical["prompt_sha256"],
        "system_prompt_utf8_base64": base64.b64encode(prompt_bytes).decode("ascii"),
        "direct_cli_equal": direct == canonical,
        "native_wrapper_equal": wrapper == canonical,
        "mirrored_core_sources_equal": True,
        "adapter_count": len(ADAPTERS),
    }


def compare_proofs(directory: Path) -> None:
    files = sorted(directory.rglob("*.json"))
    if not files:
        raise SystemExit(f"no proof files found under {directory}")
    proofs = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    required_platforms = {"Linux", "Darwin", "Windows"}
    platforms = {proof["platform"] for proof in proofs}
    assert required_platforms <= platforms, f"missing platforms: {sorted(required_platforms - platforms)}"
    identity_fields = (
        "harness_id",
        "mode",
        "prompt_sha256",
        "system_prompt_utf8_base64",
    )
    for field in identity_fields:
        values = {proof[field] for proof in proofs}
        assert len(values) == 1, f"cross-platform drift in {field}: {values}"
    for proof in proofs:
        prompt = base64.b64decode(proof["system_prompt_utf8_base64"])
        assert hashlib.sha256(prompt).hexdigest() == proof["prompt_sha256"]
        assert proof["direct_cli_equal"] is True
        assert proof["native_wrapper_equal"] is True
        assert proof["mirrored_core_sources_equal"] is True
        assert proof["adapter_count"] == len(ADAPTERS)
    print(
        json.dumps(
            {
                "status": "pass",
                "proofs": len(proofs),
                "platforms": sorted(platforms),
                "prompt_sha256": proofs[0]["prompt_sha256"],
            },
            ensure_ascii=False,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--proof", type=Path)
    group.add_argument("--compare-dir", type=Path)
    args = parser.parse_args()
    if args.compare_dir:
        compare_proofs(args.compare_dir)
        return 0
    proof = build_proof()
    args.proof.parent.mkdir(parents=True, exist_ok=True)
    args.proof.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(proof, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
