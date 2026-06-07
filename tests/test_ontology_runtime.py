import json
import os
import shutil
import sqlite3
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

    def test_document_adapters_parse_real_formats(self):
        adapter_corpus = self.root / "adapter-corpus"
        adapter_corpus.mkdir()
        write_text_pdf(adapter_corpus / "manual.pdf", "Project Helios depends on Memory Curator")
        write_hwpx(adapter_corpus / "manual.hwpx", "Project Helios depends on Memory Curator")
        write_docx(adapter_corpus / "brief.docx", "Project Helios depends on Memory Curator")
        write_xlsx(adapter_corpus / "matrix.xlsx", "Project Helios", "Memory Curator")
        write_pptx(adapter_corpus / "slides.pptx", "Project Helios depends on Memory Curator")
        image_expected = write_ocr_image(adapter_corpus / "scan.png", "Memory Curator OCR")

        rt = self.runtime()
        ingest = rt.ingest_path(adapter_corpus, access_scope="internal")
        by_name = {item["display_name"]: item for item in ingest["sources"]}

        self.assertEqual(by_name["manual.pdf"]["parser_status"], "parsed", by_name)
        self.assertEqual(by_name["manual.hwpx"]["parser_status"], "parsed", by_name)
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
        self.assertIn("Hephaestus Ontology", gui_path.read_text(encoding="utf-8"))

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
        self.assertTrue(Path(payload["gui_path"]).exists())
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
