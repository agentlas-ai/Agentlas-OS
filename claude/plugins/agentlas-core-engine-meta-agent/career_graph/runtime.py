from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

AGENTLAS_DIR = ".agentlas"
CONFIG_FILE = "career-graph.json"
SOURCE_MANIFEST_FILE = "career-graph-sources.json"
INBOX_DIR = "career-graph-inbox"
DB_FILE = "career-graph.sqlite"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_id(prefix: str, *parts: Any) -> str:
    raw = "\x1f".join(str(part) for part in parts)
    return f"{prefix}:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]}"


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def compact_text(value: Any, limit: int = 8000) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            text = str(value)
    text = " ".join(text.split())
    return text[:limit]


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 256), b""):
            digest.update(chunk)
    return digest.hexdigest()


def iter_jsonl(path: Path) -> Iterable[tuple[int, dict[str, Any]]]:
    if not path.is_file():
        return
    for line_no, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            item = {"raw": line, "parse_error": "json_decode"}
        if isinstance(item, dict):
            yield line_no, item
        else:
            yield line_no, {"value": item}


@dataclass(frozen=True)
class RuntimeConfig:
    project: Path
    db_path: Path | None = None
    include_networking_home: bool = False

    @property
    def root(self) -> Path:
        return Path(self.project).expanduser().resolve()

    @property
    def agentlas_dir(self) -> Path:
        return self.root / AGENTLAS_DIR

    @property
    def sqlite_path(self) -> Path:
        return Path(self.db_path).expanduser().resolve() if self.db_path else self.agentlas_dir / DB_FILE


class CareerGraphRuntime:
    """Derived graph index over Agentlas ledger files.

    The graph is rebuildable. Canonical Markdown/JSONL/JSON files remain the
    source of truth; this runtime only stores source pointers and typed links.
    """

    def __init__(self, config: RuntimeConfig):
        self.config = config

    # -- setup -----------------------------------------------------------------
    def ensure_files(self) -> dict[str, Any]:
        root = self.config.root
        agentlas = self.config.agentlas_dir
        inbox = agentlas / INBOX_DIR
        db_path = self.config.sqlite_path
        agentlas.mkdir(parents=True, exist_ok=True)
        inbox.mkdir(parents=True, exist_ok=True)

        config_path = agentlas / CONFIG_FILE
        if not config_path.exists():
            config_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "1.0",
                        "kind": "agentlas-career-graph",
                        "state": "active",
                        "model": "ledger_first_derived_index",
                        "projectRoot": str(root),
                        "dbPath": str(db_path),
                        "inboxPath": str(inbox),
                        "sourceManifest": str(agentlas / SOURCE_MANIFEST_FILE),
                        "canonicalSourcePolicy": {
                            "sourceOfTruth": "markdown_jsonl_json",
                            "graphIsRebuildable": True,
                            "fallbackWhenStale": "read_canonical_files",
                            "neverScanHomeDirectory": True,
                            "neverScanSiblingProjects": True,
                        },
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

        manifest_path = agentlas / SOURCE_MANIFEST_FILE
        if not manifest_path.exists():
            manifest_path.write_text(
                json.dumps(
                    {
                        "schemaVersion": "1.0",
                        "kind": "agentlas-career-graph-source-manifest",
                        "projectRoot": str(root),
                        "sources": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )

        return {
            "project_root": str(root),
            "agentlas_dir": str(agentlas),
            "config_path": str(config_path),
            "source_manifest": str(manifest_path),
            "inbox_path": str(inbox),
            "db_path": str(db_path),
        }

    def connect(self) -> sqlite3.Connection:
        self.ensure_files()
        conn = sqlite3.connect(self.config.sqlite_path)
        conn.row_factory = sqlite3.Row
        self._ensure_schema(conn)
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ingest_runs (
              run_id TEXT PRIMARY KEY,
              project_root TEXT NOT NULL,
              started_at TEXT NOT NULL,
              finished_at TEXT,
              status TEXT NOT NULL,
              source_count INTEGER NOT NULL DEFAULT 0,
              node_count INTEGER NOT NULL DEFAULT 0,
              edge_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS sources (
              source_id TEXT PRIMARY KEY,
              path TEXT NOT NULL,
              kind TEXT NOT NULL,
              checksum TEXT,
              mtime REAL,
              size INTEGER,
              line_count INTEGER,
              last_ingested_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS nodes (
              node_id TEXT PRIMARY KEY,
              node_type TEXT NOT NULL,
              label TEXT NOT NULL,
              text TEXT,
              source_path TEXT,
              source_line INTEGER,
              source_ref TEXT,
              payload_json TEXT,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS edges (
              edge_id TEXT PRIMARY KEY,
              from_node TEXT NOT NULL,
              to_node TEXT NOT NULL,
              edge_type TEXT NOT NULL,
              label TEXT,
              source_path TEXT,
              payload_json TEXT,
              created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(node_type);
            CREATE INDEX IF NOT EXISTS idx_nodes_source ON nodes(source_path);
            CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_node);
            CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_node);
            """
        )
        conn.commit()

    # -- ingest ----------------------------------------------------------------
    def ingest(self, rebuild: bool = True) -> dict[str, Any]:
        self.ensure_files()
        started = utc_now()
        run_id = stable_id("ingest", self.config.root, started)
        sources = self._canonical_sources()
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        project_node = self._node(
            "Project",
            stable_id("project", self.config.root),
            self.config.root.name,
            str(self.config.root),
            source_path=str(self.config.root),
        )
        nodes.append(project_node)

        for source in sources:
            source_nodes, source_edges = self._ingest_source(source, project_node["node_id"])
            nodes.extend(source_nodes)
            edges.extend(source_edges)

        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO ingest_runs(run_id, project_root, started_at, status) VALUES (?, ?, ?, ?)",
                (run_id, str(self.config.root), started, "running"),
            )
            if rebuild:
                conn.execute("DELETE FROM edges")
                conn.execute("DELETE FROM nodes")
                conn.execute("DELETE FROM sources")
            for source in sources:
                self._write_source(conn, source, started)
            for node in nodes:
                self._write_node(conn, node)
            for edge in edges:
                self._write_edge(conn, edge)
            finished = utc_now()
            conn.execute(
                """
                UPDATE ingest_runs
                SET finished_at = ?, status = ?, source_count = ?, node_count = ?, edge_count = ?
                WHERE run_id = ?
                """,
                (finished, "ok", len(sources), len(nodes), len(edges), run_id),
            )
            conn.commit()

        return {
            "status": "ok",
            "project": str(self.config.root),
            "db_path": str(self.config.sqlite_path),
            "run_id": run_id,
            "sources": len(sources),
            "nodes": len(nodes),
            "edges": len(edges),
            "rebuild": rebuild,
        }

    def _canonical_sources(self) -> list[dict[str, Any]]:
        agentlas = self.config.agentlas_dir
        sources: list[dict[str, Any]] = []

        def add(kind: str, path: Path) -> None:
            if path.exists():
                sources.append({"kind": kind, "path": path})

        add("project_memory", agentlas / "project-soul-memory.md")
        add("memory_log", agentlas / "memory-log.jsonl")
        add("memory_tickets", agentlas / "memory-tickets.jsonl")
        add("curator_decisions", agentlas / "curator-decisions.jsonl")
        add("sitemap", agentlas / "sitemap.json")
        add("code_map", agentlas / "code-map" / "project-map.json")

        journal_dir = agentlas / "stormbreaker" / "journal"
        if journal_dir.is_dir():
            for path in sorted(journal_dir.glob("*.jsonl")):
                add("run_journal", path)

        local_ledgers = agentlas / "ledgers"
        if local_ledgers.is_dir():
            for name in ("routing-decisions.jsonl", "executions.jsonl", "agent-evolution-proposals.jsonl"):
                add(name.replace(".jsonl", "").replace("-", "_"), local_ledgers / name)

        if self.config.include_networking_home:
            home = Path(os.environ.get("AGENTLAS_NETWORKING_HOME", "~/.agentlas/networking")).expanduser()
            for name in ("routing-decisions.jsonl", "executions.jsonl"):
                add(f"networking_{name.replace('.jsonl', '').replace('-', '_')}", home / "ledgers" / name)

        manifest = read_json(agentlas / SOURCE_MANIFEST_FILE, default={}) or {}
        for item in manifest.get("sources", []) if isinstance(manifest, dict) else []:
            if not isinstance(item, dict):
                continue
            path = Path(str(item.get("path") or "")).expanduser()
            if not path.is_absolute():
                path = self.config.root / path
            add(f"registered_{item.get('kind') or 'source'}", path)

        return sources

    def _ingest_source(self, source: dict[str, Any], project_node: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        kind = source["kind"]
        path = Path(source["path"])
        if kind == "project_memory":
            node = self._node("ProjectMemory", stable_id("project-memory", path), path.name, path.read_text(encoding="utf-8", errors="replace"), path)
            return [node], [self._edge(project_node, node["node_id"], "has_memory", path)]
        if kind in {
            "memory_log",
            "memory_tickets",
            "curator_decisions",
            "run_journal",
            "routing_decisions",
            "executions",
            "agent_evolution_proposals",
            "networking_routing_decisions",
            "networking_executions",
        }:
            return self._ingest_jsonl(path, kind, project_node)
        if kind == "sitemap":
            return self._ingest_sitemap(path, project_node)
        if kind == "code_map":
            return self._ingest_code_map(path, project_node)
        return self._ingest_registered(path, kind, project_node)

    def _ingest_jsonl(self, path: Path, kind: str, project_node: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        node_type = {
            "memory_log": "MemoryEvent",
            "memory_tickets": "MemoryTicket",
            "curator_decisions": "CuratorDecision",
            "run_journal": "RunStep",
            "routing_decisions": "RoutingDecision",
            "executions": "ExecutionReceipt",
            "agent_evolution_proposals": "EvolutionProposal",
            "networking_routing_decisions": "RoutingDecision",
            "networking_executions": "ExecutionReceipt",
        }.get(kind, "LedgerEvent")
        edge_type = {
            "MemoryEvent": "has_memory_event",
            "MemoryTicket": "has_memory_ticket",
            "CuratorDecision": "has_curator_decision",
            "RunStep": "has_run_step",
            "RoutingDecision": "has_routing_decision",
            "ExecutionReceipt": "has_execution_receipt",
            "EvolutionProposal": "has_evolution_proposal",
        }.get(node_type, "has_ledger_event")
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        for line_no, item in iter_jsonl(path):
            label = self._label_for_item(item, fallback=f"{node_type} line {line_no}")
            text = compact_text(item.get("content") or item.get("summary") or item.get("detail") or item)
            node = self._node(node_type, stable_id(node_type.lower(), path, line_no, text), label, text, path, line_no, item)
            nodes.append(node)
            edges.append(self._edge(project_node, node["node_id"], edge_type, path, item))
            derived_nodes, derived_edges = self._derived_ledger_nodes(item, node, kind, path, line_no, project_node)
            nodes.extend(derived_nodes)
            edges.extend(derived_edges)
        return nodes, edges

    def _derived_ledger_nodes(
        self,
        item: dict[str, Any],
        parent_node: dict[str, Any],
        kind: str,
        path: Path,
        line_no: int,
        project_node: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        failure_text = self._failure_signature_text(item, kind)
        if failure_text:
            label = str(item.get("signature") or item.get("step_id") or item.get("receipt_id") or "failure")
            payload = {
                "sourceKind": kind,
                "stepId": item.get("step_id"),
                "receiptId": item.get("receipt_id"),
                "event": item.get("event"),
                "status": item.get("status"),
                "error": failure_text,
            }
            failure = self._node(
                "FailureSignature",
                stable_id("failure-signature", path, line_no, label, failure_text),
                label,
                failure_text,
                path,
                line_no,
                payload,
            )
            nodes.append(failure)
            edges.append(self._edge(project_node, failure["node_id"], "has_failure_signature", path, payload))
            edges.append(self._edge(parent_node["node_id"], failure["node_id"], "produced_failure_signature", path, payload))

        for candidate in self._playbook_candidates(item):
            label = str(candidate.get("id") or candidate.get("kind") or "playbook_candidate")
            text = compact_text(candidate.get("summary") or candidate.get("title") or candidate)
            playbook = self._node(
                "PlaybookCandidate",
                stable_id("playbook-candidate", path, line_no, label, text),
                label,
                text,
                path,
                line_no,
                candidate,
            )
            nodes.append(playbook)
            edges.append(self._edge(project_node, playbook["node_id"], "has_playbook_candidate", path, candidate))
            edges.append(self._edge(parent_node["node_id"], playbook["node_id"], "suggests_playbook_candidate", path, candidate))
        return nodes, edges

    def _failure_signature_text(self, item: dict[str, Any], kind: str) -> str | None:
        event = str(item.get("event") or item.get("action") or "").lower()
        status = str(item.get("status") or item.get("verdict") or "").lower()
        failed = event in {"fail", "failed", "error"} or status in {"fail", "failed", "error", "blocked"}
        if not failed:
            return None
        raw = item.get("error") or item.get("message") or item.get("detail") or item.get("summary") or item.get("reason")
        if raw is None:
            raw = {"event": item.get("event"), "status": item.get("status"), "sourceKind": kind}
        return compact_text(raw)

    def _playbook_candidates(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        memory_playbook = item.get("memory_playbook")
        if isinstance(memory_playbook, dict) and isinstance(memory_playbook.get("candidates"), list):
            candidates.extend(candidate for candidate in memory_playbook["candidates"] if isinstance(candidate, dict))
        if isinstance(item.get("playbook_candidates"), list):
            candidates.extend(candidate for candidate in item["playbook_candidates"] if isinstance(candidate, dict))
        if isinstance(item.get("candidate"), dict) and str(item["candidate"].get("kind") or "").endswith("playbook_candidate"):
            candidates.append(item["candidate"])
        if str(item.get("kind") or "").endswith("playbook_candidate"):
            candidates.append(item)
        return candidates

    def _ingest_sitemap(self, path: Path, project_node: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        data = read_json(path, default={}) or {}
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        by_id: dict[str, str] = {}
        for index, item in enumerate(data.get("nodes", []) if isinstance(data, dict) else []):
            if not isinstance(item, dict):
                continue
            label = str(item.get("id") or item.get("node_id") or item.get("name") or f"sitemap-node-{index}")
            node = self._node("SitemapNode", stable_id("sitemap", path, label), label, compact_text(item), path, None, item)
            nodes.append(node)
            by_id[label] = node["node_id"]
            edges.append(self._edge(project_node, node["node_id"], "has_sitemap_node", path, item))
        for item in data.get("edges", []) if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            src = by_id.get(str(item.get("from") or ""))
            dst = by_id.get(str(item.get("to") or ""))
            if src and dst:
                edges.append(self._edge(src, dst, str(item.get("kind") or item.get("type") or "relates_to"), path, item))
        return nodes, edges

    def _ingest_code_map(self, path: Path, project_node: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        data = read_json(path, default={}) or {}
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        modules: dict[str, str] = {}
        for item in data.get("modules", []) if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("id") or item.get("path") or "module")
            node = self._node("CodeModule", stable_id("code-module", path, label), label, compact_text(item), path, None, item)
            nodes.append(node)
            modules[label] = node["node_id"]
            edges.append(self._edge(project_node, node["node_id"], "has_code_module", path, item))
        for item in data.get("entryPoints", []) if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("path") or "entry")
            node = self._node("CodeEntryPoint", stable_id("code-entry", path, label), label, compact_text(item), path, None, item)
            nodes.append(node)
            edges.append(self._edge(project_node, node["node_id"], "has_entry_point", path, item))
        for item in data.get("topSymbols", []) if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            label = str(item.get("name") or item.get("key") or "symbol")
            node = self._node("CodeSymbol", stable_id("code-symbol", path, item.get("defAt") or label), label, compact_text(item), path, None, item)
            nodes.append(node)
            edges.append(self._edge(project_node, node["node_id"], "has_code_symbol", path, item))
        for item in data.get("moduleEdges", []) if isinstance(data, dict) else []:
            if not isinstance(item, dict):
                continue
            raw = str(item.get("edge") or "")
            unicode_arrow = "\u2192"
            if unicode_arrow in raw:
                left, right = [part.strip() for part in raw.split(unicode_arrow, 1)]
            elif "->" in raw:
                left, right = [part.strip() for part in raw.split("->", 1)]
            else:
                continue
            if left in modules and right in modules:
                edges.append(self._edge(modules[left], modules[right], "references_module", path, item))
        return nodes, edges

    def _ingest_registered(self, path: Path, kind: str, project_node: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if path.is_dir():
            text = f"Registered career graph source directory: {path}"
        else:
            text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else str(path)
        node = self._node("RegisteredSource", stable_id("registered-source", path), path.name, text, path, None, {"kind": kind})
        return [node], [self._edge(project_node, node["node_id"], "has_registered_source", path, {"kind": kind})]

    # -- readers ---------------------------------------------------------------
    def status(self) -> dict[str, Any]:
        files = self.ensure_files()
        exists = self.config.sqlite_path.exists()
        counts = {"sources": 0, "nodes": 0, "edges": 0}
        stale: list[dict[str, Any]] = []
        if exists:
            with self.connect() as conn:
                counts = {
                    "sources": conn.execute("SELECT count(*) FROM sources").fetchone()[0],
                    "nodes": conn.execute("SELECT count(*) FROM nodes").fetchone()[0],
                    "edges": conn.execute("SELECT count(*) FROM edges").fetchone()[0],
                }
                known = {row["path"]: row for row in conn.execute("SELECT path, checksum FROM sources")}
            for source in self._canonical_sources():
                path = Path(source["path"])
                old = known.get(str(path))
                if old and path.is_file() and old["checksum"] != file_checksum(path):
                    stale.append({"path": str(path), "reason": "checksum_changed"})
                elif not old:
                    stale.append({"path": str(path), "reason": "not_ingested"})
        return {
            "status": "active",
            **files,
            "db_exists": exists,
            "counts": counts,
            "canonical_sources": len(self._canonical_sources()),
            "stale": stale,
            "policy": "ledger_first_derived_index",
        }

    def query(self, text: str, limit: int = 8) -> dict[str, Any]:
        if not self.config.sqlite_path.exists():
            return {"status": "missing_index", "query": text, "results": [], "hint": "run career-graph ingest first"}
        terms = [term.lower() for term in text.split() if len(term) > 1]
        with self.connect() as conn:
            rows = [dict(row) for row in conn.execute("SELECT * FROM nodes")]
        scored: list[tuple[int, dict[str, Any]]] = []
        for row in rows:
            hay = f"{row.get('label') or ''} {row.get('text') or ''} {row.get('node_type') or ''}".lower()
            score = sum(hay.count(term) for term in terms)
            if score:
                row["payload"] = read_payload(row.pop("payload_json", None))
                scored.append((score, row))
        scored.sort(key=lambda pair: (-pair[0], pair[1]["node_type"], pair[1]["label"]))
        return {
            "status": "ok",
            "query": text,
            "results": [
                {
                    "score": score,
                    "node_id": row["node_id"],
                    "type": row["node_type"],
                    "label": row["label"],
                    "source_ref": row["source_ref"],
                    "text": (row.get("text") or "")[:500],
                }
                for score, row in scored[:limit]
            ],
        }

    def trace(self, node_or_edge_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            node = conn.execute("SELECT * FROM nodes WHERE node_id = ?", (node_or_edge_id,)).fetchone()
            if node:
                edges = [dict(row) for row in conn.execute("SELECT * FROM edges WHERE from_node = ? OR to_node = ?", (node_or_edge_id, node_or_edge_id))]
                return {"status": "ok", "kind": "node", "node": dict(node), "edges": edges}
            edge = conn.execute("SELECT * FROM edges WHERE edge_id = ?", (node_or_edge_id,)).fetchone()
            if edge:
                return {"status": "ok", "kind": "edge", "edge": dict(edge)}
        return {"status": "not_found", "id": node_or_edge_id}

    def verify(self) -> dict[str, Any]:
        status = self.status()
        issues: list[str] = []
        if not status["db_exists"]:
            issues.append("career graph index is missing")
        if status["counts"]["nodes"] == 0:
            issues.append("career graph has zero nodes")
        if status["stale"]:
            issues.append("career graph has stale or unindexed canonical sources")
        return {**status, "verify_status": "pass" if not issues else "fail", "issues": issues}

    def public_card(self, write: bool = False) -> dict[str, Any]:
        """Return a redacted, Hub-safe projection of the local graph.

        Raw paths, prompts, transcripts, and source text stay local. The public
        card only exposes aggregate counts and source/node/edge types.
        """
        status = self.status()
        card: dict[str, Any] = {
            "schemaVersion": "1.0",
            "kind": "agentlas-public-career-card",
            "generatedAt": utc_now(),
            "projectName": self.config.root.name,
            "indexStatus": "indexed" if status["db_exists"] else "missing_index",
            "policy": "redacted_aggregate_projection",
            "privacy": {
                "rawLocalPathsIncluded": False,
                "rawPromptsIncluded": False,
                "rawTranscriptsIncluded": False,
                "sourceTextIncluded": False,
            },
            "counts": status["counts"],
            "canonicalSources": status["canonical_sources"],
            "staleSourceCount": len(status["stale"]),
            "sourceKinds": {},
            "nodeTypes": {},
            "edgeTypes": {},
        }
        if self.config.sqlite_path.exists():
            with self.connect() as conn:
                card["sourceKinds"] = {
                    row["kind"]: row["count"]
                    for row in conn.execute("SELECT kind, count(*) AS count FROM sources GROUP BY kind ORDER BY kind")
                }
                card["nodeTypes"] = {
                    row["node_type"]: row["count"]
                    for row in conn.execute("SELECT node_type, count(*) AS count FROM nodes GROUP BY node_type ORDER BY node_type")
                }
                card["edgeTypes"] = {
                    row["edge_type"]: row["count"]
                    for row in conn.execute("SELECT edge_type, count(*) AS count FROM edges GROUP BY edge_type ORDER BY edge_type")
                }
        if write:
            target = self.config.agentlas_dir / "public-career-card.json"
            target.write_text(json.dumps(card, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            card["writtenTo"] = ".agentlas/public-career-card.json"
        return card

    # -- write helpers ---------------------------------------------------------
    def _write_source(self, conn: sqlite3.Connection, source: dict[str, Any], at: str) -> None:
        path = Path(source["path"])
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            checksum = file_checksum(path)
            line_count = len(text.splitlines())
            size = path.stat().st_size
            mtime = path.stat().st_mtime
        else:
            checksum = stable_id("dir", path)
            line_count = 0
            size = 0
            mtime = path.stat().st_mtime if path.exists() else None
        conn.execute(
            """
            INSERT OR REPLACE INTO sources(source_id, path, kind, checksum, mtime, size, line_count, last_ingested_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (stable_id("source", path), str(path), source["kind"], checksum, mtime, size, line_count, at),
        )

    def _write_node(self, conn: sqlite3.Connection, node: dict[str, Any]) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO nodes(node_id, node_type, label, text, source_path, source_line, source_ref, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                node["node_id"],
                node["node_type"],
                node["label"],
                node.get("text"),
                node.get("source_path"),
                node.get("source_line"),
                node.get("source_ref"),
                json.dumps(node.get("payload") or {}, ensure_ascii=False, sort_keys=True),
                node["created_at"],
            ),
        )

    def _write_edge(self, conn: sqlite3.Connection, edge: dict[str, Any]) -> None:
        conn.execute(
            """
            INSERT OR REPLACE INTO edges(edge_id, from_node, to_node, edge_type, label, source_path, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edge["edge_id"],
                edge["from_node"],
                edge["to_node"],
                edge["edge_type"],
                edge.get("label"),
                edge.get("source_path"),
                json.dumps(edge.get("payload") or {}, ensure_ascii=False, sort_keys=True),
                edge["created_at"],
            ),
        )

    def _node(
        self,
        node_type: str,
        node_id: str,
        label: str,
        text: str,
        source_path: Path | str | None = None,
        source_line: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        source_ref = None
        if source_path is not None:
            source_ref = str(source_path) + (f":{source_line}" if source_line else "")
        return {
            "node_id": node_id,
            "node_type": node_type,
            "label": label,
            "text": compact_text(text),
            "source_path": str(source_path) if source_path is not None else None,
            "source_line": source_line,
            "source_ref": source_ref,
            "payload": payload or {},
            "created_at": utc_now(),
        }

    def _edge(
        self,
        from_node: str,
        to_node: str,
        edge_type: str,
        source_path: Path | str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "edge_id": stable_id("edge", from_node, to_node, edge_type, source_path),
            "from_node": from_node,
            "to_node": to_node,
            "edge_type": edge_type,
            "label": edge_type,
            "source_path": str(source_path) if source_path is not None else None,
            "payload": payload or {},
            "created_at": utc_now(),
        }

    def _label_for_item(self, item: dict[str, Any], fallback: str) -> str:
        for key in ("id", "ticket_id", "receipt_id", "step_id", "node_id", "kind", "action", "status"):
            value = item.get(key)
            if value:
                return str(value)
        content = compact_text(item.get("content") or item.get("summary") or item.get("detail"), limit=80)
        return content or fallback


def read_payload(value: str | None) -> Any:
    if not value:
        return {}
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {}
