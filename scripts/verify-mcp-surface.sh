#!/usr/bin/env bash
# C-4: MCP surface preservation. Every local-capable host exposes exactly one
# local Agentlas OS Core MCP. Cloud and Hub stay upstream behind that Core;
# adapters must not register a second remote MCP that bypasses governance.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

fail() {
  echo "verify-mcp-surface: $*" >&2
  exit 1
}

# 1. Claude Code: bundled .mcp.json registers the local Core.
python3 <<'PY' || fail "claude plugin .mcp.json contract broken"
import json
data = json.load(open("claude/plugins/agentlas-core-engine-meta-agent/.mcp.json"))
assert set(data) == {"hephaestus-network"}, data
server = data["hephaestus-network"]
assert server.get("command") == "${CLAUDE_PLUGIN_ROOT}/bin/hephaestus", data
assert server.get("args") == ["mcp", "serve"], data
PY

# 2. Gemini: extension manifest registers the same local Core.
python3 <<'PY' || fail "gemini extension MCP contract broken"
import json
data = json.load(open("gemini/extension/gemini-extension.json"))
servers = data.get("mcpServers") or {}
assert set(servers) == {"hephaestus-network"}, data
server = servers["hephaestus-network"]
assert server.get("command") == "${extensionPath}/bin/hephaestus", data
assert server.get("args") == ["mcp", "serve"], data
PY

# 3. Codex + Antigravity: the installer registers the same local Core and no
# direct remote Hub endpoint.
grep -q '\[mcp_servers\.hephaestus-network\]' scripts/install-all-runtimes.sh \
  || fail "codex MCP registration block missing"
grep -q 'register_antigravity_mcp' scripts/install-all-runtimes.sh \
  || fail "antigravity MCP registration missing"
# ★`if rg -q ...` 는 rg 가 없는 머신에서 exit 127 이 false 로 읽혀 검사 자체를
# 건너뛰고 스크립트는 "passed" 를 찍었다(실측 2026-08-21: 이 머신에 rg 실물 없음).
# 게이트의 조건절에 외부 바이너리를 쓰려면 부재는 통과가 아니라 실패여야 한다.
# grep -E 는 POSIX 이므로 부재 자체가 없다.
if grep -qE 'AGENTLAS_MCP_URL|agentlas\.cloud/api/mcp' \
  scripts/install-all-runtimes.sh \
  claude/plugins/agentlas-core-engine-meta-agent/.mcp.json \
  gemini/extension/gemini-extension.json; then
  fail "direct remote MCP bypass reintroduced"
elif [ $? -gt 1 ]; then
  fail "direct remote MCP bypass check could not run"
fi

# 4. Ontology runtime output contract: the keys the MCP/natural-language
#    surface relies on must stay present (additive changes only).
PYTHONPATH="$root" python3 <<'PY' || fail "ontology query/verify output contract broken"
import tempfile
from pathlib import Path
from ontology import OntologyRuntime, RuntimeConfig

with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    doc = root / "doc.md"
    doc.write_text("Surface Probe depends on Contract Check.", encoding="utf-8")
    rt = OntologyRuntime(RuntimeConfig(db_path=root / "db.sqlite"))
    rt.ingest_path(doc, access_scope="internal")
    answer = rt.query("Surface Probe")
    for key in ("query", "chunks", "related_entities", "relation_edges",
                "memory_candidate_suggestions", "working_memory", "vector_adapter"):
        assert key in answer, f"query output lost key: {key}"
    report = rt.verify()
    for key in ("status", "schema_version", "counts", "storage_adapter", "vector_adapter"):
        assert key in report, f"verify output lost key: {key}"
PY

# 5. Runtime release identity owns the Workforce protocol. A protocol-only
# source change under an unchanged manifest version cannot reach existing
# users because the verified updater compares release tags. Keep serverInfo,
# the manifest capability, and the required typed authoring boundary joined.
PYTHONPATH="$root" python3 <<'PY' || fail "Workforce protocol release identity drifted"
import json
from agentlas_cloud.mcp_stdio import (
    SERVER_INFO,
    TOOLS,
    WORKFORCE_PROTOCOL_VERSION,
)

manifest = json.load(open("manifest.json", encoding="utf-8"))
assert SERVER_INFO["version"] == manifest["version"], (SERVER_INFO, manifest["version"])
assert manifest["workforceProtocolVersion"] == WORKFORCE_PROTOCOL_VERSION
names = {tool["name"] for tool in TOOLS}
assert "workforce.preflight_work_order" in names
search = next(tool for tool in TOOLS if tool["name"] == "workforce.search_candidates")
assert "workOrderRef" in search["inputSchema"]["properties"]
PY

echo "MCP surface verification passed."
