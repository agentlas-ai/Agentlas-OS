#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

export PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}"

python3 -m unittest discover -s "$root/tests" -v

db="$tmp/ontology.sqlite"
"$root/bin/ontology" --db "$db" ingest "$root/examples/ontology-corpus" --scope internal >"$tmp/ingest.json"
"$root/bin/ontology" --db "$db" query "Project Helios Memory Curator" --agent verifier >"$tmp/query.json"
"$root/bin/ontology" --db "$db" graph entity "Project Helios" >"$tmp/entity.json"
"$root/bin/ontology" --db "$db" memory candidates >"$tmp/candidates.json"
"$root/bin/ontology" --db "$db" working-memory read --agent verifier >"$tmp/working-memory.json"
"$root/bin/ontology" --db "$db" working-memory prune --agent verifier >"$tmp/prune.json"
"$root/bin/ontology" --db "$db" verify >"$tmp/verify.json"

python3 - "$tmp" <<'PY'
import json
import pathlib
import sys

tmp = pathlib.Path(sys.argv[1])
ingest = json.loads((tmp / "ingest.json").read_text())
query = json.loads((tmp / "query.json").read_text())
entity = json.loads((tmp / "entity.json").read_text())
candidates = json.loads((tmp / "candidates.json").read_text())
working = json.loads((tmp / "working-memory.json").read_text())
verify = json.loads((tmp / "verify.json").read_text())

statuses = {item["source_type"]: item["parser_status"] for item in ingest["sources"]}
assert statuses["markdown"] == "parsed", statuses
assert statuses["text"] == "parsed", statuses
assert statuses["json"] == "parsed", statuses
assert statuses["csv"] == "parsed", statuses
assert statuses["hwp"] == "unsupported_pending_adapter", statuses
assert ingest["chunks_written"] >= 4, ingest
assert query["chunks"], query
assert query["relation_edges"], query
assert query["memory_candidate_suggestions"], query
assert entity["relations"], entity
assert candidates["candidates"], candidates
assert working["items"], working
assert verify["status"] == "pass", verify
assert verify["direct_durable_memory_write_blocked"] is True, verify
PY

echo "Ontology runtime verification passed."
