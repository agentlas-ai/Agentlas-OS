#!/usr/bin/env bash
# Verify the additive memory-schema migration (owner-approved 3-layer wizard rule, 2026-08-08).
#
# MISSING-ONLY seeding means a file born at schema 1.0 never receives fields a
# later template declares — measured live: memory-map.json stuck at 1.0 while
# the template shipped 1.1. `_apply_additive_memory_migrations` is the repair:
# add ONLY missing declared fields, never rewrite an existing value, bump
# schemaVersion monotonically. This gate re-injects the defect (a real 1.0
# install with a user-customized value) and fails unless:
#   1) new fields arrive (sources[], activations[], 1.1 roots, promotionPath)
#   2) the customized value survives byte-identical
#   3) a second run changes nothing (idempotent)
#   4) an unrecognized file shape is skipped with a warning, not rewritten
set -euo pipefail
cd "$(dirname "$0")/.."

python3 - <<'PY'
import sys, json, shutil, tempfile, pathlib
sys.path.insert(0, ".")
from agentlas_cloud.project_bootstrap import _apply_additive_memory_migrations

base = pathlib.Path(tempfile.mkdtemp(prefix="wizard-mig-gate."))
try:
    (base / ".agentlas").mkdir(parents=True)
    mm = {
        "schemaVersion": "1.0",
        "projectId": "X",
        "canonicalMemoryRoots": {
            "project": [".agentlas/project-soul-memory.md"],
            "agent_repo": ["memory.md"],
            "sitemap": [".agentlas/sitemap.json", ".agentlas/validation-ledger.jsonl"],
            "team_memory": [],
            "session": [".agentlas/memory-tickets.jsonl"],
        },
        "writeOwners": {
            "project": "10-single-agent-builder or 20-multi-agent-team-builder",
            "agent_repo": "30-agentlas-packager",
            "sitemap": "30-agentlas-packager",
            "team_memory": "30-agentlas-packager",
            "session": "AGENTS.md",
        },
        "trustLabels": ["verified", "memory_derived", "inferred", "stale_check_needed"],
    }
    act = {
        "schemaVersion": "1.0",
        "kind": "agentlas-auto-activation",
        "state": "seed",
        "activationPolicy": {"mergeOnly": True},
        "seedFiles": [".agentlas/project-soul-memory.md"],
        "safety": {"noSecrets": True},
    }
    json.dump(mm, open(base / ".agentlas/memory-map.json", "w"), ensure_ascii=False, indent=1)
    json.dump(act, open(base / ".agentlas/activation.json", "w"), ensure_ascii=False, indent=1)

    migrated, warnings = _apply_additive_memory_migrations(base)
    assert sorted(migrated) == ["activation.json", "memory-map.json"], (migrated, warnings)
    d = json.load(open(base / ".agentlas/memory-map.json"))
    a = json.load(open(base / ".agentlas/activation.json"))
    assert d["schemaVersion"] == "1.2" and d["sources"] == []
    assert "curator_decisions" in d["canonicalMemoryRoots"] and "promotionPath" in d
    assert d["writeOwners"]["project"] == "10-single-agent-builder or 20-multi-agent-team-builder", "custom value rewritten"
    assert d["canonicalMemoryRoots"]["sitemap"] == [".agentlas/sitemap.json", ".agentlas/validation-ledger.jsonl"]
    assert a["schemaVersion"] == "1.1" and a["activations"] == [] and a["activationPolicy"] == {"mergeOnly": True}

    before = (base / ".agentlas/memory-map.json").read_bytes() + (base / ".agentlas/activation.json").read_bytes()
    migrated2, _ = _apply_additive_memory_migrations(base)
    after = (base / ".agentlas/memory-map.json").read_bytes() + (base / ".agentlas/activation.json").read_bytes()
    assert migrated2 == [] and before == after, "not idempotent"

    json.dump({"totally": "different"}, open(base / ".agentlas/activation.json", "w"))
    _, w3 = _apply_additive_memory_migrations(base)
    assert any("unrecognized_shape" in x for x in w3), w3
    assert json.load(open(base / ".agentlas/activation.json")) == {"totally": "different"}, "unrecognized shape rewritten"
    print("PASS verify-wizard-migration")
finally:
    shutil.rmtree(base, ignore_errors=True)
PY
