from __future__ import annotations

import csv
import json
import platform
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from .korean_document_model import HephaestusKoreanDocumentModel, KoreanParseResult


@dataclass
class ParsedRecord:
    text: str
    span: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    source_type: str
    parser_status: str
    records: list[ParsedRecord]
    parser_message: str = ""
    adapter_name: str = ""


class SourceParserRegistry:
    def __init__(self) -> None:
        self.korean_model = HephaestusKoreanDocumentModel()

    def parse(self, path: Path) -> ParsedDocument:
        suffix = path.suffix.lower()
        if suffix in {".md", ".markdown"}:
            return self._parse_text(path, "markdown")
        if suffix in {".txt", ".text", ".log"}:
            return self._parse_text(path, "text")
        if suffix == ".json":
            return self._parse_json(path)
        if suffix == ".csv":
            return self._parse_csv(path)
        if suffix == ".docx":
            return self._parse_docx(path)
        if suffix == ".xlsx":
            return self._parse_xlsx(path)
        if suffix == ".xls":
            return unsupported("xls", "xls_parser_adapter")
        if suffix == ".hml":
            return unsupported("hwpml", "hwpml_parser_adapter")
        if suffix == ".pptx":
            return self._parse_pptx(path)
        if suffix == ".pdf":
            return self._parse_pdf(path)
        if suffix == ".hwpx":
            return self._parse_hwpx(path)
        if suffix == ".hwp":
            return self._parse_hwp(path)
        if suffix in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tiff", ".bmp"}:
            return self._parse_image_ocr(path)
        return unsupported(suffix.lstrip(".") or "unknown", "unregistered_parser_adapter")

    def adapter_statuses(self) -> list[tuple[str, str]]:
        return [
            ("markdown_parser", "available"),
            ("text_parser", "available"),
            ("json_parser", "available"),
            ("csv_parser", "available"),
            ("docx_xml_parser", "available"),
            ("xlsx_xml_parser", "available"),
            ("xls_parser_adapter", "unsupported_pending_adapter"),
            ("hwpml_parser_adapter", "unsupported_pending_adapter"),
            ("pptx_xml_parser", "available"),
            ("pdf_text_adapter", "available" if shutil.which("pdftotext") else "unavailable_missing_pdftotext"),
            (self.korean_model.hwpx_adapter_name, "available"),
            (self.korean_model.hwp_adapter_name, "available"),
            ("macos_vision_ocr_adapter", "available" if macos_vision_available() else "unavailable_missing_macos_vision"),
            ("tesseract_ocr_adapter", "available" if shutil.which("tesseract") else "unavailable_missing_tesseract"),
        ]

    def _parse_text(self, path: Path, source_type: str) -> ParsedDocument:
        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        return ParsedDocument(
            source_type=source_type,
            parser_status="parsed",
            records=[
                ParsedRecord(
                    text=text,
                    span={"kind": "line_range", "line_start": 1, "line_end": max(1, len(lines))},
                    metadata={"line_count": len(lines)},
                )
            ],
            adapter_name=f"{source_type}_parser",
        )

    def _parse_json(self, path: Path) -> ParsedDocument:
        payload = json.loads(path.read_text(encoding="utf-8"))
        records = [
            ParsedRecord(text=f"{key}: {value}", span={"kind": "json_path", "path": key}, metadata={"json_path": key})
            for key, value in flatten_json(payload)
        ]
        return ParsedDocument("json", "parsed", records, adapter_name="json_parser")

    def _parse_csv(self, path: Path) -> ParsedDocument:
        records: list[ParsedRecord] = []
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for index, row in enumerate(reader, start=2):
                text = " | ".join(f"{key}: {value}" for key, value in row.items())
                records.append(
                    ParsedRecord(
                        text=text,
                        span={"kind": "csv_row", "row_start": index, "row_end": index},
                        metadata={"row": index, "columns": list(row.keys())},
                    )
                )
        return ParsedDocument("csv", "parsed", records, adapter_name="csv_parser")

    def _parse_docx(self, path: Path) -> ParsedDocument:
        try:
            with zipfile.ZipFile(path) as archive:
                document = archive.read("word/document.xml")
        except Exception as exc:
            return ParsedDocument("docx", "parser_error", [], str(exc), "docx_xml_parser")
        root = ElementTree.fromstring(document)
        paragraphs: list[str] = []
        for paragraph in root.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
            text = "".join(
                node.text or ""
                for node in paragraph.findall(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
            ).strip()
            if text:
                paragraphs.append(text)
        records = [
            ParsedRecord(
                text=text,
                span={"kind": "docx_paragraph", "paragraph": index},
                metadata={"paragraph": index},
            )
            for index, text in enumerate(paragraphs, start=1)
        ]
        return ParsedDocument("docx", "parsed", records, adapter_name="docx_xml_parser")

    def _parse_xlsx(self, path: Path) -> ParsedDocument:
        try:
            with zipfile.ZipFile(path) as archive:
                shared = self._xlsx_shared_strings(archive)
                sheet_names = sorted(name for name in archive.namelist() if name.startswith("xl/worksheets/sheet"))
                records: list[ParsedRecord] = []
                for sheet_index, sheet_name in enumerate(sheet_names, start=1):
                    root = ElementTree.fromstring(archive.read(sheet_name))
                    for row in root.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row"):
                        row_number = int(row.attrib.get("r", "0") or 0)
                        values = []
                        for cell in row.findall("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}c"):
                            values.append(self._xlsx_cell_value(cell, shared))
                        text = " | ".join(value for value in values if value)
                        if text:
                            records.append(
                                ParsedRecord(
                                    text=text,
                                    span={"kind": "xlsx_row", "sheet": sheet_index, "row_start": row_number, "row_end": row_number},
                                    metadata={"sheet": sheet_index, "row": row_number},
                                )
                            )
        except Exception as exc:
            return ParsedDocument("xlsx", "parser_error", [], str(exc), "xlsx_xml_parser")
        return ParsedDocument("xlsx", "parsed", records, adapter_name="xlsx_xml_parser")

    def _parse_pptx(self, path: Path) -> ParsedDocument:
        try:
            with zipfile.ZipFile(path) as archive:
                slide_names = sorted(name for name in archive.namelist() if re.match(r"ppt/slides/slide\d+\.xml", name))
                records: list[ParsedRecord] = []
                for slide_index, slide_name in enumerate(slide_names, start=1):
                    root = ElementTree.fromstring(archive.read(slide_name))
                    text = " ".join(
                        (node.text or "").strip()
                        for node in root.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}t")
                        if (node.text or "").strip()
                    )
                    if text:
                        records.append(
                            ParsedRecord(
                                text=text,
                                span={"kind": "pptx_slide", "slide": slide_index},
                                metadata={"slide": slide_index},
                            )
                        )
        except Exception as exc:
            return ParsedDocument("pptx", "parser_error", [], str(exc), "pptx_xml_parser")
        return ParsedDocument("pptx", "parsed", records, adapter_name="pptx_xml_parser")

    def _parse_pdf(self, path: Path) -> ParsedDocument:
        pdftotext = shutil.which("pdftotext")
        if not pdftotext:
            return unsupported("pdf", "pdf_text_adapter", "pdftotext is not installed")
        try:
            output = subprocess.run(
                [pdftotext, "-layout", "-enc", "UTF-8", str(path), "-"],
                text=True,
                capture_output=True,
                check=True,
                timeout=30,
            )
        except Exception as exc:
            return ParsedDocument("pdf", "parser_error", [], str(exc), "pdf_text_adapter")
        pages = split_pages(output.stdout)
        records = [
            ParsedRecord(
                text=text,
                span={"kind": "pdf_page", "page": index},
                metadata={"page": index},
            )
            for index, text in enumerate(pages, start=1)
            if text.strip()
        ]
        if not records:
            return ParsedDocument("pdf", "parser_error", [], "no extractable text found", "pdf_text_adapter")
        return ParsedDocument("pdf", "parsed", records, adapter_name="pdf_text_adapter")

    def _parse_hwpx(self, path: Path) -> ParsedDocument:
        return self._from_korean_result(self.korean_model.parse_hwpx(path))

    def _parse_hwp(self, path: Path) -> ParsedDocument:
        return self._from_korean_result(self.korean_model.parse_hwp(path))

    def _from_korean_result(self, result: KoreanParseResult) -> ParsedDocument:
        return ParsedDocument(
            source_type=result.source_type,
            parser_status=result.parser_status,
            records=[
                ParsedRecord(text=record.text, span=record.span, metadata=record.metadata)
                for record in result.records
            ],
            parser_message=result.parser_message,
            adapter_name=result.adapter_name,
        )

    def _parse_image_ocr(self, path: Path) -> ParsedDocument:
        macos_result: ParsedDocument | None = None
        if macos_vision_available():
            macos_result = self._parse_image_ocr_macos(path)
            if macos_result.parser_status == "parsed":
                return macos_result
        tesseract = shutil.which("tesseract")
        if tesseract:
            return self._parse_image_ocr_tesseract(path, tesseract)
        if macos_result is not None:
            return macos_result
        return unsupported("image", "image_ocr_adapter", "no OCR engine available")

    def _parse_image_ocr_tesseract(self, path: Path, tesseract: str) -> ParsedDocument:
        try:
            output = subprocess.run(
                [tesseract, str(path), "stdout"],
                text=True,
                capture_output=True,
                check=True,
                timeout=45,
            )
        except Exception as exc:
            return ParsedDocument("image", "parser_error", [], str(exc), "tesseract_ocr_adapter")
        text = output.stdout.strip()
        if not text:
            return ParsedDocument("image", "parser_error", [], "no text recognized", "tesseract_ocr_adapter")
        return ParsedDocument(
            "image",
            "parsed",
            [ParsedRecord(text=text, span={"kind": "image_ocr", "engine": "tesseract"}, metadata={"engine": "tesseract"})],
            adapter_name="tesseract_ocr_adapter",
        )

    def _parse_image_ocr_macos(self, path: Path) -> ParsedDocument:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "ocr.swift"
            script.write_text(MACOS_VISION_OCR_SWIFT, encoding="utf-8")
            try:
                output = subprocess.run(
                    ["swift", str(script), str(path)],
                    text=True,
                    capture_output=True,
                    check=True,
                    timeout=60,
                )
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as exc:
                detail = getattr(exc, "stderr", "") or str(exc)
                return unsupported("image", "macos_vision_ocr_adapter", f"macOS Vision OCR unavailable: {detail}")
            except Exception as exc:
                return ParsedDocument("image", "parser_error", [], str(exc), "macos_vision_ocr_adapter")
        text = output.stdout.strip()
        if not text:
            return ParsedDocument("image", "parser_error", [], "no text recognized", "macos_vision_ocr_adapter")
        return ParsedDocument(
            "image",
            "parsed",
            [ParsedRecord(text=text, span={"kind": "image_ocr", "engine": "macos_vision"}, metadata={"engine": "macos_vision"})],
            adapter_name="macos_vision_ocr_adapter",
        )

    def _xlsx_shared_strings(self, archive: zipfile.ZipFile) -> list[str]:
        try:
            root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
        except KeyError:
            return []
        values = []
        for item in root.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
            values.append(
                "".join(
                    node.text or ""
                    for node in item.findall(".//{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t")
                )
            )
        return values

    def _xlsx_cell_value(self, cell: ElementTree.Element, shared: list[str]) -> str:
        value = cell.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}v")
        if value is None or value.text is None:
            return ""
        if cell.attrib.get("t") == "s":
            index = int(value.text)
            return shared[index] if 0 <= index < len(shared) else ""
        return value.text


def flatten_json(payload: Any, prefix: str = "$") -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            rows.extend(flatten_json(value, f"{prefix}.{key}"))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            rows.extend(flatten_json(value, f"{prefix}[{index}]"))
    else:
        rows.append((prefix, str(payload)))
    return rows


def split_pages(text: str) -> list[str]:
    pages = [page.strip() for page in text.split("\f")]
    return [page for page in pages if page]


def macos_vision_available() -> bool:
    return platform.system() == "Darwin" and shutil.which("swift") is not None


MACOS_VISION_OCR_SWIFT = r"""
import Foundation
import Vision
import AppKit

let path = CommandLine.arguments[1]
let url = URL(fileURLWithPath: path)
guard let image = NSImage(contentsOf: url),
      let tiff = image.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: tiff),
      let cgImage = bitmap.cgImage else {
  fputs("image_load_failed\n", stderr)
  exit(2)
}

let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true
let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
do {
  try handler.perform([request])
  let observations = request.results ?? []
  let lines = observations.compactMap { $0.topCandidates(1).first?.string }
  print(lines.joined(separator: "\n"))
} catch {
  fputs("ocr_failed: \(error)\n", stderr)
  exit(3)
}
"""


def unsupported(source_type: str, adapter_name: str, reason: str | None = None) -> ParsedDocument:
    message = reason or f"{adapter_name} is registered but not implemented in the local runtime"
    return ParsedDocument(
        source_type=source_type,
        parser_status="unsupported_pending_adapter",
        records=[],
        parser_message=message,
        adapter_name=adapter_name,
    )
