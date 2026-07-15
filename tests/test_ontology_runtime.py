import gc
import hashlib
import json
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from contextlib import closing
from pathlib import Path
from unittest import mock


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
        (self.corpus / "invalid.hwp").write_bytes(b"HWP adapter fixture")

    def tearDown(self):
        self.tmp.cleanup()

    def runtime(self):
        from ontology import OntologyRuntime, RuntimeConfig

        return OntologyRuntime(RuntimeConfig(db_path=self.db_path))

    def counts(self):
        with closing(sqlite3.connect(self.db_path)) as conn:
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
        self.assertEqual(parsed["hwp"], "parser_error")
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

        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "select source_id, chunk_index, source_span_json, source_lineage_json from chunks order by chunk_index limit 1"
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[1], 0)
        self.assertIn("line_start", row[2])
        self.assertIn(row[0], row[3])

    def test_backup_closes_sqlite_connections_and_preserves_data(self):
        rt = self.runtime()
        rt.ingest_path(self.corpus, access_scope="internal")
        destination = self.root / "backup.sqlite"

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", ResourceWarning)
            result = rt.backup(destination)
            gc.collect()

        self.assertEqual(result, {"status": "ok", "backup_path": str(destination)})
        leaked = [
            warning
            for warning in caught
            if issubclass(warning.category, ResourceWarning)
            and "unclosed database" in str(warning.message)
        ]
        self.assertEqual(leaked, [], [str(warning.message) for warning in leaked])
        with closing(sqlite3.connect(destination)) as conn:
            self.assertGreater(conn.execute("select count(*) from sources").fetchone()[0], 0)

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

    def test_document_adapters_parse_real_formats(self):
        adapter_corpus = self.root / "adapter-corpus"
        adapter_corpus.mkdir()
        write_text_pdf(adapter_corpus / "manual.pdf", "Project Helios depends on Memory Curator")
        write_hwpx(adapter_corpus / "manual.hwpx", "Project Helios depends on Memory Curator")
        write_hwp5(adapter_corpus / "manual.hwp", "Project Helios depends on Memory Curator")
        write_docx(adapter_corpus / "brief.docx", "Project Helios depends on Memory Curator")
        write_xlsx(adapter_corpus / "matrix.xlsx", "Project Helios", "Memory Curator")
        write_pptx(adapter_corpus / "slides.pptx", "Project Helios depends on Memory Curator")
        image_expected = write_ocr_image(adapter_corpus / "scan.png", "Memory Curator OCR")

        rt = self.runtime()
        ingest = rt.ingest_path(adapter_corpus, access_scope="internal")
        by_name = {item["display_name"]: item for item in ingest["sources"]}

        self.assertEqual(by_name["manual.pdf"]["parser_status"], "parsed", by_name)
        self.assertEqual(by_name["manual.hwpx"]["parser_status"], "parsed", by_name)
        self.assertEqual(by_name["manual.hwp"]["parser_status"], "parsed", by_name)
        self.assertEqual(by_name["brief.docx"]["parser_status"], "parsed", by_name)
        self.assertEqual(by_name["matrix.xlsx"]["parser_status"], "parsed", by_name)
        self.assertEqual(by_name["slides.pptx"]["parser_status"], "parsed", by_name)
        if image_expected:
            self.assertEqual(by_name["scan.png"]["parser_status"], "parsed", by_name)
        else:
            self.assertEqual(by_name["scan.png"]["parser_status"], "unsupported_pending_adapter", by_name)

        self.assertGreaterEqual(ingest["chunks_written"], 5)
        answer = rt.query("Project Helios Memory Curator")
        self.assertTrue(answer["chunks"], answer)
        self.assertTrue(answer["relation_edges"], answer)

    def test_hwpx_parser_preserves_table_spans_for_ontology(self):
        from ontology.parsers import SourceParserRegistry

        source = self.root / "table.hwpx"
        write_hwpx_table(source)
        parsed = SourceParserRegistry().parse(source)

        self.assertEqual(parsed.parser_status, "parsed")
        self.assertEqual(parsed.adapter_name, "hephaestus_hwpx_parser")
        tables = [record for record in parsed.records if record.span["kind"] == "hwpx_table"]
        self.assertEqual(len(tables), 1)
        self.assertEqual(tables[0].span["row_count"], 2)
        self.assertEqual(tables[0].span["column_count"], 2)
        self.assertIn("Project Helios", tables[0].text)
        self.assertIn("parser_model", tables[0].span)

    def test_hwp5_first_party_parser_reads_cfb_bodytext(self):
        from ontology.parsers import SourceParserRegistry

        source = self.root / "manual.hwp"
        write_hwp5(source, "Project Helios depends on Memory Curator")
        parsed = SourceParserRegistry().parse(source)

        self.assertEqual(parsed.parser_status, "parsed", parsed.parser_message)
        self.assertEqual(parsed.adapter_name, "hephaestus_hwp5_parser")
        self.assertEqual(parsed.records[0].span["kind"], "hwp5_para_text")
        self.assertIn("Project Helios", parsed.records[0].text)
        self.assertIn("parser_model", parsed.records[0].span)

    def test_image_ocr_engine_failure_is_adapter_pending(self):
        from ontology.parsers import SourceParserRegistry

        image = self.root / "scan.png"
        image.write_bytes(b"not a useful image fixture")
        registry = SourceParserRegistry()

        with (
            mock.patch("ontology.parsers.macos_vision_available", return_value=True),
            mock.patch("ontology.parsers.shutil.which", return_value=None),
            mock.patch(
                "ontology.parsers.subprocess.run",
                side_effect=subprocess.CalledProcessError(
                    returncode=2,
                    cmd=["swift", "ocr.swift", str(image)],
                    stderr="image_load_failed",
                ),
            ),
        ):
            parsed = registry.parse(image)

        self.assertEqual(parsed.source_type, "image")
        self.assertEqual(parsed.parser_status, "unsupported_pending_adapter")
        self.assertEqual(parsed.adapter_name, "macos_vision_ocr_adapter")
        self.assertIn("macOS Vision OCR unavailable", parsed.parser_message)

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
                "--record-memory",
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

        gui = subprocess.run(
            [sys.executable, "-m", "ontology", "--db", db, "gui", str(self.root), "--no-open"],
            cwd=Path(__file__).resolve().parents[1],
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        gui_payload = json.loads(gui.stdout)
        self.assertEqual(gui_payload["status"], "gui_ready")
        self.assertFalse(gui_payload["opened"])
        gui_path = Path(gui_payload["gui_path"])
        self.assertTrue(gui_path.exists())
        gui_html = gui_path.read_text(encoding="utf-8")
        self.assertIn("Hephaestus Ontology", gui_html)
        self.assertIn('data-app="ontology-dashboard"', gui_html)
        self.assertIn("Ontology Command Center", gui_html)
        self.assertIn("Knowledge Graph", gui_html)
        self.assertIn("Ask Ontology", gui_html)
        self.assertIn("Memory Candidate Queue", gui_html)
        self.assertIn("data-view-target=\"sources\"", gui_html)
        self.assertIn("data-copy=\"/hep-build ontology\"", gui_html)

    def test_hephaestus_runner_creates_project_gui_without_browser(self):
        env = os.environ.copy()
        repo = Path(__file__).resolve().parents[1]
        project = self.root / "runner-project"
        (project / ".agentlas" / "ontology-inbox").mkdir(parents=True)
        (project / ".agentlas" / "ontology-inbox" / "company.md").write_text(
            "Runner Company depends on Review Board.",
            encoding="utf-8",
        )

        result = subprocess.run(
            [str(repo / "bin" / "hephaestus"), "ontology", "--no-open", str(project)],
            cwd=repo,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "gui_ready")
        self.assertFalse(payload["opened"])
        gui_path = Path(payload["gui_path"])
        self.assertTrue(gui_path.exists())
        gui_html = gui_path.read_text(encoding="utf-8")
        self.assertIn("Ontology Command Center", gui_html)
        self.assertIn("data-view-target=\"commands\"", gui_html)
        self.assertTrue(Path(payload["db_path"]).exists())

    def test_auto_activation_uses_project_local_inbox_and_blocks_cross_project_mixing(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        repo = Path(__file__).resolve().parents[1]

        company_project = self.root / "company-project"
        personal_project = self.root / "personal-project"
        (company_project / ".agentlas" / "ontology-inbox").mkdir(parents=True)
        (personal_project / ".agentlas" / "ontology-inbox").mkdir(parents=True)
        (company_project / ".agentlas" / "ontology-inbox" / "company.md").write_text(
            "Company Alpha Roadmap depends on Board Approval.",
            encoding="utf-8",
        )
        (personal_project / ".agentlas" / "ontology-inbox" / "personal.md").write_text(
            "Personal Garden Plan depends on Soil Delivery.",
            encoding="utf-8",
        )

        company_auto = subprocess.run(
            [sys.executable, "-m", "ontology", "auto", str(company_project)],
            cwd=repo,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        personal_auto = subprocess.run(
            [sys.executable, "-m", "ontology", "auto", str(personal_project)],
            cwd=repo,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

        company_payload = json.loads(company_auto.stdout)
        personal_payload = json.loads(personal_auto.stdout)
        self.assertEqual(company_payload["status"], "active")
        self.assertEqual(personal_payload["status"], "active")
        self.assertIn("inbox_and_registered_sources_only", company_payload["auto_ingest_policy"])
        self.assertNotEqual(company_payload["db_path"], personal_payload["db_path"])

        company_query = subprocess.run(
            [
                sys.executable,
                "-m",
                "ontology",
                "--db",
                company_payload["db_path"],
                "query",
                "Soil Delivery",
            ],
            cwd=repo,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        personal_query = subprocess.run(
            [
                sys.executable,
                "-m",
                "ontology",
                "--db",
                personal_payload["db_path"],
                "query",
                "Soil Delivery",
            ],
            cwd=repo,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )

        self.assertFalse(json.loads(company_query.stdout)["chunks"])
        self.assertTrue(json.loads(personal_query.stdout)["chunks"])

    def test_sources_add_registers_external_source_without_copying_it(self):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
        repo = Path(__file__).resolve().parents[1]
        project = self.root / "registered-project"
        source = self.root / "company-source.md"
        source.write_text("Registered Company Manual depends on Review Board.", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ontology",
                "sources",
                "add",
                str(source),
                "--project",
                str(project),
                "--kind",
                "company",
                "--scope",
                "private",
            ],
            cwd=repo,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "registered")
        self.assertEqual(payload["source"]["kind"], "company")
        self.assertEqual(payload["source"]["scope"], "private")

        copied = project / ".agentlas" / "ontology-inbox" / source.name
        self.assertFalse(copied.exists())

        listed = subprocess.run(
            [sys.executable, "-m", "ontology", "sources", "list", "--project", str(project)],
            cwd=repo,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        sources = json.loads(listed.stdout)["sources"]
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["path"], str(source.resolve()))

class OntologySearchUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "ontology.sqlite"
        self.corpus = self.root / "corpus"
        self.corpus.mkdir()
        (self.corpus / "contract-ko.md").write_text(
            "# 계약서 자동화\n\n이 문서는 계약서 자동 생성 파이프라인과 견적서 검토 절차를 설명한다.",
            encoding="utf-8",
        )
        (self.corpus / "unrelated-ko.md").write_text(
            "# 일상 기록\n\n오늘 점심 메뉴는 김치찌개였고 산책을 했다.",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def runtime(self, **config_kwargs):
        from ontology import OntologyRuntime, RuntimeConfig

        return OntologyRuntime(RuntimeConfig(db_path=self.db_path, **config_kwargs))

    def test_tokenizer_handles_cjk_input(self):
        from ontology.embeddings import tokenize

        tokens = tokenize("한글 계약서 자동 생성 견적서")
        self.assertTrue(tokens)
        self.assertIn("계약", tokens)
        adapter_vector_sum = sum(abs(v) for v in self.runtime().vector_adapter.embed("계약서 자동 생성"))
        self.assertGreater(adapter_vector_sum, 0.0)

    def test_korean_query_ranks_relevant_document_first(self):
        rt = self.runtime()
        rt.ingest_path(self.corpus, access_scope="internal")
        answer = rt.query("계약서 자동 생성")
        self.assertTrue(answer["chunks"], answer)
        self.assertIn("계약서", answer["chunks"][0]["text"])
        texts = " ".join(chunk["text"] for chunk in answer["chunks"])
        self.assertNotIn("김치찌개", texts)
        self.assertEqual(answer["search"]["fusion"], "rrf")

    def test_v1_database_migrates_to_trigram_and_reembeds(self):
        rt = self.runtime()
        rt.ingest_path(self.corpus, access_scope="internal")
        del rt
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute("DROP TABLE chunk_fts")
            conn.execute(
                "CREATE VIRTUAL TABLE chunk_fts USING fts5(chunk_id UNINDEXED, text, tokenize='porter')"
            )
            conn.execute("DELETE FROM schema_migrations WHERE version >= 2")
            conn.execute(
                "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (1, '2026-01-01T00:00:00Z')"
            )
            conn.execute("UPDATE chunks SET vector_json = '[]'")
        rt2 = self.runtime()
        report = rt2.verify()
        self.assertEqual(report["status"], "pass")
        answer = rt2.query("계약서 생성")
        self.assertTrue(answer["chunks"], answer)
        with closing(sqlite3.connect(self.db_path)) as conn:
            vector = conn.execute("SELECT vector_json FROM chunks LIMIT 1").fetchone()[0]
        self.assertTrue(json.loads(vector))

    def test_query_expansion_hook_widens_recall(self):
        calls = []

        def expansion_hook(question):
            calls.append(question)
            return ["계약서 자동 생성"]

        rt = self.runtime(query_expansion_hook=expansion_hook)
        rt.ingest_path(self.corpus, access_scope="internal")
        answer = rt.query("표준 약정 문서 만들기")
        self.assertEqual(calls, ["표준 약정 문서 만들기"])
        self.assertIn("계약서 자동 생성", answer["search"]["expanded_queries"])
        texts = " ".join(chunk["text"] for chunk in answer["chunks"])
        self.assertIn("계약서", texts)

    def test_rerank_hook_never_receives_private_chunks(self):
        seen_chunk_ids = []

        def rerank_hook(question, candidates):
            seen_chunk_ids.extend(item["chunk_id"] for item in candidates)
            return [item["chunk_id"] for item in candidates]

        private_doc = self.root / "private.md"
        private_doc.write_text("비공개 계약서 단가 협상 메모.", encoding="utf-8")
        rt = self.runtime(rerank_hook=rerank_hook)
        rt.ingest_path(self.corpus, access_scope="internal")
        rt.ingest_path(private_doc, access_scope="private")
        answer = rt.query("계약서 단가", allowed_scopes=["public", "internal", "private"])
        self.assertTrue(seen_chunk_ids, "rerank hook should run for cloud-safe chunks")
        returned_private = [
            chunk for chunk in answer["chunks"] if chunk["privacy_scope"] == "private"
        ]
        self.assertTrue(returned_private, "private chunks must still be searchable locally")
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            private_ids = {
                row["chunk_id"]
                for row in conn.execute("SELECT chunk_id FROM chunks WHERE privacy_scope = 'private'")
            }
        self.assertFalse(private_ids & set(seen_chunk_ids), "private chunk leaked to rerank hook")

    def test_chunking_adds_overlap_between_windows(self):
        from ontology import RuntimeConfig, OntologyRuntime

        rt = OntologyRuntime(RuntimeConfig(db_path=self.db_path, chunk_token_limit=20, chunk_overlap_ratio=0.2))
        long_doc = self.root / "long.md"
        long_doc.write_text(" ".join(f"word{i}" for i in range(100)), encoding="utf-8")
        rt.ingest_path(long_doc, access_scope="internal")
        with closing(sqlite3.connect(self.db_path)) as conn:
            conn.row_factory = sqlite3.Row
            spans = [
                json.loads(row["source_span_json"])
                for row in conn.execute("SELECT source_span_json FROM chunks ORDER BY chunk_index")
            ]
        self.assertGreater(len(spans), 1)
        for left, right in zip(spans, spans[1:]):
            self.assertLess(right["token_start"], left["token_end"], "windows must overlap")


class AgentExperienceProjectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db_path = self.root / "experience.sqlite"

    def tearDown(self):
        self.tmp.cleanup()

    def runtime(self):
        from ontology import OntologyRuntime, RuntimeConfig

        return OntologyRuntime(RuntimeConfig(db_path=self.db_path))

    def test_v3_projection_schema_and_write_time_embedding(self):
        rt = self.runtime()
        result = rt.ingest_experience(
            agent_id="hub:release-writer",
            summary="Release notes must mention migration risk and stay concise.",
            tags=["release", "migration"],
            salience=0.8,
            source_memory_id="desktop-memory-1",
            source_updated_at="2026-07-15T00:00:00Z",
            source_refs=[{"kind": "desktop_memory", "id": "desktop-memory-1"}],
        )

        experience = result["experience"]
        self.assertEqual(experience["agent_id"], "hub:release-writer")
        self.assertEqual(experience["source_memory_id"], "desktop-memory-1")
        self.assertEqual(experience["embedding"]["adapter"], "model2vec_potion_base_8m_int8_hybrid")
        self.assertEqual(experience["embedding"]["dimensions"], 352)
        self.assertTrue(experience["embedding"]["content_hash"])
        with closing(sqlite3.connect(self.db_path)) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(memory_candidates)")}
            required = {
                "agent_id",
                "memory_kind",
                "tags_json",
                "salience",
                "privacy_scope",
                "source_memory_id",
                "source_updated_at",
                "embedding_adapter",
                "embedding_dimensions",
                "embedding_json",
                "embedding_content_hash",
            }
            self.assertTrue(required <= columns)
            vector = json.loads(conn.execute("SELECT embedding_json FROM memory_candidates").fetchone()[0])
            self.assertEqual(len(vector), 352)

    def test_real_v2_candidate_table_migrates_additively_and_reembeds(self):
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.executescript(
                """
                CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
                INSERT INTO schema_migrations(version, applied_at) VALUES (2, '2026-07-01T00:00:00Z');
                CREATE TABLE memory_candidates (
                  ticket_id TEXT PRIMARY KEY,
                  idempotency_key TEXT NOT NULL UNIQUE,
                  query TEXT NOT NULL,
                  candidate_text TEXT NOT NULL,
                  source_refs_json TEXT NOT NULL,
                  reason TEXT NOT NULL,
                  confidence REAL NOT NULL,
                  risk TEXT NOT NULL,
                  expiry TEXT,
                  suggested_scope TEXT NOT NULL,
                  status TEXT NOT NULL,
                  durable_write_enabled INTEGER NOT NULL DEFAULT 0 CHECK (durable_write_enabled = 0),
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL
                );
                INSERT INTO memory_candidates VALUES (
                  'legacy-ticket', 'legacy-key', 'release', 'Keep rollback instructions concise.',
                  '[]', 'legacy v2 ticket', 0.7, 'low', NULL, 'session', 'pending_review', 0,
                  '2026-07-01T00:00:00Z', '2026-07-01T00:00:00Z'
                );
                """
            )
        rt = self.runtime()
        self.assertEqual(rt.verify()["schema_version"], 3)
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT embedding_adapter, embedding_dimensions, embedding_json FROM memory_candidates WHERE ticket_id = 'legacy-ticket'"
            ).fetchone()
        self.assertEqual(row[0], "model2vec_potion_base_8m_int8_hybrid")
        self.assertEqual(row[1], 352)
        self.assertEqual(len(json.loads(row[2])), 352)

    def test_read_only_hybrid_recall_is_agent_isolated_and_adaptive(self):
        rt = self.runtime()
        for index in range(3):
            rt.ingest_experience(
                agent_id="hub:release-writer",
                summary=f"Release migration checklist {index}: verify schema rollback and concise notes.",
                tags=["release", "migration"],
                salience=0.5 + (index * 0.1),
                source_memory_id=f"memory-{index}",
            )
        rt.ingest_experience(
            agent_id="hub:other-agent",
            summary="Release migration checklist belongs to another agent.",
            tags=["release", "migration"],
            source_memory_id="other-memory",
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            before = tuple(
                conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("memory_candidates", "memory_links", "working_memory", "memory_candidate_events")
            )

        all_fit = rt.query(
            "release migration checklist",
            agent_id="hub:release-writer",
            record_memory=False,
            experience_token_budget=500,
        )["experience_memory"]
        self.assertEqual(all_fit["mode"], "all_relevant")
        self.assertEqual(all_fit["selected_count"], 3)
        self.assertTrue(all(item["agent_id"] == "hub:release-writer" for item in all_fit["items"]))

        budgeted = rt.query_experience(
            "release migration checklist",
            agent_id="hub:release-writer",
            token_budget=14,
            top_k=1,
        )
        self.assertEqual(budgeted["mode"], "hybrid_top_k")
        self.assertEqual(budgeted["selected_count"], 1)
        with closing(sqlite3.connect(self.db_path)) as conn:
            after = tuple(
                conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
                for table in ("memory_candidates", "memory_links", "working_memory", "memory_candidate_events")
            )
        self.assertEqual(before, after, "recall must not create tickets, links, or hot-cache writes")

    def test_cli_query_agent_reads_experience_without_mutation(self):
        rt = self.runtime()
        rt.ingest_experience(
            agent_id="hub:cli-agent",
            summary="Use a rollback checklist for every database migration.",
            tags=["rollback", "migration"],
            source_memory_id="cli-1",
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            before = conn.total_changes, conn.execute("SELECT count(*) FROM memory_candidates").fetchone()[0]
        repo = Path(__file__).resolve().parents[1]
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ontology",
                "--db",
                str(self.db_path),
                "query",
                "database migration rollback",
                "--agent",
                "hub:cli-agent",
            ],
            cwd=repo,
            text=True,
            capture_output=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["search"]["record_memory"], False)
        self.assertEqual(payload["experience_memory"]["selected_count"], 1)
        self.assertEqual(payload["memory_candidate_suggestions"], [])
        self.assertEqual(payload["working_memory"], [])
        with closing(sqlite3.connect(self.db_path)) as conn:
            after_count = conn.execute("SELECT count(*) FROM memory_candidates").fetchone()[0]
            working_count = conn.execute("SELECT count(*) FROM working_memory").fetchone()[0]
            event_count = conn.execute("SELECT count(*) FROM memory_candidate_events").fetchone()[0]
        self.assertEqual(before[1], after_count)
        self.assertEqual((working_count, event_count), (0, 0))

    def test_supersedes_hides_old_memory_but_contradiction_remains_explicit(self):
        rt = self.runtime()
        old = rt.ingest_experience(
            agent_id="hub:deploy",
            summary="Deploy releases on Friday after lunch.",
            tags=["deploy"],
            source_memory_id="old",
        )["experience"]
        new = rt.ingest_experience(
            agent_id="hub:deploy",
            summary="Deploy releases on Tuesday morning after approval.",
            tags=["deploy"],
            source_memory_id="new",
        )["experience"]
        conflict = rt.ingest_experience(
            agent_id="hub:deploy",
            summary="Never deploy releases before Wednesday.",
            tags=["deploy"],
            source_memory_id="conflict",
        )["experience"]
        rt.link_memory(new["ticket_id"], old["ticket_id"], "supersedes", "Schedule was explicitly revised")
        rt.link_memory(conflict["ticket_id"], new["ticket_id"], "contradicts", "Human curator marked conflict")

        result = rt.query_experience("when should releases deploy", agent_id="hub:deploy")
        ids = {item["ticket_id"] for item in result["items"]}
        self.assertNotIn(old["ticket_id"], ids)
        self.assertIn(new["ticket_id"], ids)
        relation_types = {
            link["link_type"] for item in result["items"] for link in item.get("relations", [])
        }
        self.assertIn("contradicts", relation_types)

    def test_automatic_relations_are_semantic_similar_to_only(self):
        rt = self.runtime()
        rt.ingest_experience(
            agent_id="hub:copy",
            summary="Concise release notes include migration risks.",
            source_memory_id="a",
        )
        second = rt.ingest_experience(
            agent_id="hub:copy",
            summary="Migration risks belong in concise release notes.",
            source_memory_id="b",
            similar_threshold=0.5,
        )
        self.assertTrue(second["similar_links"])
        self.assertTrue(all(link["link_type"] == "similar_to" for link in second["similar_links"]))
        with closing(sqlite3.connect(self.db_path)) as conn:
            types = {row[0] for row in conn.execute("SELECT DISTINCT link_type FROM memory_links")}
        self.assertEqual(types, {"similar_to"})

    def test_experience_upsert_reconciles_stale_automatic_similarity(self):
        rt = self.runtime()
        rt.ingest_experience(
            agent_id="hub:copy",
            summary="Concise migration release notes include rollback risks.",
            source_memory_id="stable-a",
        )
        second = rt.ingest_experience(
            agent_id="hub:copy",
            summary="Migration release notes stay concise and include rollback risks.",
            source_memory_id="stable-b",
            similar_threshold=0.7,
        )["experience"]
        with closing(sqlite3.connect(self.db_path)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM memory_links").fetchone()[0], 1)

        rt.ingest_experience(
            agent_id="hub:copy",
            summary="Sunny picnic weather and garden flowers.",
            source_memory_id="stable-b",
            similar_threshold=0.7,
        )
        with closing(sqlite3.connect(self.db_path)) as conn:
            touching = conn.execute(
                "SELECT count(*) FROM memory_links WHERE from_ticket = ? OR to_ticket = ?",
                (second["ticket_id"], second["ticket_id"]),
            ).fetchone()[0]
        self.assertEqual(touching, 0, "content changes must remove stale machine-inferred edges")

    def test_expired_or_cross_scope_successor_does_not_hide_memory(self):
        rt = self.runtime()
        old = rt.ingest_experience(
            agent_id="hub:deploy",
            summary="Deploy releases after the approval checklist.",
            source_memory_id="visible-old",
        )["experience"]
        newer = rt.ingest_experience(
            agent_id="hub:deploy",
            summary="Deploy releases after the revised approval checklist.",
            source_memory_id="expired-new",
        )["experience"]
        rt.link_memory(newer["ticket_id"], old["ticket_id"], "supersedes", "Explicit schedule revision")
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE memory_candidates SET expiry = '2020-01-01T00:00:00+00:00' WHERE ticket_id = ?",
                (newer["ticket_id"],),
            )
        result = rt.query_experience("deploy approval checklist", agent_id="hub:deploy")
        self.assertIn(old["ticket_id"], {item["ticket_id"] for item in result["items"]})
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            conn.execute(
                "UPDATE memory_candidates SET expiry = NULL, privacy_scope = 'public' WHERE ticket_id = ?",
                (newer["ticket_id"],),
            )
        malformed = rt.query_experience("deploy approval checklist", agent_id="hub:deploy")
        self.assertIn(old["ticket_id"], {item["ticket_id"] for item in malformed["items"]})

    def test_bundled_model2vec_runs_real_inference_with_english_and_korean_regression(self):
        from ontology.embeddings import cosine_similarity, select_vector_adapter, vector_adapter_metadata

        adapter = select_vector_adapter("auto")
        metadata = vector_adapter_metadata(adapter)
        self.assertEqual(metadata["name"], "model2vec_potion_base_8m_int8_hybrid")
        self.assertEqual(metadata["dimensions"], 352)
        self.assertEqual(
            metadata["asset"]["content_sha256"],
            "fe492f69607b750142aa48d47d579b53252b3288547c27d4d0e473d6af485e1e",
        )
        english = adapter.embed("database migration rollback checklist")
        digest = hashlib.sha256(
            b"".join(struct.pack("<i", round(value * 1_000_000)) for value in english)
        ).hexdigest()
        self.assertEqual(digest, "78fb16e49ce5164015ea9f7a57be5149c24d7870593daf1382df0eef7f46d8b3")
        self.assertGreater(
            cosine_similarity(english, adapter.embed("schema migration rollback plan")),
            cosine_similarity(english, adapter.embed("sunny picnic weather")),
        )

        korean = adapter.embed("한국어 계약서 자동 생성")
        self.assertEqual(len(korean), 352)
        self.assertGreater(
            cosine_similarity(korean, adapter.embed("계약서 생성 자동화")),
            cosine_similarity(korean, adapter.embed("오늘 점심 김치찌개")),
        )

    def test_auto_degrades_to_hash_only_when_verified_asset_is_absent(self):
        from ontology.embeddings import select_vector_adapter, vector_adapter_metadata

        with mock.patch("ontology.embeddings.find_verified_model_asset", return_value=None):
            adapter = select_vector_adapter("auto")
        metadata = vector_adapter_metadata(adapter)
        self.assertEqual(metadata["name"], "local_hashing")
        self.assertEqual(metadata["status"], "degraded_fallback")
        self.assertEqual(metadata["fallback_reason"], "verified_local_model2vec_asset_not_found")
        self.assertEqual(len(adapter.embed("계약서 자동화")), 96)

    def test_desktop_projection_contract_accepts_status_and_short_or_full_adapter_identity(self):
        rt = self.runtime()
        adapter = rt.vector_adapter
        records = [
            (
                "desktop-full-identity",
                "Always prepare a rollback checklist before a database migration.",
                adapter.identity,
            ),
            (
                "desktop-short-name",
                "Schema migrations require a tested rollback plan.",
                adapter.name,
            ),
        ]
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            for ticket, summary, adapter_value in records:
                vector = adapter.embed(summary)
                conn.execute(
                    """
                    INSERT INTO memory_candidates(
                      ticket_id, idempotency_key, query, candidate_text, source_refs_json,
                      reason, confidence, risk, expiry, suggested_scope, status,
                      durable_write_enabled, agent_id, memory_kind, tags_json, salience,
                      privacy_scope, source_memory_id, source_updated_at,
                      embedding_adapter, embedding_dimensions, embedding_json,
                      embedding_content_hash, created_at, updated_at
                    ) VALUES (?, ?, '', ?, '[]', 'desktop projection fixture', 0.8, 'projection', NULL,
                              'agent_repo', 'accepted', 0, 'hub:desktop-contract', 'experience',
                              '["migration","rollback"]', 0.8, 'private', ?,
                              '2026-07-15T00:00:00+00:00', ?, ?, ?, ?,
                              '2026-07-15T00:00:00+00:00', '2026-07-15T00:00:00+00:00')
                    """,
                    (
                        ticket,
                        f"key-{ticket}",
                        summary,
                        ticket,
                        adapter_value,
                        len(vector),
                        json.dumps(vector),
                        hashlib.sha256(summary.encode("utf-8")).hexdigest(),
                    ),
                )
        result = rt.query_experience(
            "database migration rollback strategy",
            agent_id="hub:desktop-contract",
        )
        selected = {item["ticket_id"] for item in result["items"]}
        self.assertEqual(selected, {"desktop-full-identity", "desktop-short-name"})

        projected = rt.ingest_experience(
            agent_id="hub:desktop-contract",
            summary="Prepare and test the rollback checklist before every database migration.",
            source_memory_id="core-projection",
            similar_threshold=0.7,
        )["experience"]
        with closing(sqlite3.connect(self.db_path)) as conn:
            linked = conn.execute(
                """
                SELECT count(*) FROM memory_links
                WHERE link_type = 'similar_to'
                  AND ((from_ticket = ? AND to_ticket = ?) OR (from_ticket = ? AND to_ticket = ?))
                """,
                (
                    projected["ticket_id"],
                    "desktop-full-identity",
                    "desktop-full-identity",
                    projected["ticket_id"],
                ),
            ).fetchone()[0]
        self.assertEqual(linked, 1, "write-time relation linking must accept a legacy full identity")

        reconciled = rt.relate_memory_candidates(threshold=0.35)
        self.assertGreaterEqual(reconciled["similar_links_created"], 1)
        with closing(sqlite3.connect(self.db_path)) as conn:
            linked = conn.execute(
                """
                SELECT count(*) FROM memory_links
                WHERE link_type = 'similar_to'
                  AND from_ticket = 'desktop-full-identity'
                  AND to_ticket = 'desktop-short-name'
                """
            ).fetchone()[0]
        self.assertEqual(linked, 1, "batch relation linking must canonicalize short and full identities")

    def test_runtime_adapter_identity_drift_reembeds_desktop_projection(self):
        rt = self.runtime()
        created = rt.ingest_experience(
            agent_id="hub:drift",
            summary="Keep a rollback plan for schema migrations.",
            source_memory_id="drift-row",
        )["experience"]
        with closing(sqlite3.connect(self.db_path)) as conn, conn:
            config = json.loads(
                conn.execute(
                    "SELECT config_json FROM runtime_adapters WHERE kind = 'vector'"
                ).fetchone()[0]
            )
            config["identity"] = "stale-model-revision-and-content-sha"
            conn.execute(
                "UPDATE runtime_adapters SET config_json = ? WHERE kind = 'vector'",
                (json.dumps(config),),
            )
            conn.execute(
                "UPDATE memory_candidates SET embedding_dimensions = 1, embedding_json = '[0.0]' WHERE ticket_id = ?",
                (created["ticket_id"],),
            )
        migrated = self.runtime()
        with closing(sqlite3.connect(self.db_path)) as conn:
            row = conn.execute(
                "SELECT embedding_adapter, embedding_dimensions, embedding_json FROM memory_candidates WHERE ticket_id = ?",
                (created["ticket_id"],),
            ).fetchone()
            runtime_config = json.loads(
                conn.execute("SELECT config_json FROM runtime_adapters WHERE kind = 'vector'").fetchone()[0]
            )
        self.assertEqual(row[0], migrated.vector_adapter.name)
        self.assertEqual(row[1], 352)
        self.assertEqual(len(json.loads(row[2])), 352)
        self.assertEqual(runtime_config["identity"], migrated.vector_adapter.identity)


def write_text_pdf(path: Path, text: str) -> None:
    stream = f"BT /F1 24 Tf 72 720 Td ({pdf_escape(text)}) Tj ET".encode("utf-8")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        b"5 0 obj << /Length " + str(len(stream)).encode("ascii") + b" >> stream\n" + stream + b"\nendstream endobj\n",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(output))
        output.extend(obj)
    xref_start = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(f"trailer << /Root 1 0 R /Size {len(objects) + 1} >>\nstartxref\n{xref_start}\n%%EOF\n".encode("ascii"))
    path.write_bytes(output)


def pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_hwpx(path: Path, text: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "Contents/section0.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<hp:section xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
  <hp:p><hp:run><hp:t>{text}</hp:t></hp:run></hp:p>
</hp:section>
""",
        )


def write_hwpx_table(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "Contents/section0.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<hp:section xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph">
  <hp:p><hp:run><hp:t>Project document table</hp:t></hp:run></hp:p>
  <hp:tbl>
    <hp:tr>
      <hp:tc><hp:p><hp:run><hp:t>Name</hp:t></hp:run></hp:p></hp:tc>
      <hp:tc><hp:p><hp:run><hp:t>Depends On</hp:t></hp:run></hp:p></hp:tc>
    </hp:tr>
    <hp:tr>
      <hp:tc><hp:p><hp:run><hp:t>Project Helios</hp:t></hp:run></hp:p></hp:tc>
      <hp:tc><hp:p><hp:run><hp:t>Memory Curator</hp:t></hp:run></hp:p></hp:tc>
    </hp:tr>
  </hp:tbl>
</hp:section>
""",
        )


def write_hwp5(path: Path, text: str) -> None:
    signature = b"HWP Document File" + b"\x00" * (32 - len(b"HWP Document File"))
    file_header = signature + struct.pack("<II", 0x05000000, 0)
    section = hwp_record(67, text.encode("utf-16le"))
    write_minimal_cfb(
        path,
        {
            "FileHeader": file_header,
            "BodyText/Section0": section,
        },
    )


def hwp_record(tag_id: int, payload: bytes, level: int = 0) -> bytes:
    if len(payload) < 0xFFF:
        return struct.pack("<I", tag_id | (level << 10) | (len(payload) << 20)) + payload
    return struct.pack("<II", tag_id | (level << 10) | (0xFFF << 20), len(payload)) + payload


def write_minimal_cfb(path: Path, streams: dict[str, bytes]) -> None:
    file_header = streams["FileHeader"]
    section0 = streams["BodyText/Section0"]
    sector_size = 512
    file_header_sector = 0
    section_sector = 1
    directory_sector = 2
    fat_sector = 3

    header = bytearray(sector_size)
    header[:8] = bytes.fromhex("d0cf11e0a1b11ae1")
    struct.pack_into("<H", header, 24, 0x003E)
    struct.pack_into("<H", header, 26, 3)
    struct.pack_into("<H", header, 28, 0xFFFE)
    struct.pack_into("<H", header, 30, 9)
    struct.pack_into("<H", header, 32, 6)
    struct.pack_into("<I", header, 44, 1)
    struct.pack_into("<I", header, 48, directory_sector)
    struct.pack_into("<I", header, 56, 4096)
    struct.pack_into("<I", header, 60, 0xFFFFFFFE)
    struct.pack_into("<I", header, 64, 0)
    struct.pack_into("<I", header, 68, 0xFFFFFFFE)
    struct.pack_into("<I", header, 72, 0)
    difat = [fat_sector] + [0xFFFFFFFF] * 108
    struct.pack_into("<109I", header, 76, *difat)

    directory = (
        cfb_directory_entry("Root Entry", 5, child=1)
        + cfb_directory_entry("FileHeader", 2, right=2, start_sector=file_header_sector, stream_size=len(file_header))
        + cfb_directory_entry("BodyText", 1, child=3)
        + cfb_directory_entry("Section0", 2, start_sector=section_sector, stream_size=len(section0))
    )

    fat = [0xFFFFFFFE, 0xFFFFFFFE, 0xFFFFFFFE, 0xFFFFFFFD] + [0xFFFFFFFF] * 124
    payload = bytearray(header)
    payload.extend(pad_sector(file_header, sector_size))
    payload.extend(pad_sector(section0, sector_size))
    payload.extend(pad_sector(directory, sector_size))
    payload.extend(struct.pack("<128I", *fat))
    path.write_bytes(payload)


def cfb_directory_entry(
    name: str,
    object_type: int,
    *,
    left: int = 0xFFFFFFFF,
    right: int = 0xFFFFFFFF,
    child: int = 0xFFFFFFFF,
    start_sector: int = 0xFFFFFFFE,
    stream_size: int = 0,
) -> bytes:
    entry = bytearray(128)
    encoded_name = name.encode("utf-16le") + b"\x00\x00"
    entry[: len(encoded_name)] = encoded_name
    struct.pack_into("<H", entry, 64, len(encoded_name))
    entry[66] = object_type
    entry[67] = 1
    struct.pack_into("<III", entry, 68, left, right, child)
    struct.pack_into("<I", entry, 116, start_sector)
    struct.pack_into("<Q", entry, 120, stream_size)
    return bytes(entry)


def pad_sector(payload: bytes, sector_size: int) -> bytes:
    padding = (-len(payload)) % sector_size
    return payload + (b"\x00" * padding)


def write_docx(path: Path, text: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>
</w:document>
""",
        )


def write_xlsx(path: Path, subject: str, target: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "xl/sharedStrings.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <si><t>name</t></si>
  <si><t>depends_on</t></si>
  <si><t>{subject}</t></si>
  <si><t>{target}</t></si>
</sst>
""",
        )
        archive.writestr(
            "xl/worksheets/sheet1.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row>
    <row r="2"><c t="s"><v>2</v></c><c t="s"><v>3</v></c></row>
  </sheetData>
</worksheet>
""",
        )


def write_pptx(path: Path, text: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "ppt/slides/slide1.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
</p:sld>
""",
        )


def write_ocr_image(path: Path, text: str) -> bool:
    if not shutil.which("swift"):
        path.write_bytes(b"no ocr engine fixture")
        return False
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        path.write_bytes(b"no pil fixture")
        return False
    image = Image.new("RGB", (900, 180), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 52)
    except Exception:
        font = None
    draw.text((40, 55), text, fill="black", font=font)
    image.save(path)
    return sys.platform == "darwin"


if __name__ == "__main__":
    unittest.main()
