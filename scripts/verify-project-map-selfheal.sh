#!/usr/bin/env bash
# The project's agent/capability map must heal itself.
#
# `.agentlas/agent-ontology/` is derived from sitemap.json, routing-card.json,
# memory-map.json and company-blueprint.json — all files the project bootstrap
# rewrites. Nothing re-derived the map afterwards, so an ordinary seed left it
# stale, and a stale map fail-closes routing for the entire project ("project
# Agent Ontology is stale; routing stopped"). One test-suite run was enough to
# take ten routing paths down at once; all ten passed again after a manual
# `ao migrate --overwrite`. A repair a human has to remember is not a repair.
#
# Two halves, and the second is the one that keeps the first honest:
#   1) sources moved + generated output untouched -> the map is re-derived
#   2) generated output edited by hand -> never overwritten, reported instead
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
import json, pathlib, shutil, sys, tempfile

sys.path.insert(0, ".")
from agentlas_cloud.agent_graph.loader import source_fingerprint
from agentlas_cloud.agent_graph.migrate import migrate_ontology
from agentlas_cloud.project_bootstrap import ensure_project

source = pathlib.Path(".").resolve()
workspace = pathlib.Path(tempfile.mkdtemp(prefix="project-map-selfheal.")) / "project"
workspace.mkdir(parents=True)
try:
    for name in ("AGENTS.md", "agentlas.json", "manifest.json"):
        if (source / name).exists():
            shutil.copy2(source / name, workspace / name)
    private = workspace / ".agentlas"
    private.mkdir()
    for name in ("sitemap.json", "routing-card.json", "memory-map.json", "company-blueprint.json"):
        if (source / ".agentlas" / name).exists():
            shutil.copy2(source / ".agentlas" / name, private / name)

    migrate_ontology(workspace, write=True, overwrite=True)
    report_path = private / "agent-ontology" / "migrate-report.json"
    recorded = json.loads(report_path.read_text(encoding="utf-8"))["source_fingerprint"]
    assert recorded == source_fingerprint(workspace), "fresh materialization is already stale"

    sitemap_path = private / "sitemap.json"
    sitemap = json.loads(sitemap_path.read_text(encoding="utf-8"))
    sitemap["purpose"] = f"{sitemap.get('purpose', '')} (map source moved)"
    sitemap_path.write_text(json.dumps(sitemap, ensure_ascii=False), encoding="utf-8")
    assert recorded != source_fingerprint(workspace), "moving a map source did not change the fingerprint"

    result = ensure_project(workspace, reason="verify-project-map-selfheal")
    healed = json.loads(report_path.read_text(encoding="utf-8"))["source_fingerprint"]
    assert healed == source_fingerprint(workspace), "bootstrap left the map stale; routing would fail closed"
    assert not [w for w in result.get("warnings", []) if "ontology_refresh" in w], result.get("warnings")

    hand_edited = private / "agent-ontology" / "agents.jsonl"
    hand_edited.write_text('{"id":"hand-edited"}\n', encoding="utf-8")
    sitemap["purpose"] = f"{sitemap['purpose']} (again)"
    sitemap_path.write_text(json.dumps(sitemap, ensure_ascii=False), encoding="utf-8")
    guarded = ensure_project(workspace, reason="verify-project-map-selfheal-hand-edit")
    assert hand_edited.read_text(encoding="utf-8").strip() == '{"id":"hand-edited"}', "hand-edited materialization was overwritten"
    assert any(
        "ontology_refresh_skipped" in warning for warning in guarded.get("warnings", [])
    ), guarded.get("warnings")

    print("PASS verify-project-map-selfheal")
finally:
    shutil.rmtree(workspace.parent, ignore_errors=True)
PY
