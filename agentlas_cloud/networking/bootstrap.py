"""Global ~/.agentlas/networking/ bootstrap.

Concurrency contract (multiple runtimes share one home):
- init is guarded by an exclusive lock file;
- JSON writes are atomic (tmp + fsync + rename);
- JSONL appends take an exclusive flock per append.

Privacy contract: only explicitly registered paths are ever indexed.
The user's home folder itself is never accepted as a source.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # POSIX only — Windows runtimes fall back to best-effort, lock-free writes.
    import fcntl

    def _lock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)

    def _unlock(handle) -> None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
except ImportError:  # pragma: no cover
    def _lock(handle) -> None:
        return None

    def _unlock(handle) -> None:
        return None

SCHEMA_VERSION = "2.0"

HIGH_RISK_CAPABILITIES = [
    "file_write",
    "cloud_call",
    "payment",
    "publish",
    "delete",
    "private_data_export",
    "external_tool",
]

SUBDIRS = [
    "cards/agents",
    "cards/teams",
    "cards/plugins",
    "policies",
    "memory",
    "ledgers",
    "cache",
]

JSONL_FILES = [
    "memory/feedback.jsonl",
    "memory/playbook-candidates.jsonl",
    "memory/memory-events.jsonl",
    "ledgers/routing-decisions.jsonl",
    "ledgers/executions.jsonl",
    "ledgers/capability-grants.jsonl",
    "cache/hub-search.jsonl",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def networking_home() -> Path:
    override = os.environ.get("AGENTLAS_NETWORKING_HOME")
    if override:
        return Path(override).expanduser()
    return Path(os.path.expanduser("~")) / ".agentlas" / "networking"


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with open(path, "a", encoding="utf-8") as handle:
        _lock(handle)
        try:
            handle.write(line + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            _unlock(handle)


def read_jsonl(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    if limit is not None:
        return records[-limit:]
    return records


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def default_config() -> dict[str, Any]:
    from ..plugin_discovery import hub_base_url

    return {
        "schemaVersion": SCHEMA_VERSION,
        "locales": ["ko", "en"],
        "hub_url": hub_base_url(),
        "telemetry": False,
        "created_at": utc_now(),
    }


def default_sources() -> dict[str, Any]:
    home = Path(os.path.expanduser("~"))
    codex_home = Path(os.environ.get("CODEX_HOME", str(home / ".codex")))
    candidates = [
        home / ".claude" / "plugins" / "cache",
        codex_home / "plugins" / "cache",
        home / ".gemini" / "extensions",
    ]
    return {
        "schemaVersion": SCHEMA_VERSION,
        "note": "Only explicitly registered paths are indexed. The home folder is never scanned.",
        "sources": [
            {"path": str(path), "kind": "package_tree", "added_by": "init", "added_at": utc_now()}
            for path in candidates
            if path.is_dir()
        ],
    }


def default_routing_policy() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "t_high": 4.5,
        "t_low": 3.0,
        "margin": 0.8,
        "min_ready_cards": 5,
        "max_hops": 2,
        "clarify_max_candidates": 3,
        # Semantic + domain-coherence routing signals (see networking/domains.py).
        # semantic_weight is kept below the route margin (0.8) so the offline
        # semantic recall enhancer can break ties but never overturns the lexical
        # route/clarify decision.
        "semantic_weight": 0.5,
        "domain_boost": 1.5,
        "domain_penalty": 6.0,
        # Router Agent cascade: when the deterministic router lands on
        # clarify/propose_new, attach an escalation directive so the host runtime
        # resolves the ambiguous request with an LLM reasoning pass (BYOC — the
        # engine never calls a model itself). Set False for pure deterministic.
        "router_llm_escalation": True,
    }


def default_capability_policy() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "high_risk": list(HIGH_RISK_CAPABILITIES),
        "auto_run_requires": "routing_ready_or_trusted_card_and_no_pending_approvals",
    }


def default_approval_policy() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "default_grant_scope": "per_call",
        "hub_first_use": "ask",
        "grant_scopes": ["per_call", "session", "project", "global"],
    }


def default_routing_profile() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "boosts": {},
        "suppressions": {},
        "corrections": [],
        "note": "User-local preference signal only. Never promotes a card's routing_status.",
    }


def default_memory_map() -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "layers": [
            {
                "scope": "user_global",
                "path": "~/.agentlas/networking/memory/",
                "owner": "network-router",
                "content": "structured routing summaries, preferences, corrections only",
                "forbidden": ["raw prompts", "secrets", "file contents", "transcripts"],
            },
            {
                "scope": "project",
                "path": "<project>/.agentlas/",
                "owner": "project PM Soul / Memory Curator",
                "content": "existing project-local memory architecture (extended, not replaced)",
            },
            {
                "scope": "session",
                "path": "(runtime session only)",
                "owner": "runtime",
                "content": "working context, discarded after the session",
            },
        ],
        "export_policy": "Local memory never leaves this machine without explicit per-export user approval.",
    }


def _default_playbook_registry() -> dict[str, Any]:
    from .playbooks import default_playbook_registry

    return default_playbook_registry()


def init_networking(home: Path | str | None = None) -> dict[str, Any]:
    base = Path(home) if home else networking_home()
    base.mkdir(parents=True, exist_ok=True)
    lock_path = base / ".init.lock"
    with open(lock_path, "w", encoding="utf-8") as lock:
        _lock(lock)
        try:
            created: list[str] = []
            existing: list[str] = []
            for sub in SUBDIRS:
                (base / sub).mkdir(parents=True, exist_ok=True)
            defaults: dict[str, Any] = {
                "config.json": default_config(),
                "sources.json": default_sources(),
                "policies/routing-policy.json": default_routing_policy(),
                "policies/capability-policy.json": default_capability_policy(),
                "policies/approval-policy.json": default_approval_policy(),
                "memory/routing-profile.json": default_routing_profile(),
                "memory/hierarchical-memory-map.json": default_memory_map(),
                "memory/playbook-registry.json": _default_playbook_registry(),
                "cache/plugin-index.json": {"schemaVersion": SCHEMA_VERSION, "plugins": []},
            }
            for rel, payload in defaults.items():
                target = base / rel
                if target.exists():
                    existing.append(rel)
                else:
                    atomic_write_json(target, payload)
                    created.append(rel)
            for rel in JSONL_FILES:
                target = base / rel
                if target.exists():
                    existing.append(rel)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.touch()
                    created.append(rel)
            version_file = base / "VERSION"
            migrated_from = None
            if version_file.exists():
                previous = version_file.read_text(encoding="utf-8").strip()
                if previous != SCHEMA_VERSION:
                    migrated_from = previous
                    version_file.write_text(SCHEMA_VERSION + "\n", encoding="utf-8")
            else:
                version_file.write_text(SCHEMA_VERSION + "\n", encoding="utf-8")
                created.append("VERSION")
            return {
                "home": str(base),
                "schema_version": SCHEMA_VERSION,
                "created": created,
                "existing": existing,
                "migrated_from": migrated_from,
            }
        finally:
            _unlock(lock)


def _forbidden_source(path: Path) -> str | None:
    resolved = path.resolve()
    home = Path(os.path.expanduser("~")).resolve()
    if resolved == home:
        return "refusing to register the home directory itself; register specific package folders instead"
    if resolved == Path("/"):
        return "refusing to register the filesystem root"
    return None


def add_source(path: Path | str, home: Path | str | None = None, kind: str = "package_tree") -> dict[str, Any]:
    base = Path(home) if home else networking_home()
    init_networking(base)
    source_path = Path(path).expanduser().resolve()
    reason = _forbidden_source(source_path)
    if reason:
        return {"status": "rejected", "reason": reason, "path": str(source_path)}
    if not source_path.is_dir():
        return {"status": "rejected", "reason": "path does not exist or is not a directory", "path": str(source_path)}
    sources_file = base / "sources.json"
    payload = read_json(sources_file, default={"schemaVersion": SCHEMA_VERSION, "sources": []})
    entries = payload.get("sources") or []
    if any(entry.get("path") == str(source_path) for entry in entries):
        return {"status": "exists", "path": str(source_path), "count": len(entries)}
    entries.append({"path": str(source_path), "kind": kind, "added_by": "user", "added_at": utc_now()})
    payload["sources"] = entries
    atomic_write_json(sources_file, payload)
    return {"status": "added", "path": str(source_path), "count": len(entries)}


def remove_source(path: Path | str, home: Path | str | None = None) -> dict[str, Any]:
    base = Path(home) if home else networking_home()
    sources_file = base / "sources.json"
    payload = read_json(sources_file, default={"schemaVersion": SCHEMA_VERSION, "sources": []})
    target = str(Path(path).expanduser().resolve())
    entries = payload.get("sources") or []
    remaining = [entry for entry in entries if entry.get("path") != target]
    payload["sources"] = remaining
    atomic_write_json(sources_file, payload)
    return {"status": "removed" if len(remaining) != len(entries) else "not_found", "path": target, "count": len(remaining)}


def network_status(home: Path | str | None = None) -> dict[str, Any]:
    from .card_lint import effective_status
    from .card_store import load_global_cards

    base = Path(home) if home else networking_home()
    if not (base / "VERSION").exists():
        return {"home": str(base), "initialized": False}
    cards, quarantined = load_global_cards(base)
    counts: dict[str, int] = {}
    for card in cards:
        status = effective_status(card)
        counts[status] = counts.get(status, 0) + 1
    counts["quarantined"] = counts.get("quarantined", 0) + len(quarantined)
    policy = read_json(base / "policies" / "routing-policy.json", default=default_routing_policy())
    bench_status = read_json(base / "cache" / "bench-status.json", default=None)
    ready = counts.get("routing_ready", 0) + counts.get("trusted", 0)
    bench_passed = bool(bench_status and bench_status.get("passed"))
    auto_routing_enabled = ready >= int(policy.get("min_ready_cards", 5)) and bench_passed
    return {
        "home": str(base),
        "initialized": True,
        "schema_version": (base / "VERSION").read_text(encoding="utf-8").strip(),
        "card_counts": counts,
        "ready_cards": ready,
        "benchmark": bench_status or {"passed": False, "note": "benchmark has not been run"},
        "auto_routing_enabled": auto_routing_enabled,
        "auto_routing_note": None
        if auto_routing_enabled
        else f"auto routing requires >= {policy.get('min_ready_cards', 5)} routing_ready cards and a passing benchmark",
        "sources": read_json(base / "sources.json", default={}).get("sources", []),
    }
