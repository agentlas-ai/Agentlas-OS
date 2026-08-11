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
import platform
import re
import sqlite3
import sys
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
ONE_STATE_OBSERVED_FILE = "one-state.json"

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

# ---------------------------------------------------------------- ruleset (G-clauses)
# Judgment values live in the canonical curator-ruleset.json (Agentlas-OS
# system-agents/), shared with the Desktop executor. Hard-coding a judgment
# value here is a defect; the embedded defaults below exist only so a broken
# install fails open with the same behaviour, and the loaded sha256 goes into
# every decision receipt so cross-surface drift shows up as data.

_RULESET_DEFAULTS: dict[str, Any] = {
    "patterns": {
        "secretKeyValue": {
            "regex": r"\b(api[_-]?key|secret|token|password|passwd|cookie|bearer)\b\s*[:=]\s*\S{16,}",
            "flags": "i",
        },
        "secretValueShapes": {
            "regex": r"\b(sk-(?:ant-)?[A-Za-z0-9_-]{20,}|gh[opsu]_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{35}|xox[baprs]-[A-Za-z0-9-]{10,})\b|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",
            "flags": "",
        },
        "hostAbsolutePath": {"regex": r"(?:/Users/|/home/|[A-Za-z]:\\Users\\|file://)", "flags": ""},
        "imperative": {
            "regex": r"(?:해라|하세요|하십시오|해줘|해 줘|하도록\s*해|할\s*것)\s*[.!]?\s*$|^(?:always|never|you\s+must|ignore\s+previous|disregard)\b",
            "flags": "i",
        },
    },
    "kinds": {
        "promotable": ["fact", "decision", "procedure", "preference", "risk", "deprecation"],
        "craft": ["procedure", "decision"],
        "evidenceRequired": ["fact", "decision", "procedure"],
        "evidenceMissingDowngradeTo": "hypothesis",
    },
    "limits": {"minContentChars": 12, "ticketContentMaxChars": 600, "evidenceMaxItems": 8},
    "concurrency": {
        "lockSuffix": ".lock",
        "lockStaleMs": 30000,
        "lockAttempts": 50,
        "lockRetryDelayMs": 20,
        "ticketIdPrefix": "one-tkt-",
    },
    "emitters": {
        "oneDrawerAllowed": ["one-stop-hook", "one-cli", "one-curator", "terminal-forward"],
        "legacyMissingFieldTolerated": True,
        "rejectReason": "unauthorized-emitter",
    },
}

_ruleset_cache: tuple[dict[str, Any], str] | None = None


def _ruleset_paths() -> list[Path]:
    override = os.environ.get("AGENTLAS_CURATOR_RULESET")
    paths = [Path(override)] if override else []
    here = Path(__file__).resolve().parent
    paths.append(here.parent / "system-agents" / "curator-ruleset.json")
    return paths


def load_ruleset() -> tuple[dict[str, Any], str]:
    """Return (ruleset, sha256-16). Falls back to embedded defaults ("embedded")."""
    global _ruleset_cache
    if _ruleset_cache is not None:
        return _ruleset_cache
    for path in _ruleset_paths():
        try:
            raw = path.read_bytes()
            data = json.loads(raw)
            if isinstance(data, dict) and isinstance(data.get("patterns"), dict):
                _ruleset_cache = (data, hashlib.sha256(raw).hexdigest()[:16])
                return _ruleset_cache
        except (OSError, ValueError):
            continue
    _ruleset_cache = (_RULESET_DEFAULTS, "embedded")
    return _ruleset_cache


def _rule(path: str, default: Any) -> Any:
    node: Any = load_ruleset()[0]
    for key in path.split("."):
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def _rule_re(name: str) -> "re.Pattern[str]":
    spec = _rule(f"patterns.{name}", {}) or {}
    fallback = _RULESET_DEFAULTS["patterns"][name]
    regex = spec.get("regex") or fallback["regex"]
    flags = re.IGNORECASE if "i" in str(spec.get("flags", fallback["flags"])) else 0
    return re.compile(regex, flags)


# Kinds eligible for durable promotion; observations and inferences are not.
PROMOTABLE_KINDS = frozenset({"fact", "decision", "procedure", "preference", "risk", "deprecation"})
# Craft kinds that may become Experience chip candidates.
CRAFT_KINDS = frozenset({"procedure", "decision"})

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

# Imperative/secret/host-path judgment regexes come from the ruleset (_rule_re).


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
              project_scope_key TEXT,
              environment_key   TEXT,
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

    # D9 — the product-shipped operations skill fills the empty skills/ slot.
    # MISSING-ONLY per file so a user's local edits are never overwritten;
    # existing installs receive it on their next seed (on/`agentlas-one seed`).
    ops_src = Path(__file__).resolve().parent.parent / "skills" / "agentlas-operations"
    ops_dst = root / "skills" / "agentlas-operations"
    if ops_src.is_dir():
        ops_dst.mkdir(parents=True, exist_ok=True)
        for source in sorted(ops_src.glob("*.md")):
            target = ops_dst / source.name
            if not target.exists():
                try:
                    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
                    mark(target, True)
                except OSError:
                    pass

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


def _slugify(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9가-힣._-]+", "-", value.strip()).strip("-._")
    return slug[:96]


def resolve_project_slug(workspace: str) -> str:
    """Context-based stable project slug (D4) — survives folder moves.

    Resolution order comes from the ruleset (slugResolution.order):
    activation.projectId > git remote > memory-map.projectId > folder name.
    Returns "" when there is no workspace; never invents a value.
    """
    if not workspace:
        return ""
    ws = Path(workspace).expanduser()
    agentlas = ws / ".agentlas"

    def from_activation() -> str:
        try:
            data = json.loads((agentlas / "activation.json").read_text(encoding="utf-8"))
            return str(data.get("projectId") or "")
        except (OSError, ValueError):
            return ""

    def from_git_remote() -> str:
        # Read .git/config directly — no subprocess from a session-end hook.
        try:
            config = (ws / ".git" / "config").read_text(encoding="utf-8")
        except OSError:
            return ""
        match = re.search(r"url\s*=\s*(\S+)", config)
        if not match:
            return ""
        tail = match.group(1).rstrip("/").split("/")[-1]
        return tail[:-4] if tail.endswith(".git") else tail

    def from_memory_map() -> str:
        try:
            data = json.loads((agentlas / "memory-map.json").read_text(encoding="utf-8"))
            return str(data.get("projectId") or "")
        except (OSError, ValueError):
            return ""

    resolvers = {
        "activation.projectId": from_activation,
        "gitRemote": from_git_remote,
        "memoryMap.projectId": from_memory_map,
        "folderName": lambda: ws.name,
    }
    for source in _rule("slugResolution.order",
                        ["activation.projectId", "gitRemote", "memoryMap.projectId", "folderName"]):
        value = _slugify(resolvers.get(source, lambda: "")())
        if value:
            return value
    return _slugify(ws.name)


class _LedgerLock:
    """G6 write lock — O_EXCL create with stale takeover.

    Values come from the ruleset; the scheme is the terminal's proven
    appendJsonlOnce contract promoted to a cross-surface rule. Failing to
    acquire returns False and the caller skips the write (never blocks a
    session, never appends without the dedupe check).
    """

    def __init__(self, target: Path):
        self.path = Path(str(target) + str(_rule("concurrency.lockSuffix", ".lock")))
        self.fd: int | None = None

    def __enter__(self) -> bool:
        stale_ms = int(_rule("concurrency.lockStaleMs", 30000))
        attempts = int(_rule("concurrency.lockAttempts", 50))
        delay = int(_rule("concurrency.lockRetryDelayMs", 20)) / 1000.0
        for _ in range(attempts):
            try:
                self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                return True
            except FileExistsError:
                try:
                    if (time.time() - self.path.stat().st_mtime) * 1000 > stale_ms:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                time.sleep(delay)
            except OSError:
                return False
        return False

    def __exit__(self, *exc: Any) -> None:
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.path.unlink(missing_ok=True)


def emit_ticket(
    root: Path,
    *,
    content: str,
    kind: str = "fact",
    scope: str = "agent_repo",
    evidence: list[str] | None = None,
    turn_key: str = "",
    source: str = "host-session",
    emitter: str = "one-cli",
    workspace: str = "",
    project_slug: str = "",
    supersedes: str = "",
) -> dict[str, Any] | None:
    """Emit a memory ticket without writing durable memory directly.

    G6: the append happens under the ledger lock with a content-hash dedupe,
    so duplicate hook channels, concurrent sessions, and manual reruns cannot
    produce duplicate tickets. The ticket id is the content hash — collisions
    are dedupes by definition, not accidents. Returns None when the content is
    already ticketed or the lock cannot be acquired (retry next turn).
    G7: every ticket names its emitter so the curator can refuse writers that
    are not One's own pipeline.
    """
    root = Path(root).expanduser()
    meta = root / META_DIR
    meta.mkdir(parents=True, exist_ok=True)
    one_id = read_one_id(root)
    evidence = evidence or []

    # Downgrade unsupported facts, decisions, and procedures to hypotheses.
    downgrade_kinds = set(_rule("kinds.evidenceRequired", ["fact", "decision", "procedure"]))
    downgraded = False
    if kind in downgrade_kinds and not evidence:
        kind = str(_rule("kinds.evidenceMissingDowngradeTo", "hypothesis"))
        downgraded = True

    body = content.strip()[: int(_rule("limits.ticketContentMaxChars", 600))]
    key = _content_hash(body)
    supersedes_arg = str(supersedes or "")
    ticket = {
        "schemaVersion": SCHEMA_VERSION,
        "ticketId": f"{_rule('concurrency.ticketIdPrefix', 'one-tkt-')}{key}",
        "agentId": one_id,
        "turnKey": turn_key,
        "source": source,
        "emitter": emitter,
        "workspace": os.path.basename(workspace.rstrip("/")) if workspace else "",
        "projectSlug": project_slug,
        "state": "queued",
        "candidate": {
            "type": kind,
            "scope": scope,
            "content": body,
            "evidence": evidence[: int(_rule("limits.evidenceMaxItems", 8))],
            **({"supersedes": supersedes_arg} if supersedes_arg else {}),
        },
        "downgraded": downgraded,
        "createdAt": _now(),
    }
    tickets_path = meta / MEMORY_TICKETS_FILE
    with _LedgerLock(tickets_path) as acquired:
        if not acquired:
            return None
        if key in _existing_ticket_hashes(meta):
            return None
        with tickets_path.open("a", encoding="utf-8") as handle:
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
                supersedes = str(candidate.get("supersedes") or "")
                found.append({
                    "content": content,
                    "kind": str(candidate.get("memory_kind") or "hypothesis"),
                    "scope": str(candidate.get("suggested_scope") or "agent_repo"),
                    "evidence": [str(item) for item in evidence][:8] if isinstance(evidence, list) else [],
                    # G4/G8 — a worker may explicitly name the durable block this
                    # replaces (its h:16hex). Anything else is ignored, never guessed.
                    "supersedes": supersedes if re.fullmatch(r"[0-9a-f]{16}", supersedes) else "",
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


def _record_state_transition(root: Path, enabled: bool) -> None:
    """Record ON/OFF transitions once, so quiet gaps stay attributable later.

    Consecutive stops in the same state write nothing — an unbounded ledger is
    the disease, not the cure. A missing drawer means One never seeded; skip
    rather than create folders for a disabled agent.
    """
    meta = root / META_DIR
    if not meta.is_dir():
        return
    observed = meta / ONE_STATE_OBSERVED_FILE
    prev: bool | None = None
    try:
        prev = bool(json.loads(observed.read_text(encoding="utf-8")).get("on"))
    except (OSError, ValueError):
        prev = None
    if prev is not None and prev == enabled:
        return
    try:
        with (meta / INVOCATION_LEDGER_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "schemaVersion": SCHEMA_VERSION,
                "agentId": ONE_AGENT_ID,
                "event": "one_state",
                "from": prev,
                "to": enabled,
                "createdAt": _now(),
            }, ensure_ascii=False) + "\n")
        _atomic_write(observed, json.dumps({"on": enabled, "updatedAt": _now()}) + "\n")
    except OSError:
        return


def stop_hook(root: Path, payload: dict[str, Any], host: str = "") -> dict[str, Any]:
    """Run the non-blocking session-end checkpoint.

    Preserve results by recording a missing capsule instead of forcing one.
    """
    root = Path(root).expanduser()
    enabled = (root / "state.json").exists()
    _record_state_transition(root, enabled)
    if not enabled:
        return {"skipped": "one_off"}
    # M-1 — first-touch self-migration of legacy workspaces (idempotent).
    try:
        migrate_one_workspace(root)
    except Exception:
        pass  # migration must never block a session; curate() retries it

    workspace = str(payload.get("cwd") or payload.get("workspace") or "")
    transcripts = resolve_transcripts(payload, host)
    transcript = transcripts[0] if transcripts else ""
    started = _session_started_at(transcript)

    # The runtime turns worker `## Memory Events` envelopes into tickets.
    # Dedupe now lives inside emit_ticket under the G6 ledger lock, so duplicate
    # hook channels and concurrent sessions converge on a single ticket.
    harvested = 0
    events: list[dict[str, Any]] = []
    for path in transcripts:
        events.extend(harvest_memory_events(path))
    # Hosts without a transcript path (OpenCode) supply assistant text instead.
    supplied = payload.get("assistant_texts") or payload.get("assistantTexts")
    if isinstance(supplied, str):
        supplied = [supplied]
    if isinstance(supplied, list):
        events.extend(harvest_memory_events_from_texts(supplied))
    project_slug = resolve_project_slug(workspace)
    for event in events:
        if emit_ticket(
            root,
            content=event["content"],
            kind=event["kind"],
            scope=event["scope"],
            evidence=event["evidence"],
            source="memory-events",
            emitter="one-stop-hook",
            workspace=workspace,
            project_slug=project_slug,
            supersedes=str(event.get("supersedes") or ""),
        ):
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
            emitter="one-stop-hook",
            workspace=workspace,
            project_slug=project_slug,
        )
    # Curate once at session end so tickets do not accumulate indefinitely.
    # Curator failure must never block session completion.
    try:
        receipt["curated"] = curate(root)["decisions"]
    except Exception as exc:
        receipt["curated"] = {"error": str(exc)[:120]}
    return receipt


WORKSPACE_CONTRACT_VERSION = "1.1.0"
TICKET_SLUGS_FILE = "ticket-slugs.json"
MIGRATIONS_FILE = "migrations.jsonl"


def _migration_receipt(meta: Path, event: dict[str, Any]) -> None:
    payload = json.dumps(event, ensure_ascii=False, sort_keys=True)
    key = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    ledger = meta / MIGRATIONS_FILE
    try:
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                if json.loads(line).get("dedupe") == key:
                    return
            except ValueError:
                continue
    except OSError:
        pass
    with ledger.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "schemaVersion": SCHEMA_VERSION, "kind": "workspace-migration",
            "dedupe": key, **event, "createdAt": _now(),
        }, ensure_ascii=False) + "\n")


def migrate_one_workspace(root: Path) -> dict[str, Any] | None:
    """M-1 — first-touch, idempotent upgrade of a legacy One workspace.

    Backfill lives in a SIDECAR (ticket-slugs.json), never by rewriting the
    append-only ticket ledger. Attribution uses receipt-time matching only;
    an ambiguous or unmatched ticket stays "unknown" — guessing is forbidden.
    """
    root = Path(root).expanduser()
    state_path = root / "state.json"
    meta = root / META_DIR
    if not meta.is_dir():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if str(state.get("contractVersion") or "1.0.0") >= WORKSPACE_CONTRACT_VERSION:
        return None

    # Step 1 — sidecar slug attribution for legacy tickets.
    receipts_by_second: dict[str, set[str]] = {}
    for row in _read_jsonl(meta / INVOCATION_LEDGER_FILE):
        if row.get("event") != "session_stop" or not row.get("workspace"):
            continue
        receipts_by_second.setdefault(str(row.get("createdAt")), set()).add(str(row["workspace"]))
    sidecar: dict[str, dict[str, str]] = {}
    unknown = matched = 0
    for ticket in _read_jsonl(meta / MEMORY_TICKETS_FILE):
        tid = str(ticket.get("ticketId") or "")
        if not tid or ticket.get("projectSlug"):
            continue
        workspaces = receipts_by_second.get(str(ticket.get("createdAt")), set())
        if len(workspaces) == 1:
            name = next(iter(workspaces))
            sidecar[tid] = {"workspace": name, "slug": _slugify(name)}
            matched += 1
        else:
            sidecar[tid] = {"workspace": "", "slug": "unknown"}
            unknown += 1
    _atomic_write(meta / TICKET_SLUGS_FILE, json.dumps(sidecar, ensure_ascii=False, indent=1) + "\n")

    # Step 2 — guarded chip schema extension + backfill from the sidecar.
    exp_db = meta / EXPERIENCE_DB_FILE
    altered = backfilled = 0
    if exp_db.exists():
        conn = sqlite3.connect(exp_db)
        try:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(experience_candidates)")}
            for column in ("project_scope_key", "environment_key"):
                if column not in columns:
                    conn.execute(f"ALTER TABLE experience_candidates ADD COLUMN {column} TEXT")
                    altered += 1
            environment = f"{sys.platform}-{platform.machine()}"
            for chip_id, source_ticket, scope_key in conn.execute(
                "SELECT id, source_ticket, scope_key FROM experience_candidates"
                " WHERE project_scope_key IS NULL"
            ).fetchall():
                if scope_key in ("agent_repo", "user_identity"):
                    project_key = "global"
                else:
                    project_key = (sidecar.get(str(source_ticket)) or {}).get("slug") or "unknown"
                conn.execute(
                    "UPDATE experience_candidates SET project_scope_key = ?, environment_key = ?"
                    " WHERE id = ?",
                    (project_key, environment, chip_id),
                )
                backfilled += 1
            conn.commit()
        finally:
            conn.close()

    # Step 3 — bump the contract version, preserving every other field.
    state["contractVersion"] = WORKSPACE_CONTRACT_VERSION
    try:
        _atomic_write(state_path, json.dumps(state, ensure_ascii=False, indent=2) + "\n")
    except OSError:
        pass

    summary = {"event": "one-workspace-1.1.0", "ticketsMatched": matched,
               "ticketsUnknown": unknown, "chipColumnsAdded": altered, "chipsBackfilled": backfilled}
    _migration_receipt(meta, summary)
    return summary


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
    """Apply deterministic admission rules without an LLM; ordering is contractual.

    Every judgment value comes from the shared curator ruleset (G1/G3) so the
    Desktop executor and this one cannot silently drift apart.
    """
    content = str(candidate.get("content") or "")
    kind = str(candidate.get("type") or "")
    evidence = candidate.get("evidence") or []

    if _rule_re("secretKeyValue").search(content) or _rule_re("secretValueShapes").search(content):
        return ("reject", "policy-secret")
    if _rule_re("hostAbsolutePath").search(content):
        return ("reject", "host-absolute-path")
    if _rule_re("imperative").search(content.strip()):
        return ("reject", "imperative-not-memory")
    if len(_normalize(content)) < int(_rule("limits.minContentChars", 12)):
        return ("reject", "too-short")
    if _content_hash(content) in durable_hashes:
        return ("deduped", "already-durable")
    if kind not in set(_rule("kinds.promotable", list(PROMOTABLE_KINDS))):
        return ("defer", f"kind-not-promotable:{kind}")
    if not evidence:
        return ("defer", "evidence-required")
    return ("admit", "evidence-backed")


def _mentions_project_specifics(content: str, folder: str) -> bool:
    """Folder-name half of the project-specifics guard (curator.ts port).

    Host absolute paths are already outright rejected by _classify; here we
    only catch an agent_repo candidate that names its own project folder, so
    the curator can narrow it to project scope instead of letting project A's
    specifics resurface in project B.
    """
    min_chars = int(_rule("projectSpecificsGuard.minFolderNameChars", 4))
    if not folder or len(folder) < min_chars:
        return False
    escaped = re.escape(folder)
    return re.search(
        rf"(?:^|[^A-Za-z0-9]){escaped}(?:$|[^A-Za-z0-9])", content, re.IGNORECASE
    ) is not None


def _durable_hashes(soul_path: Path) -> set[str]:
    if not soul_path.exists():
        return set()
    return set(re.findall(r"<!--\s*h:([0-9a-f]{16})\s*-->", soul_path.read_text(encoding="utf-8")))


def _append_durable(
    soul_path: Path,
    candidate: dict[str, Any],
    ticket_id: str,
    project_slug: str = "",
) -> None:
    """Persist durable memory as a human-readable Markdown capsule."""
    content = str(candidate.get("content") or "").strip()
    kind = str(candidate.get("type") or "fact")
    evidence = ", ".join(str(item) for item in (candidate.get("evidence") or [])[:4])
    project_line = f"  - Project: {project_slug}\n" if project_slug else ""
    block = (
        f"\n- **[{kind}]** {content}\n"
        f"  - Evidence: {evidence or 'none'}\n"
        f"{project_line}"
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


def _make_experience_chip(
    db_path: Path,
    candidate: dict[str, Any],
    ticket_id: str,
    project_scope_key: str = "global",
) -> str | None:
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
            "  status, public_safe, source_ticket, pack_id, project_scope_key, environment_key,"
            "  created_at, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (chip_id, ONE_AGENT_ID, scope_key,
             content[:400], json.dumps(terms, ensure_ascii=False), "internal", 0.5,
             "candidate", 0, ticket_id, pack_id,
             project_scope_key, f"{sys.platform}-{platform.machine()}", now, now),
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

    # M-1 — retry the first-touch migration here so a stop-hook failure cannot
    # leave a legacy workspace behind (idempotent; version-gated).
    try:
        migrate_one_workspace(root)
    except Exception:
        pass

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

    # G7 — the One drawer only accepts tickets from One's own pipeline. Legacy
    # rows without the field are tolerated (they predate the contract).
    allowed_emitters = set(_rule("emitters.oneDrawerAllowed", []))
    legacy_ok = bool(_rule("emitters.legacyMissingFieldTolerated", True))
    ruleset_sha = load_ruleset()[1]
    # Legacy tickets carry no projectSlug; the M-1 sidecar holds their
    # receipt-matched attribution ("unknown" when ambiguous — never guessed).
    try:
        slug_sidecar = json.loads((meta / TICKET_SLUGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        slug_sidecar = {}

    with decisions_path.open("a", encoding="utf-8") as handle:
        for ticket in pending:
            candidate = ticket.get("candidate") or {}
            # Project-specifics guard (curator.ts port) — an agent_repo label
            # that names its own project folder narrows to project scope; it is
            # still stored, just never resurfaced in an unrelated project.
            scope_narrowed = False
            if str(candidate.get("scope")) == "agent_repo" and _mentions_project_specifics(
                str(candidate.get("content") or ""), str(ticket.get("workspace") or "")
            ):
                candidate = {**candidate, "scope": "project"}
                scope_narrowed = True
            if "emitter" in ticket and str(ticket.get("emitter")) not in allowed_emitters:
                action, reason = ("reject", str(_rule("emitters.rejectReason", "unauthorized-emitter")))
            elif "emitter" not in ticket and not legacy_ok:
                action, reason = ("reject", str(_rule("emitters.rejectReason", "unauthorized-emitter")))
            else:
                action, reason = _classify(candidate, durable)
            counts[action] = counts.get(action, 0) + 1

            chip_id = None
            if action == "admit":
                tid = str(ticket.get("ticketId") or "")
                ticket_slug = str(ticket.get("projectSlug") or "") \
                    or str((slug_sidecar.get(tid) or {}).get("slug") or "")
                if ticket_slug == "unknown":
                    ticket_slug = ""
                # G4/G8 — an explicitly declared replacement hides the old block
                # from recall via the pointer sidecar; the soul stays append-only.
                old_hash = str(candidate.get("supersedes") or "")
                if old_hash and old_hash in durable:
                    _record_supersede(meta, old_hash,
                                      _content_hash(str(candidate.get("content") or "")))
                _append_durable(soul_path, candidate, str(ticket.get("ticketId")),
                                project_slug=ticket_slug)
                durable.add(_content_hash(str(candidate.get("content") or "")))
                if str(candidate.get("type")) in CRAFT_KINDS and exp_db.exists():
                    # Cluster key (D4): agent_repo/user_identity chips are
                    # cross-project ("global"); project-scope chips carry their
                    # context slug, "unknown" when attribution is impossible.
                    if str(candidate.get("scope")) in ("agent_repo", "user_identity"):
                        project_key = "global"
                    else:
                        project_key = ticket_slug or "unknown"
                    chip_id = _make_experience_chip(exp_db, candidate, str(ticket.get("ticketId")),
                                                    project_scope_key=project_key)
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
                "rulesetSha256": ruleset_sha,
                **({"scopeNarrowed": True} if scope_narrowed else {}),
                "createdAt": _now(),
            }, ensure_ascii=False) + "\n")

    # G8 — monthly rotation of decided tickets (idempotent; lock-guarded).
    # Failure must never block curation results.
    try:
        rotate_one_ledgers(root)
    except Exception:
        pass

    return {
        "pending": len(pending),
        "decisions": counts,
        "experienceChips": chips,
        "agentId": ONE_AGENT_ID,
    }


SUPERSEDED_MAP_FILE = "superseded-map.json"
ARCHIVE_DIR = "archive"


def rotate_one_ledgers(root: Path) -> dict[str, int]:
    """G8 file-layer decay — move decided tickets from past months to archive.

    Runs under the G6 ledger lock; the active ledgers stay append-only between
    rotations and nothing is deleted — archived months live in
    .agentlas/archive/{tickets,decisions}-YYYY-MM.jsonl. Idempotent: a second
    run in the same month rotates nothing.
    """
    root = Path(root).expanduser()
    meta = root / META_DIR
    tickets_path = meta / MEMORY_TICKETS_FILE
    decisions_path = meta / CURATOR_DECISIONS_FILE
    if not tickets_path.exists():
        return {"archivedTickets": 0, "archivedDecisions": 0}
    current_month = _now()[:7]
    decided = {
        str(row.get("ticketId")) for row in _read_jsonl(decisions_path) if row.get("ticketId")
    }

    with _LedgerLock(tickets_path) as acquired:
        if not acquired:
            return {"archivedTickets": 0, "archivedDecisions": 0, "skipped": 1}

        keep_t: list[dict[str, Any]] = []
        archive_t: dict[str, list[dict[str, Any]]] = {}
        archived_ids: set[str] = set()
        for row in _read_jsonl(tickets_path):
            month = str(row.get("createdAt") or "")[:7]
            tid = str(row.get("ticketId") or "")
            if month and month < current_month and tid in decided:
                archive_t.setdefault(month, []).append(row)
                archived_ids.add(tid)
            else:
                keep_t.append(row)
        if not archived_ids:
            return {"archivedTickets": 0, "archivedDecisions": 0}

        keep_d: list[dict[str, Any]] = []
        archive_d: dict[str, list[dict[str, Any]]] = {}
        archived_decisions = 0
        for row in _read_jsonl(decisions_path):
            if str(row.get("ticketId") or "") in archived_ids:
                month = str(row.get("createdAt") or "")[:7] or current_month
                archive_d.setdefault(month, []).append(row)
                archived_decisions += 1
            else:
                keep_d.append(row)

        archive_root = meta / ARCHIVE_DIR
        archive_root.mkdir(parents=True, exist_ok=True)
        for prefix, groups in (("tickets", archive_t), ("decisions", archive_d)):
            for month, rows in groups.items():
                with (archive_root / f"{prefix}-{month}.jsonl").open("a", encoding="utf-8") as handle:
                    for row in rows:
                        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        _atomic_write(tickets_path,
                      "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep_t))
        _atomic_write(decisions_path,
                      "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in keep_d))

    summary = {"archivedTickets": len(archived_ids), "archivedDecisions": archived_decisions}
    _migration_receipt(meta, {"event": "ledger-rotation", "month": current_month, **summary})
    return summary


def _superseded_hashes(meta: Path) -> set[str]:
    try:
        data = json.loads((meta / SUPERSEDED_MAP_FILE).read_text(encoding="utf-8"))
        return set(data.keys()) if isinstance(data, dict) else set()
    except (OSError, ValueError):
        return set()


def _record_supersede(meta: Path, old_hash: str, new_hash: str) -> None:
    """G4 for the file layer — a pointer sidecar, never a soul-file rewrite.

    The soul stays append-only; recall consults this map to hide replaced
    blocks. The old block's text remains recoverable in the file itself.
    """
    path = meta / SUPERSEDED_MAP_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data[old_hash] = new_hash
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")


_DURABLE_BLOCK_RE = re.compile(
    r"^- \*\*\[(?P<kind>\w+)\]\*\* (?P<content>.+?)\n"
    r"(?:  - (?:근거|Evidence): (?P<evidence>.*?)\n)?"
    r"(?:  - Project: (?P<project>.*?)\n)?"
    r"  - (?:티켓|Ticket): `(?P<ticket>[^`]+)`",
    re.MULTILINE,
)


def parse_durable_blocks(soul_text: str) -> list[dict[str, str]]:
    """Parse durable soul blocks into structured rows (pure seam for recall/tests)."""
    rows: list[dict[str, str]] = []
    for match in _DURABLE_BLOCK_RE.finditer(soul_text):
        rows.append({
            "kind": match.group("kind"),
            "content": match.group("content").strip(),
            "evidence": (match.group("evidence") or "").strip(),
            "project": (match.group("project") or "").strip(),
            "ticket": match.group("ticket"),
        })
    return rows


def _recall_tokens(text: str) -> set[str]:
    return {tok for tok in re.findall(r"[A-Za-z가-힣0-9_./-]{2,}", text.lower())}


def select_one_recall(
    question: str,
    workspace: str = "",
    root: Path | None = None,
) -> list[str]:
    """P3 — pick the One know-how lines for a session capsule.

    L1 only ships non-aging kinds (ruleset l1Kinds); facts age with code and
    stay with the self-correcting project layer. Ranking = token overlap with
    the question, boosted for the current project slug; budgets come from the
    ruleset. Returns [] when One is off or there is nothing relevant — recall
    must never invent content.
    """
    root = (root or Path("~/.agentlas/one")).expanduser()
    if not (root / "state.json").exists():
        return []
    meta = root / META_DIR
    soul = meta / PROJECT_SOUL_FILE
    try:
        blocks = parse_durable_blocks(soul.read_text(encoding="utf-8"))
    except OSError:
        return []
    if not blocks:
        return []
    try:
        sidecar = json.loads((meta / TICKET_SLUGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        sidecar = {}
    superseded = _superseded_hashes(meta)

    l1_kinds = set(_rule("recallBudgets.one.l1Kinds", ["procedure", "decision", "risk"]))
    max_blocks = int(_rule("recallBudgets.one.l1MaxBlocks", 6))
    max_chars = int(_rule("recallBudgets.one.l1MaxChars", 1200))
    boost = float(_rule("recallBudgets.one.currentSlugBoost", 1.5))
    current_slug = resolve_project_slug(workspace)

    q_tokens = _recall_tokens(question)
    scored: list[tuple[float, int, dict[str, str]]] = []
    for index, block in enumerate(blocks):
        if block["kind"] not in l1_kinds:
            continue
        # G8 — explicitly superseded blocks never resurface in recall.
        if _content_hash(block["content"]) in superseded:
            continue
        slug = block["project"] or str((sidecar.get(block["ticket"]) or {}).get("slug") or "")
        overlap = len(q_tokens & _recall_tokens(block["content"])) if q_tokens else 0
        same_project = bool(current_slug and slug == current_slug)
        # A single shared token is noise, not relevance — require two, unless the
        # block belongs to the current project (its craft stays eligible).
        if overlap < 2 and not same_project:
            continue
        score = float(overlap)
        if same_project:
            score = score * boost + 0.1
        if score <= 0:
            continue
        # Later blocks win ties — recency without timestamps.
        scored.append((score, index, {**block, "slug": slug}))

    scored.sort(key=lambda item: (-item[0], -item[1]))
    lines: list[str] = []
    used = 0
    seen: set[str] = set()
    for score, _idx, block in scored[: max_blocks * 3]:
        # Pre-G6 double-hook eras left literal duplicate durable blocks;
        # recall must not spend budget saying the same thing twice.
        key = _content_hash(block["content"])
        if key in seen:
            continue
        seen.add(key)
        tag = f" {block['slug']}" if block.get("slug") else ""
        line = f"one[{block['kind']}{tag}]: {block['content']}"
        if used + len(line) > max_chars or len(lines) >= max_blocks:
            break
        lines.append(line)
        used += len(line)
    return lines


def status(root: Path) -> dict[str, Any]:
    """Measure the One workspace directly, reporting absence instead of inventing counts."""
    root = Path(root).expanduser()
    meta = root / META_DIR

    def lines(path: Path) -> int:
        if not path.exists():
            return -1
        with path.open(encoding="utf-8") as handle:
            return sum(1 for line in handle if line.strip())

    def session_receipts(path: Path) -> int:
        """Count session receipts only; state-transition markers share the ledger."""
        if not path.exists():
            return -1
        count = 0
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("event") == "session_stop":
                    count += 1
        return count

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
        "invocations": session_receipts(meta / INVOCATION_LEDGER_FILE),
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
            evidence=args.evidence, turn_key=args.turn_key, emitter="one-cli",
        ) or {"skipped": "duplicate-or-locked", "hint": "same content already ticketed, or ledger lock busy — retry"}
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
