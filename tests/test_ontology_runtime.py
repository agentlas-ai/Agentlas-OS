import json
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
import unittest
import zipfile
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
        self.assertIn("data-copy=\"/hephaestus ontology\"", gui_html)

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
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
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
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            spans = [
                json.loads(row["source_span_json"])
                for row in conn.execute("SELECT source_span_json FROM chunks ORDER BY chunk_index")
            ]
        self.assertGreater(len(spans), 1)
        for left, right in zip(spans, spans[1:]):
            self.assertLess(right["token_start"], left["token_end"], "windows must overlap")


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
