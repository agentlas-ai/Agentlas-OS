from __future__ import annotations

import re
import struct
import zlib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


PARSER_MODEL_VERSION = "hephaestus_docparse_v1"

HWP5_CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
CFB_FREESECT = 0xFFFFFFFF
CFB_ENDOFCHAIN = 0xFFFFFFFE
CFB_FATSECT = 0xFFFFFFFD
CFB_DIFSECT = 0xFFFFFFFC
CFB_NOSTREAM = 0xFFFFFFFF

HWP_TAG_PARA_TEXT = 67


@dataclass
class KoreanParsedRecord:
    text: str
    span: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KoreanParseResult:
    source_type: str
    parser_status: str
    records: list[KoreanParsedRecord]
    parser_message: str = ""
    adapter_name: str = ""


@dataclass
class CfbDirectoryEntry:
    index: int
    name: str
    object_type: int
    left: int
    right: int
    child: int
    start_sector: int
    stream_size: int


class HephaestusKoreanDocumentModel:
    """First-party Korean document extraction model for ontology ingestion.

    This is not a renderer. It extracts source-grounded paragraph/table text
    with stable spans so the ontology runtime can cite and reprocess source
    regions.
    """

    hwpx_adapter_name = "hephaestus_hwpx_parser"
    hwp_adapter_name = "hephaestus_hwp5_parser"

    def parse_hwpx(self, path: Path) -> KoreanParseResult:
        try:
            with zipfile.ZipFile(path) as archive:
                xml_names = self._hwpx_xml_names(archive)
                if not xml_names:
                    return KoreanParseResult(
                        "hwpx",
                        "parser_error",
                        [],
                        "no xml parts found in HWPX package",
                        self.hwpx_adapter_name,
                    )
                records: list[KoreanParsedRecord] = []
                counters = {"paragraph": 0, "table": 0}
                for name in xml_names:
                    root = ElementTree.fromstring(archive.read(name))
                    self._walk_hwpx_blocks(root, name, records, counters)
        except zipfile.BadZipFile as exc:
            return KoreanParseResult("hwpx", "parser_error", [], f"invalid HWPX zip: {exc}", self.hwpx_adapter_name)
        except Exception as exc:
            return KoreanParseResult("hwpx", "parser_error", [], str(exc), self.hwpx_adapter_name)

        if not records:
            return KoreanParseResult("hwpx", "parser_error", [], "no extractable text found", self.hwpx_adapter_name)
        message = f"{PARSER_MODEL_VERSION}: records={len(records)}, tables={counters['table']}"
        return KoreanParseResult("hwpx", "parsed", records, message, self.hwpx_adapter_name)

    def parse_hwp(self, path: Path) -> KoreanParseResult:
        try:
            cfb = CompoundFileBinary(path.read_bytes())
            streams = cfb.streams()
            header = self._find_stream(streams, "FileHeader")
            if header is None:
                return KoreanParseResult("hwp", "parser_error", [], "missing HWP FileHeader stream", self.hwp_adapter_name)
            header_info = self._parse_hwp5_file_header(header)
            if header_info["encrypted"]:
                return KoreanParseResult(
                    "hwp",
                    "unsupported_pending_adapter",
                    [],
                    "encrypted or distribution-protected HWP is not parsed by the first-party adapter",
                    self.hwp_adapter_name,
                )
            section_streams = self._hwp_body_sections(streams)
            if not section_streams:
                return KoreanParseResult("hwp", "parser_error", [], "missing BodyText/Section streams", self.hwp_adapter_name)

            records: list[KoreanParsedRecord] = []
            for section_index, (section_name, payload) in enumerate(section_streams, start=1):
                section_payload = self._maybe_decompress_hwp_section(payload, bool(header_info["compressed"]))
                section_records = self._parse_hwp_section_records(section_payload, section_name, section_index)
                records.extend(section_records)
        except CfbParseError as exc:
            return KoreanParseResult("hwp", "parser_error", [], str(exc), self.hwp_adapter_name)
        except zlib.error as exc:
            return KoreanParseResult("hwp", "parser_error", [], f"HWP section decompression failed: {exc}", self.hwp_adapter_name)
        except Exception as exc:
            return KoreanParseResult("hwp", "parser_error", [], str(exc), self.hwp_adapter_name)

        if not records:
            return KoreanParseResult("hwp", "parser_error", [], "no extractable text found", self.hwp_adapter_name)
        message = f"{PARSER_MODEL_VERSION}: records={len(records)}, compressed={bool(header_info['compressed'])}"
        return KoreanParseResult("hwp", "parsed", records, message, self.hwp_adapter_name)

    def _hwpx_xml_names(self, archive: zipfile.ZipFile) -> list[str]:
        names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
        section_names = sorted(
            name
            for name in names
            if name.lower().startswith("contents/section") or re.search(r"/section\d+\.xml$", name.lower())
        )
        remaining = sorted(name for name in names if name not in set(section_names))
        return section_names + remaining

    def _walk_hwpx_blocks(
        self,
        node: ElementTree.Element,
        file_name: str,
        records: list[KoreanParsedRecord],
        counters: dict[str, int],
    ) -> None:
        local = local_name(node.tag)
        if local in {"tbl", "table"}:
            table = self._hwpx_table_record(node, file_name, counters)
            if table is not None:
                records.append(table)
            return
        if local in {"p", "para", "paragraph"}:
            text = normalize_text(text_from_xml_excluding(node, {"tbl", "table"}))
            if text:
                counters["paragraph"] += 1
                records.append(
                    KoreanParsedRecord(
                        text=text,
                        span={
                            "kind": "hwpx_paragraph",
                            "file": file_name,
                            "paragraph": counters["paragraph"],
                            "parser_model": PARSER_MODEL_VERSION,
                        },
                        metadata={"xml_file": file_name, "block_type": "paragraph"},
                    )
                )
        for child in list(node):
            self._walk_hwpx_blocks(child, file_name, records, counters)

    def _hwpx_table_record(
        self,
        table: ElementTree.Element,
        file_name: str,
        counters: dict[str, int],
    ) -> KoreanParsedRecord | None:
        rows: list[list[str]] = []
        for row in iter_descendants_by_local(table, {"tr", "row"}):
            cells = []
            for cell in children_by_local(row, {"tc", "cell"}):
                cell_text = normalize_text(text_from_xml(cell))
                cells.append(cell_text)
            if any(cells):
                rows.append(cells)
        if not rows:
            return None
        counters["table"] += 1
        width = max(len(row) for row in rows)
        lines = []
        for row_index, row in enumerate(rows, start=1):
            padded = row + [""] * (width - len(row))
            lines.append(f"table {counters['table']} row {row_index}: " + " | ".join(padded))
        return KoreanParsedRecord(
            text="\n".join(lines),
            span={
                "kind": "hwpx_table",
                "file": file_name,
                "table": counters["table"],
                "row_count": len(rows),
                "column_count": width,
                "parser_model": PARSER_MODEL_VERSION,
            },
            metadata={
                "xml_file": file_name,
                "block_type": "table",
                "row_count": len(rows),
                "column_count": width,
            },
        )

    def _find_stream(self, streams: dict[str, bytes], stream_name: str) -> bytes | None:
        target = stream_name.lower()
        for name, payload in streams.items():
            if name.lower().split("/")[-1] == target:
                return payload
        return None

    def _parse_hwp5_file_header(self, payload: bytes) -> dict[str, Any]:
        if len(payload) < 40:
            raise CfbParseError("HWP FileHeader stream is too short")
        signature = payload[:32].split(b"\x00", 1)[0]
        if signature != b"HWP Document File":
            raise CfbParseError("not a HWP 5 FileHeader stream")
        properties = struct.unpack_from("<I", payload, 36)[0]
        return {
            "compressed": bool(properties & 0x01),
            "encrypted": bool(properties & 0x02 or properties & 0x04),
            "properties": properties,
        }

    def _hwp_body_sections(self, streams: dict[str, bytes]) -> list[tuple[str, bytes]]:
        sections = []
        for name, payload in streams.items():
            normalized = name.replace("\\", "/").lower()
            if re.search(r"(^|/)bodytext/section\d+$", normalized) or re.search(r"(^|/)section\d+$", normalized):
                sections.append((name, payload))
        return sorted(sections, key=lambda item: natural_key(item[0]))

    def _maybe_decompress_hwp_section(self, payload: bytes, compressed: bool) -> bytes:
        if not compressed:
            return payload
        try:
            return zlib.decompress(payload, -15)
        except zlib.error:
            return zlib.decompress(payload)

    def _parse_hwp_section_records(
        self,
        payload: bytes,
        section_name: str,
        section_index: int,
    ) -> list[KoreanParsedRecord]:
        records = []
        offset = 0
        record_index = 0
        while offset + 4 <= len(payload):
            header = struct.unpack_from("<I", payload, offset)[0]
            offset += 4
            tag_id = header & 0x3FF
            level = (header >> 10) & 0x3FF
            size = (header >> 20) & 0xFFF
            if size == 0xFFF:
                if offset + 4 > len(payload):
                    break
                size = struct.unpack_from("<I", payload, offset)[0]
                offset += 4
            if size < 0 or offset + size > len(payload):
                break
            body = payload[offset : offset + size]
            offset += size
            record_index += 1
            if tag_id != HWP_TAG_PARA_TEXT:
                continue
            text = normalize_text(decode_hwp_para_text(body))
            if not text:
                continue
            records.append(
                KoreanParsedRecord(
                    text=text,
                    span={
                        "kind": "hwp5_para_text",
                        "section": section_index,
                        "stream": section_name,
                        "record": record_index,
                        "level": level,
                        "parser_model": PARSER_MODEL_VERSION,
                    },
                    metadata={
                        "stream": section_name,
                        "section": section_index,
                        "record": record_index,
                        "tag_id": tag_id,
                    },
                )
            )
        return records


class CfbParseError(ValueError):
    pass


class CompoundFileBinary:
    def __init__(self, data: bytes):
        self.data = data
        if len(data) < 512 or data[:8] != HWP5_CFB_MAGIC:
            raise CfbParseError("not a Compound File Binary HWP document")
        self.sector_shift = struct.unpack_from("<H", data, 30)[0]
        self.mini_sector_shift = struct.unpack_from("<H", data, 32)[0]
        self.sector_size = 1 << self.sector_shift
        self.mini_sector_size = 1 << self.mini_sector_shift
        self.major_version = struct.unpack_from("<H", data, 26)[0]
        self.fat_sector_count = struct.unpack_from("<I", data, 44)[0]
        self.first_directory_sector = struct.unpack_from("<I", data, 48)[0]
        self.mini_stream_cutoff = struct.unpack_from("<I", data, 56)[0]
        self.first_mini_fat_sector = struct.unpack_from("<I", data, 60)[0]
        self.mini_fat_sector_count = struct.unpack_from("<I", data, 64)[0]
        self.first_difat_sector = struct.unpack_from("<I", data, 68)[0]
        self.difat_sector_count = struct.unpack_from("<I", data, 72)[0]
        self.fat = self._read_fat()
        self.directory = self._read_directory()
        self.root = self.directory[0] if self.directory else None
        self._mini_fat: list[int] | None = None
        self._mini_stream: bytes | None = None

    def streams(self) -> dict[str, bytes]:
        if not self.directory:
            raise CfbParseError("CFB directory is empty")
        paths: dict[int, str] = {}
        self._walk_directory_tree(self.directory[0].child, "", paths)
        streams = {}
        for entry in self.directory:
            if entry.object_type == 2:
                name = paths.get(entry.index, entry.name)
                streams[name] = self._read_stream(entry)
        return streams

    def _walk_directory_tree(self, index: int, prefix: str, paths: dict[int, str]) -> None:
        if index == CFB_NOSTREAM or index >= len(self.directory):
            return
        entry = self.directory[index]
        self._walk_directory_tree(entry.left, prefix, paths)
        path = f"{prefix}/{entry.name}" if prefix else entry.name
        paths[index] = path
        if entry.object_type == 1:
            self._walk_directory_tree(entry.child, path, paths)
        self._walk_directory_tree(entry.right, prefix, paths)

    def _read_fat(self) -> list[int]:
        difat = list(struct.unpack_from("<109I", self.data, 76))
        next_difat = self.first_difat_sector
        for _ in range(self.difat_sector_count):
            if next_difat in {CFB_ENDOFCHAIN, CFB_FREESECT}:
                break
            sector = self._sector_bytes(next_difat)
            entries_per_sector = self.sector_size // 4
            entries = list(struct.unpack_from(f"<{entries_per_sector}I", sector, 0))
            difat.extend(entries[:-1])
            next_difat = entries[-1]
        fat = []
        for sector_id in [item for item in difat if item not in {CFB_FREESECT, CFB_ENDOFCHAIN}]:
            sector = self._sector_bytes(sector_id)
            entries_per_sector = self.sector_size // 4
            fat.extend(struct.unpack_from(f"<{entries_per_sector}I", sector, 0))
            if len(fat) >= self.fat_sector_count * entries_per_sector:
                break
        return fat

    def _read_directory(self) -> list[CfbDirectoryEntry]:
        raw = self._read_regular_chain(self.first_directory_sector)
        entries = []
        for index in range(0, len(raw), 128):
            chunk = raw[index : index + 128]
            if len(chunk) < 128:
                continue
            name_size = struct.unpack_from("<H", chunk, 64)[0]
            if name_size < 2:
                continue
            name_raw = chunk[: name_size - 2]
            name = name_raw.decode("utf-16le", errors="ignore")
            object_type = chunk[66]
            if object_type == 0:
                continue
            stream_size = struct.unpack_from("<Q", chunk, 120)[0]
            if self.major_version == 3:
                stream_size &= 0xFFFFFFFF
            entries.append(
                CfbDirectoryEntry(
                    index=index // 128,
                    name=name,
                    object_type=object_type,
                    left=struct.unpack_from("<I", chunk, 68)[0],
                    right=struct.unpack_from("<I", chunk, 72)[0],
                    child=struct.unpack_from("<I", chunk, 76)[0],
                    start_sector=struct.unpack_from("<I", chunk, 116)[0],
                    stream_size=stream_size,
                )
            )
        return entries

    def _read_stream(self, entry: CfbDirectoryEntry) -> bytes:
        if (
            entry.stream_size < self.mini_stream_cutoff
            and entry.start_sector not in {CFB_ENDOFCHAIN, CFB_FREESECT}
            and self.mini_fat_sector_count > 0
            and self.root is not None
            and self.root.stream_size > 0
        ):
            return self._read_mini_chain(entry.start_sector, entry.stream_size)
        return self._read_regular_chain(entry.start_sector, entry.stream_size)

    def _read_regular_chain(self, start_sector: int, size: int | None = None) -> bytes:
        if start_sector in {CFB_ENDOFCHAIN, CFB_FREESECT}:
            return b""
        out = bytearray()
        sector = start_sector
        seen = set()
        while sector not in {CFB_ENDOFCHAIN, CFB_FREESECT}:
            if sector in seen:
                raise CfbParseError("CFB sector chain loop detected")
            if sector >= len(self.fat):
                raise CfbParseError(f"CFB sector {sector} is outside FAT")
            seen.add(sector)
            out.extend(self._sector_bytes(sector))
            sector = self.fat[sector]
        data = bytes(out)
        return data[:size] if size is not None else data

    def _read_mini_chain(self, start_sector: int, size: int) -> bytes:
        mini_fat = self._load_mini_fat()
        mini_stream = self._load_mini_stream()
        out = bytearray()
        sector = start_sector
        seen = set()
        while sector not in {CFB_ENDOFCHAIN, CFB_FREESECT}:
            if sector in seen:
                raise CfbParseError("CFB mini sector chain loop detected")
            if sector >= len(mini_fat):
                raise CfbParseError(f"CFB mini sector {sector} is outside mini FAT")
            seen.add(sector)
            start = sector * self.mini_sector_size
            end = start + self.mini_sector_size
            out.extend(mini_stream[start:end])
            sector = mini_fat[sector]
        return bytes(out)[:size]

    def _load_mini_fat(self) -> list[int]:
        if self._mini_fat is not None:
            return self._mini_fat
        size = self.mini_fat_sector_count * self.sector_size
        raw = self._read_regular_chain(self.first_mini_fat_sector, size)
        self._mini_fat = list(struct.unpack_from(f"<{len(raw) // 4}I", raw, 0)) if raw else []
        return self._mini_fat

    def _load_mini_stream(self) -> bytes:
        if self._mini_stream is not None:
            return self._mini_stream
        if self.root is None:
            raise CfbParseError("CFB root entry is missing")
        self._mini_stream = self._read_regular_chain(self.root.start_sector, self.root.stream_size)
        return self._mini_stream

    def _sector_bytes(self, sector_id: int) -> bytes:
        start = (sector_id + 1) * self.sector_size
        end = start + self.sector_size
        if start < self.sector_size or end > len(self.data):
            raise CfbParseError(f"CFB sector {sector_id} is outside file")
        return self.data[start:end]


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def text_from_xml(node: ElementTree.Element) -> str:
    values = []
    for item in node.iter():
        if local_name(item.tag) in {"t", "text"} and item.text:
            values.append(item.text)
    return " ".join(values)


def text_from_xml_excluding(node: ElementTree.Element, excluded_names: set[str]) -> str:
    values = []

    def walk(item: ElementTree.Element) -> None:
        if item is not node and local_name(item.tag) in excluded_names:
            return
        if local_name(item.tag) in {"t", "text"} and item.text:
            values.append(item.text)
        for child in list(item):
            walk(child)

    walk(node)
    return " ".join(values)


def iter_descendants_by_local(node: ElementTree.Element, names: set[str]) -> list[ElementTree.Element]:
    return [item for item in node.iter() if item is not node and local_name(item.tag) in names]


def children_by_local(node: ElementTree.Element, names: set[str]) -> list[ElementTree.Element]:
    return [item for item in list(node) if local_name(item.tag) in names]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def decode_hwp_para_text(payload: bytes) -> str:
    if len(payload) % 2:
        payload = payload[:-1]
    text = payload.decode("utf-16le", errors="ignore")
    cleaned = []
    for char in text:
        code = ord(char)
        if char in {"\n", "\r", "\t"}:
            cleaned.append(" ")
        elif code < 32 or 0xE000 <= code <= 0xF8FF:
            cleaned.append(" ")
        else:
            cleaned.append(char)
    return "".join(cleaned)


def natural_key(value: str) -> list[int | str]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]
