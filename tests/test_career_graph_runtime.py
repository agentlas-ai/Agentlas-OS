from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from career_graph import CareerGraphRuntime, RuntimeConfig


class CareerGraphRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name)
        agentlas = self.project / ".agentlas"
        (agentlas / "code-map").mkdir(parents=True)
        (agentlas / "ledgers").mkdir(parents=True)
        (agentlas / "stormbreaker" / "journal").mkdir(parents=True)
        (agentlas / "project-soul-memory.md").write_text(
            "# Project Soul Memory\n\n## Decisions\n\n- Release work requires smoke proof.\n",
            encoding="utf-8",
        )
        (agentlas / "memory-log.jsonl").write_text(
            json.dumps(
                {
                    "action": "written",
                    "scope": "project",
                    "kind": "evidence",
                    "content": "Release failure recovered by rerunning billing webhook smoke tests.",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (agentlas / "memory-tickets.jsonl").write_text("", encoding="utf-8")
        (agentlas / "curator-decisions.jsonl").write_text("", encoding="utf-8")
        (agentlas / "sitemap.json").write_text(
            json.dumps(
                {
                    "project": "demo",
                    "nodes": [{"id": "billing.webhook", "status": "revalidate"}],
                    "edges": [],
                }
            ),
            encoding="utf-8",
        )
        (agentlas / "code-map" / "project-map.json").write_text(
            json.dumps(
                {
                    "project": "demo",
                    "modules": [{"id": "billing", "role": "webhook backend"}],
                    "entryPoints": [{"path": "app/api/billing/webhook.ts"}],
                    "topSymbols": [{"name": "handleBillingWebhook", "defAt": "app/api/billing/webhook.ts:10"}],
                }
            ),
            encoding="utf-8",
        )
        (agentlas / "stormbreaker" / "journal" / "run-1.jsonl").write_text(
            json.dumps({"event": "fail", "step_id": "smoke", "error": "webhook 500"}) + "\n",
            encoding="utf-8",
        )
        (agentlas / "ledgers" / "routing-decisions.jsonl").write_text(
            json.dumps(
                {
                    "receipt_id": "receipt-release-1",
                    "action": "pipeline",
                    "memory_playbook": {
                        "candidates": [
                            {
                                "kind": "playbook_candidate",
                                "id": "candidate:release-end-to-end",
                                "summary": "Release work should keep tests and smoke proof tied to one receipt.",
                                "scope": "project",
                                "status": "candidate_only",
                            }
                        ]
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        (agentlas / "ledgers" / "agent-evolution-proposals.jsonl").write_text(
            json.dumps(
                {
                    "kind": "agent_evolution_proposal",
                    "proposal_id": "proposal-1",
                    "agent_id": "demo-agent",
                    "proposal_type": "rule",
                    "summary": "Tighten release smoke proof instructions after webhook failures.",
                    "target_path": "AGENTS.md",
                    "risk": "medium",
                    "status": "applied",
                    "before_hash": "before",
                    "after_hash": "after",
                }
            )
            + "\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def runtime(self) -> CareerGraphRuntime:
        return CareerGraphRuntime(RuntimeConfig(project=self.project))

    def test_ingest_builds_rebuildable_index_from_ledgers(self) -> None:
        result = self.runtime().ingest()
        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["sources"], 5)
        self.assertGreaterEqual(result["nodes"], 6)
        self.assertTrue((self.project / ".agentlas" / "career-graph.sqlite").exists())

    def test_query_returns_source_refs_for_agent_to_inspect(self) -> None:
        runtime = self.runtime()
        runtime.ingest()
        result = runtime.query("release webhook failure", limit=5)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["results"])
        refs = [item["source_ref"] for item in result["results"]]
        self.assertTrue(any("memory-log.jsonl" in ref for ref in refs))

    def test_verify_detects_stale_source_after_edit(self) -> None:
        runtime = self.runtime()
        runtime.ingest()
        memory_log = self.project / ".agentlas" / "memory-log.jsonl"
        with memory_log.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"content": "New release failure evidence"}) + "\n")
        result = runtime.verify()
        self.assertEqual(result["verify_status"], "fail")
        self.assertTrue(result["stale"])

    def test_public_card_is_redacted_and_writable(self) -> None:
        runtime = self.runtime()
        runtime.ingest()
        result = runtime.public_card(write=True)
        raw = json.dumps(result, sort_keys=True)
        self.assertEqual(result["kind"], "agentlas-public-career-card")
        self.assertGreater(result["counts"]["nodes"], 0)
        self.assertFalse(result["privacy"]["rawLocalPathsIncluded"])
        self.assertNotIn(str(self.project), raw)
        self.assertTrue((self.project / ".agentlas" / "public-career-card.json").exists())

    def test_ingest_promotes_failure_and_playbook_nodes(self) -> None:
        runtime = self.runtime()
        runtime.ingest()
        with runtime.connect() as conn:
            node_types = {
                row["node_type"]: row["count"]
                for row in conn.execute("SELECT node_type, count(*) AS count FROM nodes GROUP BY node_type")
            }
            edge_types = {
                row["edge_type"]: row["count"]
                for row in conn.execute("SELECT edge_type, count(*) AS count FROM edges GROUP BY edge_type")
            }

        self.assertGreaterEqual(node_types.get("FailureSignature", 0), 1)
        self.assertGreaterEqual(node_types.get("PlaybookCandidate", 0), 1)
        self.assertGreaterEqual(node_types.get("EvolutionProposal", 0), 1)
        self.assertGreaterEqual(edge_types.get("has_failure_signature", 0), 1)
        self.assertGreaterEqual(edge_types.get("has_playbook_candidate", 0), 1)
        self.assertGreaterEqual(edge_types.get("has_evolution_proposal", 0), 1)

    def test_networking_lease_receipt_flows_into_graph(self) -> None:
        """24h lease evidence contract: hub_invocation writes lease-bearing execution
        receipts to the networking home ledger, and an include_networking_home
        ingest must preserve that lease payload on the ExecutionReceipt node while
        the public card stays counts-only (no lease details, no local paths)."""
        import os

        networking_home = self.project / "networking-home"
        (networking_home / "ledgers").mkdir(parents=True)
        receipt = {
            "action": "hub_invoke",
            "status": "prepared",
            "slug": "instagram-uploader",
            "summary": "Borrowed instagram-uploader under an active 24h lease.",
            "lease": {"active": True, "leased_until": "2026-07-10T00:00:00Z", "charged_credits": 0},
            "at": "2026-07-09T12:00:00Z",
        }
        (networking_home / "ledgers" / "executions.jsonl").write_text(
            json.dumps(receipt) + "\n",
            encoding="utf-8",
        )

        previous = os.environ.get("AGENTLAS_NETWORKING_HOME")
        os.environ["AGENTLAS_NETWORKING_HOME"] = str(networking_home)
        try:
            runtime = CareerGraphRuntime(RuntimeConfig(project=self.project, include_networking_home=True))
            result = runtime.ingest(rebuild=True)
            self.assertEqual(result["status"], "ok")

            query = runtime.query("instagram-uploader lease")
            receipts = [row for row in query["results"] if row["type"] == "ExecutionReceipt"]
            self.assertTrue(receipts, f"lease-bearing execution receipt must be queryable: {query['results']}")
            self.assertIn("executions.jsonl", receipts[0]["source_ref"])

            # 노드 payload에 lease 원본이 보존된다 — 그래프는 정본 포인터+파생 인덱스이므로
            # lease 증거가 파생 층에서 유실되면 안 된다.
            with runtime.connect() as conn:
                rows = [
                    dict(row)
                    for row in conn.execute("SELECT node_type, payload_json FROM nodes WHERE node_type = 'ExecutionReceipt'")
                ]
            self.assertTrue(rows)
            payloads = [json.loads(row["payload_json"]) for row in rows if row["payload_json"]]
            lease_payloads = [p for p in payloads if isinstance(p.get("lease"), dict)]
            self.assertTrue(lease_payloads, "lease field must be preserved in ExecutionReceipt payload")
            self.assertEqual(lease_payloads[0]["lease"]["leased_until"], "2026-07-10T00:00:00Z")

            # 공개 카드는 여전히 집계만 — lease 상세/로컬 경로가 새면 안 된다.
            card = runtime.public_card(write=False)
            serialized = json.dumps(card)
            self.assertNotIn("leased_until", serialized)
            self.assertNotIn(str(networking_home), serialized)
            self.assertGreaterEqual(card["nodeTypes"].get("ExecutionReceipt", 0), 1)
        finally:
            if previous is None:
                os.environ.pop("AGENTLAS_NETWORKING_HOME", None)
            else:
                os.environ["AGENTLAS_NETWORKING_HOME"] = previous

    def test_cli_ingest_and_query(self) -> None:
        ingest = subprocess.run(
            [sys.executable, "-m", "career_graph", "--project", str(self.project), "ingest"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(json.loads(ingest.stdout)["status"], "ok")
        query = subprocess.run(
            [sys.executable, "-m", "career_graph", "--project", str(self.project), "query", "billing webhook"],
            cwd=Path(__file__).resolve().parents[1],
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertTrue(json.loads(query.stdout)["results"])


if __name__ == "__main__":
    unittest.main()
