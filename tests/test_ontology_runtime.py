import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class OntologyRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "ontology.sqlite"
        self.corpus = self.root / "corpus"
        self.corpus.mkdir()
        (self.corpus / "company.md").write_text(
            "\n".join(
                [
                    "# Atlas Robotics",
                    "",
                    "Atlas Robotics owns Project Helios.",
                    "Project Helios depends on Memory Curator.",
                    "Memory Curator creates candidate tickets, not durable memory.",
                    "GraphRAG retrieves chunks and relation edges for Agent Working Memory.",
                ]
            ),
            encoding="utf-8",
        )
        (self.corpus / "notes.txt").write_text(
            "Agent Working Memory caches graph-backed retrieval for a session and expires stale facts.",
            encoding="utf-8",
        )
        (self.corpus / "facts.json").write_text(
            json.dumps(
                {
                    "team": "Project Helios",
                    "owner": "Atlas Robotics",
                    "depends_on": "Memory Curator",
                    "privacy": "internal",
                }
            ),
            encoding="utf-8",
        )
        (self.corpus / "matrix.csv").write_text(
            "name,role,depends_on\nProject Helios,knowledge runtime,Memory Curator\n",
            encoding="utf-8",
        )
        (self.corpus / "unsupported.hwp").write_bytes(b"HWP adapter fixture")

    def tearDown(self):
        self.tmp.cleanup()

    def runtime(self):
        from ontology import OntologyRuntime, RuntimeConfig

        return OntologyRuntime(RuntimeConfig(db_path=self.db_path))

    def counts(self):
        with sqlite3.connect(self.db_path) as conn:
            return {
                "sources": conn.execute("select count(*) from sources").fetchone()[0],
                "chunks": conn.execute("select count(*) from chunks").fetchone()[0],
                "entities": conn.execute("select count(*) from entities").fetchone()[0],
                "relations": conn.execute("select count(*) from relations").fetchone()[0],
                "memory_candidates": conn.execute("select count(*) from memory_candidates").fetchone()[0],
            }

    def test_ingest_query_graph_and_working_memory_flow(self):
        rt = self.runtime()
        ingest = rt.ingest_path(self.corpus, access_scope="internal")

        parsed = {item["source_type"]: item["parser_status"] for item in ingest["sources"]}
        self.assertEqual(parsed["markdown"], "parsed")
        self.assertEqual(parsed["text"], "parsed")
        self.assertEqual(parsed["json"], "parsed")
        self.assertEqual(parsed["csv"], "parsed")
        self.assertEqual(parsed["hwp"], "unsupported_pending_adapter")
        self.assertGreaterEqual(ingest["chunks_written"], 4)
        self.assertGreaterEqual(ingest["entities_written"], 3)
        self.assertGreaterEqual(ingest["relations_written"], 2)

        answer = rt.query("What does Project Helios depend on?", agent_id="agent-alpha")
        self.assertTrue(answer["chunks"], answer)
        self.assertTrue(answer["related_entities"], answer)
        self.assertTrue(answer["relation_edges"], answer)
        self.assertTrue(answer["memory_candidate_suggestions"], answer)
        self.assertTrue(answer["working_memory"], answer)

        edge_text = json.dumps(answer["relation_edges"])
        self.assertIn("Project Helios", edge_text)
        self.assertIn("Memory Curator", edge_text)
        self.assertNotIn("Atlas Robotics Atlas Robotics", edge_text)

        first_chunk = answer["chunks"][0]
        self.assertIn("source_span", first_chunk)
        self.assertIn("source_lineage", first_chunk)
        self.assertIn("checksum", first_chunk)

        candidates = rt.list_memory_candidates()
        self.assertTrue(candidates)
        self.assertEqual(candidates[0]["status"], "pending_review")
        self.assertIn("source_refs", candidates[0])
        self.assertIn(candidates[0]["suggested_scope"], {"session", "agent_repo", "project", "team_memory"})
        self.assertFalse(candidates[0]["durable_write_enabled"])

        cached = rt.read_working_memory("agent-alpha")
        self.assertTrue(cached)
        self.assertEqual(cached[0]["agent_id"], "agent-alpha")
        self.assertGreaterEqual(cached[0]["confidence"], 0)
        self.assertIn("source_refs", cached[0])

    def test_ingest_is_idempotent_and_preserves_lineage(self):
        rt = self.runtime()
        rt.ingest_path(self.corpus, access_scope="internal")
        first = self.counts()
        rt.ingest_path(self.corpus, access_scope="internal")
        second = self.counts()
        self.assertEqual(first, second)

        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "select source_id, chunk_index, source_span_json, source_lineage_json from chunks order by chunk_index limit 1"
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[1], 0)
        self.assertIn("line_start", row[2])
        self.assertIn(row[0], row[3])

    def test_graph_entity_query_returns_evidence_edges(self):
        rt = self.runtime()
        rt.ingest_path(self.corpus, access_scope="internal")

        graph = rt.graph_entity("Project Helios")
        self.assertEqual(graph["entity"]["canonical_name"], "Project Helios")
        self.assertTrue(graph["relations"], graph)
        self.assertTrue(graph["evidence_chunks"], graph)
        self.assertTrue(any("Memory Curator" in json.dumps(edge) for edge in graph["relations"]))

    def test_working_memory_prune_expires_stale_cache_items(self):
        rt = self.runtime()
        rt.ingest_path(self.corpus, access_scope="internal")
        rt.add_working_memory(
            agent_id="agent-beta",
            task_scope="session-1",
            memory_item="expired cache item",
            source_refs=[{"source_id": "manual", "chunk_id": "manual"}],
            confidence=0.4,
            importance=0.1,
            ttl_seconds=-1,
        )
        before = rt.read_working_memory("agent-beta", include_expired=True)
        self.assertEqual(len(before), 1)

        result = rt.prune_working_memory("agent-beta")
        after = rt.read_working_memory("agent-beta", include_expired=True)
        self.assertEqual(result["expired"], 1)
        self.assertEqual(after[0]["status"], "expired")
        self.assertEqual(after[0]["invalidation_reason"], "ttl_expired")

    def test_privacy_scope_blocks_private_results_by_default(self):
        private_doc = self.root / "private.md"
        private_doc.write_text("Private Alpha Roadmap depends on Secret Vendor.", encoding="utf-8")

        rt = self.runtime()
        rt.ingest_path(private_doc, access_scope="private")
        blocked = rt.query("Secret Vendor", allowed_scopes=["public", "internal"])
        allowed = rt.query("Secret Vendor", allowed_scopes=["private"])

        self.assertEqual(blocked["chunks"], [])
        self.assertTrue(allowed["chunks"])

    def test_direct_durable_memory_write_is_blocked(self):
        from ontology import DirectDurableMemoryWriteBlocked

        rt = self.runtime()
        with self.assertRaises(DirectDurableMemoryWriteBlocked):
            rt.write_durable_memory("agent-alpha", {"fact": "must not be written directly"})

    def test_cli_end_to_end_verify_and_json_outputs(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        db = str(self.db_path)

        ingest = subprocess.run(
            [sys.executable, "-m", "ontology", "--db", db, "ingest", str(self.corpus), "--scope", "internal"],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        ingest_payload = json.loads(ingest.stdout)
        self.assertGreaterEqual(ingest_payload["chunks_written"], 4)

        query = subprocess.run(
            [
                sys.executable,
                "-m",
                "ontology",
                "--db",
                db,
                "query",
                "Project Helios Memory Curator",
                "--agent",
                "agent-cli",
            ],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        query_payload = json.loads(query.stdout)
        self.assertTrue(query_payload["chunks"])
        self.assertTrue(query_payload["relation_edges"])
        self.assertTrue(query_payload["memory_candidate_suggestions"])

        graph = subprocess.run(
            [sys.executable, "-m", "ontology", "--db", db, "graph", "entity", "Project Helios"],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertTrue(json.loads(graph.stdout)["relations"])

        verify = subprocess.run(
            [sys.executable, "-m", "ontology", "--db", db, "verify"],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        verify_payload = json.loads(verify.stdout)
        self.assertEqual(verify_payload["status"], "pass")


if __name__ == "__main__":
    unittest.main()
