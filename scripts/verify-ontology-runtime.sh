#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

export PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}"

python3 -m unittest discover -s "$root/tests" -v

db="$tmp/ontology.sqlite"
adapter_corpus="$tmp/adapter-corpus"
mkdir -p "$adapter_corpus"
python3 - "$adapter_corpus" <<'PY'
import json
import shutil
import struct
import sys
import zipfile
from pathlib import Path

adapter = Path(sys.argv[1])

def pdf_escape(text):
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

def write_text_pdf(path, text):
    stream = f"BT /F1 24 Tf 72 720 Td ({pdf_escape(text)}) Tj ET".encode()
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >> endobj\n",
        b"4 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
        b"5 0 obj << /Length " + str(len(stream)).encode() + b" >> stream\n" + stream + b"\nendstream endobj\n",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(out))
        out.extend(obj)
    xref_start = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode())
    out.extend(f"trailer << /Root 1 0 R /Size {len(objects) + 1} >>\nstartxref\n{xref_start}\n%%EOF\n".encode())
    path.write_bytes(out)

def write_zip(path, entries):
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in entries.items():
            archive.writestr(name, text)

def write_hwp5(path, text):
    signature = b"HWP Document File" + b"\x00" * (32 - len(b"HWP Document File"))
    file_header = signature + struct.pack("<II", 0x05000000, 0)
    section = hwp_record(67, text.encode("utf-16le"))
    write_minimal_cfb(path, {
        "FileHeader": file_header,
        "BodyText/Section0": section,
    })

def hwp_record(tag_id, payload, level=0):
    if len(payload) < 0xFFF:
        return struct.pack("<I", tag_id | (level << 10) | (len(payload) << 20)) + payload
    return struct.pack("<II", tag_id | (level << 10) | (0xFFF << 20), len(payload)) + payload

def write_minimal_cfb(path, streams):
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
    struct.pack_into("<I", header, 68, 0xFFFFFFFE)
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
    name,
    object_type,
    *,
    left=0xFFFFFFFF,
    right=0xFFFFFFFF,
    child=0xFFFFFFFF,
    start_sector=0xFFFFFFFE,
    stream_size=0,
):
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

def pad_sector(payload, sector_size):
    padding = (-len(payload)) % sector_size
    return payload + (b"\x00" * padding)

write_text_pdf(adapter / "manual.pdf", "Project Helios depends on Memory Curator")
write_zip(adapter / "manual.hwpx", {
    "Contents/section0.xml": """<?xml version="1.0" encoding="UTF-8"?>
<hp:section xmlns:hp="http://www.hancom.co.kr/hwpml/2011/paragraph"><hp:p><hp:run><hp:t>Project Helios depends on Memory Curator</hp:t></hp:run></hp:p></hp:section>
"""
})
write_hwp5(adapter / "manual.hwp", "Project Helios depends on Memory Curator")
write_zip(adapter / "brief.docx", {
    "word/document.xml": """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Project Helios depends on Memory Curator</w:t></w:r></w:p></w:body></w:document>
"""
})
write_zip(adapter / "matrix.xlsx", {
    "xl/sharedStrings.xml": """<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><si><t>name</t></si><si><t>depends_on</t></si><si><t>Project Helios</t></si><si><t>Memory Curator</t></si></sst>
""",
    "xl/worksheets/sheet1.xml": """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c t="s"><v>0</v></c><c t="s"><v>1</v></c></row><row r="2"><c t="s"><v>2</v></c><c t="s"><v>3</v></c></row></sheetData></worksheet>
""",
})
write_zip(adapter / "slides.pptx", {
    "ppt/slides/slide1.xml": """<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>Project Helios depends on Memory Curator</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld></p:sld>
"""
})
image_expected = False
try:
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("RGB", (900, 180), "white")
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 52)
    except Exception:
        font = None
    draw.text((40, 55), "Memory Curator OCR", fill="black", font=font)
    image.save(adapter / "scan.png")
    image_expected = sys.platform == "darwin" and shutil.which("swift") is not None
except Exception:
    (adapter / "scan.png").write_bytes(b"ocr fixture unavailable")

(adapter / "adapter-meta.json").write_text(json.dumps({"image_expected": image_expected}), encoding="utf-8")
PY
"$root/bin/ontology" --db "$db" ingest "$root/examples/ontology-corpus" --scope internal >"$tmp/ingest.json"
"$root/bin/ontology" --db "$db" ingest "$adapter_corpus" --scope internal >"$tmp/adapter-ingest.json"
"$root/bin/ontology" --db "$db" query "Project Helios Memory Curator" --agent verifier --record-memory >"$tmp/query.json"
"$root/bin/ontology" --db "$db" graph entity "Project Helios" >"$tmp/entity.json"
"$root/bin/ontology" --db "$db" memory candidates >"$tmp/candidates.json"
"$root/bin/ontology" --db "$db" working-memory read --agent verifier >"$tmp/working-memory.json"
"$root/bin/ontology" --db "$db" working-memory prune --agent verifier >"$tmp/prune.json"
"$root/bin/ontology" --db "$db" verify >"$tmp/verify.json"
safe_project="$tmp/safe-project"
mkdir -p "$safe_project/.agentlas/ontology-inbox"
printf 'Safe Project Knowledge depends on Memory Curator.\n' >"$safe_project/.agentlas/ontology-inbox/source.md"
"$root/bin/ontology" auto "$safe_project" >"$tmp/auto.json"
"$root/bin/ontology" sources list --project "$safe_project" >"$tmp/sources.json"

python3 - "$tmp" <<'PY'
import json
import pathlib
import sys

tmp = pathlib.Path(sys.argv[1])
ingest = json.loads((tmp / "ingest.json").read_text())
adapter_ingest = json.loads((tmp / "adapter-ingest.json").read_text())
query = json.loads((tmp / "query.json").read_text())
entity = json.loads((tmp / "entity.json").read_text())
candidates = json.loads((tmp / "candidates.json").read_text())
working = json.loads((tmp / "working-memory.json").read_text())
verify = json.loads((tmp / "verify.json").read_text())
auto = json.loads((tmp / "auto.json").read_text())
sources = json.loads((tmp / "sources.json").read_text())

statuses = {item["source_type"]: item["parser_status"] for item in ingest["sources"]}
assert statuses["markdown"] == "parsed", statuses
assert statuses["text"] == "parsed", statuses
assert statuses["json"] == "parsed", statuses
assert statuses["csv"] == "parsed", statuses
assert statuses["hwp"] == "parser_error", statuses
adapter_statuses = {item["display_name"]: item["parser_status"] for item in adapter_ingest["sources"]}
assert adapter_statuses["manual.pdf"] == "parsed", adapter_statuses
assert adapter_statuses["manual.hwpx"] == "parsed", adapter_statuses
assert adapter_statuses["manual.hwp"] == "parsed", adapter_statuses
assert adapter_statuses["brief.docx"] == "parsed", adapter_statuses
assert adapter_statuses["matrix.xlsx"] == "parsed", adapter_statuses
assert adapter_statuses["slides.pptx"] == "parsed", adapter_statuses
meta = json.loads((tmp / "adapter-corpus" / "adapter-meta.json").read_text())
if meta["image_expected"]:
    assert adapter_statuses["scan.png"] == "parsed", adapter_statuses
assert ingest["chunks_written"] >= 4, ingest
assert adapter_ingest["chunks_written"] >= 6, adapter_ingest
assert query["chunks"], query
assert query["relation_edges"], query
assert query["memory_candidate_suggestions"], query
assert entity["relations"], entity
assert candidates["candidates"], candidates
assert working["items"], working
assert verify["status"] == "pass", verify
assert verify["direct_durable_memory_write_blocked"] is True, verify
assert auto["status"] == "active", auto
assert auto["auto_ingest_policy"] == "inbox_and_registered_sources_only", auto
assert auto["verify"]["status"] == "pass", auto
assert pathlib.Path(auto["db_path"]).name == "ontology-runtime.sqlite", auto
assert sources["sources"] == [], sources
PY

echo "Ontology runtime verification passed."
