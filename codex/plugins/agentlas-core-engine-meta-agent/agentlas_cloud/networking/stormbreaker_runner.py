"""Stormbreaker auto-runner for routed pipeline execution fabrics.

This module is the local product runner for `action: "pipeline"` route
decisions. The router still owns selection and policy labeling; the runner owns
packet materialization, optional external executor launch, packet ledgers, and
the final gate.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Mapping

from .bootstrap import append_jsonl, atomic_write_json, networking_home, utc_now
from .execution_fabric import evaluate_final_gate
from .goal_loop import GoalLoopConfig, run_goal_loop
from .receipts import record_execution
from .router import route_request
from .run_journal import RunJournal


RUNNER_VERSION = "stormbreaker.auto_runner.v1"
STORMBREAKER_RESEARCH_LOADOUTS = {"auto", "safe", "public-web", "social", "browser", "full", "recommended"}
STORMBREAKER_RESEARCH_DEPTHS = {"quick", "deep"}
STORMBREAKER_DEFAULT_RESEARCH_LOADOUT = "safe"
STORMBREAKER_DEFAULT_RESEARCH_DEPTH = "quick"
STORMBREAKER_DEFAULT_FOLLOW_RESULTS = 1
STORMBREAKER_RESEARCH_MODULES = {
    "browser.agent_cli",
    "browser.browser_use",
    "browser.playwright_mcp",
    "browser.stagehand",
    "browser.steel",
    "browser.hyperagent",
    "platform.reddit",
    "platform.reddit.oauth",
    "platform.threads",
    "platform.threads.public",
    "read.http",
    "read.insane_fetch",
    "read.jina",
    "search.ddg_html",
    "search.github_repos",
    "search.jina",
    "search.news_rss",
}
STORMBREAKER_SAFE_RESEARCH_MODULES = ["search.ddg_html", "search.news_rss", "read.http"]


def run_stormbreaker_query(
    query: str,
    *,
    home: Path | str | None = None,
    project_dir: Path | str = ".",
    runtime: str | None = "terminal",
    use_hub: bool = True,
    hub_approved: bool = False,
    hub_only: bool = False,
    scope: str = "network",
    caller_id: str | None = None,
    session_inventory: list[Any] | None = None,
    executor_command: str | None = None,
    execute_card_commands: bool = False,
    max_workers: int | None = None,
    timeout_seconds: int = 900,
    research_evidence: bool = False,
    research_loadout: str = STORMBREAKER_DEFAULT_RESEARCH_LOADOUT,
    research_depth: str = STORMBREAKER_DEFAULT_RESEARCH_DEPTH,
    research_follow_results: int = STORMBREAKER_DEFAULT_FOLLOW_RESULTS,
    research_variants: list[str] | None = None,
) -> dict[str, Any]:
    """Route a query, then run the returned Stormbreaker pipeline fabric."""

    decision = route_request(
        query,
        home=home,
        project_dir=project_dir,
        runtime=runtime,
        use_hub=use_hub,
        hub_approved=hub_approved,
        hub_only=hub_only,
        scope=scope,
        caller_id=caller_id,
        session_inventory=session_inventory,
    )
    decision = dict(decision)
    decision["_stormbreaker_user_query"] = query
    result = run_stormbreaker_decision(
        decision,
        home=home,
        project_dir=project_dir,
        executor_command=executor_command,
        execute_card_commands=execute_card_commands,
        max_workers=max_workers,
        timeout_seconds=timeout_seconds,
        research_evidence=research_evidence,
        research_loadout=research_loadout,
        research_depth=research_depth,
        research_follow_results=research_follow_results,
        research_variants=research_variants,
    )
    result["route_decision"] = _decision_summary(decision)
    return result


def run_stormbreaker_decision(
    decision: Mapping[str, Any],
    *,
    home: Path | str | None = None,
    project_dir: Path | str = ".",
    executor_command: str | None = None,
    execute_card_commands: bool = False,
    max_workers: int | None = None,
    timeout_seconds: int = 900,
    research_evidence: bool = False,
    research_loadout: str = STORMBREAKER_DEFAULT_RESEARCH_LOADOUT,
    research_depth: str = STORMBREAKER_DEFAULT_RESEARCH_DEPTH,
    research_follow_results: int = STORMBREAKER_DEFAULT_FOLLOW_RESULTS,
    research_variants: list[str] | None = None,
) -> dict[str, Any]:
    """Run a previously routed Stormbreaker pipeline decision."""

    if decision.get("action") != "pipeline":
        return {
            "status": "not_executed",
            "runner_version": RUNNER_VERSION,
            "reason": "Stormbreaker auto-runner only executes action=pipeline decisions",
            "route_action": decision.get("action"),
            "receipt_id": decision.get("receipt_id"),
        }

    fabric = decision.get("execution_fabric")
    if not isinstance(fabric, Mapping):
        return {
            "status": "error",
            "runner_version": RUNNER_VERSION,
            "reason": "pipeline decision is missing execution_fabric",
            "receipt_id": decision.get("receipt_id"),
        }

    project = Path(project_dir).expanduser().resolve()
    project.mkdir(parents=True, exist_ok=True)
    base = Path(home) if home else networking_home()
    pipeline_id = str(fabric.get("pipeline_id") or decision.get("pipeline_id") or uuid.uuid4().hex[:12])
    handoff_dir = str(decision.get("handoff_dir") or f".agentlas/pipeline/{pipeline_id}/")
    journal = _resolve_project_path(project, str(fabric.get("resume_policy", {}).get("journal") or f"{handoff_dir}stormbreaker-execution-ledger.jsonl"))
    journal.parent.mkdir(parents=True, exist_ok=True)

    mode = _execution_mode(executor_command, execute_card_commands)
    packet_by_id = {str(packet.get("packet_id")): dict(packet) for packet in fabric.get("packets") or [] if packet.get("packet_id")}
    packet_statuses: dict[str, str] = {}
    packet_results: list[dict[str, Any]] = []
    started_sessions: list[dict[str, Any]] = []
    max_parallel = _max_workers(max_workers, fabric)
    user_query = str(decision.get("_stormbreaker_user_query") or decision.get("query") or "").strip()
    research_options = _research_options(
        loadout=research_loadout,
        depth=research_depth,
        follow_results=research_follow_results,
        variants=research_variants,
    )

    _append_journal(
        journal,
        {
            "event": "runner_started",
            "runner_version": RUNNER_VERSION,
            "pipeline_id": pipeline_id,
            "route_receipt_id": decision.get("receipt_id"),
            "execution_mode": mode,
            "max_workers": max_parallel,
            "research_evidence": "enabled" if research_evidence else "disabled",
            "research_options": research_options if research_evidence else None,
        },
    )

    for group in fabric.get("parallel_groups") or []:
        group_id = str(group.get("group_id") or "group")
        group_packet_ids = [str(packet_id) for packet_id in group.get("packet_ids") or []]
        blocked_deps = [packet_id for packet_id in group.get("depends_on") or [] if packet_statuses.get(str(packet_id)) != "passing"]
        if blocked_deps:
            for packet_id in group_packet_ids:
                packet = packet_by_id.get(packet_id)
                if not packet:
                    continue
                result = _blocked_packet_result(
                    packet,
                    project=project,
                    journal=journal,
                    home=base,
                    parent_receipt_id=str(decision.get("receipt_id") or ""),
                    detail=f"dependency_not_passing: {', '.join(blocked_deps)}",
                    pipeline_id=pipeline_id,
                    group_id=group_id,
                )
                packet_statuses[packet_id] = result["status"]
                packet_results.append(result)
            continue

        ready_packets = [packet_by_id[packet_id] for packet_id in group_packet_ids if packet_id in packet_by_id]
        if not ready_packets:
            continue

        workers = min(max_parallel, len(ready_packets))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="stormbreaker-packet") as executor:
            futures = {
                executor.submit(
                    _run_packet,
                    packet,
                    project=project,
                    home=base,
                    journal=journal,
                    parent_receipt_id=str(decision.get("receipt_id") or ""),
                    pipeline_id=pipeline_id,
                    group_id=group_id,
                    executor_command=executor_command,
                    execute_card_commands=execute_card_commands,
                    timeout_seconds=timeout_seconds,
                    research_evidence=research_evidence,
                    research_options=research_options,
                    user_query=user_query,
                ): packet
                for packet in ready_packets
            }
            for future in as_completed(futures):
                packet = futures[future]
                packet_id = str(packet["packet_id"])
                try:
                    result = future.result()
                except Exception as exc:  # pragma: no cover - defensive finalizer
                    result = _blocked_packet_result(
                        packet,
                        project=project,
                        journal=journal,
                        home=base,
                        parent_receipt_id=str(decision.get("receipt_id") or ""),
                        detail=f"runner_exception: {exc}",
                        pipeline_id=pipeline_id,
                        group_id=group_id,
                    )
                packet_statuses[packet_id] = result["status"]
                packet_results.append(result)
                started_sessions.append(
                    {
                        "packet_id": packet_id,
                        "session_id": result.get("session_id"),
                        "status": result["status"],
                        "mode": result.get("execution_mode"),
                    }
                )

    final_gate = evaluate_final_gate(dict(fabric), packet_statuses)
    status = "completed" if final_gate["can_report_success"] else "blocked"
    _append_journal(
        journal,
        {
            "event": "runner_finished",
            "pipeline_id": pipeline_id,
            "status": status,
            "final_gate": final_gate,
        },
    )

    result = {
        "status": status,
        "runner_version": RUNNER_VERSION,
        "execution_mode": mode,
        "claim_level": _claim_level(mode),
        "pipeline_id": pipeline_id,
        "route_receipt_id": decision.get("receipt_id"),
        "handoff_dir": handoff_dir,
        "journal": _relative_to_project(project, journal),
        "max_workers": max_parallel,
        "sessions_started": started_sessions,
        "packet_statuses": packet_statuses,
        "packets": sorted(packet_results, key=lambda item: (item.get("stage_order") or 0, item.get("packet_id") or "")),
        "final_gate": final_gate,
    }
    if research_evidence:
        result["research_options"] = research_options
    return result


def _run_packet(
    packet: dict[str, Any],
    *,
    project: Path,
    home: Path,
    journal: Path,
    parent_receipt_id: str,
    pipeline_id: str,
    group_id: str,
    executor_command: str | None,
    execute_card_commands: bool,
    timeout_seconds: int,
    research_evidence: bool,
    research_options: dict[str, Any],
    user_query: str = "",
) -> dict[str, Any]:
    packet_id = str(packet["packet_id"])
    write_scope = _resolve_project_path(project, str(packet.get("write_scope") or f".agentlas/pipeline/{pipeline_id}/{packet_id}/"))
    write_scope.mkdir(parents=True, exist_ok=True)
    packet_file = write_scope / "packet.json"
    stdout_file = write_scope / "stdout.log"
    stderr_file = write_scope / "stderr.log"
    result_file = write_scope / "packet-result.json"
    session = packet.get("session_hint") or {}
    session_id = str(session.get("session_id") or "host:primary")
    mode = _execution_mode(executor_command, execute_card_commands)
    started_at = utc_now()
    execution_receipt_id = uuid.uuid4().hex[:16]
    research_summary = _collect_packet_research_evidence(
        packet,
        enabled=research_evidence,
        project=project,
        write_scope=write_scope,
        home=home,
        options=research_options,
        user_query=user_query,
    )

    packet_contract = {
        "runner_version": RUNNER_VERSION,
        "packet": packet,
        "pipeline_id": pipeline_id,
        "parallel_group": group_id,
        "session_hint": session,
        "write_scope": str(write_scope),
        "data_policy": packet.get("data_policy") or [],
    }
    if research_summary is not None:
        packet_contract["research_evidence"] = research_summary
    atomic_write_json(packet_file, packet_contract)
    _append_journal(
        journal,
        {
            "event": "packet_started",
            "pipeline_id": pipeline_id,
            "packet_id": packet_id,
            "stage": packet.get("stage"),
            "session_id": session_id,
            "parallel_group": group_id,
            "write_scope": _relative_to_project(project, write_scope),
            "execution_mode": mode,
            "research_evidence": research_summary,
        },
    )

    packet_for_execution = dict(packet)
    if research_summary is not None:
        packet_for_execution["research_evidence"] = research_summary
    loop_spec = packet.get("loop") if isinstance(packet.get("loop"), dict) else None
    if loop_spec and str(loop_spec.get("goal_command") or "").strip():
        # The packet declared a goal loop: re-run it until the goal verifies,
        # guarded against stalls/runaway/transient failures (goal_loop).
        completed = _run_packet_goal_loop(
            packet_for_execution,
            project=project,
            write_scope=write_scope,
            packet_file=packet_file,
            stdout_file=stdout_file,
            stderr_file=stderr_file,
            executor_command=executor_command,
            execute_card_commands=execute_card_commands,
            timeout_seconds=timeout_seconds,
        )
    else:
        completed = _execute_packet_command(
            packet_for_execution,
            project=project,
            write_scope=write_scope,
            packet_file=packet_file,
            stdout_file=stdout_file,
            stderr_file=stderr_file,
            executor_command=executor_command,
            execute_card_commands=execute_card_commands,
            timeout_seconds=timeout_seconds,
        )
    status = "passing" if completed["ok"] else "blocked"
    detail = str(completed["detail"])
    result = {
        "runner_version": RUNNER_VERSION,
        "execution_receipt_id": execution_receipt_id,
        "packet_id": packet_id,
        "pipeline_id": pipeline_id,
        "stage": packet.get("stage"),
        "stage_order": packet.get("stage_order"),
        "card": packet.get("card"),
        "session_id": session_id,
        "parallel_group": group_id,
        "execution_mode": mode,
        "status": status,
        "detail": detail,
        "started_at": started_at,
        "finished_at": utc_now(),
        "write_scope": _relative_to_project(project, write_scope),
        "packet_file": _relative_to_project(project, packet_file),
        "result_file": _relative_to_project(project, result_file),
        "stdout_file": _relative_to_project(project, stdout_file),
        "stderr_file": _relative_to_project(project, stderr_file),
        "returncode": completed.get("returncode"),
    }
    if completed.get("goal_loop") is not None:
        result["goal_loop"] = completed["goal_loop"]
    if research_summary is not None:
        result["research_evidence"] = research_summary
    atomic_write_json(result_file, result)
    record_execution(
        execution_receipt_id,
        str(packet.get("card") or "unknown"),
        status,
        home=home,
        detail=detail,
        pipeline_id=pipeline_id,
        packet_id=packet_id,
        stage_order=_int_or_none(packet.get("stage_order")),
        session_id=session_id,
        parallel_group=group_id,
        parent_receipt_id=parent_receipt_id or None,
    )
    _append_journal(journal, {"event": "packet_finished", **result})
    return result


def _execute_packet_command(
    packet: Mapping[str, Any],
    *,
    project: Path,
    write_scope: Path,
    packet_file: Path,
    stdout_file: Path,
    stderr_file: Path,
    executor_command: str | None,
    execute_card_commands: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    if executor_command:
        return _run_subprocess(
            executor_command,
            packet,
            project=project,
            write_scope=write_scope,
            packet_file=packet_file,
            stdout_file=stdout_file,
            stderr_file=stderr_file,
            timeout_seconds=timeout_seconds,
        )

    if execute_card_commands:
        command = str(packet.get("canonical_command") or "").strip()
        if not command:
            stdout_file.write_text("", encoding="utf-8")
            stderr_file.write_text("card has no canonical_command\n", encoding="utf-8")
            return {"ok": False, "detail": "missing canonical_command", "returncode": None}
        if command.startswith("/"):
            stdout_file.write_text("", encoding="utf-8")
            stderr_file.write_text(
                f"{command} is a runtime slash command, not a shell command. Use --executor-command to bridge this runtime.\n",
                encoding="utf-8",
            )
            return {"ok": False, "detail": "slash_command_requires_runtime_adapter", "returncode": None}
        return _run_subprocess(
            command,
            packet,
            project=project,
            write_scope=write_scope,
            packet_file=packet_file,
            stdout_file=stdout_file,
            stderr_file=stderr_file,
            timeout_seconds=timeout_seconds,
        )

    stdout_file.write_text("packet contract materialized; no external executor configured\n", encoding="utf-8")
    stderr_file.write_text("", encoding="utf-8")
    return {"ok": True, "detail": "packet_contract_materialized", "returncode": 0}


def _run_packet_goal_loop(
    packet: Mapping[str, Any],
    *,
    project: Path,
    write_scope: Path,
    packet_file: Path,
    stdout_file: Path,
    stderr_file: Path,
    executor_command: str | None,
    execute_card_commands: bool,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Run a packet as a goal-seeking loop (`goal_loop.run_goal_loop`).

    Activated when the packet declares ``loop: {goal_command, ...}``. Each
    iteration runs the packet's normal command once, then the goal verifier
    (``goal_command``, run in the project dir) decides whether the goal is met
    (exit 0). The verifier's stdout doubles as the progress signal, so a task
    that keeps advancing is sustained while a flatlined one trips stall
    detection. A failing iteration is a transient failure (retried with backoff),
    not fatal — the loop is hardened against breaking, runaway, and false-success.
    """

    spec = packet.get("loop") if isinstance(packet.get("loop"), dict) else {}
    goal_command = str(spec.get("goal_command") or "").strip()
    journal = RunJournal(write_scope / "goal-loop-journal.jsonl")
    config = GoalLoopConfig(
        max_iterations=_positive_int(spec.get("max_iterations"), 10),
        stall_window=_positive_int(spec.get("stall_window"), 3),
        max_consecutive_failures=_positive_int(spec.get("max_consecutive_failures"), 3),
        backoff_base=float(spec.get("backoff_base") or 0.0),
    )

    def iterate(state: Any, iteration: int) -> tuple[Any, str]:
        completed = _execute_packet_command(
            packet,
            project=project,
            write_scope=write_scope,
            packet_file=packet_file,
            stdout_file=stdout_file,
            stderr_file=stderr_file,
            executor_command=executor_command,
            execute_card_commands=execute_card_commands,
            timeout_seconds=timeout_seconds,
        )
        if not completed.get("ok"):
            raise RuntimeError(str(completed.get("detail") or "iteration_failed"))
        check = _run_goal_check(goal_command, project=project, timeout_seconds=timeout_seconds)
        progress = f"goal_rc={check.get('returncode')}:{_short_digest(check.get('stdout') or '')}"
        return {"completed": completed, "check": check}, progress

    def goal(state: Any) -> tuple[bool, str | None]:
        check = (state or {}).get("check") or {}
        if check.get("returncode") == 0:
            return True, f"goal verifier `{goal_command}` passed (exit 0)"
        return False, None

    outcome = run_goal_loop(iterate=iterate, goal=goal, journal=journal, config=config)
    detail = f"goal_loop:{outcome.outcome}:{outcome.iterations}it"
    if outcome.detail:
        detail = f"{detail}:{outcome.detail}"
    return {
        "ok": outcome.reached_goal,
        "detail": detail,
        "returncode": 0 if outcome.reached_goal else 1,
        "goal_loop": outcome.as_dict(),
    }


def _run_goal_check(command: str, *, project: Path, timeout_seconds: int) -> dict[str, Any]:
    """Run a packet's goal verifier in the project dir; exit 0 means goal met."""

    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(project),
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return {"returncode": None, "stdout": ""}
    return {"returncode": completed.returncode, "stdout": completed.stdout or ""}


def _short_digest(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:12]


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 1 else default


def _run_subprocess(
    command: str,
    packet: Mapping[str, Any],
    *,
    project: Path,
    write_scope: Path,
    packet_file: Path,
    stdout_file: Path,
    stderr_file: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    env = os.environ.copy()
    env.update(
        {
            "STORMBREAKER_PACKET_ID": str(packet.get("packet_id") or ""),
            "STORMBREAKER_STAGE": str(packet.get("stage") or ""),
            "STORMBREAKER_STAGE_ORDER": str(packet.get("stage_order") or ""),
            "STORMBREAKER_CARD_ID": str(packet.get("card") or ""),
            "STORMBREAKER_CANONICAL_COMMAND": str(packet.get("canonical_command") or ""),
            "STORMBREAKER_WRITE_SCOPE": str(write_scope),
            "STORMBREAKER_PACKET_FILE": str(packet_file),
            "STORMBREAKER_PROJECT_DIR": str(project),
            "STORMBREAKER_RESEARCH_EVIDENCE_FILE": str(((packet.get("research_evidence") or {}).get("file")) or ""),
            "STORMBREAKER_RESEARCH_PREFLIGHT_FILE": str(((packet.get("research_evidence") or {}).get("preflight", {}).get("file")) or ""),
            "STORMBREAKER_RESEARCH_STATUS_FILE": str(((packet.get("research_evidence") or {}).get("readiness", {}).get("file")) or ""),
            "STORMBREAKER_RESEARCH_RECEIPT_ID": str(((packet.get("research_evidence") or {}).get("receipt_id")) or ""),
        }
    )
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=str(project),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout_file.write_text(exc.stdout or "", encoding="utf-8")
        stderr_file.write_text((exc.stderr or "") + f"\ncommand timed out after {timeout_seconds}s\n", encoding="utf-8")
        return {"ok": False, "detail": f"executor_timeout:{timeout_seconds}s", "returncode": None}
    except OSError as exc:
        stdout_file.write_text("", encoding="utf-8")
        stderr_file.write_text(str(exc), encoding="utf-8")
        return {"ok": False, "detail": f"executor_os_error:{exc}", "returncode": None}

    stdout_file.write_text(completed.stdout or "", encoding="utf-8")
    stderr_file.write_text(completed.stderr or "", encoding="utf-8")
    if completed.returncode == 0:
        return {"ok": True, "detail": "executor_completed", "returncode": completed.returncode}
    return {"ok": False, "detail": f"executor_failed:{completed.returncode}", "returncode": completed.returncode}


def _blocked_packet_result(
    packet: Mapping[str, Any],
    *,
    project: Path,
    journal: Path,
    home: Path,
    parent_receipt_id: str,
    detail: str,
    pipeline_id: str,
    group_id: str,
) -> dict[str, Any]:
    packet_id = str(packet["packet_id"])
    write_scope = _resolve_project_path(project, str(packet.get("write_scope") or f".agentlas/pipeline/{pipeline_id}/{packet_id}/"))
    write_scope.mkdir(parents=True, exist_ok=True)
    execution_receipt_id = uuid.uuid4().hex[:16]
    result = {
        "runner_version": RUNNER_VERSION,
        "execution_receipt_id": execution_receipt_id,
        "packet_id": packet_id,
        "pipeline_id": pipeline_id,
        "stage": packet.get("stage"),
        "stage_order": packet.get("stage_order"),
        "card": packet.get("card"),
        "session_id": (packet.get("session_hint") or {}).get("session_id") or "host:primary",
        "parallel_group": group_id,
        "execution_mode": "dependency_gate",
        "status": "blocked",
        "detail": detail,
        "started_at": utc_now(),
        "finished_at": utc_now(),
        "write_scope": _relative_to_project(project, write_scope),
        "packet_file": _relative_to_project(project, write_scope / "packet.json"),
        "result_file": _relative_to_project(project, write_scope / "packet-result.json"),
    }
    atomic_write_json(write_scope / "packet.json", {"runner_version": RUNNER_VERSION, "packet": packet, "blocked_by": detail})
    atomic_write_json(write_scope / "packet-result.json", result)
    record_execution(
        execution_receipt_id,
        str(packet.get("card") or "unknown"),
        "blocked",
        home=home,
        detail=detail,
        pipeline_id=pipeline_id,
        packet_id=packet_id,
        stage_order=_int_or_none(packet.get("stage_order")),
        session_id=str(result["session_id"]),
        parallel_group=group_id,
        parent_receipt_id=parent_receipt_id or None,
    )
    _append_journal(journal, {"event": "packet_finished", **result})
    return result


def _append_journal(path: Path, payload: dict[str, Any]) -> None:
    append_jsonl(path, {"ts": utc_now(), **payload})


def _collect_packet_research_evidence(
    packet: Mapping[str, Any],
    *,
    enabled: bool,
    project: Path,
    write_scope: Path,
    home: Path,
    options: Mapping[str, Any],
    user_query: str = "",
) -> dict[str, Any] | None:
    if not enabled:
        return None
    if not _packet_wants_research(packet):
        return None

    evidence_file = write_scope / "research-evidence.json"
    request = _packet_research_request(packet, options=options, home=home, user_query=user_query)
    preflight_file = write_scope / "research-preflight.json"
    preflight = _packet_research_preflight(request, home=home)
    atomic_write_json(preflight_file, preflight)
    readiness_file = write_scope / "research-status.json"
    readiness = _packet_research_status(home=home)
    atomic_write_json(readiness_file, readiness)
    from agentlas_cloud.research import run_research

    result = run_research(_engine_research_request(request), home=home)
    atomic_write_json(evidence_file, result)
    receipt = result.get("receipt") if isinstance(result, dict) else {}
    request_payload = result.get("request") if isinstance(result, dict) else {}
    policy_payload = receipt.get("policy") if isinstance(receipt, Mapping) else {}
    evidence_quality = policy_payload.get("evidence_quality") if isinstance(policy_payload, Mapping) else {}
    evidence_coverage = policy_payload.get("evidence_coverage") if isinstance(policy_payload, Mapping) else {}
    capability_summary = result.get("capability_summary") if isinstance(result.get("capability_summary"), Mapping) else {}
    if not capability_summary and isinstance(policy_payload, Mapping):
        maybe_capability = policy_payload.get("capability_summary")
        capability_summary = maybe_capability if isinstance(maybe_capability, Mapping) else {}
    results = result.get("results") if isinstance(result, dict) else []
    result_summaries = []
    if isinstance(results, list):
        for item in results[:8]:
            if not isinstance(item, Mapping):
                continue
            result_summaries.append(
                {
                    "title": item.get("title"),
                    "url": item.get("url"),
                    "platform": item.get("platform"),
                    "confidence": item.get("confidence"),
                    "limits": item.get("limits") or [],
                }
            )
    return {
        "status": result.get("status") if isinstance(result, dict) else "error",
        "file": _relative_to_project(project, evidence_file),
        "preflight": _research_preflight_summary(preflight, file=_relative_to_project(project, preflight_file)),
        "readiness": _research_status_summary(readiness, file=_relative_to_project(project, readiness_file)),
        "receipt_id": receipt.get("receipt_id") if isinstance(receipt, Mapping) else None,
        "request_hash": request_payload.get("request_hash") if isinstance(request_payload, Mapping) else None,
        "request": _research_request_summary(request_payload),
        "module_chain": receipt.get("module_chain") if isinstance(receipt, Mapping) else [],
        "options": dict(options),
        "recommendation": _research_recommendation_summary(request.get("_stormbreaker_recommendation")),
        "capability_summary": _research_capability_summary(capability_summary),
        "result_count": len(results) if isinstance(results, list) else 0,
        "evidence_quality": {
            "status": evidence_quality.get("status"),
            "score": evidence_quality.get("score"),
            "direct_read_count": evidence_quality.get("direct_read_count"),
            "search_result_count": evidence_quality.get("search_result_count"),
            "source_class_counts": evidence_quality.get("source_class_counts") or {},
        }
        if isinstance(evidence_quality, Mapping)
        else {},
        "evidence_coverage": {
            "status": evidence_coverage.get("status"),
            "search_only": evidence_coverage.get("search_only"),
            "official_social_evidence": evidence_coverage.get("official_social_evidence"),
            "public_social_fallback_evidence": evidence_coverage.get("public_social_fallback_evidence"),
            "public_social_fallback_platforms": evidence_coverage.get("public_social_fallback_platforms") or [],
            "official_social_modules_missing": evidence_coverage.get("official_social_modules_missing") or [],
            "missing_credentials": evidence_coverage.get("missing_credentials") or [],
            "browser_evidence": evidence_coverage.get("browser_evidence"),
            "completion_blockers": evidence_coverage.get("completion_blockers") or [],
            "warnings": evidence_coverage.get("warnings") or [],
        }
        if isinstance(evidence_coverage, Mapping)
        else {},
        "results": result_summaries,
    }


def _research_capability_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    browser = value.get("browser") if isinstance(value.get("browser"), Mapping) else {}
    social = value.get("social") if isinstance(value.get("social"), Mapping) else {}
    trust = value.get("trust") if isinstance(value.get("trust"), Mapping) else {}
    web = value.get("web") if isinstance(value.get("web"), Mapping) else {}
    return {
        "status": value.get("status"),
        "loadout": value.get("loadout"),
        "max_weight": value.get("max_weight"),
        "depth": value.get("depth"),
        "mounted_modules": _dedupe_strings(_string_list(value.get("mounted_modules")))[:24],
        "heavy_modules_mounted": [
            {"id": item.get("id"), "weight": item.get("weight")}
            for item in _mapping_list(value.get("heavy_modules_mounted"))[:12]
            if isinstance(item, Mapping)
        ],
        "browser": {
            "requested": browser.get("requested"),
            "attempted": browser.get("attempted"),
            "used": browser.get("used"),
            "status": browser.get("status"),
            "modules": _dedupe_strings(_string_list(browser.get("modules")))[:8],
            "evidence": browser.get("evidence"),
        },
        "social": {
            "requested": social.get("requested"),
            "official_evidence": social.get("official_evidence"),
            "public_fallback_evidence": social.get("public_fallback_evidence"),
            "public_fallback_platforms": _dedupe_strings(_string_list(social.get("public_fallback_platforms")))[:8],
            "official_missing_modules": _dedupe_strings(_string_list(social.get("official_missing_modules")))[:8],
            "missing_proofs": _dedupe_strings(_string_list(social.get("missing_proofs")))[:8],
        },
        "web": {
            "search_evidence": web.get("search_evidence"),
            "direct_read_evidence": web.get("direct_read_evidence"),
            "search_only": web.get("search_only"),
        },
        "trust": {
            "usable_result_count": trust.get("usable_result_count"),
            "warnings": _dedupe_strings(_string_list(trust.get("warnings")))[:8],
            "missing_proofs": _dedupe_strings(_string_list(trust.get("missing_proofs")))[:8],
            "can_use_for_build_context": trust.get("can_use_for_build_context"),
        },
}


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _packet_research_status(*, home: Path) -> dict[str, Any]:
    from agentlas_cloud.research import run_research_status

    return run_research_status(home=home)


def _packet_research_preflight(request: Mapping[str, Any], *, home: Path) -> dict[str, Any]:
    from agentlas_cloud.research import run_research_preflight

    max_cost = request.get("max_cost") if isinstance(request.get("max_cost"), Mapping) else {}
    max_requests = max_cost.get("requests") if isinstance(max_cost, Mapping) else None
    try:
        max_requests_value = int(max_requests) if max_requests is not None else None
    except (TypeError, ValueError):
        max_requests_value = None
    return run_research_preflight(
        query=str(request.get("query") or "agent research evidence"),
        source_hints=_string_list(request.get("source_hints")),
        loadout=str(request.get("loadout") or STORMBREAKER_DEFAULT_RESEARCH_LOADOUT),
        depth=str(request.get("depth") or STORMBREAKER_DEFAULT_RESEARCH_DEPTH),
        follow_results=_safe_int(request.get("follow_results"), 0),
        query_variants=_string_list(request.get("query_variants")),
        max_requests=max_requests_value,
        max_weight=str(request.get("max_weight") or ""),
        allowed_modules=_string_list(request.get("allowed_modules")),
        forbidden_modules=_string_list(request.get("forbidden_modules")),
        home=home,
    )


def _research_preflight_summary(preflight: Any, *, file: str) -> dict[str, Any]:
    if not isinstance(preflight, Mapping):
        return {"file": file, "status": "error"}
    summary = preflight.get("summary") if isinstance(preflight.get("summary"), Mapping) else {}
    boundaries = preflight.get("boundaries") if isinstance(preflight.get("boundaries"), Mapping) else {}
    slot_summary = preflight.get("slot_summary") if isinstance(preflight.get("slot_summary"), Mapping) else {}
    readiness_blockers = preflight.get("readiness_blockers") if isinstance(preflight.get("readiness_blockers"), list) else []
    mount_decision = preflight.get("mount_decision") if isinstance(preflight.get("mount_decision"), Mapping) else {}
    return {
        "file": file,
        "status": preflight.get("status"),
        "requested_loadout": preflight.get("requested_loadout"),
        "resolved_loadout": preflight.get("resolved_loadout"),
        "commands_will_run": preflight.get("commands_will_run"),
        "network_will_run": preflight.get("network_will_run"),
        "browser_will_run": preflight.get("browser_will_run"),
        "mounted_module_count": summary.get("mounted_module_count"),
        "heavy_mounted_module_count": summary.get("heavy_mounted_module_count"),
        "browser_modules_mounted": summary.get("browser_modules_mounted"),
        "readiness_blocker_count": summary.get("readiness_blocker_count"),
        "slot_summary": _compact_slot_summary(slot_summary),
        "mount_decision": _research_mount_decision_summary(mount_decision),
        "readiness_blockers": [_compact_readiness_blocker(item) for item in readiness_blockers[:8] if isinstance(item, Mapping)],
        "boundaries": {
            "heavy_modules_are_detachable": boundaries.get("heavy_modules_are_detachable"),
            "browser_requires_browser_or_full_loadout_or_explicit_allow": boundaries.get("browser_requires_browser_or_full_loadout_or_explicit_allow"),
            "preflight_executes_modules": boundaries.get("preflight_executes_modules"),
        },
    }


def _research_status_summary(status: Any, *, file: str) -> dict[str, Any]:
    if not isinstance(status, Mapping):
        return {"file": file, "status": "error"}
    summary = status.get("summary") if isinstance(status.get("summary"), Mapping) else {}
    proof_coverage = status.get("proof_coverage") if isinstance(status.get("proof_coverage"), Mapping) else {}
    requirements = status.get("requirements") if isinstance(status.get("requirements"), list) else []
    return {
        "file": file,
        "status": status.get("status"),
        "goal_ready": bool(status.get("goal_ready")),
        "commands_will_run": status.get("commands_will_run"),
        "network_will_run": status.get("network_will_run"),
        "credentials_exposed_to_model": status.get("credentials_exposed_to_model"),
        "summary": {
            "core_engine_ok": summary.get("core_engine_ok"),
            "public_social_fallbacks_ok": summary.get("public_social_fallbacks_ok"),
            "browser_hardpoint_ok": summary.get("browser_hardpoint_ok"),
            "credentialed_social_ok": summary.get("credentialed_social_ok"),
            "official_social_missing": _dedupe_strings(_string_list(summary.get("official_social_missing")))[:8],
            "missing_or_unready_proofs": _dedupe_strings(_string_list(summary.get("missing_or_unready_proofs")))[:8],
            "missing_env": _dedupe_strings(_string_list(summary.get("missing_env")))[:8],
        },
        "proof_coverage": {
            "required_ok": _dedupe_strings(_string_list(proof_coverage.get("required_ok")))[:8],
            "required_missing": _dedupe_strings(_string_list(proof_coverage.get("required_missing")))[:8],
            "public_fallback_ok": _dedupe_strings(_string_list(proof_coverage.get("public_fallback_ok")))[:8],
            "public_fallback_missing": _dedupe_strings(_string_list(proof_coverage.get("public_fallback_missing")))[:8],
            "browser_hardpoint_status": proof_coverage.get("browser_hardpoint_status"),
        },
        "requirements": [
            _compact_research_requirement(item)
            for item in requirements[:12]
            if isinstance(item, Mapping)
        ],
        "next_commands": _dedupe_strings(_string_list(status.get("next_commands")))[:8],
    }


def _compact_research_requirement(item: Mapping[str, Any]) -> dict[str, Any]:
    setup = item.get("setup") if isinstance(item.get("setup"), Mapping) else {}
    return {
        "id": item.get("id"),
        "status": item.get("status"),
        "missing_proofs": _dedupe_strings(_string_list(item.get("missing_proofs")))[:6],
        "check_command": item.get("check_command") or "",
        "missing_env": _dedupe_strings(_string_list(setup.get("missing_env")))[:8],
    }


def _compact_slot_summary(slot_summary: Mapping[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    for slot, payload in slot_summary.items():
        if not isinstance(payload, Mapping):
            continue
        compact[str(slot)] = {
            "mounted_count": payload.get("mounted_count"),
            "detached_count": payload.get("detached_count"),
            "unready_mounted_count": payload.get("unready_mounted_count"),
            "mounted_modules": _dedupe_strings(_string_list(payload.get("mounted_modules")))[:12],
        }
    return compact


def _compact_readiness_blocker(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "slot": item.get("slot"),
        "state": item.get("state"),
        "reason": item.get("reason"),
        "missing_env": _dedupe_strings(_string_list(item.get("missing_env")))[:8],
    }


def _research_request_summary(request: Any) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        return {}
    summary: dict[str, Any] = {}
    query = " ".join(str(request.get("query") or "").split())[:300]
    if query:
        summary["query"] = query
    for key in ("loadout", "depth"):
        value = request.get(key)
        if value is not None:
            summary[key] = str(value)
    if "follow_results" in request:
        summary["follow_results"] = request.get("follow_results")
    if "max_weight" in request:
        summary["max_weight"] = request.get("max_weight")
    list_limits = {
        "query_variants": 8,
        "source_hints": 8,
        "allowed_modules": 24,
        "forbidden_modules": 24,
    }
    for key, limit in list_limits.items():
        values = _dedupe_strings(_string_list(request.get(key)))[:limit]
        if values:
            summary[key] = values
    return summary


def _packet_wants_research(packet: Mapping[str, Any]) -> bool:
    if isinstance(packet.get("research_request"), Mapping):
        return True
    stage = str(packet.get("stage") or "").lower()
    return stage in {"plan", "research"}


def _packet_research_request(
    packet: Mapping[str, Any],
    *,
    options: Mapping[str, Any],
    home: Path,
    user_query: str = "",
) -> dict[str, Any]:
    raw = packet.get("research_request")
    if isinstance(raw, Mapping):
        request = dict(raw)
    else:
        query = _default_research_query(packet, user_query=user_query)
        search_query = _searchable_research_query(packet, user_query=user_query, fallback=query)
        request = {
            "query": query,
            "intent": "search",
            "source_hints": [f"search:auto:{search_query}"],
            "loadout": options.get("loadout") or STORMBREAKER_DEFAULT_RESEARCH_LOADOUT,
            "follow_results": options.get("follow_results", STORMBREAKER_DEFAULT_FOLLOW_RESULTS),
        }

    request["query"] = str(request.get("query") or _default_research_query(packet, user_query=user_query))[:300]
    request["intent"] = str(request.get("intent") or "search")
    requested_loadout = _research_loadout(str(request.get("loadout") or options.get("loadout") or "safe"))
    if requested_loadout == "recommended":
        _apply_recommended_research_options(request, raw=raw, options=options, home=home)
        requested_loadout = _research_loadout(str(request.get("loadout") or "safe"))
    request["loadout"] = requested_loadout
    request["privacy_scope"] = "public"
    request["depth"] = _research_depth(str(request.get("depth") or options.get("depth") or "quick"))
    try:
        follow_results = int(request.get("follow_results", options.get("follow_results", 0)) or 0)
    except (TypeError, ValueError):
        follow_results = 0
    request["follow_results"] = max(0, min(10, follow_results))
    source_hints = _string_list(request.get("source_hints"))
    if not source_hints:
        source_hints = [f"search:auto:{request['query']}"]
    query_variants = _dedupe_strings(
        _string_list(request.get("query_variants")) + _string_list(options.get("query_variants"))
    )
    if request["loadout"] in {"social", "full"} and _has_auto_search_hint(source_hints):
        query_variants = _dedupe_strings(query_variants + ["reddit", "threads"])
    request["query_variants"] = query_variants[:5]
    if request["loadout"] in {"social", "full"} and _has_auto_search_hint(source_hints):
        social_query = _primary_auto_search_query(source_hints) or _searchable_research_text(str(request["query"]))
        source_hints.extend(_social_source_hints(social_query))
    request["source_hints"] = _dedupe_strings(source_hints)[:5]
    allowed = _string_list(request.get("allowed_modules"))
    allowed = [item for item in allowed if item in STORMBREAKER_RESEARCH_MODULES]
    if allowed:
        request["allowed_modules"] = allowed
    elif request["loadout"] == "safe":
        request["allowed_modules"] = list(STORMBREAKER_SAFE_RESEARCH_MODULES)
    else:
        request.pop("allowed_modules", None)
    forbidden = _string_list(request.get("forbidden_modules"))
    allowed_for_forbid = _string_list(request.get("allowed_modules"))
    request["forbidden_modules"] = [item for item in forbidden if item not in allowed_for_forbid]
    max_requests = max(1, min(10, _safe_int(request.pop("_stormbreaker_max_requests", 5), 5)))
    request["max_cost"] = {"tokens": 5000, "requests": max_requests, "seconds": 45}
    return request


def _apply_recommended_research_options(
    request: dict[str, Any],
    *,
    raw: Any,
    options: Mapping[str, Any],
    home: Path,
) -> None:
    from agentlas_cloud.research import run_research_recommendation

    recommendation = run_research_recommendation(
        query=str(request.get("query") or ""),
        source_hints=_string_list(request.get("source_hints")),
        home=home,
    )
    rec = recommendation.get("recommendation") if isinstance(recommendation, Mapping) else {}
    if not isinstance(rec, Mapping):
        rec = {}
    request["_stormbreaker_recommendation"] = {
        "status": recommendation.get("status") if isinstance(recommendation, Mapping) else "error",
        "loadout": rec.get("loadout"),
        "depth": rec.get("depth"),
        "follow_results": rec.get("follow_results"),
        "max_requests": rec.get("max_requests"),
        "query_variants": rec.get("query_variants") or [],
        "reasons": rec.get("reasons") or [],
        "mount_decision": rec.get("mount_decision") if isinstance(rec.get("mount_decision"), Mapping) else {},
    }
    request["loadout"] = _research_loadout(str(rec.get("loadout") or STORMBREAKER_DEFAULT_RESEARCH_LOADOUT))
    if not isinstance(raw, Mapping) or "depth" not in raw:
        request["depth"] = rec.get("depth") or options.get("depth") or STORMBREAKER_DEFAULT_RESEARCH_DEPTH
    if not isinstance(raw, Mapping) or "follow_results" not in raw:
        request["follow_results"] = rec.get("follow_results", options.get("follow_results", STORMBREAKER_DEFAULT_FOLLOW_RESULTS))
    request["query_variants"] = _dedupe_strings(_string_list(request.get("query_variants")) + _string_list(rec.get("query_variants")))
    request["_stormbreaker_max_requests"] = rec.get("max_requests", 5)


def _engine_research_request(request: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in request.items() if not str(key).startswith("_stormbreaker_")}


def _research_recommendation_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    summary: dict[str, Any] = {}
    for key in ("status", "loadout", "depth", "follow_results", "max_requests"):
        if value.get(key) is not None:
            summary[key] = value.get(key)
    variants = _dedupe_strings(_string_list(value.get("query_variants")))[:5]
    if variants:
        summary["query_variants"] = variants
    reasons = _dedupe_strings(_string_list(value.get("reasons")))[:8]
    if reasons:
        summary["reasons"] = reasons
    mount_decision = value.get("mount_decision") if isinstance(value.get("mount_decision"), Mapping) else {}
    if mount_decision:
        summary["mount_decision"] = _research_mount_decision_summary(mount_decision)
    return summary


def _research_mount_decision_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    summary: dict[str, Any] = {}
    for key in (
        "source",
        "selected_loadout",
        "mode",
        "browser_hardpoints",
        "credentialed_social",
        "public_social_fallbacks",
        "adaptive_public_reader",
        "heavy_modules",
        "operator_approval_recommended",
        "readiness",
        "next_escalation",
        "core_boundary",
    ):
        if key in value:
            summary[key] = value.get(key)
    blockers = _dedupe_strings(_string_list(value.get("readiness_blockers")))[:8]
    if blockers:
        summary["readiness_blockers"] = blockers
    signals = _dedupe_strings(_string_list(value.get("signals_true")))[:8]
    if signals:
        summary["signals_true"] = signals
    reasons = _dedupe_strings(_string_list(value.get("reasons")))[:8]
    if reasons:
        summary["reasons"] = reasons
    return summary


def _research_options(
    *,
    loadout: str,
    depth: str,
    follow_results: int,
    variants: list[str] | None,
) -> dict[str, Any]:
    return {
        "loadout": _research_loadout(loadout),
        "depth": _research_depth(depth),
        "follow_results": max(0, min(10, _safe_int(follow_results, STORMBREAKER_DEFAULT_FOLLOW_RESULTS))),
        "query_variants": _dedupe_strings(_string_list(variants))[:5],
    }


def _research_loadout(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized in STORMBREAKER_RESEARCH_LOADOUTS:
        return normalized
    return STORMBREAKER_DEFAULT_RESEARCH_LOADOUT


def _research_depth(value: str) -> str:
    normalized = str(value or "").strip()
    if normalized in STORMBREAKER_RESEARCH_DEPTHS:
        return normalized
    return STORMBREAKER_DEFAULT_RESEARCH_DEPTH


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        item = value.strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _has_auto_search_hint(source_hints: list[str]) -> bool:
    return any(hint.lower().startswith("search:auto:") for hint in source_hints)


def _primary_auto_search_query(source_hints: list[str]) -> str:
    for hint in source_hints:
        if hint.lower().startswith("search:auto:"):
            return _searchable_research_text(hint.split(":", 2)[2])
    return ""


def _social_source_hints(query: str) -> list[str]:
    compact = _searchable_research_text(query)
    if not compact:
        return []
    return [f"reddit:search:{compact}", f"threads:keyword:{compact}"]


def _searchable_research_query(packet: Mapping[str, Any], *, user_query: str = "", fallback: str = "") -> str:
    return _searchable_research_text(str(user_query or "").strip()) or _searchable_research_text(fallback)


def _searchable_research_text(value: str) -> str:
    return " ".join(str(value or "").split())[:180]


def _default_research_query(packet: Mapping[str, Any], *, user_query: str = "") -> str:
    parts = [
        str(user_query or ""),
        str(packet.get("stage") or ""),
        str(packet.get("card") or ""),
        str(packet.get("canonical_command") or ""),
    ]
    produced = " ".join(str(item) for item in (packet.get("produces") or []))
    parts.append(produced)
    query = " ".join(part for part in parts if part).strip()
    return query or "agent research evidence"


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        return [str(value)]
    try:
        return [str(item) for item in value]
    except TypeError:
        return [str(value)]


def _resolve_project_path(project: Path, raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if not path.is_absolute():
        path = project / path
    resolved = path.resolve()
    try:
        resolved.relative_to(project)
    except ValueError as exc:
        raise ValueError(f"Stormbreaker write path escapes project: {raw_path}") from exc
    return resolved


def _relative_to_project(project: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(project))
    except ValueError:
        return str(path)


def _execution_mode(executor_command: str | None, execute_card_commands: bool) -> str:
    if executor_command:
        return "executor_command"
    if execute_card_commands:
        return "card_command"
    return "materialize"


def _claim_level(mode: str) -> str:
    if mode == "materialize":
        return "handoff_artifacts_materialized"
    if mode == "card_command":
        return "card_command_executed"
    return "external_executor_completed"


def _max_workers(configured: int | None, fabric: Mapping[str, Any]) -> int:
    if configured is not None:
        return max(1, int(configured))
    sessions = fabric.get("sessions") or []
    total = 0
    for session in sessions:
        if not isinstance(session, Mapping):
            continue
        try:
            total += int(session.get("max_parallel") or 1)
        except (TypeError, ValueError):
            total += 1
    return max(1, total or 1)


def _decision_summary(decision: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "action": decision.get("action"),
        "receipt_id": decision.get("receipt_id"),
        "match_reason": decision.get("match_reason"),
        "allowed_by": decision.get("allowed_by") or [],
        "blocked_by_axiom": decision.get("blocked_by_axiom") or [],
    }


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
