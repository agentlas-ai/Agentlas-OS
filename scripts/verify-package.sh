#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

fail() {
  echo "verify-package: $*" >&2
  exit 1
}

required_files=(
  "AGENTS.md"
  "README.md"
  "README.ko.md"
  "README.zh-CN.md"
  "README.ja.md"
  "README.hi.md"
  "ARCHITECTURE.md"
  "docs/source-of-truth.md"
  "docs/runtime-sync-boundaries.md"
  "docs/mode-classifier.md"
  "docs/clarify-question-loop.md"
  "docs/agentlas-auto-activation.md"
  "docs/skill-lifecycle-promotion.md"
  "docs/super-ontology-candidate-contract.md"
  "agent.md"
  "agents/10-single-agent-builder/agent.md"
  "agents/20-multi-agent-team-builder/agent.md"
  "agents/30-agentlas-packager/agent.md"
  "skills/mode-classification/SKILL.md"
  "skills/clarify-question-loop/SKILL.md"
  "skills/agentlas-auto-activation/SKILL.md"
  "skills/skill-lifecycle-promotion/SKILL.md"
  ".agents/skills/mode-classification/SKILL.md"
  ".agents/skills/clarify-question-loop/SKILL.md"
  ".agents/skills/agentlas-auto-activation/SKILL.md"
  ".agents/skills/skill-lifecycle-promotion/SKILL.md"
  "modes/single-agent-creator.md"
  "modes/team-builder.md"
  "modes/agentlas-packager.md"
  ".agents/agentlas-core-engine-meta-agent/agent.md"
  ".agents/plugins/marketplace.json"
  ".agentlas/mode-map.json"
  ".agentlas/agent-card.json"
  ".agentlas/company-blueprint.json"
  ".agentlas/sitemap.json"
  ".agentlas/memory-map.json"
  ".agentlas/memory-tickets.jsonl"
  ".agentlas/vault-references.json"
  ".agentlas/activation.json"
  ".agentlas/skill-registry.json"
  ".agentlas/skill-trials.jsonl"
  ".agentlas/curator-decisions.jsonl"
  ".agentlas/super-ontology-contract.json"
  ".agentlas/super-ontology-open-world-coverage.json"
  ".agentlas/super-ontology-consensus-coordination.json"
  ".agentlas/super-ontology-task-coverage.json"
  ".agentlas/super-ontology-contextual-flow.json"
  ".agentlas/super-ontology-causal-impact.json"
  ".agentlas/super-ontology-assurance-case.json"
  ".agentlas/super-ontology-knowledge-homeostasis.json"
  ".agentlas/super-ontology-adversarial-provenance.json"
  ".agentlas/super-ontology-epistemic-calibration.json"
  ".agentlas/super-ontology-semantic-alignment.json"
  ".agentlas/super-ontology-resilience-control.json"
  ".agentlas/super-ontology-invariant-verification.json"
  ".agentlas/super-ontology-observability-telemetry.json"
  ".agentlas/super-ontology-objective-proxy-validity.json"
  ".agentlas/super-ontology-stakeholder-preference-governance.json"
  ".agentlas/super-ontology-normative-authority-drift.json"
  ".agentlas/super-ontology-side-effect-containment.json"
  ".agentlas/super-ontology-source-lineage-version.json"
  ".agentlas/super-ontology-entity-identity-resolution.json"
  ".agentlas/super-ontology-temporal-state-transition.json"
  ".agentlas/super-ontology-replays.jsonl"
  ".agentlas/super-ontology-evidence.jsonl"
  ".agentlas/super-ontology-memory-bridge.jsonl"
  "schemas/activation.schema.json"
  "schemas/skill-registry.schema.json"
  "schemas/super-ontology-contract.schema.json"
  "schemas/super-ontology-open-world-coverage.schema.json"
  "schemas/super-ontology-consensus-coordination.schema.json"
  "schemas/super-ontology-task-coverage.schema.json"
  "schemas/super-ontology-contextual-flow.schema.json"
  "schemas/super-ontology-causal-impact.schema.json"
  "schemas/super-ontology-assurance-case.schema.json"
  "schemas/super-ontology-knowledge-homeostasis.schema.json"
  "schemas/super-ontology-adversarial-provenance.schema.json"
  "schemas/super-ontology-epistemic-calibration.schema.json"
  "schemas/super-ontology-semantic-alignment.schema.json"
  "schemas/super-ontology-resilience-control.schema.json"
  "schemas/super-ontology-invariant-verification.schema.json"
  "schemas/super-ontology-observability-telemetry.schema.json"
  "schemas/super-ontology-objective-proxy-validity.schema.json"
  "schemas/super-ontology-stakeholder-preference-governance.schema.json"
  "schemas/super-ontology-normative-authority-drift.schema.json"
  "schemas/super-ontology-side-effect-containment.schema.json"
  "schemas/super-ontology-source-lineage-version.schema.json"
  "schemas/super-ontology-entity-identity-resolution.schema.json"
  "schemas/super-ontology-temporal-state-transition.schema.json"
  "schemas/super-ontology-memory-bridge.schema.json"
  "templates/activation.json.tpl"
  "templates/skill-registry.json.tpl"
  "templates/super-ontology-contract.json.tpl"
  "templates/super-ontology-open-world-coverage.json.tpl"
  "templates/super-ontology-consensus-coordination.json.tpl"
  "templates/super-ontology-task-coverage.json.tpl"
  "templates/super-ontology-contextual-flow.json.tpl"
  "templates/super-ontology-causal-impact.json.tpl"
  "templates/super-ontology-assurance-case.json.tpl"
  "templates/super-ontology-knowledge-homeostasis.json.tpl"
  "templates/super-ontology-adversarial-provenance.json.tpl"
  "templates/super-ontology-epistemic-calibration.json.tpl"
  "templates/super-ontology-semantic-alignment.json.tpl"
  "templates/super-ontology-resilience-control.json.tpl"
  "templates/super-ontology-invariant-verification.json.tpl"
  "templates/super-ontology-observability-telemetry.json.tpl"
  "templates/super-ontology-objective-proxy-validity.json.tpl"
  "templates/super-ontology-stakeholder-preference-governance.json.tpl"
  "templates/super-ontology-normative-authority-drift.json.tpl"
  "templates/super-ontology-side-effect-containment.json.tpl"
  "templates/super-ontology-source-lineage-version.json.tpl"
  "templates/super-ontology-entity-identity-resolution.json.tpl"
  "templates/super-ontology-temporal-state-transition.json.tpl"
  "templates/super-ontology-memory-bridge.jsonl.tpl"
  "assets/agentlas-agent-lab-banner.svg"
  "assets/agentlas-meta-agent-architecture.svg"
  "assets/install-claude-code-chat.svg"
  "assets/install-claude-cli.svg"
  "assets/install-codex-chat.svg"
  "assets/install-codex-desktop-settings.svg"
  "assets/install-codex-cli.svg"
  "CLAUDE.md"
  "GEMINI.md"
  ".claude-plugin/marketplace.json"
  ".claude/commands/meta-agent.md"
  ".claude/agents/agentlas-core-engine-meta-agent.md"
  ".claude/skills/agentlas-core-engine-meta-agent/SKILL.md"
  "claude/.claude-plugin/marketplace.json"
  "claude/plugins/agentlas-core-engine-meta-agent/.claude-plugin/plugin.json"
  "claude/plugins/agentlas-core-engine-meta-agent/SKILL.md"
  "claude/plugins/agentlas-core-engine-meta-agent/skills/mode-classification/SKILL.md"
  "claude/plugins/agentlas-core-engine-meta-agent/skills/clarify-question-loop/SKILL.md"
  "claude/plugins/agentlas-core-engine-meta-agent/skills/agentlas-auto-activation/SKILL.md"
  "claude/plugins/agentlas-core-engine-meta-agent/skills/skill-lifecycle-promotion/SKILL.md"
  ".gemini/GEMINI.md"
  "codex/plugins/agentlas-core-engine-meta-agent/.codex-plugin/plugin.json"
  "codex/.agents/plugins/marketplace.json"
  "codex/plugins/agentlas-core-engine-meta-agent/skills/agentlas-core-engine-meta-agent/SKILL.md"
  "codex/plugins/agentlas-core-engine-meta-agent/skills/mode-classification/SKILL.md"
  "codex/plugins/agentlas-core-engine-meta-agent/skills/clarify-question-loop/SKILL.md"
  "codex/plugins/agentlas-core-engine-meta-agent/skills/agentlas-auto-activation/SKILL.md"
  "codex/plugins/agentlas-core-engine-meta-agent/skills/skill-lifecycle-promotion/SKILL.md"
)

for path in "${required_files[@]}"; do
  [[ -e "$path" ]] || fail "missing required file: $path"
done

agent_count="$(find agents -mindepth 2 -maxdepth 2 -name agent.md | wc -l | tr -d ' ')"
[[ "$agent_count" == "3" ]] || fail "expected exactly 3 visible core agents, found $agent_count"

python3 - <<'PY'
import json
from pathlib import Path

for path in Path(".").rglob("*.json"):
    if ".git" in path.parts:
        continue
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SystemExit(f"invalid json: {path}: {exc}")

for path in list(Path("skills").glob("*/SKILL.md")) + list(Path(".agents/skills").glob("*/SKILL.md")):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise SystemExit(f"skill missing YAML frontmatter: {path}")
    if "\n---" not in text[4:]:
        raise SystemExit(f"skill frontmatter not closed: {path}")

mode_map = json.loads(Path(".agentlas/mode-map.json").read_text(encoding="utf-8"))
for mode, payload in mode_map["modes"].items():
    for key in ("contract", "agent", "primarySkill"):
        value = payload[key]
        if not Path(value).exists():
            raise SystemExit(f"mode {mode} references missing {key}: {value}")
PY

if grep -R -nE '00-meta|05-mode|10-agent-repo|20-runtime|30-memory|40-pm|50-policy|60-eval|70-sitemap|80-llm' \
  AGENTS.md README.md ARCHITECTURE.md agent.md agents modes docs skills .agents .agentlas templates >/tmp/agentlas-meta-old-ids.txt 2>/dev/null; then
  cat /tmp/agentlas-meta-old-ids.txt >&2
  fail "old concept-agent ids still present"
fi

echo "Package verification passed."
