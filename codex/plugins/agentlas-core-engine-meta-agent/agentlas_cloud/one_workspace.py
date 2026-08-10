"""Agentlas One personal-agent workspace seed and emission choke point.

One uses the same memory layers as a single agent, requires hooks, and keeps
raw memory separate from sealed Experience DTOs. Existing host hooks were
collection-only, while other agents already owned ticket, curator, invocation,
notes, vault-reference, and Experience stores.

Raw tickets, curator decisions, and soul memory stay under
``<root>/.agentlas/``. ``<root>/experience/`` accepts sealed, secret-free DTOs
only and must never contain raw memory.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

CONTRACT_VERSION = "1.0.0"
SCHEMA_VERSION = "agentlas.one-workspace.v1"

# Canonical .agentlas workspace layer.
META_DIR = ".agentlas"
AGENT_CARD_FILE = "agent-card.json"
ROUTING_CARD_FILE = "routing-card.json"
MEMORY_MAP_FILE = "memory-map.json"
MEMORY_TICKETS_FILE = "memory-tickets.jsonl"
CURATOR_DECISIONS_FILE = "curator-decisions.jsonl"
PROJECT_SOUL_FILE = "project-soul-memory.md"
INVOCATION_LEDGER_FILE = "invocation-ledger.jsonl"
VAULT_REFERENCES_FILE = "vault-references.json"
WORK_BRIEF_FILE = "work-brief.json"
EXPERIENCE_DB_FILE = "experience.sqlite"
EVOLUTION_LOG_FILE = "self-evolution.jsonl"

# Required hooks layer.
HOOKS_DIR = "hooks"
MEMORY_UPGRADE_HOOK = "memory-upgrade.yaml"
ON_STOP_HOOK = "on_stop.yaml"

# Sealed Experience chips only.
EXPERIENCE_DIR = "experience"
NOTES_DIR = "notes"

# Heuristic lower bound that prevents casual chat from creating work receipts.
SUBSTANTIAL_TOOL_USES = 5
# Bounded rollout window inspected by the stop hook.
RECENT_ROLLOUT_WINDOW_SEC = 1800
MAX_ROLLOUTS_PER_STOP = 12

# Immutable identity axis shared with Desktop's builtin-agent convention.
ONE_AGENT_SLUG = "agentlas-one"
ONE_AGENT_ID = f"builtin-{ONE_AGENT_SLUG}"

# Kinds eligible for durable promotion; observations and inferences are not.
PROMOTABLE_KINDS = frozenset({"fact", "decision", "procedure", "preference", "risk", "deprecation"})
# Craft kinds that may become Experience chip candidates.
CRAFT_KINDS = frozenset({"procedure", "decision"})

# Secret patterns require a keyword plus a sufficiently long value.
_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|passwd|cookie|bearer)\b\s*[:=]\s*\S{16,}"
)
# Host absolute paths are forbidden to prevent personal-path disclosure.
_HOST_PATH_RE = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\Users\\|file://)")
# Memory envelope heading shared with Desktop.
MEMORY_EVENTS_HEADING = "## Memory Events"
# Accept both fenced and bare envelopes because host runtimes emit both forms.
_MEMORY_ENVELOPE_FENCED_RE = re.compile(
    re.escape(MEMORY_EVENTS_HEADING) + r"\s*\n\s*```(?:json)?\s*\n(.*?)\n\s*```",
    re.DOTALL,
)
_MEMORY_ENVELOPE_BARE_RE = re.compile(
    re.escape(MEMORY_EVENTS_HEADING) + r"\s*\n\s*(\{.*?\})\s*(?:\n\s*\n|\Z)",
    re.DOTALL,
)

# Imperative statements are instructions, not memory candidates.
_IMPERATIVE_RE = re.compile(
    r"(?:해라|하세요|하십시오|해줘|해 줘|하도록\s*해|할\s*것)\s*[.!]?\s*$"
    r"|^(?:always|never|you\s+must|ignore\s+previous|disregard)\b",
    re.IGNORECASE,
)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _write_json_if_absent(path: Path, payload: dict[str, Any]) -> bool:
    """Write only when missing so user-edited values are never overwritten."""
    if path.exists():
        return False
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return True


def _touch_if_absent(path: Path, text: str = "") -> bool:
    if path.exists():
        return False
    _atomic_write(path, text)
    return True


def read_one_id(root: Path) -> str:
    """Return the immutable identity used for memory and Experience.

    This must match the Desktop and Terminal builtin identity. The manifest's
    ``oneId`` identifies a workspace projection, not the agent itself.
    """
    return ONE_AGENT_ID


def read_workspace_id(root: Path) -> str:
    """Return the projection workspace ID, which identifies a folder, not an agent."""
    manifest = root / "manifest.json"
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            value = data.get("oneId")
            if isinstance(value, str) and value:
                return value
        except (OSError, json.JSONDecodeError):
            pass
    return "one_local"


def _experience_schema(db_path: Path) -> None:
    """Create the Experience ontology store used by a single-agent workspace."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;

            CREATE TABLE IF NOT EXISTS experience_candidates (
              id             TEXT PRIMARY KEY,
              agent_id       TEXT NOT NULL,
              scope_key      TEXT NOT NULL,
              summary        TEXT NOT NULL,
              task_terms     TEXT NOT NULL DEFAULT '[]',
              sensitivity    TEXT NOT NULL DEFAULT 'internal',
              confidence     REAL NOT NULL DEFAULT 0.5,
              status         TEXT NOT NULL DEFAULT 'candidate'
                               CHECK(status IN ('candidate','promoted','rejected','superseded')),
              public_safe    INTEGER NOT NULL DEFAULT 0,
              source_ticket  TEXT,
              created_at     TEXT NOT NULL,
              updated_at     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS experience_packs (
              id             TEXT PRIMARY KEY,
              agent_id       TEXT NOT NULL,
              name           TEXT NOT NULL,
              description    TEXT NOT NULL DEFAULT '',
              scope_key      TEXT NOT NULL,
              status         TEXT NOT NULL DEFAULT 'draft'
                               CHECK(status IN ('draft','active','retired')),
              created_at     TEXT NOT NULL,
              updated_at     TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS experience_promotion_receipts (
              id             TEXT PRIMARY KEY,
              candidate_id   TEXT NOT NULL,
              decision       TEXT NOT NULL CHECK(decision IN ('admit','reject','defer')),
              reason         TEXT NOT NULL DEFAULT '',
              evidence       TEXT NOT NULL DEFAULT '[]',
              created_at     TEXT NOT NULL,
              FOREIGN KEY(candidate_id) REFERENCES experience_candidates(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_exp_cand_agent  ON experience_candidates(agent_id, status);
            CREATE INDEX IF NOT EXISTS idx_exp_cand_scope  ON experience_candidates(scope_key, status);
            CREATE INDEX IF NOT EXISTS idx_exp_pack_agent  ON experience_packs(agent_id, status);
            """
        )
        # Add the column idempotently for stores created before pack binding.
        existing = {row[1] for row in conn.execute("PRAGMA table_info(experience_candidates)")}
        if "pack_id" not in existing:
            conn.execute("ALTER TABLE experience_candidates ADD COLUMN pack_id TEXT")
        conn.commit()
    finally:
        conn.close()


def seed(root: Path, name: str = "One") -> dict[str, Any]:
    """Seed One as a single-agent workspace; repeated runs are idempotent."""
    root = Path(root).expanduser()
    one_id = read_one_id(root)
    meta = root / META_DIR
    created: list[str] = []

    def mark(path: Path, made: bool) -> None:
        if made:
            created.append(str(path.relative_to(root)))

    for directory in (
        meta,
        root / EXPERIENCE_DIR,
        root / HOOKS_DIR,
        root / "skills",
        root / "knowledge",
        root / "tools",
        meta / NOTES_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    # --- Identity -----------------------------------------------------------
    mark(meta / AGENT_CARD_FILE, _write_json_if_absent(meta / AGENT_CARD_FILE, {
        "contractVersion": CONTRACT_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "agentId": one_id,
        "kind": "personal-single-agent",
        "name": name,
        "uploadable": False,
        "note": "Private personal agent. Hub and Cloud uploads are disabled.",
        "createdAt": _now(),
    }))

    mark(meta / ROUTING_CARD_FILE, _write_json_if_absent(meta / ROUTING_CARD_FILE, {
        "contractVersion": CONTRACT_VERSION,
        "agentId": one_id,
        "exposure": "local-only",
        "note": "Local routing only. This non-uploadable agent is not visible in Hub search.",
    }))

    # --- Memory ownership map ----------------------------------------------
    mark(meta / MEMORY_MAP_FILE, _write_json_if_absent(meta / MEMORY_MAP_FILE, {
        "contractVersion": CONTRACT_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "agentId": one_id,
        "canonicalMemoryRoots": {
            "raw": f"{META_DIR}/",
            "sealedChips": f"{EXPERIENCE_DIR}/",
        },
        "writeOwners": {
            "durable": "agentlas-memory-curator",
            "tickets": "runtime",
            "soul": "agentlas-pm-soul",
        },
        "promotionPath": [
            "observation", "memory-event", "memory-ticket",
            "curator", "policy-gate", "durable",
        ],
        "trustLabels": ["verified", "memory_derived", "inferred", "stale_check_needed"],
        "runtimeOwned": [MEMORY_TICKETS_FILE, CURATOR_DECISIONS_FILE, INVOCATION_LEDGER_FILE],
        "neverUpload": [
            MEMORY_TICKETS_FILE, CURATOR_DECISIONS_FILE, PROJECT_SOUL_FILE,
            INVOCATION_LEDGER_FILE, VAULT_REFERENCES_FILE, EXPERIENCE_DB_FILE,
        ],
    }))

    # --- Raw memory ledgers -------------------------------------------------
    mark(meta / MEMORY_TICKETS_FILE, _touch_if_absent(meta / MEMORY_TICKETS_FILE))
    mark(meta / CURATOR_DECISIONS_FILE, _touch_if_absent(meta / CURATOR_DECISIONS_FILE))
    mark(meta / INVOCATION_LEDGER_FILE, _touch_if_absent(meta / INVOCATION_LEDGER_FILE))
    mark(meta / EVOLUTION_LOG_FILE, _touch_if_absent(meta / EVOLUTION_LOG_FILE))

    mark(meta / PROJECT_SOUL_FILE, _touch_if_absent(meta / PROJECT_SOUL_FILE, (
        f"# {name} — Soul Memory\n\n"
        "Owned by PM Soul. Keep intent, decisions, open loops, and acceptance criteria; never raw transcripts.\n\n"
        "## Intent\n\n## Decisions\n\n## Open Loops\n\n## Acceptance Criteria\n"
    )))

    mark(meta / VAULT_REFERENCES_FILE, _write_json_if_absent(meta / VAULT_REFERENCES_FILE, {
        "contractVersion": CONTRACT_VERSION,
        "references": [],
        "note": "Never store credential values. Store reference names only.",
    }))

    mark(meta / WORK_BRIEF_FILE, _write_json_if_absent(meta / WORK_BRIEF_FILE, {
        "contractVersion": CONTRACT_VERSION,
        "agentId": one_id,
        "goals": [],
        "constraints": [],
        "note": "Goals and constraints derived from the build interview.",
    }))

    # --- Experience ontology store -----------------------------------------
    exp_db = meta / EXPERIENCE_DB_FILE
    existed = exp_db.exists()
    _experience_schema(exp_db)
    mark(exp_db, not existed)

    _touch_if_absent(root / EXPERIENCE_DIR / "README.md", (
        "# Sealed Chips Only\n\n"
        "Store only experience ontology chips and playbooks that pass Secret-Free DTO validation.\n"
        "Raw memory, including memory tickets, is forbidden here; keep it under `.agentlas/`.\n"
    ))

    # --- Hooks --------------------------------------------------------------
    mark(root / HOOKS_DIR / MEMORY_UPGRADE_HOOK, _touch_if_absent(
        root / HOOKS_DIR / MEMORY_UPGRADE_HOOK,
        "# Memory-ticket and experience-chip evolution enforcement\n"
        f"schemaVersion: {SCHEMA_VERSION}\n"
        "when:\n"
        "  - event: turn_end\n"
        "    require: memory_events_scanned\n"
        "  - event: session_stop\n"
        "    require: ticket_or_reason\n"
        "rules:\n"
        "  # Never write durable memory directly. Use ticket -> curator -> policy gate.\n"
        "  - id: no-direct-durable-write\n"
        "    enforce: deny\n"
        "  # Downgrade unsupported facts, decisions, and procedures to hypotheses.\n"
        "  - id: evidence-required\n"
        "    kinds: [fact, decision, procedure]\n"
        "    on_missing_evidence: downgrade_to_hypothesis\n"
        "  # A component may not promote content it harvested itself.\n"
        "  - id: no-self-confirmation\n"
        "    enforce: deny\n"
    ))

    mark(root / HOOKS_DIR / ON_STOP_HOOK, _touch_if_absent(
        root / HOOKS_DIR / ON_STOP_HOOK,
        "# Session completion cleanup and reporting hook\n"
        f"schemaVersion: {SCHEMA_VERSION}\n"
        "when:\n"
        "  - event: session_stop\n"
        "action:\n"
        "  # Preserve results: record a missing capsule instead of forcing one.\n"
        "  - record_session_receipt\n"
        "  - if_substantial_and_no_capsule: record_gap\n"
        "never:\n"
        "  - block_the_session\n"
        "  - write_durable_without_curator\n"
    ))

    # --- Tool requirements -------------------------------------------------
    _touch_if_absent(root / "tools" / "requirements.yaml", (
        "# Tool and MCP requirements for the runtime\n"
        f"schemaVersion: {SCHEMA_VERSION}\n"
        "required: []\n"
        "optional: []\n"
    ))

    return {
        "root": str(root),
        "agentId": one_id,
        "created": created,
        "alreadyPresent": len(created) == 0,
    }


def _existing_ticket_hashes(meta: Path) -> set[str]:
    """Hash existing ticket content so re-reading a transcript stays idempotent."""
    return {
        _content_hash(str((row.get("candidate") or {}).get("content") or ""))
        for row in _read_jsonl(meta / MEMORY_TICKETS_FILE)
    }


def emit_ticket(
    root: Path,
    *,
    content: str,
    kind: str = "fact",
    scope: str = "agent_repo",
    evidence: list[str] | None = None,
    turn_key: str = "",
    source: str = "host-session",
) -> dict[str, Any]:
    """Emit a memory ticket without writing durable memory directly."""
    root = Path(root).expanduser()
    meta = root / META_DIR
    meta.mkdir(parents=True, exist_ok=True)
    one_id = read_one_id(root)
    evidence = evidence or []

    # Downgrade unsupported facts, decisions, and procedures to hypotheses.
    downgraded = False
    if kind in ("fact", "decision", "procedure") and not evidence:
        kind = "hypothesis"
        downgraded = True

    ticket = {
        "schemaVersion": SCHEMA_VERSION,
        "ticketId": f"one-tkt-{int(time.time() * 1000)}",
        "agentId": one_id,
        "turnKey": turn_key,
        "source": source,
        "state": "queued",
        "candidate": {
            "type": kind,
            "scope": scope,
            "content": content.strip()[:600],
            "evidence": evidence[:8],
        },
        "downgraded": downgraded,
        "createdAt": _now(),
    }
    with (meta / MEMORY_TICKETS_FILE).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(ticket, ensure_ascii=False) + "\n")
    return ticket


def record_session_receipt(
    root: Path,
    *,
    substantial: bool,
    capsule_written: bool,
    workspace: str = "",
    detail: str = "",
) -> dict[str, Any]:
    """Write a session receipt and record explicitly when no capsule was used."""
    root = Path(root).expanduser()
    meta = root / META_DIR
    meta.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schemaVersion": SCHEMA_VERSION,
        "agentId": read_one_id(root),
        "event": "session_stop",
        "workspace": os.path.basename(workspace.rstrip("/")) if workspace else "",
        "substantial": bool(substantial),
        "capsuleWritten": bool(capsule_written),
        "gap": bool(substantial and not capsule_written),
        "detail": detail[:300],
        "createdAt": _now(),
    }
    with (meta / INVOCATION_LEDGER_FILE).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, ensure_ascii=False) + "\n")
    return receipt


def _scan_transcript(path: str) -> tuple[int, int]:
    """Count tool and edit calls without reading transcript content."""
    tool_uses = edits = 0
    editors = {"Edit", "Write", "MultiEdit", "NotebookEdit", "apply_patch"}
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if '"tool_use"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                content = ((row.get("message") or {}).get("content")) or []
                if not isinstance(content, list):
                    continue
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_uses += 1
                        if block.get("name") in editors:
                            edits += 1
    except OSError:
        return (0, 0)
    return (tool_uses, edits)


def _assistant_texts_in(node: Any, out: list[str]) -> None:
    """Collect assistant text from one transcript record.

    Runtime envelopes differ: Claude Code uses ``message.role`` while Codex
    uses ``payload.role``. Find assistant nodes without assuming one envelope,
    and exclude user prompts and tool output.
    """
    if isinstance(node, dict):
        # The three measured runtimes identify assistant output differently:
        #   · Claude Code / Codex : role == "assistant"
        #   - Antigravity: no role; source == "MODEL" (for example, PLANNER_RESPONSE)
        is_assistant = node.get("role") == "assistant" or node.get("source") == "MODEL"
        if is_assistant:
            content = node.get("content")
            if isinstance(content, str):
                out.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and isinstance(block.get("text"), str):
                        out.append(block["text"])
            return
        for value in node.values():
            _assistant_texts_in(value, out)
    elif isinstance(node, list):
        for value in node:
            _assistant_texts_in(value, out)


def _iter_assistant_text(path: str):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if MEMORY_EVENTS_HEADING not in line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                found: list[str] = []
                _assistant_texts_in(row, found)
                for text in found:
                    yield text
    except OSError:
        return


def harvest_memory_events(transcript: str) -> list[dict[str, Any]]:
    """Turn worker ``## Memory Events`` envelopes into runtime tickets.

    Extract only candidate arrays from transcript envelopes. Never retain raw
    prompts or transcripts.
    """
    if not transcript:
        return []
    return harvest_memory_events_from_texts(_iter_assistant_text(transcript))


def harvest_memory_events_from_texts(texts: Any) -> list[dict[str, Any]]:
    """Harvest envelopes from assistant text a host supplies directly.

    Not every runtime hands a Stop hook a transcript path. OpenCode plugins
    receive the assistant text in process, so accept text as well as a file and
    keep one parser for both. Callers must pass assistant output only.
    """
    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for text in texts or []:
        if not isinstance(text, str):
            continue
        matches = list(_MEMORY_ENVELOPE_FENCED_RE.finditer(text))
        if not matches:
            matches = list(_MEMORY_ENVELOPE_BARE_RE.finditer(text))
        for match in matches:
            try:
                envelope = json.loads(match.group(1))
            except json.JSONDecodeError:
                continue
            if not isinstance(envelope, dict):
                continue
            for candidate in envelope.get("candidates") or []:
                if not isinstance(candidate, dict):
                    continue
                content = str(candidate.get("content") or "").strip()
                if not content:
                    continue
                key = _content_hash(content)
                if key in seen:
                    continue
                seen.add(key)
                evidence = candidate.get("evidence")
                found.append({
                    "content": content,
                    "kind": str(candidate.get("memory_kind") or "hypothesis"),
                    "scope": str(candidate.get("suggested_scope") or "agent_repo"),
                    "evidence": [str(item) for item in evidence][:8] if isinstance(evidence, list) else [],
                })
    return found


def resolve_transcript(payload: dict[str, Any], host: str = "") -> str:
    """Resolve a transcript using the host payload or its measured storage convention.

    Claude Code supplies ``transcript_path`` in its Stop payload. Codex does
    not; it stores rollouts under ``~/.codex/sessions/<Y>/<M>/<D>``. Return an
    empty path rather than guessing and reading an unrelated file.
    """
    direct = str(payload.get("transcript_path") or payload.get("rollout_path") or "")
    if direct and os.path.exists(direct):
        return direct

    paths = resolve_transcripts(payload, host)
    return paths[0] if paths else ""


def _goose_transcripts(payload: dict[str, Any]) -> list[str]:
    """Resolve a goose session file from its SessionEnd payload.

    goose reports ``session_id`` and ``working_dir`` but no transcript path, so
    prefer the file named after the session and fall back to the recent window.
    The layout is read at runtime rather than assumed: when nothing matches, the
    checkpoint harvests nothing instead of guessing.
    """
    base = Path(os.path.expanduser("~/.local/share/goose/sessions"))
    if not base.is_dir():
        return []
    session_id = str(payload.get("session_id") or payload.get("sessionId") or "").strip()
    if session_id:
        for suffix in (".jsonl", ".json"):
            candidate = base / f"{session_id}{suffix}"
            if candidate.is_file():
                return [str(candidate)]
    cutoff = time.time() - RECENT_ROLLOUT_WINDOW_SEC
    found: list[tuple[float, str]] = []
    for candidate in base.glob("*.jsonl"):
        try:
            mtime = candidate.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            found.append((mtime, str(candidate)))
    found.sort(reverse=True)
    return [path for _mtime, path in found[:MAX_ROLLOUTS_PER_STOP]]


def resolve_transcripts(payload: dict[str, Any], host: str = "") -> list[str]:
    """Resolve every transcript eligible for memory-event harvesting.

    Codex supplies neither a session id nor transcript path in the Stop payload.
    Scanning only the newest rollout can select another actively appended session,
    so inspect every rollout modified inside the bounded recent window. Content
    hashes make repeated reads idempotent.
    """
    # Host keys differ: Claude Code uses snake_case while Antigravity uses camelCase.
    direct = ""
    for key in ("transcript_path", "transcriptPath", "rollout_path", "rolloutPath"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            direct = value
            break
    if direct and os.path.exists(direct):
        return [direct]

    host = (host or str(payload.get("host") or "")).lower()
    if host == "goose":
        return _goose_transcripts(payload)
    if host != "codex":
        return []

    base = Path(os.path.expanduser("~/.codex/sessions"))
    if not base.is_dir():
        return []
    cutoff = time.time() - RECENT_ROLLOUT_WINDOW_SEC
    found: list[tuple[float, str]] = []
    # Limit scanning to today and yesterday to stay within the Stop-hook budget.
    for day_offset in (0, 86400):
        day_dir = base / time.strftime("%Y/%m/%d", time.localtime(time.time() - day_offset))
        if not day_dir.is_dir():
            continue
        for candidate in day_dir.glob("rollout-*.jsonl"):
            try:
                mtime = candidate.stat().st_mtime
            except OSError:
                continue
            if mtime >= cutoff:
                found.append((mtime, str(candidate)))
    found.sort(reverse=True)
    return [path for _mtime, path in found[:MAX_ROLLOUTS_PER_STOP]]


def _session_started_at(transcript: str) -> float:
    """Return the session start time without mistaking append time for creation time.

    ``st_ctime`` changes on every transcript append. On macOS/BSD,
    ``st_birthtime`` is the actual creation time. Return zero when unavailable
    so the caller avoids manufacturing a false gap.
    """
    if not transcript:
        return 0.0
    try:
        stat = os.stat(transcript)
    except OSError:
        return 0.0
    birth = getattr(stat, "st_birthtime", 0.0) or 0.0
    return float(birth)


def _capsule_written_since(workspace: str, since_epoch: float) -> bool:
    """Check whether the canonical learning directory received a session capsule."""
    if not workspace:
        return False
    learnings = Path(workspace) / ".agentlas" / "pm" / "learnings"
    if not learnings.is_dir():
        return False
    try:
        return any(
            entry.is_file() and entry.stat().st_mtime >= since_epoch
            for entry in learnings.glob("*.md")
        )
    except OSError:
        return False


def stop_hook(root: Path, payload: dict[str, Any], host: str = "") -> dict[str, Any]:
    """Run the non-blocking session-end checkpoint.

    Preserve results by recording a missing capsule instead of forcing one.
    """
    root = Path(root).expanduser()
    if not (root / "state.json").exists():
        return {"skipped": "one_off"}

    workspace = str(payload.get("cwd") or payload.get("workspace") or "")
    transcripts = resolve_transcripts(payload, host)
    transcript = transcripts[0] if transcripts else ""
    started = _session_started_at(transcript)

    # The runtime turns worker `## Memory Events` envelopes into tickets.
    harvested = 0
    already = _existing_ticket_hashes(root / META_DIR)
    events: list[dict[str, Any]] = []
    for path in transcripts:
        events.extend(harvest_memory_events(path))
    # Hosts without a transcript path (OpenCode) supply assistant text instead.
    supplied = payload.get("assistant_texts") or payload.get("assistantTexts")
    if isinstance(supplied, str):
        supplied = [supplied]
    if isinstance(supplied, list):
        events.extend(harvest_memory_events_from_texts(supplied))
    for event in events:
        key = _content_hash(event["content"])
        if key in already:
            continue
        already.add(key)
        emit_ticket(
            root,
            content=event["content"],
            kind=event["kind"],
            scope=event["scope"],
            evidence=event["evidence"],
            source="memory-events",
        )
        harvested += 1

    tool_uses, edits = _scan_transcript(transcript) if transcript else (0, 0)
    # Record receipts only for edits or sufficiently tool-heavy work, not casual chat.
    substantial = edits > 0 or tool_uses >= SUBSTANTIAL_TOOL_USES
    capsule = _capsule_written_since(workspace, started)

    if not substantial and harvested == 0:
        return {"skipped": "not_substantial", "toolUses": tool_uses, "edits": edits}

    receipt = record_session_receipt(
        root,
        substantial=bool(substantial),
        capsule_written=capsule,
        workspace=workspace,
        detail=f"host={host or 'claude'} tool_uses={tool_uses} edits={edits} harvested={harvested}",
    )
    receipt["harvested"] = harvested
    if receipt["gap"]:
        emit_ticket(
            root,
            content=(
                f"The session performed substantial work ({edits} edits, {tool_uses} tool uses), "
                f"but wrote no learning capsule under .agentlas/pm/learnings/."
            ),
            kind="conflict",
            scope="agent_repo",
            evidence=[f"invocation-ledger:{receipt['createdAt']}"],
            source="on_stop",
        )
    # Curate once at session end so tickets do not accumulate indefinitely.
    # Curator failure must never block session completion.
    try:
        receipt["curated"] = curate(root)["decisions"]
    except Exception as exc:
        receipt["curated"] = {"error": str(exc)[:120]}
    return receipt


def _normalize(text: str) -> str:
    return " ".join(text.lower().split())


def _content_hash(text: str) -> str:
    return hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()[:16]


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _classify(candidate: dict[str, Any], durable_hashes: set[str]) -> tuple[str, str]:
    """Apply deterministic admission rules without an LLM; ordering is contractual."""
    content = str(candidate.get("content") or "")
    kind = str(candidate.get("type") or "")
    evidence = candidate.get("evidence") or []

    if _SECRET_RE.search(content):
        return ("reject", "policy-secret")
    if _HOST_PATH_RE.search(content):
        return ("reject", "host-absolute-path")
    if _IMPERATIVE_RE.search(content.strip()):
        return ("reject", "imperative-not-memory")
    if len(_normalize(content)) < 12:
        return ("reject", "too-short")
    if _content_hash(content) in durable_hashes:
        return ("deduped", "already-durable")
    if kind not in PROMOTABLE_KINDS:
        return ("defer", f"kind-not-promotable:{kind}")
    if not evidence:
        return ("defer", "evidence-required")
    return ("admit", "evidence-backed")


def _durable_hashes(soul_path: Path) -> set[str]:
    if not soul_path.exists():
        return set()
    return set(re.findall(r"<!--\s*h:([0-9a-f]{16})\s*-->", soul_path.read_text(encoding="utf-8")))


def _append_durable(soul_path: Path, candidate: dict[str, Any], ticket_id: str) -> None:
    """Persist durable memory as a human-readable Markdown capsule."""
    content = str(candidate.get("content") or "").strip()
    kind = str(candidate.get("type") or "fact")
    evidence = ", ".join(str(item) for item in (candidate.get("evidence") or [])[:4])
    block = (
        f"\n- **[{kind}]** {content}\n"
        f"  - Evidence: {evidence or 'none'}\n"
        f"  - Ticket: `{ticket_id}` · {_now()}  <!-- h:{_content_hash(content)} -->\n"
    )
    with soul_path.open("a", encoding="utf-8") as handle:
        handle.write(block)


def _ensure_pack(conn: sqlite3.Connection, scope_key: str) -> str:
    """Group chips by ``(agent_id, scope_key)`` to match Desktop experience packs.

    Do not invent topic clusters; scope is already deterministic.
    """
    pack_id = f"one-pack-{hashlib.sha256(scope_key.encode('utf-8')).hexdigest()[:12]}"
    row = conn.execute("SELECT 1 FROM experience_packs WHERE id = ?", (pack_id,)).fetchone()
    if row is None:
        now = _now()
        conn.execute(
            "INSERT INTO experience_packs"
            " (id, agent_id, name, description, scope_key, status, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (pack_id, ONE_AGENT_ID, f"One Experience · {scope_key}",
             "Approved know-how chips from the same scope", scope_key, "active", now, now),
        )
    else:
        conn.execute(
            "UPDATE experience_packs SET updated_at = ? WHERE id = ?", (_now(), pack_id)
        )
    return pack_id


def _make_experience_chip(db_path: Path, candidate: dict[str, Any], ticket_id: str) -> str | None:
    """Create an experience-chip candidate when procedural knowledge becomes durable.

    Do not auto-promote it; measured behavior shows automatic promotion is unsafe.
    """
    content = str(candidate.get("content") or "").strip()
    chip_id = f"one-chip-{_content_hash(content)}"
    terms = sorted({
        word for word in re.findall(r"[A-Za-z가-힣][A-Za-z0-9가-힣_.-]{2,}", content)
    })[:12]
    conn = sqlite3.connect(db_path)
    try:
        existing = conn.execute(
            "SELECT 1 FROM experience_candidates WHERE id = ?", (chip_id,)
        ).fetchone()
        if existing:
            return None
        now = _now()
        scope_key = str(candidate.get("scope") or "agent_repo")
        pack_id = _ensure_pack(conn, scope_key)
        conn.execute(
            "INSERT INTO experience_candidates"
            " (id, agent_id, scope_key, summary, task_terms, sensitivity, confidence,"
            "  status, public_safe, source_ticket, pack_id, created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (chip_id, ONE_AGENT_ID, scope_key,
             content[:400], json.dumps(terms, ensure_ascii=False), "internal", 0.5,
             "candidate", 0, ticket_id, pack_id, now, now),
        )
        conn.execute(
            "INSERT INTO experience_promotion_receipts"
            " (id, candidate_id, decision, reason, evidence, created_at) VALUES (?,?,?,?,?,?)",
            (f"{chip_id}-r{int(time.time() * 1000)}", chip_id, "defer",
             "Chip candidate created without automatic promotion",
             json.dumps(candidate.get("evidence") or [], ensure_ascii=False), now),
        )
        conn.commit()
        return chip_id
    finally:
        conn.close()


def curate(root: Path) -> dict[str, Any]:
    """Record ticket decisions and promote only admitted content.

    Keep the ticket ledger append-only. A decision marks a ticket as consumed,
    avoiding races caused by rewriting the ledger.
    """
    root = Path(root).expanduser()
    meta = root / META_DIR
    tickets_path = meta / MEMORY_TICKETS_FILE
    decisions_path = meta / CURATOR_DECISIONS_FILE
    soul_path = meta / PROJECT_SOUL_FILE
    exp_db = meta / EXPERIENCE_DB_FILE

    if not tickets_path.exists():
        return {"error": "not_seeded", "hint": "agentlas-one seed"}

    # Idempotently backfill chips created before packs existed.
    if exp_db.exists():
        conn = sqlite3.connect(exp_db)
        try:
            orphans = conn.execute(
                "SELECT id, scope_key FROM experience_candidates WHERE pack_id IS NULL"
            ).fetchall()
            for chip_id, scope_key in orphans:
                conn.execute(
                    "UPDATE experience_candidates SET pack_id = ?, updated_at = ? WHERE id = ?",
                    (_ensure_pack(conn, scope_key or "agent_repo"), _now(), chip_id),
                )
            conn.commit()
        finally:
            conn.close()

    decided = {
        str(row.get("ticketId"))
        for row in _read_jsonl(decisions_path)
        if row.get("ticketId")
    }
    durable = _durable_hashes(soul_path)

    counts = {"admit": 0, "reject": 0, "defer": 0, "deduped": 0}
    chips: list[str] = []
    pending = [row for row in _read_jsonl(tickets_path) if str(row.get("ticketId")) not in decided]

    with decisions_path.open("a", encoding="utf-8") as handle:
        for ticket in pending:
            candidate = ticket.get("candidate") or {}
            action, reason = _classify(candidate, durable)
            counts[action] = counts.get(action, 0) + 1

            chip_id = None
            if action == "admit":
                _append_durable(soul_path, candidate, str(ticket.get("ticketId")))
                durable.add(_content_hash(str(candidate.get("content") or "")))
                if str(candidate.get("type")) in CRAFT_KINDS and exp_db.exists():
                    chip_id = _make_experience_chip(exp_db, candidate, str(ticket.get("ticketId")))
                    if chip_id:
                        chips.append(chip_id)
                        # Chip creation is the observable self-evolution event.
                        with (meta / EVOLUTION_LOG_FILE).open("a", encoding="utf-8") as evo:
                            evo.write(json.dumps({
                                "schemaVersion": SCHEMA_VERSION,
                                "agentId": ONE_AGENT_ID,
                                "event": "experience_chip_created",
                                "chipId": chip_id,
                                "kind": candidate.get("type"),
                                "sourceTicket": ticket.get("ticketId"),
                                "autoPromoted": False,
                                "createdAt": _now(),
                            }, ensure_ascii=False) + "\n")

            handle.write(json.dumps({
                "schemaVersion": SCHEMA_VERSION,
                "ticketId": ticket.get("ticketId"),
                "agentId": ONE_AGENT_ID,
                "action": action,
                "reason": reason,
                "kind": candidate.get("type"),
                "experienceChip": chip_id,
                "curatorMode": "deterministic",
                "createdAt": _now(),
            }, ensure_ascii=False) + "\n")

    return {
        "pending": len(pending),
        "decisions": counts,
        "experienceChips": chips,
        "agentId": ONE_AGENT_ID,
    }


def status(root: Path) -> dict[str, Any]:
    """Measure the One workspace directly, reporting absence instead of inventing counts."""
    root = Path(root).expanduser()
    meta = root / META_DIR

    def lines(path: Path) -> int:
        if not path.exists():
            return -1
        with path.open(encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())

    exp_db = meta / EXPERIENCE_DB_FILE
    chips = packs = orphan_chips = -1
    if exp_db.exists():
        conn = sqlite3.connect(f"file:{exp_db}?mode=ro", uri=True)
        try:
            chips = conn.execute("SELECT COUNT(*) FROM experience_candidates").fetchone()[0]
            packs = conn.execute("SELECT COUNT(*) FROM experience_packs").fetchone()[0]
            orphan_chips = conn.execute(
                "SELECT COUNT(*) FROM experience_candidates WHERE pack_id IS NULL"
            ).fetchone()[0]
        except sqlite3.Error:
            pass
        finally:
            conn.close()

    return {
        "root": str(root),
        "agentId": read_one_id(root),
        "seeded": (meta / MEMORY_MAP_FILE).exists(),
        "tickets": lines(meta / MEMORY_TICKETS_FILE),
        "curatorDecisions": lines(meta / CURATOR_DECISIONS_FILE),
        "invocations": lines(meta / INVOCATION_LEDGER_FILE),
        "evolutionEvents": lines(meta / EVOLUTION_LOG_FILE),
        "experienceChips": chips,
        "experiencePacks": packs,
        "chipsWithoutPack": orphan_chips,
        "soulBytes": (meta / PROJECT_SOUL_FILE).stat().st_size if (meta / PROJECT_SOUL_FILE).exists() else -1,
    }


def _main(argv: list[str]) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="one_workspace")
    parser.add_argument("command", choices=["seed", "status", "emit", "receipt", "stop-hook", "curate"])
    parser.add_argument("--root", default=os.path.expanduser("~/.agentlas/one"))
    parser.add_argument("--name", default="One")
    parser.add_argument("--content", default="")
    parser.add_argument("--kind", default="fact")
    parser.add_argument("--scope", default="agent_repo")
    parser.add_argument("--evidence", action="append", default=[])
    parser.add_argument("--turn-key", default="")
    parser.add_argument("--workspace", default="")
    parser.add_argument("--substantial", action="store_true")
    parser.add_argument("--capsule-written", action="store_true")
    parser.add_argument("--detail", default="")
    parser.add_argument("--host", default="")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if args.command == "seed":
        out = seed(root, args.name)
    elif args.command == "status":
        out = status(root)
    elif args.command == "emit":
        if not args.content.strip():
            print("--content must not be empty", flush=True)
            return 2
        out = emit_ticket(
            root, content=args.content, kind=args.kind, scope=args.scope,
            evidence=args.evidence, turn_key=args.turn_key,
        )
    elif args.command == "curate":
        out = curate(root)
    elif args.command == "stop-hook":
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            payload = {}
        try:
            out = stop_hook(root, payload, args.host)
        except Exception as exc:  # The hook must never block the session.
            out = {"error": str(exc)[:200], "blocked": False}
        print(json.dumps({}))          # Keep Claude Code session flow unchanged.
        sys.stderr.write(json.dumps(out, ensure_ascii=False) + "\n")
        return 0
    else:
        out = record_session_receipt(
            root, substantial=args.substantial, capsule_written=args.capsule_written,
            workspace=args.workspace, detail=args.detail,
        )
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv[1:]))
