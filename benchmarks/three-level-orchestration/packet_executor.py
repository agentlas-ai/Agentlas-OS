#!/usr/bin/env python3
"""Controlled Stormbreaker packet executor for Terra/Qwen architecture tests.

The adapter gives both models the same JSON command protocol and local shell
loop.  It exits zero only after a stage-specific acceptance check passes, so
Stormbreaker cannot treat a successful API call as a successful task.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
SCHEMA = ROOT / "command-response.schema.json"
MAX_OUTPUT_CHARS = 24_000
BLOCKED_COMMAND_MARKERS = (
    "sudo ",
    "rm -rf /",
    "git push",
    "curl ",
    "wget ",
    "ssh ",
    "scp ",
    "nc ",
    "ncat ",
    "osascript ",
    "open ",
)


def env_required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def read_packet() -> dict[str, Any]:
    path = Path(env_required("STORMBREAKER_PACKET_FILE"))
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("packet"), dict):
        raise RuntimeError("invalid Stormbreaker packet contract")
    return value


def compact_json(value: Any, limit: int = 16_000) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2)
    return rendered if len(rendered) <= limit else rendered[:limit] + "\n...[truncated]"


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n")


def flatten_messages(messages: list[dict[str, str]]) -> str:
    return "\n\n".join(
        f"--- MESSAGE {index + 1} role={message['role']} ---\n{message['content']}"
        for index, message in enumerate(messages)
    )


def call_codex(messages: list[dict[str, str]], model: str) -> dict[str, Any]:
    codex = os.environ.get("AGENTLAS_PACKET_CODEX") or shutil.which("codex")
    if not codex:
        raise RuntimeError("codex executable not found")
    with tempfile.TemporaryDirectory(prefix="agentlas-packet-codex-") as empty_cwd:
        output_path = Path(empty_cwd) / "last.json"
        prompt = (
            "You are the language-model backend for a controlled Agentlas "
            "Stormbreaker packet executor. Do not inspect this host and do not "
            "use tools. Infer the next shell commands only from the conversation. "
            "Return exactly the required JSON object. Commands run later inside "
            "the isolated benchmark project.\n\n" + flatten_messages(messages)
        )
        completed = subprocess.run(
            [
                codex,
                "exec",
                "--model",
                model,
                "--sandbox",
                "read-only",
                "--cd",
                empty_cwd,
                "--skip-git-repo-check",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--output-schema",
                str(SCHEMA),
                "--output-last-message",
                str(output_path),
                "-c",
                "model_reasoning_effort=max",
                "-",
            ],
            input=prompt,
            text=True,
            capture_output=True,
            timeout=int(os.environ.get("AGENTLAS_PACKET_MODEL_TIMEOUT", "900")),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(f"codex exit={completed.returncode}: {completed.stderr[-2000:]}")
        value = json.loads(output_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("Codex response was not an object")
    return value


def call_openai_compatible(messages: list[dict[str, str]], model: str) -> dict[str, Any]:
    base = os.environ.get("AGENTLAS_PACKET_API_BASE", "http://127.0.0.1:11434/v1").rstrip("/")
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
    ).encode()
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ.get('AGENTLAS_PACKET_API_KEY', 'ollama')}",
        },
        method="POST",
    )
    with urllib.request.urlopen(
        request,
        timeout=int(os.environ.get("AGENTLAS_PACKET_MODEL_TIMEOUT", "900")),
    ) as response:
        payload = json.loads(response.read().decode())
    content = payload["choices"][0]["message"]["content"]
    value = json.loads(content) if isinstance(content, str) else content
    if not isinstance(value, dict):
        raise RuntimeError("OpenAI-compatible response was not an object")
    return value


def call_model(messages: list[dict[str, str]], model: str) -> dict[str, Any]:
    backend = os.environ.get("AGENTLAS_PACKET_BACKEND", "openai").strip().lower()
    if backend == "codex":
        return call_codex(messages, model)
    if backend == "openai":
        return call_openai_compatible(messages, model)
    raise RuntimeError(f"unsupported AGENTLAS_PACKET_BACKEND: {backend}")


def command_problem(command: str) -> str | None:
    normalized = " ".join(command.lower().split())
    for marker in BLOCKED_COMMAND_MARKERS:
        if marker in normalized:
            return f"blocked command marker: {marker.strip()}"
    if "../" in command or command.strip().startswith("cd .."):
        return "path traversal outside the benchmark project is blocked"
    return None


def run_command(command: str, project: Path) -> tuple[int, str]:
    problem = command_problem(command)
    if problem:
        return 126, problem
    run_env = os.environ.copy()
    run_env.update(
        {
            "PAGER": "cat",
            "GIT_PAGER": "cat",
            "GIT_EDITOR": "true",
            "EDITOR": "true",
            "TERM": "dumb",
        }
    )
    completed = subprocess.run(
        command,
        shell=True,
        cwd=project,
        env=run_env,
        text=True,
        capture_output=True,
        timeout=int(os.environ.get("AGENTLAS_PACKET_COMMAND_TIMEOUT", "180")),
        check=False,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n...[truncated]"
    return completed.returncode, output


def verify_stage(stage: str, write_scope: Path, project: Path) -> tuple[bool, str]:
    if stage == "plan":
        plan = write_scope / "plan.md"
        return plan.is_file() and bool(plan.read_text(encoding="utf-8").strip()), (
            f"required plan artifact: {plan}"
        )
    command = os.environ.get("AGENTLAS_PACKET_VERIFY_COMMAND", "").strip()
    if not command:
        return False, "AGENTLAS_PACKET_VERIFY_COMMAND is required for build/verify stages"
    code, output = run_command(command, project)
    return code == 0, f"verifier exit={code}\n{output}"


def prior_packet_artifacts(write_scope: Path) -> str:
    sections: list[str] = []
    for path in sorted(write_scope.parent.glob("*/plan.md")):
        if path == write_scope / "plan.md":
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        sections.append(f"### {path.relative_to(write_scope.parent)}\n{content}")
    return "\n\n".join(sections)[:12_000]


def system_prompt(contract: dict[str, Any], project: Path, write_scope: Path) -> str:
    packet = contract["packet"]
    stage = str(packet.get("stage") or "")
    bundle = packet.get("hub_runtime_bundle") or {}
    entry = bundle.get("entry") or {}
    goal = contract.get("execution_goal") or {}
    brief = contract.get("work_brief") or {}
    harness = contract.get("execution_harness") or {}
    prior_artifacts = prior_packet_artifacts(write_scope)
    stage_rule = {
        "plan": f"Inspect the project read-only, then write a concrete implementation and verification plan to {write_scope / 'plan.md'}.",
        "build": "Implement the requested project change, use the upstream plan, run relevant checks, and repair failures.",
        "verify": "Act as an independent verifier. Run the verifier, inspect failures, repair concrete defects, and rerun it.",
    }.get(stage, "Complete this packet and verify its declared artifact.")
    return "\n\n".join(
        [
            str(harness.get("system_prompt") or ""),
            "## Controlled packet executor",
            f"Project directory: {project}",
            f"Packet write scope: {write_scope}",
            f"Stage: {stage}",
            f"Card: {packet.get('card')}",
            f"Produces: {packet.get('produces') or []}",
            f"Depends on: {packet.get('depends_on') or []}",
            f"Goal: {goal.get('request') or brief.get('goal') or 'missing'}",
            f"Work brief: {compact_json(brief, 6000)}",
            f"Prior packet artifacts:\n{prior_artifacts or '(none)'}",
            f"Stage rule: {stage_rule}",
            "The shell starts in the project directory. Do not use network commands, sudo, external publishing, or paths outside the project. Avoid interactive programs and pagers. Use GIT_PAGER=cat when needed.",
            "Return JSON only with keys analysis, plan, commands, task_complete. commands is an array of {keystrokes,duration}; keystrokes contains non-interactive shell commands. Set task_complete only after observable verification.",
            f"## Routed runtime bundle\n{str(entry.get('content') or '')}",
        ]
    )


def main() -> int:
    contract = read_packet()
    packet = contract["packet"]
    project = Path(env_required("STORMBREAKER_PROJECT_DIR")).resolve()
    write_scope = Path(env_required("STORMBREAKER_WRITE_SCOPE")).resolve()
    stage = str(packet.get("stage") or "")
    model = env_required("AGENTLAS_PACKET_MODEL")
    max_turns = int(os.environ.get("AGENTLAS_PACKET_MAX_TURNS", "12"))
    receipt_path = write_scope / "model-invocations.jsonl"
    observation_path = write_scope / "executor-observations.jsonl"
    result_path = write_scope / "packet-executor-result.json"
    messages = [
        {"role": "system", "content": system_prompt(contract, project, write_scope)},
        {"role": "user", "content": "Begin this packet. Inspect real state before making claims."},
    ]
    command_count = 0
    last_check = "not run"

    for turn in range(1, max_turns + 1):
        started = time.monotonic()
        prompt_hash = hashlib.sha256(compact_json(messages, 100_000).encode()).hexdigest()
        response = call_model(messages, model)
        elapsed = time.monotonic() - started
        response_text = compact_json(response, 32_000)
        append_jsonl(
            receipt_path,
            {
                "schema": "agentlas.benchmark.model-invocation.v1",
                "packetId": packet.get("packet_id"),
                "stage": stage,
                "model": model,
                "backend": os.environ.get("AGENTLAS_PACKET_BACKEND", "openai"),
                "turn": turn,
                "promptSha256": prompt_hash,
                "responseSha256": hashlib.sha256(response_text.encode()).hexdigest(),
                "elapsedSeconds": round(elapsed, 3),
                "commandCount": len(response.get("commands") or []),
                "taskComplete": response.get("task_complete") is True,
            },
        )
        messages.append({"role": "assistant", "content": response_text})
        commands = response.get("commands")
        if not isinstance(commands, list):
            commands = []
        observations: list[str] = []
        for item in commands:
            if not isinstance(item, dict):
                continue
            command = str(item.get("keystrokes") or "").strip()
            if not command:
                continue
            command_count += 1
            try:
                code, output = run_command(command, project)
            except subprocess.TimeoutExpired:
                code, output = 124, "command timed out"
            append_jsonl(
                observation_path,
                {
                    "schema": "agentlas.benchmark.command-observation.v1",
                    "packetId": packet.get("packet_id"),
                    "stage": stage,
                    "model": model,
                    "turn": turn,
                    "command": command,
                    "commandSha256": hashlib.sha256(command.encode()).hexdigest(),
                    "exitCode": code,
                    "output": output,
                },
            )
            observations.append(f"$ {command}\nexit={code}\n{output}")
        if observations:
            messages.append({"role": "user", "content": "Terminal observations:\n\n" + "\n\n".join(observations)})

        if response.get("task_complete") is True:
            passed, last_check = verify_stage(stage, write_scope, project)
            append_jsonl(
                observation_path,
                {
                    "schema": "agentlas.benchmark.acceptance-observation.v1",
                    "packetId": packet.get("packet_id"),
                    "stage": stage,
                    "model": model,
                    "turn": turn,
                    "passed": passed,
                    "result": last_check,
                    "repairTriggered": not passed,
                },
            )
            messages.append({"role": "user", "content": f"Stage acceptance check:\n{last_check}"})
            if passed:
                result_path.write_text(
                    json.dumps(
                        {
                            "schema": "agentlas.benchmark.packet-executor-result.v1",
                            "status": "passing",
                            "packetId": packet.get("packet_id"),
                            "stage": stage,
                            "model": model,
                            "turns": turn,
                            "commands": command_count,
                            "acceptance": last_check,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return 0
        elif not observations:
            messages.append(
                {
                    "role": "user",
                    "content": "No command was provided and the packet is not complete. Issue the next concrete non-interactive command.",
                }
            )

    result_path.write_text(
        json.dumps(
            {
                "schema": "agentlas.benchmark.packet-executor-result.v1",
                "status": "failed",
                "packetId": packet.get("packet_id"),
                "stage": stage,
                "model": model,
                "turns": max_turns,
                "commands": command_count,
                "acceptance": last_check,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"packet executor error: {exc}", file=sys.stderr)
        raise SystemExit(2)
