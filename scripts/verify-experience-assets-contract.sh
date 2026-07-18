#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

required=(
  docs/agent-experience-assets.md
  docs/mcp-build-resolution.md
  agentlas_cloud/experience_contracts.py
  agentlas_cloud/experience_privacy.py
  agentlas_cloud/experience_taxonomy.py
  agentlas_cloud/experience_taxonomy_v1.json
  agentlas_cloud/portable_experience_bundle.py
  schemas/agent-definition.schema.json
  schemas/experience-pack.schema.json
  schemas/experience-item.schema.json
  schemas/taste-style-release.schema.json
  schemas/pairwise-preference-receipt.schema.json
  schemas/agent-loadout.schema.json
  schemas/experience-bundle.schema.json
  schemas/experience-upload-receipt.schema.json
  schemas/experience-base-resolution.schema.json
  schemas/experience-relation-lineage.schema.json
  schemas/agent-variant.schema.json
  schemas/run-receipt.schema.json
  schemas/mcp-requirement.schema.json
  schemas/mcp-policy.schema.json
  schemas/rental-resolution-receipt.schema.json
  templates/mcp-policy.json.tpl
  templates/experience-pack.json.tpl
  templates/experience-item.json.tpl
  templates/taste-style-release.json.tpl
  templates/pairwise-preference-receipt.json.tpl
  templates/agent-loadout.json.tpl
  templates/experience-bundle.json.tpl
  templates/experience-upload-receipt.json.tpl
  templates/experience-base-resolution.json.tpl
  templates/agent-variant.json.tpl
  templates/run-receipt.json.tpl
  templates/rental-resolution-receipt.json.tpl
)

for path in "${required[@]}"; do
  [[ -f "$path" ]] || { echo "experience-contract: missing $path" >&2; exit 1; }
done

PYTHONPATH="$root${PYTHONPATH:+:$PYTHONPATH}" python3 - <<'PY'
import json
from pathlib import Path

from agentlas_cloud.experience_contracts import default_mcp_policy, validate_mcp_policy
from agentlas_cloud.experience_taxonomy import EXPERIENCE_TAXONOMY_CHECKSUM, TASK_SLUGS_V1

root = Path.cwd()
schema_names = [
    "agent-definition",
    "experience-pack",
    "experience-item",
    "taste-style-release",
    "pairwise-preference-receipt",
    "agent-loadout",
    "experience-bundle",
    "experience-upload-receipt",
    "experience-base-resolution",
    "experience-relation-lineage",
    "agent-variant",
    "run-receipt",
    "mcp-requirement",
    "mcp-policy",
    "rental-resolution-receipt",
]
for name in schema_names:
    path = root / "schemas" / f"{name}.schema.json"
    schema = json.loads(path.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema", path
    version_property = "schemaVersion" if "schemaVersion" in schema["properties"] else "schema"
    assert schema["properties"][version_property]["const"].startswith("agentlas."), path

policy = default_mcp_policy()
validate_mcp_policy(policy)
assert policy["registryResolutionOrder"][0] == "system-global"
assert policy["serverDefinitionsFromPackage"] is False
assert policy["credentialValuesAllowed"] is False
assert policy["failureIsolation"] == "per-requirement"
assert policy["contextBudget"] == {
    "coreMemoryMaxTokens": 150,
    "experienceRetrievalMaxTokens": 800,
    "experienceRetrievalMaxItems": 8,
}
assert policy["toolSchemaLoading"] == "selected-tools-only"
assert policy["skillLoading"] == "triggered-only"
assert EXPERIENCE_TAXONOMY_CHECKSUM == "sha256:413833472e423352518f9591cd0e051c5bc0a7971e53ab3dc7b5aaf7d50c37ab"
assert "general" not in TASK_SLUGS_V1

mcp_template = json.loads((root / "templates" / "mcp-policy.json.tpl").read_text(encoding="utf-8"))
assert mcp_template == policy

for key in ("command", "args", "endpoint", "executable", "serverUrl", "headers"):
    assert key not in json.dumps(mcp_template, sort_keys=True), key

experience_template = json.loads((root / "templates" / "experience-pack.json.tpl").read_text(encoding="utf-8"))
assert experience_template["containsBasePackageMaterial"] is False

print("Experience asset contract static verification passed.")
PY

echo "Experience asset contract static verification passed."
