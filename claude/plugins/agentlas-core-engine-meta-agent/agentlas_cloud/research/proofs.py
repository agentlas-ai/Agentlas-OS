"""Research proof receipt inspection."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agentlas_cloud.networking.bootstrap import networking_home, read_jsonl

from .armory import module_readiness
from .engine import default_registry
from .registry import AdapterRegistry, ResearchAdapter

RESEARCH_RECEIPT_LEDGER = "ledgers/research-receipts.jsonl"
PROOF_FRESHNESS_SECONDS = 24 * 60 * 60

REQUIRED_PROOFS: tuple[dict[str, Any], ...] = (
    {
        "id": "reddit_oauth_live_check",
        "label": "Reddit OAuth cartridge live check",
        "module_id": "platform.reddit.oauth",
        "slot": "platform",
        "check_command": "bin/hephaestus research platform-check --module platform.reddit.oauth --source 'reddit:subreddit:redditdev'",
    },
    {
        "id": "threads_live_graph_check",
        "label": "Threads Graph cartridge live check",
        "module_id": "platform.threads",
        "slot": "platform",
        "check_command": "bin/hephaestus research platform-check --module platform.threads --source 'threads:keyword:agent browser'",
    },
    {
        "id": "browser_hardpoint_live_check",
        "label": "Browser hardpoint live check",
        "module_id": "browser.*",
        "slot": "browser",
        "check_command": "bin/hephaestus research bridge-check --module browser.agent_cli --url https://example.com",
    },
)

PUBLIC_FALLBACK_PROOFS: tuple[dict[str, Any], ...] = (
    {
        "id": "reddit_public_live_check",
        "label": "Reddit public fallback live check",
        "module_id": "platform.reddit",
        "slot": "platform",
        "check_command": "bin/hephaestus research platform-check --module platform.reddit --source 'reddit:subreddit:redditdev'",
    },
    {
        "id": "threads_public_live_check",
        "label": "Threads public fallback live check",
        "module_id": "platform.threads.public",
        "slot": "platform",
        "check_command": "bin/hephaestus research platform-check --module platform.threads.public --source 'threads:lookup:instagram'",
    },
)


def run_research_proofs(
    *,
    home: Path | str | None = None,
    limit: int = 50,
    registry: AdapterRegistry | None = None,
) -> dict[str, Any]:
    """Summarize proof receipts without running network, commands, or browsers."""

    base = Path(home) if home else networking_home()
    selected_registry = registry or default_registry(home=base)
    adapters = list(selected_registry.adapters)
    live_proofs = load_research_live_proofs(base)
    recent_receipts = _recent_receipts(base, limit=limit)
    proof_states = [
        _proof_state(definition, adapters=adapters, live_proofs=live_proofs)
        for definition in REQUIRED_PROOFS
    ]
    public_fallback_states = [
        _proof_state(definition, adapters=adapters, live_proofs=live_proofs)
        for definition in PUBLIC_FALLBACK_PROOFS
    ]
    missing = [proof["id"] for proof in proof_states if proof["status"] != "ok"]
    coverage = _coverage_summary(proof_states, public_fallback_states)
    return {
        "schema": "agentlas.research.proofs.v0",
        "status": "ok" if not missing else "partial",
        "commands_will_run": False,
        "network_will_run": False,
        "credentials_exposed_to_model": False,
        "home": str(base),
        "ledger": str(base / RESEARCH_RECEIPT_LEDGER),
        "receipt_count_scanned": len(read_jsonl(base / RESEARCH_RECEIPT_LEDGER, limit=500)),
        "required_proofs": proof_states,
        "public_fallback_proofs": public_fallback_states,
        "freshness_policy": {
            "max_age_seconds": PROOF_FRESHNESS_SECONDS,
            "max_age_hours": PROOF_FRESHNESS_SECONDS // 3600,
        },
        "completion": {
            "goal_ready": not missing,
            "missing_or_unready_proofs": missing,
            "stale_or_unknown_proofs": coverage["stale_or_unknown_proofs"],
            "satisfied_required_proofs": coverage["required_ok"],
            "satisfied_public_fallback_proofs": coverage["public_fallback_ok"],
        },
        "coverage": coverage,
        "recent_receipts": [_receipt_summary(receipt) for receipt in recent_receipts],
        "next_commands": _dedupe(
            proof["check_command"]
            for proof in proof_states
            if proof["status"] != "ok" and proof.get("check_command")
        ),
    }


def load_research_live_proofs(base: Path, *, limit: int = 500) -> dict[str, Any]:
    """Return the latest receipt summary for each recognized live proof."""

    receipts = read_jsonl(base / RESEARCH_RECEIPT_LEDGER, limit=limit)
    proofs: dict[str, Any] = {}
    for receipt in receipts:
        if not isinstance(receipt, dict):
            continue
        proof_id = proof_id_for_receipt(receipt)
        if not proof_id:
            continue
        proofs[proof_id] = _receipt_summary(receipt)
    return proofs


def proof_id_for_receipt(receipt: dict[str, Any]) -> str:
    """Classify a receipt as one of the live proof gates, if applicable."""

    attempts = receipt.get("attempts") if isinstance(receipt.get("attempts"), list) else []
    policy = receipt.get("policy") if isinstance(receipt.get("policy"), dict) else {}
    if _attempt_ok(attempts, "platform.reddit.oauth"):
        return "reddit_oauth_live_check"
    if _attempt_ok(attempts, "platform.threads"):
        return "threads_live_graph_check"
    if _attempt_ok(attempts, "platform.reddit"):
        return "reddit_public_live_check"
    if _attempt_ok(attempts, "platform.threads.public"):
        return "threads_public_live_check"
    browser_execution = policy.get("browser_execution") if isinstance(policy.get("browser_execution"), dict) else {}
    if browser_execution.get("status") == "used" or any(
        isinstance(attempt, dict) and str(attempt.get("module") or "").startswith("browser.") and attempt.get("status") == "ok"
        for attempt in attempts
    ):
        return "browser_hardpoint_live_check"
    return ""


def _proof_state(
    definition: dict[str, Any],
    *,
    adapters: list[ResearchAdapter],
    live_proofs: dict[str, Any],
) -> dict[str, Any]:
    proof_id = str(definition["id"])
    proof_payload = live_proofs.get(proof_id)
    if definition["slot"] == "browser":
        readiness = _browser_readiness(adapters)
        ready = bool(readiness["ready_modules"])
        check_command = _browser_check_command(readiness, str(definition["check_command"]))
    else:
        adapter = _adapter_by_id(adapters, str(definition["module_id"]))
        readiness = module_readiness(adapter) if adapter else {"state": "missing", "reason": "module_not_registered"}
        ready = readiness.get("state") == "ready"
        check_command = str(definition["check_command"])
    if ready and proof_payload:
        freshness = proof_payload.get("freshness") if isinstance(proof_payload, dict) else {}
        freshness_status = freshness.get("status") if isinstance(freshness, dict) else "unknown"
        if freshness_status == "fresh":
            status = "ok"
        elif freshness_status == "stale":
            status = "stale_live_proof"
        else:
            status = "unknown_live_proof"
    elif ready:
        status = "needs_live_proof"
    elif proof_payload:
        status = "proof_present_but_not_ready"
    else:
        status = "needs_config"
    return {
        "id": proof_id,
        "label": definition["label"],
        "module_id": definition["module_id"],
        "slot": definition["slot"],
        "status": status,
        "readiness": readiness,
        "live_proof": proof_payload or None,
        "check_command": check_command,
    }


def _adapter_by_id(adapters: list[ResearchAdapter], module_id: str) -> ResearchAdapter | None:
    for adapter in adapters:
        if adapter.module_id == module_id:
            return adapter
    return None


def _browser_readiness(adapters: list[ResearchAdapter]) -> dict[str, Any]:
    browser = [adapter for adapter in adapters if adapter.manifest.slot == "browser"]
    readiness = {adapter.module_id: module_readiness(adapter) for adapter in browser}
    return {
        "state": "ready" if any(payload.get("state") == "ready" for payload in readiness.values()) else "missing",
        "ready_modules": [module_id for module_id, payload in readiness.items() if payload.get("state") == "ready"],
        "modules": readiness,
    }


def _browser_check_command(readiness: dict[str, Any], fallback: str) -> str:
    ready_modules = readiness.get("ready_modules") if isinstance(readiness.get("ready_modules"), list) else []
    module_id = str(ready_modules[0]) if ready_modules else "browser.agent_cli"
    if module_id and module_id != "browser.agent_cli":
        return f"bin/hephaestus research bridge-check --module {module_id} --url https://example.com"
    return fallback


def _coverage_summary(required: list[dict[str, Any]], public_fallbacks: list[dict[str, Any]]) -> dict[str, Any]:
    required_ok = [item["id"] for item in required if item.get("status") == "ok"]
    required_missing = [item["id"] for item in required if item.get("status") != "ok"]
    public_ok = [item["id"] for item in public_fallbacks if item.get("status") == "ok"]
    public_missing = [item["id"] for item in public_fallbacks if item.get("status") != "ok"]
    stale_or_unknown = [
        item["id"]
        for item in [*required, *public_fallbacks]
        if item.get("status") in {"stale_live_proof", "unknown_live_proof"}
    ]
    credentialed_missing_config = [
        item["id"]
        for item in required
        if item.get("slot") == "platform" and item.get("status") in {"needs_config", "proof_present_but_not_ready"}
    ]
    credentialed_needs_live_proof = [
        item["id"]
        for item in required
        if item.get("slot") == "platform" and item.get("status") == "needs_live_proof"
    ]
    browser = next((item for item in required if item.get("slot") == "browser"), {})
    return {
        "required_ok": required_ok,
        "required_missing": required_missing,
        "public_fallback_ok": public_ok,
        "public_fallback_missing": public_missing,
        "credentialed_missing_config": credentialed_missing_config,
        "credentialed_needs_live_proof": credentialed_needs_live_proof,
        "stale_or_unknown_proofs": stale_or_unknown,
        "browser_hardpoint_ok": browser.get("status") == "ok",
        "browser_hardpoint_status": browser.get("status") or "missing",
        "goal_blocked_by": required_missing,
    }


def _recent_receipts(base: Path, *, limit: int) -> list[dict[str, Any]]:
    bounded_limit = max(0, min(int(limit), 200))
    if bounded_limit == 0:
        return []
    return read_jsonl(base / RESEARCH_RECEIPT_LEDGER, limit=bounded_limit)


def _receipt_summary(receipt: dict[str, Any]) -> dict[str, Any]:
    attempts = receipt.get("attempts") if isinstance(receipt.get("attempts"), list) else []
    return {
        "receipt_id": receipt.get("receipt_id"),
        "ts": receipt.get("ts"),
        "freshness": _freshness_summary(receipt.get("ts")),
        "request_hash": receipt.get("request_hash"),
        "module_chain": receipt.get("module_chain") or [],
        "proof_id": proof_id_for_receipt(receipt),
        "attempts": [_attempt_summary(attempt) for attempt in attempts[:8] if isinstance(attempt, dict)],
    }


def _freshness_summary(raw_ts: Any) -> dict[str, Any]:
    parsed = _parse_ts(raw_ts)
    if parsed is None:
        return {
            "status": "unknown",
            "max_age_seconds": PROOF_FRESHNESS_SECONDS,
            "reason": "missing_or_unparseable_timestamp",
        }
    now = datetime.now(timezone.utc)
    age_seconds = max(0, int((now - parsed).total_seconds()))
    return {
        "status": "fresh" if age_seconds <= PROOF_FRESHNESS_SECONDS else "stale",
        "age_seconds": age_seconds,
        "max_age_seconds": PROOF_FRESHNESS_SECONDS,
    }


def _parse_ts(raw_ts: Any) -> datetime | None:
    if not raw_ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _attempt_summary(attempt: dict[str, Any]) -> dict[str, Any]:
    return {
        "module": attempt.get("module"),
        "status": attempt.get("status"),
        "reason": attempt.get("reason"),
    }


def _attempt_ok(attempts: list[Any], module_id: str) -> bool:
    return any(isinstance(attempt, dict) and attempt.get("module") == module_id and attempt.get("status") == "ok" for attempt in attempts)


def _dedupe(values) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out
