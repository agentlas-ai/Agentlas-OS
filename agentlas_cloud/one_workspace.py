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
import math
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

# One 서랍이 자기 기억으로 받는 스코프 (오너 결정 2026-08-19).
#
# ★`project` 는 **일부러 여기 남는다.** 서랍은 project_scope_key 로 이미 프로젝트별
#   클러스터를 이루고 있고(실측: Agentlas_F 67 · agentlas-desktop 45 · Rareleecopy 45
#   · global 60 …), One 의 다차원 회수는 그 축을 쓴다. 프로젝트 맵과 겹치는 것은
#   중복이 아니라 **같은 파이프의 두 청중**이다 — 서랍은 사람의 비서가 쓰고, 맵은 그
#   프로젝트의 다음 에이전트가 쓴다. 여기서 끊으면 클러스터의 입력이 사라진다.
#
# 여기서 막는 것은 **누구 것인지 못 정한 에이전트 학습** 하나뿐이다. 그건 아래
# _route_borrowed_agent_events 가 `attribution="ambiguous"` 로 표시해 보내고,
# 추측해서 One 의 기억으로 만들지 않는다.
_ONE_OWNED_SCOPES = frozenset({"user_identity", "agent_repo", "project"})
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
# Harvest caps — a session's Memory Events are model-authored and untrusted, so
# bound count/size to keep a crafted envelope from filling disk, feeding a
# backtracking evidence-shape regex a giant string, or costing O(N^2) in the
# ticket-ledger rescan. Generous for real learnings, fatal only to abuse.
_MAX_HARVEST_CANDIDATES = 64
_MAX_CONTENT_CHARS = 4000
_MAX_EVIDENCE_ITEM_CHARS = 500
_MAX_ENVELOPE_BYTES = 1_000_000
_MAX_TEXT_BYTES = 2_000_000
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
        # Mirror of the canonical ruleset entry; the verify-curator-fixtures gate
        # asserts these embedded regexes stay byte-identical to system-agents/
        # curator-ruleset.json (2026-08-12 set 3 F3: they had drifted).
        # ★2026-08-16: the Korean sentence-ending half was REMOVED (owner decision,
        # "안전 뭐 이런거 다 풀라고 했는데"). Judging prompt injection by a list of
        # Korean imperative endings blocked ordinary writing and let other endings
        # through, measured: "하루 3회 식후에 복용하세요"(medicine), "증상이 지속되면
        # 의사와 상담하세요", "개봉 후 냉장 보관하세요", "앱을 다시 시작해줘" were all
        # rejected, while "볶아주세요" and "복용하지 마십시오" passed — the split was
        # whether an ending happened to be on the list, not what the sentence meant.
        # This is the same failure the capability-widening screen was retired for
        # (see the note further down): a wordlist cannot carry grammar across
        # languages. What stays is the explicit English override phrasing, which has
        # no ordinary-writing collision.
        "imperative": {
            "regex": r"^(?:ignore\s+(?:previous|all\s+previous|the\s+above)|disregard|forget\s+(?:everything|all|previous|the\s+above))\b",
            "flags": "i",
        },
        # R21 W2a — mirror of the canonical ruleset entry; keep byte-identical.
        "evidenceShapeAccept": {
            "regex": r"[\w./~-]+\.[A-Za-z0-9]{1,6}(?::\d+)?|:\d+\b|https?://|`[^`]+`|\b[a-f0-9]{7,40}\b|\btest[_-][\w-]+|\bverify[-_][\w-]+|\bpytest\b|arXiv:\d{4}\.\d{4,5}|\$ |^\s*(?:bash|node|python3?|npm|git)\b",
            "flags": "im",
        },
        # capabilityWidening / capabilityWideningException were REMOVED 2026-08-12
        # (owner decision): a content wordlist cannot separate a widening
        # assertion from a safety lesson across languages, and misevolution
        # defence lives in recall framing + the PreToolUse broker instead.
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
    # Honour every declared flag, not just 'i': the Desktop executor compiles
    # `new RegExp(regex, flags)` and applies them all, so dropping 'm'/'s' here
    # made the byte-identical ruleset behave differently across surfaces
    # (evidenceShapeAccept declares 'im'; its `^(?:bash|node|…)` line-anchor
    # needs MULTILINE — 2026-08-12 set 4).
    flag_str = str(spec.get("flags", fallback["flags"]))
    flags = 0
    if "i" in flag_str:
        flags |= re.IGNORECASE
    if "m" in flag_str:
        flags |= re.MULTILINE
    if "s" in flag_str:
        flags |= re.DOTALL
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
                # Record the holder pid so a stale-lock takeover can prove the
                # holder is really gone before stealing. A live-but-slow holder
                # (a >stale_ms critical section — a big under-lock read, a paused
                # process) must NOT have its lock unlinked, or two writers both
                # run check-then-append and double-write, defeating the G6 dedupe
                # this lock exists to guarantee (2026-08-12 set 4).
                try:
                    os.write(self.fd, str(os.getpid()).encode("ascii"))
                except OSError:
                    pass
                return True
            except FileExistsError:
                try:
                    if (time.time() - self.path.stat().st_mtime) * 1000 > stale_ms and self._holder_is_dead():
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
                time.sleep(delay)
            except OSError:
                return False
        return False

    def _holder_is_dead(self) -> bool:
        """True only when the recorded holder pid is provably gone. An unknown or
        living holder is treated as alive so we keep waiting rather than steal a
        lock that is still in use (a legacy lock with no pid keeps the old
        stale-mtime takeover)."""
        try:
            holder = self.path.read_text(encoding="ascii").strip()
        except OSError:
            return True
        if not holder.isdigit():
            return True
        try:
            os.kill(int(holder), 0)
            return False
        except ProcessLookupError:
            return True
        except OSError:
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
    # G6 declares the id scheme in the ruleset, so read it instead of assuming it.
    # A declaration nothing reads is how a rule quietly stops being one.
    scheme = str(_rule("concurrency.ticketIdScheme", "content-hash"))
    if scheme != "content-hash":
        raise ValueError(f"unsupported ticketIdScheme: {scheme}")
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
        # Bound BEFORE the regex: the envelope finder scans the whole assistant
        # text, so a 500MB blob spends a minute in finditer before any later cap
        # applies (measured 2026-08-12 adversarial set 2). A real assistant
        # message with a Memory Events block is well under this ceiling; truncate
        # so the block (which comes at/near the end of the answer) still parses
        # for normal sizes while abuse is cut.
        if len(text) > _MAX_TEXT_BYTES:
            text = text[-_MAX_TEXT_BYTES:]
        matches = list(_MEMORY_ENVELOPE_FENCED_RE.finditer(text))
        if not matches:
            matches = list(_MEMORY_ENVELOPE_BARE_RE.finditer(text))
        for match in matches:
            raw = match.group(1)
            # Reject the parse itself when the envelope is abusively large — a
            # 500MB blob would spend a minute in json.loads before any per-field
            # cap could help. A real Memory Events block (≤64 candidates, bounded
            # content/evidence) is well under this ceiling.
            if len(raw) > _MAX_ENVELOPE_BYTES:
                continue
            try:
                envelope = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(envelope, dict):
                continue
            candidates_raw = envelope.get("candidates") or []
            # Bound the iteration itself (not just `found`): dedup could keep
            # `found` small while a million-candidate list still spun the loop.
            if isinstance(candidates_raw, list):
                candidates_raw = candidates_raw[: _MAX_HARVEST_CANDIDATES * 8]
            for candidate in candidates_raw:
                # Bound the harvest — content, evidence, and candidate COUNT were
                # all unbounded, so one crafted envelope could fill a drawer's
                # disk, feed a quadratically-backtracking evidence-shape regex a
                # giant string (ReDoS), and cost O(N^2) in emit_ticket's ledger
                # rescan (measured 2026-08-12 adversarial set 2). These caps are
                # generous for real learnings and fatal only to abuse.
                if len(found) >= _MAX_HARVEST_CANDIDATES:
                    break
                if not isinstance(candidate, dict):
                    continue
                content = str(candidate.get("content") or "").strip()[:_MAX_CONTENT_CHARS]
                if not content:
                    continue
                key = _content_hash(content)
                if key in seen:
                    continue
                seen.add(key)
                evidence = candidate.get("evidence")
                supersedes = str(candidate.get("supersedes") or "")
                # R21 W1a — optional borrowed-agent attribution axis. A learning
                # made while acting as a hired Hub agent names that agent's slug
                # so the stop hook can route it into the per-slug drawer. Absent
                # or malformed → empty string → the One path, exactly as before.
                agent_slug = str(candidate.get("agent_slug") or "").strip().lower()
                if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{1,63}", agent_slug):
                    agent_slug = ""
                found.append({
                    "content": content,
                    "kind": str(candidate.get("memory_kind") or "hypothesis"),
                    "scope": str(candidate.get("suggested_scope") or "agent_repo"),
                    "evidence": [str(item)[:_MAX_EVIDENCE_ITEM_CHARS] for item in evidence][:8] if isinstance(evidence, list) else [],
                    # G4/G8 — a worker may explicitly name the durable block this
                    # replaces (its h:16hex). Anything else is ignored, never guessed.
                    "supersedes": supersedes if re.fullmatch(r"[0-9a-f]{16}", supersedes) else "",
                    "agent_slug": agent_slug,
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


HUB_AGENTS_DIR_ENV = "AGENTLAS_HUB_AGENTS_DIR"
ONTOLOGY_BIN_ENV = "AGENTLAS_ONTOLOGY_BIN"
# Fallback window when a transcript has no birthtime: attribute only invocations
# from the recent past instead of the drawer's whole history.
_ACTIVE_AGENT_FALLBACK_WINDOW_SEC = 6 * 3600


def _hub_agents_dir() -> Path:
    # Delegate to the ONE canonical resolver so this surface, memory_hook, and
    # local_registry can never resolve the drawer root differently under a
    # relocation env (measured 2026-08-12 adversarial set 2).
    from .networking.bootstrap import hub_agents_dir  # noqa: PLC0415

    return hub_agents_dir()


def _iso_to_epoch(value: str) -> float:
    try:
        from datetime import datetime

        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _session_active_agents(started_epoch: float) -> list[str]:
    """Slugs whose invocation ledger shows activity inside this session's window.

    R21 W1b — the ledger is written deterministically at borrow time
    (hub_invocation.py), so detection needs no model cooperation. A transcript
    without a birthtime yields started_epoch=0; fall back to a bounded recent
    window rather than attributing a drawer's entire history to this session.
    """
    base = _hub_agents_dir()
    if not base.is_dir():
        return []
    # Floor to whole seconds: ledger/ticket timestamps carry second precision
    # while a file birthtime carries sub-second — an entry stamped in the same
    # second as session start must count as inside the window (measured: the
    # truncated ts compared 0.465s "before" the start and broke rerun detection).
    window_start = float(int(started_epoch or (time.time() - _ACTIVE_AGENT_FALLBACK_WINDOW_SEC)))
    active: list[str] = []
    try:
        drawers = sorted(p for p in base.iterdir() if p.is_dir())
    except OSError:
        return []
    for drawer in drawers:
        for ledger in (drawer / "memory" / "invocation-ledger.jsonl", drawer / "invocation-ledger.jsonl"):
            if not ledger.is_file():
                continue
            for row in _read_jsonl(ledger):
                if _iso_to_epoch(str(row.get("ts") or "")) >= window_start:
                    active.append(drawer.name)
                    break
            if active and active[-1] == drawer.name:
                break
    return active


def _drawer_ticket_once(drawer: Path, record: dict[str, Any]) -> bool:
    """Append a ticket to the drawer ledger unless the same content is present.

    Same idempotency principle as emit_ticket (G6): dedupe on normalized content
    hash UNDER the cross-process _LedgerLock, so duplicate hook channels, reruns,
    and two host sessions ending near-simultaneously against this machine-global
    drawer converge on a single ticket. The check-then-append was previously
    unlocked and raced (2026-08-12 set 3: 24 concurrent callers wrote 23 rows for
    one learning). Fail to acquire → skip (never block a session end).
    """
    ledger = drawer / "memory" / "memory-tickets.jsonl"
    key = _content_hash(str(record.get("content") or ""))
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with _LedgerLock(ledger) as acquired:
        if not acquired:
            return False
        for row in _read_jsonl(ledger):
            if str(row.get("dedupe") or "") == key:
                return False
            if _content_hash(str(row.get("content") or "")) == key:
                return False
        payload = {**record, "dedupe": key}
        with ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return True


def _drawer_write_note(drawer: Path, event: dict[str, Any]) -> Path | None:
    """Write one learning note into the drawer's notes/ — the exact folder the
    grounding directive's experience_record ingests. Idempotent by content hash."""
    notes = drawer / "notes"
    key = _content_hash(str(event.get("content") or ""))
    target = notes / f"learning-{key}.md"
    if target.exists():
        return None
    from datetime import date

    notes.mkdir(parents=True, exist_ok=True)
    evidence_lines = "".join(f"- {item}\n" for item in event.get("evidence") or [])
    # Built outside the f-string on purpose: a backslash inside an f-string
    # EXPRESSION is a SyntaxError before Python 3.12, and this module declares
    # 3.9 support (every launcher accepts >= 3.9). macOS ships 3.9.6 as
    # /usr/bin/python3, so the inline form made the whole module unimportable on
    # a stock Mac — `agentlas-one on` reported "verification failed" with no
    # visible reason.
    evidence_block = evidence_lines or "- (none)\n"
    target.write_text(
        f"# {date.today().isoformat()} {event.get('kind', 'learning')} ({key})\n\n"
        f"{event.get('content', '')}\n\n"
        f"## Evidence\n\n{evidence_block}",
        encoding="utf-8",
    )
    return target


_DRAWER_RUNTIME_CACHE: dict[str, Any] = {}


def _drawer_feed_evolution(drawer: Path, slug: str, event: dict[str, Any]) -> bool:
    """Feed the drawer's ``memory_candidates`` so self-evolution can see it.

    R17 §3 gap: ``derive_proposals_from_experience`` reads ``memory_candidates``
    (evolution_proposals.py:150), but ``_ingest_drawer_notes`` only fills
    ``chunks`` (recall). So a drawer could accumulate recall-visible experience
    and STILL never produce an evolution proposal — the accumulation→evolution
    chain was broken at the store level (measured 2026-08-12: ingesting 6
    candidates via ingest_experience yields 1 proposal; via notes-ingest yields
    0). ``agent_id`` matches ``_trusted_agent_projection``'s ``f"hub:{slug}"``
    (memory_hook.py:197) so recall and evolution read the same rows. Idempotent
    by content-hash source_memory_id; fail-open on a host without the ontology
    package (recall still works via _ingest_drawer_notes)."""
    try:
        from ontology import OntologyRuntime, RuntimeConfig  # noqa: PLC0415
    except Exception:
        return False
    content = str(event.get("content") or "")
    if not content.strip():
        return False
    try:
        # Open the drawer runtime ONCE per drawer and reuse it — constructing an
        # OntologyRuntime runs select_vector_adapter + full migrate() (~500ms),
        # and this used to fire once PER event, an ~40x hot-path regression on
        # every session end (measured 2026-08-12 adversarial set). Cache by db
        # path, same pattern as _one_runtime's _ONE_RUNTIME_CACHE.
        db_path = drawer / "memory" / "experience.sqlite"
        key = str(db_path)
        runtime = _DRAWER_RUNTIME_CACHE.get(key)
        if runtime is None:
            runtime = OntologyRuntime(RuntimeConfig(db_path=db_path))
            _DRAWER_RUNTIME_CACHE[key] = runtime
        kind = str(event.get("kind") or "hypothesis")
        runtime.ingest_experience(
            agent_id=f"hub:{slug}",
            summary=content,
            tags=[kind],
            memory_kind=kind,
            source_memory_id=_content_hash(content),
            suggested_scope=str(event.get("scope") or "agent_repo"),
            reason="drawer experience; per-agent self-evolution feed (plan §46)",
        )
        return True
    except Exception:
        return False


def _ingest_drawer_notes(drawer: Path) -> str:
    """R21 W1e — the hook runs experience_record itself instead of asking the
    model to. scope=internal is contractual: private is write-only (measured —
    OntologyRuntime.query resolves scopes as ["public","internal"]). Fail-open:
    a missing binary or a failed run must never block session end."""
    binary = Path(os.environ.get(ONTOLOGY_BIN_ENV) or (Path.home() / ".agentlas" / "runtime" / "current" / "bin" / "ontology"))
    if not binary.is_file():
        return "skipped:no-binary"
    import subprocess

    try:
        completed = subprocess.run(
            [str(binary), "--db", str(drawer / "memory" / "experience.sqlite"),
             "ingest", str(drawer / "notes"), "--scope", "internal"],
            capture_output=True, timeout=60, check=False,
        )
        return "ok" if completed.returncode == 0 else f"failed:rc{completed.returncode}"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"failed:{type(exc).__name__}"


def _evidence_points_into(event: dict[str, Any], slug: str) -> bool:
    """이 학습의 근거가 그 에이전트 패키지 안을 가리키는가.

    대여 원장은 "빌렸다" 까지만 안다. 누가 이 문장을 배웠는지는 근거가 말한다 —
    그 패키지의 파일을 인용하면 그 에이전트의 학습이고, 엔진이나 다른 저장소를
    인용하면 아니다. 근거가 없으면 가져가지 않는다(모르는 것을 근거로 옮기지 않는다).
    """
    evidence = event.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return False
    needle = slug.strip().lower()
    if not needle:
        return False
    for item in evidence:
        text = str(item or "").lower()
        if needle and needle in text:
            return True
    return False


def _route_borrowed_agent_events(
    events: list[dict[str, Any]],
    *,
    started_epoch: float,
    substantial: bool,
    tool_uses: int,
    edits: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """R21 W1c/W1d — route agent-attributed learnings into per-slug drawers and
    leave a gap ticket when an active borrowed agent recorded nothing.

    Returns (events_for_one, receipt). Unattributed events flow to the One path
    unchanged; nothing is silently dropped. Fail-open on any drawer error.
    """
    receipt: dict[str, Any] = {}
    active = _session_active_agents(started_epoch)
    if not active:
        return events, receipt
    base = _hub_agents_dir()
    remaining: list[dict[str, Any]] = []
    routed_by_slug: dict[str, int] = {}
    blocked_by_slug: dict[str, int] = {}
    attributed_by_slug: dict[str, int] = {}
    # ★귀속은 모델의 자진신고가 아니라 **호스트 관측**이다.
    #
    #   예전에는 `agent_slug` 를 모델이 봉투에 적어야만 그 에이전트 서랍으로 갔다. 그런데
    #   모델이 읽는 계약(agentlas.memory-ticket.v1)에는 그 필드가 **아예 없다** — 아무도
    #   적을 수 없는 필드를 라우팅 조건으로 삼은 것이다. 실측 2026-08-19: One 서랍의 티켓
    #   1,278건이 전부 `agentId=builtin-agentlas-one` 이었고, 그중 agent_repo 253건과
    #   project 990건이 남의 자리에 쌓여 있었다(다른 코드베이스의 지식까지). 로컬 에이전트
    #   7개는 experience 0개였다 — 원인이 아니라 결과다.
    #
    #   호스트는 어느 에이전트가 돌았는지 이미 안다(invocation ledger, 대여 시점에
    #   결정론적으로 기록된다). 이 세션에서 **정확히 하나**가 돌았다면 그 세션의 학습은
    #   그 에이전트의 것이다. 둘 이상이면 누구 것인지 관측만으로는 못 정하므로 추측하지
    #   않는다 — 모델이 스스로 적은 slug 가 있으면 그것만 쓴다.
    # ★관측 귀속은 **세션 창이 확실할 때만** 한다.
    #   started_epoch 이 0이면(트랜스크립트 생성시각 없음) 창이 6시간 폴백으로 넓어져,
    #   그 사이 아무 때나 빌린 에이전트가 "이번 세션에 돌았다"로 보인다. 그 상태에서
    #   귀속하면 무관한 학습이 남의 서랍에 들어간다. 같은 이유로 아래 gap 판정도
    #   started_epoch>0 일 때만 한다 — 그 규칙을 여기서도 지킨다.
    #   모델이 스스로 적은 slug 는 이 제한과 무관하게 예전처럼 존중된다.
    observed_slug = active[0] if (len(active) == 1 and started_epoch > 0) else ""
    for event in events:
        slug = str(event.get("agent_slug") or "")
        scope = str(event.get("scope") or "")
        if not slug and scope != "user_identity":
            # 사람에 대한 사실은 에이전트의 것이 아니다 — 언제나 One 에 남는다.
            if observed_slug and _evidence_points_into(event, observed_slug):
                # ★"이 에이전트를 빌렸다"는 "이 학습을 그 에이전트가 만들었다"가 아니다.
                #   원장은 대여 사실만 안다. 같은 세션에서 One 이 직접 한 일까지 넘기면
                #   그건 귀속이 아니라 절도다(실측: 무균 파이프라인 시험에서 One 층이
                #   자라지 못했다 — 그 세션의 학습이 전부 빌린 에이전트에게 갔다).
                #
                #   실제로 잴 수 있는 근거 하나만 쓴다: 그 학습이 **그 에이전트 패키지
                #   안의 파일을 근거로 대는가**. 신약개발 채점기 이야기는 그 패키지의
                #   tools/ 를 인용하고, 엔진 이야기는 agentlas_cloud/ 를 인용한다.
                #   근거가 그 밖을 가리키면 One 에 남긴다 — 모르면 가져가지 않는다.
                slug = observed_slug
                event = {**event, "agent_slug": slug, "attribution": "host-observed"}
            elif scope == "agent_repo" and started_epoch > 0 and len(active) > 1:
                # ★"주인이 여럿이라 못 정한다"와 "세션 창을 몰라 못 정한다"는 다른 상황이다.
                #   전자만 표시한다 — 빌린 에이전트가 둘 이상 확실히 돌았으므로 이 학습을
                #   One 의 기억으로 삼으면 남의 도메인 지식을 자기 것으로 기억하게 된다.
                #   후자(창 불확실)는 아무 판단도 하지 않고 예전 그대로 One 에 남긴다 —
                #   모르는 것을 근거로 거절하면 멀쩡한 학습이 사라진다.
                event = {**event, "attribution": "ambiguous"}
        if slug not in active:
            remaining.append(event)
            continue
        # This agent DID emit an attributed learning this session, whether or not
        # it ends up routed (dedup can drop it to 0). Track it so a re-derived
        # learning the agent already recorded earlier is not falsely flagged as
        # "recorded no experience" (measured 2026-08-12 adversarial set 2).
        attributed_by_slug[slug] = attributed_by_slug.get(slug, 0) + 1
        # Drawer safety gate — R20 misevolution vectors (secret, capability
        # widening, imperative-not-memory, host path) must NEVER reach a drawer's
        # experience.sqlite: it is recalled into future sessions, so a secret or
        # a "skip approval" instruction accumulated here would leak or degrade
        # the very agent that learns it. Reuse the SAME _classify reject rules
        # the One durable path uses (shared curator ruleset), so drawer and soul
        # cannot drift. A rejected event is dropped from BOTH paths — a secret
        # must not fall back into the One soul either. Non-reject verdicts
        # (admit/defer/merge) still flow to the drawer: accumulation stays
        # generous (owner: a sterile pipeline is failure), only the dangerous
        # shapes are cut.
        verdict, _reason = _classify(
            {"content": event.get("content"), "type": event.get("kind"), "evidence": event.get("evidence") or []},
            set(),
        )
        if verdict == "reject":
            blocked_by_slug[slug] = blocked_by_slug.get(slug, 0) + 1
            continue
        drawer = base / slug
        ticket_committed = False
        try:
            ticketed = _drawer_ticket_once(drawer, {
                "ts": _utc_now_iso(),
                "source": "one-stop-hook",
                "kind": event.get("kind", "hypothesis"),
                "scope": event.get("scope", "agent_repo"),
                "content": event.get("content", ""),
                "evidence": event.get("evidence") or [],
                "status": "candidate",
            })
            ticket_committed = True
            _drawer_write_note(drawer, event)
            # Feed memory_candidates (evolution) alongside notes→chunks (recall).
            # Without this the drawer accumulates recall but never evolves.
            _drawer_feed_evolution(drawer, slug, event)
            routed_by_slug[slug] = routed_by_slug.get(slug, 0) + (1 if ticketed else 0)
        except OSError:
            # Only fall back to the One path if NOTHING landed in the drawer. If
            # the ticket already committed and a LATER step (note/feed) failed,
            # sending the event to One too would double-write the same learning
            # into both stores — the very thing attribution routing prevents
            # (measured 2026-08-12 adversarial set 2). Count it as routed instead.
            if ticket_committed:
                routed_by_slug[slug] = routed_by_slug.get(slug, 0) + 1
            else:
                remaining.append(event)  # drawer unwritable — keep the learning in One
    for slug in active:
        entry: dict[str, Any] = {"tickets": routed_by_slug.get(slug, 0)}
        # Announce, never hide: a blocked misevolution vector is a fact about the
        # session (P0 "relax only what you can announce"). Surfacing it also stops
        # a blocked event from being miscounted as a gap ("recorded nothing").
        if blocked_by_slug.get(slug):
            entry["blocked"] = blocked_by_slug[slug]
        drawer = base / slug
        # Gap means "nothing recorded THIS SESSION", not "nothing routed this
        # call" — a rerun of the same stop hook dedupes every event to zero and
        # would otherwise stamp a false 'recorded no experience' ticket onto a
        # drawer that did record (measured on the first E2E, 2026-08-11).
        # Same whole-second floor as _session_active_agents: ticket timestamps
        # truncate to seconds while birthtime carries sub-second precision.
        window_start = float(int(started_epoch or (time.time() - _ACTIVE_AGENT_FALLBACK_WINDOW_SEC)))
        already_recorded = any(
            str(row.get("source")) == "one-stop-hook"
            and _iso_to_epoch(str(row.get("ts") or "")) >= window_start
            for row in _read_jsonl(drawer / "memory" / "memory-tickets.jsonl")
        )
        # A gap means the agent recorded NOTHING worth keeping. If everything it
        # emitted was blocked by the drawer safety gate (blocked>0, routed==0),
        # that is not a gap — the agent DID emit, we refused it — and stamping a
        # "recorded no experience" ticket would both lie and contradict the
        # `blocked` field we already surfaced (measured 2026-08-12 adversarial set).
        # A gap is only real when the agent emitted NOTHING attributed this
        # session (attributed==0). If it emitted but every event was deduped
        # (already recorded in an earlier session) or blocked, that is not a gap
        # — attributed>0 covers both, so a re-derived learning no longer stamps
        # a false 'recorded no experience' ticket every session.
        # Only judge a gap when the session window is CERTAIN (started_epoch>0).
        # With no transcript birthtime the window falls back to a 6-hour span, so
        # every agent borrowed in the last 6h would look "active this session" and
        # get a false gap — routing still happens on that fallback, but the
        # negative "recorded nothing" verdict needs a real window
        # (measured 2026-08-12 adversarial set 2).
        if (
            started_epoch > 0
            and attributed_by_slug.get(slug, 0) == 0
            and substantial
            and not already_recorded
        ):
            try:
                entry["gap"] = _drawer_ticket_once(drawer, {
                    "ts": _utc_now_iso(),
                    "source": "one-stop-hook",
                    "kind": "conflict",
                    "scope": "agent_repo",
                    "content": (
                        f"Borrowed agent {slug} was active in a substantial session "
                        f"({edits} edits, {tool_uses} tool uses) but recorded no experience."
                    ),
                    "evidence": [f"invocation-ledger:{slug}", f"tool_uses={tool_uses}", f"edits={edits}"],
                    "status": "candidate",
                })
            except OSError:
                entry["gap"] = False
        if (drawer / "notes").is_dir() and any((drawer / "notes").iterdir()):
            entry["ingest"] = _ingest_drawer_notes(drawer)
        receipt[slug] = entry
    return remaining, receipt


def _utc_now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def stop_hook(root: Path, payload: dict[str, Any], host: str = "") -> dict[str, Any]:
    """Run the non-blocking session-end checkpoint.

    Preserve results by recording a missing capsule instead of forcing one.
    """
    root = Path(root).expanduser()
    enabled = (root / "state.json").exists()
    _record_state_transition(root, enabled)

    # Transcript parsing and per-agent drawer accumulation are One-INDEPENDENT.
    # They used to sit AFTER the `if not enabled: return` gate, so a user who
    # kept One off never accumulated any experience for the agents they built or
    # borrowed — the drawers stayed empty (measured 2026-08-12: 62 drawers, ~0
    # chunks). Plan §46 wants every agent to grow its own experience chips, not
    # only the personal One agent, so the drawer half runs on every session end
    # regardless of the One on/off state. The One half (soul tickets, One
    # curation) still honors the gate below.
    workspace = str(payload.get("cwd") or payload.get("workspace") or "")
    transcripts = resolve_transcripts(payload, host)
    transcript = transcripts[0] if transcripts else ""
    started = _session_started_at(transcript)

    events: list[dict[str, Any]] = []
    for path in transcripts:
        events.extend(harvest_memory_events(path))
    # Hosts without a transcript path (OpenCode) supply assistant text instead.
    supplied = payload.get("assistant_texts") or payload.get("assistantTexts")
    if isinstance(supplied, str):
        supplied = [supplied]
    if isinstance(supplied, list):
        events.extend(harvest_memory_events_from_texts(supplied))

    tool_uses, edits = _scan_transcript(transcript) if transcript else (0, 0)
    # Record receipts only for edits or sufficiently tool-heavy work, not casual chat.
    substantial = edits > 0 or tool_uses >= SUBSTANTIAL_TOOL_USES

    # ★Workforce 연속성 점검은 이 체크포인트의 어떤 조기 종료보다 앞선다.
    # "준비만 하고 끝난 세션"은 정의상 편집도 도구 사용도 적어서, 기억 기준의
    # not_substantial/one_off 분기에 먼저 걸려 조용히 빠져나가던 바로 그 경우다.
    # 계산은 한 번, 출구는 하나로 모은다.
    workforce_notice = ""
    if workspace:
        try:
            from .workforce.goal_binding import prepared_not_executed_notice

            workforce_notice = prepared_not_executed_notice(workspace)
        except Exception:
            workforce_notice = ""

    def _out(payload: dict[str, Any]) -> dict[str, Any]:
        if workforce_notice:
            payload["workforceNotice"] = workforce_notice
        return payload

    # Nothing in this checkpoint can affect a drawer or the One curator. Return
    # before consulting the fallback borrowed-agent window: transcriptless hosts
    # otherwise attach unrelated recently active agents, manufacture a non-empty
    # receipt, and turn an idle Stop event into curation work.
    if not events and not substantial:
        if not enabled:
            return _out({"skipped": "one_off"})
        return _out({"skipped": "not_substantial", "toolUses": tool_uses, "edits": edits})

    # R21 W1c/W1d — learnings attributed to a borrowed/built agent land in that
    # agent's own drawer (ticket + ingestable note + gap fallback); everything
    # else continues down the One path unchanged. Fail-open by construction.
    # Runs BEFORE the One gate so drawers accumulate even when One is off.
    try:
        events, borrowed_receipt = _route_borrowed_agent_events(
            events,
            started_epoch=started,
            substantial=substantial,
            tool_uses=tool_uses,
            edits=edits,
        )
    except Exception:
        borrowed_receipt = {}

    if not enabled:
        # One is off: the personal-agent soul path is skipped, but the drawer
        # accumulation above already ran. Report what the drawers received so a
        # One-off user still gets — and can observe — per-agent experience.
        result: dict[str, Any] = {"skipped": "one_off"}
        if borrowed_receipt:
            result["borrowedAgents"] = borrowed_receipt
        return _out(result)

    # M-1 — first-touch self-migration of legacy workspaces (idempotent).
    try:
        migrate_one_workspace(root)
    except Exception:
        pass  # migration must never block a session; curate() retries it

    harvested = 0
    declined: dict[str, int] = {}
    project_slug = resolve_project_slug(workspace)
    for event in events:
        # ★거절은 **누구 것인지 못 정한 에이전트 학습** 하나뿐이다.
        #
        #   귀속에 성공한 agent_repo 는 위 라우팅에서 이미 그 에이전트 서랍으로 갔고,
        #   여기 남은 것은 빌린 에이전트가 여럿이라 관측만으로 주인을 못 정한 경우다.
        #   추측해서 One 의 기억으로 만들면, 그 사람의 비서가 남의 도메인 지식을
        #   자기 것으로 기억하게 된다.
        #
        #   조용히 버리지는 않는다 — 무엇을 왜 안 받았는지 영수증에 남겨, 잘못
        #   라우팅된 학습이 "없었던 일"이 되지 않게 한다.
        scope = str(event.get("scope") or "")
        ambiguous = str(event.get("attribution") or "") == "ambiguous"
        if scope not in _ONE_OWNED_SCOPES or ambiguous:
            reason = "ambiguous_agent" if ambiguous else (scope or "unknown")
            declined[reason] = declined.get(reason, 0) + 1
            continue
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

    capsule = _capsule_written_since(workspace, started)

    if not substantial and harvested == 0 and not borrowed_receipt and not declined:
        return _out({"skipped": "not_substantial", "toolUses": tool_uses, "edits": edits})

    receipt = record_session_receipt(
        root,
        substantial=bool(substantial),
        capsule_written=capsule,
        workspace=workspace,
        detail=f"host={host or 'claude'} tool_uses={tool_uses} edits={edits} harvested={harvested}",
    )
    receipt["harvested"] = harvested
    # 거절한 것은 반드시 보인다 — "안 받았다"가 조용하면 잘못 라우팅된 학습이
    # 없었던 일이 된다(P0: 알릴 수 없으면 완화하지 마라).
    if declined:
        receipt["declinedByScope"] = declined
    if borrowed_receipt:
        receipt["borrowedAgents"] = borrowed_receipt
    # A missing learning capsule is a fact about the session, so it belongs on the
    # receipt (receipt["gap"], already written above) and nowhere else. It used to
    # be emitted as a `conflict` ticket, but `conflict` is not a promotable kind:
    # every one of those tickets was deferred on arrival, and deferred tickets
    # count as decided, so there was no queue to revisit them from. Measured on
    # 2026-08-11 that was 124 of 353 tickets and 130 of 134 defer decisions —
    # a third of the drawer and a third of the curator's work, with no reader.
    if receipt["gap"]:
        receipt["gapDetail"] = (
            f"substantial work ({edits} edits, {tool_uses} tool uses) with no learning capsule"
        )
    # Curate once at session end so tickets do not accumulate indefinitely.
    # Curator failure must never block session completion.
    try:
        receipt["curated"] = curate(root)["decisions"]
    except Exception as exc:
        receipt["curated"] = {"error": str(exc)[:120]}
    return _out(receipt)


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


def _classify(
    candidate: dict[str, Any],
    durable_hashes: set[str],
    durable_prefixes: set[str] | None = None,
) -> tuple[str, str]:
    """Apply deterministic admission rules without an LLM; ordering is contractual.

    Every judgment value comes from the shared curator ruleset (G1/G3) so the
    Desktop executor and this one cannot silently drift apart.
    """
    content = str(candidate.get("content") or "")
    kind = str(candidate.get("type") or "")
    evidence = candidate.get("evidence") or []

    # Secrets and host-absolute paths can hide in evidence[], not only content —
    # and evidence is persisted verbatim (drawer notes/tickets → experience.sqlite,
    # One soul "- Evidence:" lines) and recalled into later sessions. Scanning
    # content alone let a benign learning with a secret in its evidence leak into
    # both stores (measured 2026-08-12 adversarial set). Scan the same secret and
    # host-path rules across content AND every evidence item. (imperative /
    # capability-widening stay content-only: those are claims the learning makes,
    # and an evidence citation legitimately quotes commands.)
    secret_re_kv, secret_re_shape = _rule_re("secretKeyValue"), _rule_re("secretValueShapes")
    host_re = _rule_re("hostAbsolutePath")
    for text in (content, *(str(item) for item in evidence)):
        if secret_re_kv.search(text) or secret_re_shape.search(text):
            return ("reject", "policy-secret")
        if host_re.search(text):
            return ("reject", "host-absolute-path")
    if _rule_re("imperative").search(content.strip()):
        return ("reject", "imperative-not-memory")
    # Capability-widening content screening was REMOVED 2026-08-12 (owner
    # decision). A content regex/wordlist cannot separate "skip approval" (widen)
    # from "never skip approval" (safety lesson) — measured non-separable (R20) —
    # and chasing it across languages means chasing every language's word order
    # and grammar forever: three rounds of tuning kept over-blocking real safety
    # lessons (Korean verb-final lessons were rejected wholesale) while still
    # leaking assertions past the look-back window. A memory STRING cannot widen a
    # tool permission on its own — the PreToolUse broker is the only real
    # chokepoint (deny beats bypassPermissions), and recall framing ("reference,
    # not rules") is the only misevolution mitigation with measured effect
    # (injection.referenceFraming). Screening is delegated entirely to those two
    # layers; no capabilityWidening rule remains.
    if len(_normalize(content)) < int(_rule("limits.minContentChars", 12)):
        return ("reject", "too-short")
    if _content_hash(content) in durable_hashes:
        return ("deduped", "already-durable")
    # Near-duplicate merge. The server judge has always returned `merge` for a
    # candidate that repeats an existing one, and the ruleset carries the prefix
    # length, but neither local executor read it — so only byte-identical repeats
    # were caught. Measured on 2026-08-11 this catches nothing in the current
    # drawer (no pair scores above 0.4 token overlap); it is here so the contract
    # is one rule rather than three, and so a future repeat is caught on arrival.
    prefix = int(_rule("limits.serverMergeSimilarityPrefixChars", 40))
    if prefix > 0 and durable_prefixes:
        head = _normalize(content)[:prefix]
        twin = (durable_prefixes or {}).get(head) if isinstance(durable_prefixes, dict) else None
        if twin is not None and len(head) >= prefix:
            # A shared opening is a candidate, not a verdict: two learnings can
            # start the same way and end somewhere different. Confirm with whole
            # content overlap so merge can never swallow a distinct learning.
            a, b = _recall_tokens(content), _recall_tokens(twin)
            union = a | b
            overlap = len(a & b) / len(union) if union else 0.0
            if overlap >= float(_rule("limits.mergeTokenOverlapMin", 0.6)):
                return ("merge", "near-duplicate-of-durable")
    if kind not in set(_rule("kinds.promotable", list(PROMOTABLE_KINDS))):
        return ("defer", f"kind-not-promotable:{kind}")
    if not evidence:
        return ("defer", "evidence-required")
    # R21 W2a — evidence must be machine-checkable in SHAPE (path:line, URL,
    # command, hash, test/gate name). A candidate whose only support is
    # self-reported satisfaction ("user rating 5/5") never reaches durable —
    # this blocks the arXiv:2509.26354 refund reward-hacking case by evidence
    # shape, after semantic screening measured non-separable (R20). ANY single
    # well-shaped entry passes, so real evidence is never starved (harness B3).
    shape_re = _rule_re("evidenceShapeAccept")
    if not any(shape_re.search(str(item)) for item in evidence):
        return ("defer", "evidence-shape-insufficient")
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


def _durable_prefixes(soul_path: Path, prefix_chars: int) -> dict[str, str]:
    """Map each durable head to its full text, for the near-duplicate merge rule.

    The full text is what lets merge confirm a shared opening is actually the
    same learning rather than two that begin alike.
    """
    if prefix_chars <= 0 or not soul_path.exists():
        return {}
    try:
        blocks = parse_durable_blocks(soul_path.read_text(encoding="utf-8"))
    except OSError:
        return {}
    heads: dict[str, str] = {}
    for block in blocks:
        text = _normalize(block["content"])
        if len(text) >= prefix_chars:
            heads.setdefault(text[:prefix_chars], block["content"])
    return heads


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


def _decide_chip(root: Path, chip_id: str, decision: str, reason: str) -> dict[str, Any]:
    """Apply a person's decision to one chip candidate.

    Automatic promotion stays banned — measured behaviour showed it is unsafe.
    But banning it without building this path left the gate unreachable: every
    chip stayed a candidate forever and nothing could ever be promoted. A ban
    needs a door, or it is a wall.
    """
    root = Path(root).expanduser()
    db_path = root / META_DIR / EXPERIENCE_DB_FILE
    if not db_path.exists():
        return {"ok": False, "error": "no-experience-store"}
    status_for = {"promote": "promoted", "reject": "rejected"}
    if decision not in status_for:
        return {"ok": False, "error": f"unknown-decision:{decision}"}
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT status FROM experience_candidates WHERE id = ?", (chip_id,)
        ).fetchone()
        if row is None:
            # Never report a decision that was not applied to anything.
            return {"ok": False, "error": "chip-not-found", "chip": chip_id}
        now = _now()
        conn.execute(
            "UPDATE experience_candidates SET status = ?, updated_at = ? WHERE id = ?",
            (status_for[decision], now, chip_id),
        )
        # Sequence the receipt id off the existing count: a wall-clock suffix
        # collides when the creation and the decision land in the same millisecond.
        seq = conn.execute(
            "SELECT COUNT(*) FROM experience_promotion_receipts WHERE candidate_id = ?",
            (chip_id,),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO experience_promotion_receipts"
            " (id, candidate_id, decision, reason, evidence, created_at) VALUES (?,?,?,?,?,?)",
            (f"{chip_id}-d{seq + 1}", chip_id,
             "admit" if decision == "promote" else "reject",
             reason or f"owner decision: {decision}", "[]", now),
        )
        conn.commit()
        return {"ok": True, "chip": chip_id, "from": row[0], "to": status_for[decision]}
    finally:
        conn.close()


def promote_chip(root: Path, chip_id: str, reason: str = "") -> dict[str, Any]:
    """Promote one chip candidate after a person reviewed it."""
    return _decide_chip(root, chip_id, "promote", reason)


def reject_chip(root: Path, chip_id: str, reason: str = "") -> dict[str, Any]:
    """Reject one chip candidate after a person reviewed it."""
    return _decide_chip(root, chip_id, "reject", reason)


def list_chips(root: Path, status: str = "", limit: int = 20) -> list[dict[str, Any]]:
    """List chip candidates so a person can see what is waiting for a decision."""
    root = Path(root).expanduser()
    db_path = root / META_DIR / EXPERIENCE_DB_FILE
    if not db_path.exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        sql = "SELECT id, status, scope_key, summary, created_at FROM experience_candidates"
        args: tuple[Any, ...] = ()
        if status:
            sql += " WHERE status = ?"
            args = (status,)
        sql += " ORDER BY created_at DESC LIMIT ?"
        rows = conn.execute(sql, (*args, max(1, int(limit)))).fetchall()
        return [
            {"id": r[0], "status": r[1], "scope": r[2], "summary": r[3][:160], "createdAt": r[4]}
            for r in rows
        ]
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
    durable_prefixes = _durable_prefixes(
        soul_path, int(_rule("limits.serverMergeSimilarityPrefixChars", 40))
    )

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
                action, reason = _classify(candidate, durable, durable_prefixes)
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
                # The drawer declares which scopes belong to a cross-project
                # identity. Recording the boundary keeps it observable without
                # discarding anything: half the live drawer is project-scope
                # today, so enforcing silently would drop real learnings.
                **({"outsideOneBoundary": True}
                   if str(candidate.get("scope") or "") not in set(
                       _rule("scopes.oneForwardable", ["agent_repo", "user_identity"]))
                   else {}),
                "createdAt": _now(),
            }, ensure_ascii=False) + "\n")

    # G8 — monthly rotation of decided tickets (idempotent; lock-guarded).
    # Failure must never block curation results.
    try:
        rotate_one_ledgers(root)
    except Exception:
        pass

    # Keep the semantic projection current. Incremental and idempotent; a failure
    # only costs semantic rank for the new blocks, never the curation result.
    try:
        index_durable_blocks(root)
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
    """Scoring tokens, with attached punctuation removed and stopwords dropped.

    The earlier pattern kept `.` inside the token, so `한다` and `한다.` ranked as
    different terms and a question rarely matched whichever surface form a block
    happened to use.
    """
    stop = set(_rule("recallBudgets.one.stopwords", []))
    tokens: set[str] = set()
    for raw in re.findall(r"[A-Za-z가-힣0-9_./-]{2,}", text.lower()):
        tok = raw.strip("./-_")
        if len(tok) >= 2 and tok not in stop:
            tokens.add(tok)
    return tokens


def _token_matches(block_token: str, q_tokens: set[str]) -> bool:
    """Korean glues particles onto the stem, so set equality under-matches.

    `캐시` has to reach `캐시가`. Accept a shared prefix while the length gap stays
    small; a wider gap is a different word rather than an inflection.
    """
    if block_token in q_tokens:
        return True
    for q in q_tokens:
        shorter, longer = (q, block_token) if len(q) <= len(block_token) else (block_token, q)
        if len(shorter) >= 2 and len(longer) - len(shorter) <= 2 and longer.startswith(shorter):
            return True
    return False


def _idf_table(blocks: list[dict[str, str]]) -> dict[str, float]:
    """Document frequency over the durable corpus — a common term must weigh less."""
    total = max(len(blocks), 1)
    df: dict[str, int] = {}
    for block in blocks:
        for tok in _recall_tokens(block["content"]):
            df[tok] = df.get(tok, 0) + 1
    return {tok: math.log(1.0 + total / count) for tok, count in df.items()}


def _relevance_score(content: str, q_tokens: set[str], idf: dict[str, float]) -> float:
    """Length-normalised IDF overlap.

    Raw overlap counts let a long block win by accumulating incidental matches,
    which is how recall degenerated into "whatever happens to be written last".
    """
    if not q_tokens:
        return 0.0
    block_tokens = _recall_tokens(content)
    if not block_tokens:
        return 0.0
    gained = sum(idf.get(tok, 1.0) for tok in block_tokens if _token_matches(tok, q_tokens))
    if gained <= 0.0:
        return 0.0
    return gained / math.sqrt(len(block_tokens))


RECALL_USAGE_FILE = "recall-usage.json"
# Any engine hit outranks any purely local score, so the two never compete.
_ENGINE_TIER = 1000.0
ONE_INDEX_FILE = "ontology-runtime.sqlite"


_ONE_RUNTIME_CACHE: dict[str, Any] = {}


def _one_runtime(root: Path, create: bool = False):
    """Open the One drawer's semantic index, or return None when unavailable.

    Every other memory layer — project, borrowed agent, Desktop — is served by
    this engine, which is what the public LoCoMo/LongMemEval numbers measured.
    The One drawer was built later on a hand-rolled three-table schema and was
    the only layer left outside it, so its recall stayed lexical while the rest
    of the product searched semantically.

    Imported lazily and fail-open: a host without the ontology package keeps the
    lexical path rather than losing recall entirely.
    """
    path = Path(root).expanduser() / META_DIR / ONE_INDEX_FILE
    if not create and not path.exists():
        return None
    key = str(path)
    cached = _ONE_RUNTIME_CACHE.get(key)
    if cached is not None:
        return cached
    try:
        from ontology import OntologyRuntime, RuntimeConfig  # noqa: PLC0415
    except Exception:
        return None
    try:
        runtime = OntologyRuntime(RuntimeConfig(db_path=path))
    except Exception:
        return None
    # Constructing the runtime dominates the cost — measured 490ms per call
    # versus 56ms once the instance is reused. Recall runs once or twice per
    # session, so paying that on every call was the whole latency story.
    _ONE_RUNTIME_CACHE[key] = runtime
    return runtime


def index_durable_blocks(root: Path, rebuild: bool = False) -> dict[str, Any]:
    """Project durable soul blocks into the semantic index.

    The soul file stays authoritative — this is a rebuildable projection, which
    is exactly what `ingest_experience` is for. Idempotent: the content hash is
    the source id, so re-running costs nothing and never duplicates.
    """
    root = Path(root).expanduser()
    meta = root / META_DIR
    soul = meta / PROJECT_SOUL_FILE
    if not soul.exists():
        return {"indexed": 0, "skipped": "no-soul"}
    try:
        blocks = parse_durable_blocks(soul.read_text(encoding="utf-8"))
    except OSError:
        return {"indexed": 0, "skipped": "unreadable-soul"}
    runtime = _one_runtime(root, create=True)
    if runtime is None:
        return {"indexed": 0, "skipped": "no-ontology-runtime"}

    superseded = _superseded_hashes(meta)
    state_path = meta / "index-state.json"
    try:
        seen = set(json.loads(state_path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        seen = set()
    if rebuild:
        seen = set()

    indexed = 0
    for block in blocks:
        digest = _content_hash(block["content"])
        if digest in superseded or digest in seen:
            continue
        try:
            runtime.ingest_experience(
                agent_id=ONE_AGENT_ID,
                summary=block["content"],
                tags=[block["kind"], block["project"]] if block["project"] else [block["kind"]],
                memory_kind=block["kind"],
                source_memory_id=digest,
                suggested_scope="agent_repo",
                reason="One durable soul projection; the soul file remains authoritative.",
            )
        except Exception:
            continue
        seen.add(digest)
        indexed += 1
    try:
        _atomic_write(state_path, json.dumps(sorted(seen), ensure_ascii=False) + "\n")
    except OSError:
        pass
    return {"indexed": indexed, "durable": len(blocks), "known": len(seen)}


def _semantic_candidates(root: Path, question: str, top_k: int) -> dict[str, float]:
    """Content hash -> rank score from the semantic index, empty when unavailable."""
    if not question.strip():
        return {}
    runtime = _one_runtime(root)
    if runtime is None:
        return {}
    try:
        result = runtime.query_experience(
            question, agent_id=ONE_AGENT_ID, top_k=max(1, top_k), token_budget=200_000
        )
    except Exception:
        return {}
    scores: dict[str, float] = {}
    items = result.get("items") if isinstance(result, dict) else None
    for position, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        digest = str(item.get("source_memory_id") or "")
        if not digest:
            text = str(item.get("candidate_text") or "")
            digest = _content_hash(text) if text else ""
        if digest:
            # Reciprocal rank: position matters, absolute engine scores do not
            # have to be commensurable with the lexical score.
            scores.setdefault(digest, 1.0 / (1.0 + position))
    return scores


def record_recall_receipt(root: Path, block_hashes: list[str]) -> None:
    """Count which durable blocks recall actually delivered.

    Kept as a bounded counter sidecar rather than a ledger line: the file can
    never grow past the number of durable blocks, while an append-per-session
    ledger would grow without limit for a signal that only needs a total.

    Recall itself stays pure — the caller decides to record, so read-only
    measurement never mutates the drawer.
    """
    if not block_hashes:
        return
    root = Path(root).expanduser()
    path = root / META_DIR / RECALL_USAGE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    now = _now()
    for digest in block_hashes:
        row = data.get(digest)
        count = int(row.get("count", 0)) if isinstance(row, dict) else 0
        data[digest] = {"count": count + 1, "lastAt": now}
    try:
        _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=1) + "\n")
    except OSError:
        # Observability must never break a session.
        return


def recall_coverage(root: Path) -> dict[str, Any]:
    """Report how much durable memory recall has ever surfaced.

    Without this number a ranking change cannot be evaluated: the drawer grows
    while the per-session budget stays fixed, so reach is the thing to watch.
    """
    root = Path(root).expanduser()
    meta = root / META_DIR
    try:
        blocks = parse_durable_blocks((meta / PROJECT_SOUL_FILE).read_text(encoding="utf-8"))
    except OSError:
        return {"durable": -1, "everRecalled": -1, "neverRecalled": -1, "reachedPct": -1.0}
    try:
        data = json.loads((meta / RECALL_USAGE_FILE).read_text(encoding="utf-8"))
        seen = set(data) if isinstance(data, dict) else set()
    except (OSError, ValueError):
        seen = set()
    digests = {_content_hash(block["content"]) for block in blocks}
    reached = len(digests & seen)
    total = len(digests)
    return {
        "durable": total,
        "everRecalled": reached,
        "neverRecalled": total - reached,
        "reachedPct": round(reached * 100.0 / total, 1) if total else 0.0,
    }


def rank_one_blocks(
    eligible: list[tuple[int, dict[str, str]]],
    question: str,
    *,
    root: Path,
    current_slug: str = "",
    semantic: dict[str, float] | None = None,
    idf: dict[str, float] | None = None,
    q_tokens: set[str] | None = None,
    min_relevance: float | None = None,
    boost: float | None = None,
    semantic_weight: float | None = None,
) -> list[tuple[float, int, dict[str, str]]]:
    """Order eligible blocks for a question. The single ranking implementation.

    When the index answers, its order wins: measured on LongMemEval (200 items,
    recall@10) the engine reached 96.5% while a local score reached 93.5%, so
    re-ranking the better ranker only loses ground. The local score still decides
    among blocks the engine did not return, so lexical matches are never dropped.

    Kept separate from `select_one_recall` because recall@k has to see the whole
    ranking while a session sees only what fits the capsule budget — and because
    a benchmark that re-implements the ranking measures the copy, not the product.
    """
    if q_tokens is None:
        q_tokens = _recall_tokens(question)
    if idf is None:
        idf = _idf_table([block for _index, block in eligible]) if q_tokens else {}
    if semantic is None:
        semantic = _semantic_candidates(root, question, max(8, len(eligible)))
    if min_relevance is None:
        min_relevance = float(_rule("recallBudgets.one.minRelevanceScore", 0.35))
    if boost is None:
        boost = float(_rule("recallBudgets.one.currentSlugBoost", 1.5))
    if semantic_weight is None:
        semantic_weight = float(_rule("recallBudgets.one.semanticWeight", 1.0))

    ranked: list[tuple[float, int, dict[str, str]]] = []
    for index, block in eligible:
        engine_rank = semantic.get(_content_hash(block["content"]), 0.0)
        if engine_rank > 0.0:
            # Above every locally scored block, ordered by the engine's own rank.
            score = _ENGINE_TIER + semantic_weight * engine_rank
        else:
            score = _relevance_score(block["content"], q_tokens, idf)
            if score < min_relevance:
                continue
            # The current project is a weight, not a filter — personal craft has
            # to stay reachable across projects (owner decision), but it must not
            # win on its own with zero relevance. The engine tier is left alone so
            # this can never reorder a better ranker.
            if current_slug and block["slug"] == current_slug:
                score *= boost
        ranked.append((score, index, block))
    ranked.sort(key=lambda item: (-item[0], -item[1]))
    return ranked


def select_one_recall_detailed(
    question: str,
    workspace: str = "",
    root: Path | None = None,
) -> tuple[list[str], list[str]]:
    """Recall lines plus the content hash of each selected block, for receipts."""
    lines = select_one_recall(question, workspace=workspace, root=root)
    hashes: list[str] = []
    for line in lines:
        body = line.split("]: ", 1)[-1]
        hashes.append(_content_hash(body))
    return lines, hashes


def select_one_recall(
    question: str,
    workspace: str = "",
    root: Path | None = None,
) -> list[str]:
    """P3 — pick the One know-how lines for a session capsule.

    Relevance owns the budget. A question that matches nothing gets the small
    current-project fallback instead of the whole budget, because the previous
    rule (every current-project block scores above zero, ties broken by file
    order) made an unrelated question and an empty question return the same
    lines — measured identical on 2026-08-11.

    Facts get their own small slot rather than the L1 kinds list: they were
    excluded outright, and the ruleset's claim that the project layer recalls
    them instead has no code path for the One drawer.
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
    fact_slots = int(_rule("recallBudgets.one.factSlotMaxBlocks", 1))
    off_topic_max = int(_rule("recallBudgets.one.offTopicMaxBlocks", 2))
    min_relevance = float(_rule("recallBudgets.one.minRelevanceScore", 0.35))
    current_slug = resolve_project_slug(workspace)

    eligible: list[tuple[int, dict[str, str]]] = []
    for index, block in enumerate(blocks):
        if block["kind"] not in l1_kinds and block["kind"] != "fact":
            continue
        # G8 — explicitly superseded blocks never resurface in recall.
        if _content_hash(block["content"]) in superseded:
            continue
        slug = block["project"] or str((sidecar.get(block["ticket"]) or {}).get("slug") or "")
        eligible.append((index, {**block, "slug": slug}))
    if not eligible:
        return []

    q_tokens = _recall_tokens(question)
    idf = _idf_table([block for _index, block in eligible]) if q_tokens else {}

    # Semantic half of the hybrid. The same engine already serves every other
    # memory layer; here it contributes rank, and lexical contributes the rest,
    # so a block phrased differently from the question can still be found.
    semantic = _semantic_candidates(root, question, max_blocks * 4)
    semantic_weight = float(_rule("recallBudgets.one.semanticWeight", 1.0))

    relevant = rank_one_blocks(
        eligible, question, root=root, current_slug=current_slug,
        semantic=semantic, idf=idf, q_tokens=q_tokens,
        min_relevance=min_relevance, boost=boost, semantic_weight=semantic_weight,
    )

    picks: list[dict[str, str]] = []
    if relevant:
        facts_taken = 0
        for _score, _index, block in relevant:
            if block["kind"] == "fact":
                if facts_taken >= fact_slots:
                    continue
                facts_taken += 1
            picks.append(block)
            if len(picks) >= max_blocks:
                break
    else:
        # Nothing matched. Fall back to the newest current-project craft, capped
        # well below the full budget so an unrelated question cannot spend it.
        limit = max_blocks if not q_tokens else off_topic_max
        fallback = [
            block for _index, block in eligible
            if block["kind"] in l1_kinds and (not current_slug or block["slug"] == current_slug)
        ]
        picks = fallback[-limit:][::-1] if limit else []

    lines: list[str] = []
    used = 0
    seen: set[str] = set()
    for block in picks:
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
    # Promotion has to be countable, or a promotion path that silently never runs
    # looks exactly like one that works.
    promoted_chips = pending_chips = -1
    if exp_db.exists():
        conn = sqlite3.connect(f"file:{exp_db}?mode=ro", uri=True)
        try:
            chips = conn.execute("SELECT COUNT(*) FROM experience_candidates").fetchone()[0]
            packs = conn.execute("SELECT COUNT(*) FROM experience_packs").fetchone()[0]
            orphan_chips = conn.execute(
                "SELECT COUNT(*) FROM experience_candidates WHERE pack_id IS NULL"
            ).fetchone()[0]
            promoted_chips = conn.execute(
                "SELECT COUNT(*) FROM experience_candidates WHERE status = 'promoted'"
            ).fetchone()[0]
            pending_chips = conn.execute(
                "SELECT COUNT(*) FROM experience_candidates WHERE status = 'candidate'"
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
        "promotedChips": promoted_chips,
        "chipsAwaitingDecision": pending_chips,
        "soulBytes": (meta / PROJECT_SOUL_FILE).stat().st_size if (meta / PROJECT_SOUL_FILE).exists() else -1,
    }


def _main(argv: list[str]) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="one_workspace")
    parser.add_argument("command", choices=[
        "seed", "status", "emit", "receipt", "stop-hook", "curate",
        "chips", "promote", "reject", "recall-coverage",
    ])
    parser.add_argument("--chip", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--status", dest="chip_status", default="")
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
    elif args.command == "chips":
        out = {"chips": list_chips(root, args.chip_status)}
    elif args.command in ("promote", "reject"):
        if not args.chip.strip():
            print("--chip must name a chip id", flush=True)
            return 2
        decide = promote_chip if args.command == "promote" else reject_chip
        out = decide(root, args.chip.strip(), args.reason)
        if not out.get("ok"):
            print(json.dumps(out, ensure_ascii=False), flush=True)
            return 1
    elif args.command == "recall-coverage":
        out = recall_coverage(root)
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
        # Session flow stays unblocked. The one thing that is surfaced is a
        # fact the user cannot otherwise see: a Workforce roster that was
        # prepared and never executed. A warning, never a block — the decision
        # is the person's; only the silence is removed.
        notice = out.get("workforceNotice") if isinstance(out, dict) else ""
        print(json.dumps({"systemMessage": notice} if notice else {}, ensure_ascii=False))
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
