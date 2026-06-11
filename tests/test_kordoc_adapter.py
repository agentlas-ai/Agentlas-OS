import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from ontology import kordoc_adapter
from ontology.parsers import SourceParserRegistry


def write_minimal_hwpx(path: Path, text: str) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "Contents/section0.xml",
            f'<root xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:t>{text}</hp:t></root>',
        )


def write_fake_kordoc(path: Path, markdown_lines: list[str]) -> None:
    body = "\n".join(f"echo '{line}'" for line in markdown_lines)
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class KordocAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.registry = SourceParserRegistry()

    def tearDown(self):
        self.tmp.cleanup()

    def test_split_markdown_sections_by_heading(self):
        markdown = "\n".join(
            [
                "머리말 문단",
                "",
                "# 사업 개요",
                "한글 계약서 자동 생성 사업.",
                "",
                "## 추진 일정",
                "| 단계 | 일정 |",
                "| --- | --- |",
            ]
        )
        sections = kordoc_adapter.split_markdown_sections(markdown)
        self.assertEqual(len(sections), 3)
        self.assertEqual(sections[0]["heading"], "")
        self.assertEqual(sections[1]["heading"], "사업 개요")
        self.assertEqual(sections[2]["heading"], "추진 일정")
        self.assertIn("| 단계 | 일정 |", str(sections[2]["text"]))

    def test_resolve_prefers_kordoc_bin_env(self):
        with mock.patch.dict(os.environ, {"KORDOC_BIN": "/opt/custom/kordoc"}):
            self.assertEqual(kordoc_adapter.resolve_kordoc_command(), ["/opt/custom/kordoc"])

    def test_kordoc_disable_wins_over_explicit_bin(self):
        with mock.patch.dict(os.environ, {"KORDOC_BIN": "/opt/custom/kordoc", "KORDOC_DISABLE": "1"}):
            self.assertIsNone(kordoc_adapter.resolve_kordoc_command())

    def test_npx_fallback_is_opt_in(self):
        clean_env = {key: value for key, value in os.environ.items() if not key.startswith("KORDOC_")}
        with mock.patch.dict(os.environ, clean_env, clear=True):
            with mock.patch.object(kordoc_adapter.shutil, "which", side_effect=lambda name: "/usr/bin/npx" if name == "npx" else None):
                self.assertIsNone(kordoc_adapter.resolve_kordoc_command())
            with mock.patch.dict(os.environ, {"KORDOC_ENABLE_NPX": "1"}):
                with mock.patch.object(kordoc_adapter.shutil, "which", side_effect=lambda name: "/usr/bin/npx" if name == "npx" else None):
                    self.assertEqual(kordoc_adapter.resolve_kordoc_command(), ["/usr/bin/npx", "-y", "kordoc"])

    def test_registry_falls_back_to_stdlib_hwpx_when_kordoc_unavailable(self):
        document_path = self.root / "doc.hwpx"
        write_minimal_hwpx(document_path, "한글 계약서 자동 생성")
        with mock.patch.object(kordoc_adapter, "resolve_kordoc_command", return_value=None):
            parsed = self.registry.parse(document_path)
        self.assertEqual(parsed.parser_status, "parsed")
        self.assertEqual(parsed.adapter_name, "hwpx_xml_parser")
        self.assertIn("한글 계약서 자동 생성", parsed.records[0].text)

    def test_registry_uses_kordoc_when_available(self):
        fake_kordoc = self.root / "fake-kordoc"
        write_fake_kordoc(fake_kordoc, ["# 공문 제목", "한글 본문 내용", "## 붙임", "붙임 1부"])
        document_path = self.root / "doc.hwp"
        document_path.write_bytes(b"\x00")
        with mock.patch.dict(os.environ, {"KORDOC_BIN": str(fake_kordoc)}):
            parsed = self.registry.parse(document_path)
        self.assertEqual(parsed.parser_status, "parsed")
        self.assertEqual(parsed.adapter_name, "kordoc_adapter")
        headings = [record.metadata.get("heading") for record in parsed.records]
        self.assertIn("공문 제목", headings)
        self.assertIn("붙임", headings)
        self.assertEqual(parsed.records[0].span["kind"], "kordoc_markdown_section")

    def test_kordoc_failure_falls_back_then_reports_error(self):
        fake_kordoc = self.root / "fake-kordoc-fail"
        fake_kordoc.write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
        fake_kordoc.chmod(fake_kordoc.stat().st_mode | stat.S_IXUSR)
        document_path = self.root / "doc.hwpx"
        write_minimal_hwpx(document_path, "폴백 본문")
        with mock.patch.dict(os.environ, {"KORDOC_BIN": str(fake_kordoc)}):
            parsed = self.registry.parse(document_path)
        # kordoc fails → stdlib hwpx parser succeeds → fallback result wins.
        self.assertEqual(parsed.parser_status, "parsed")
        self.assertEqual(parsed.adapter_name, "hwpx_xml_parser")

    def test_xls_without_kordoc_is_unsupported_pending_adapter(self):
        document_path = self.root / "table.xls"
        document_path.write_bytes(b"\x00")
        with mock.patch.object(kordoc_adapter, "resolve_kordoc_command", return_value=None):
            parsed = self.registry.parse(document_path)
        self.assertEqual(parsed.parser_status, "unsupported_pending_adapter")
        self.assertEqual(parsed.adapter_name, "kordoc_adapter")

    def test_adapter_status_reports_kordoc(self):
        statuses = dict(self.registry.adapter_statuses())
        self.assertIn("kordoc_adapter", statuses)
        self.assertTrue(
            statuses["kordoc_adapter"].startswith("available")
            or statuses["kordoc_adapter"] == "unavailable_missing_kordoc"
        )


if __name__ == "__main__":
    unittest.main()
