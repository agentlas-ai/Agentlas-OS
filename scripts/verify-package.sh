#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

fail() {
  echo "verify-package: $*" >&2
  exit 1
}

required_files=(
  ".gitattributes"
  "AGENTS.md"
  "README.md"
  "README.ko.md"
  "README.zh-CN.md"
  "README.ja.md"
  "README.hi.md"
  "ARCHITECTURE.md"
  "gemini/extension/gemini-extension.json"
  "gemini/extension/GEMINI.md"
  "docs/source-of-truth.md"
  "docs/agent-trust-contract.md"
  "docs/runtime-sync-boundaries.md"
  "docs/runtime-memory-hooks.md"
  "docs/mode-classifier.md"
  "docs/clarify-question-loop.md"
  "docs/global-command-contract.md"
  "docs/agentlas-auto-activation.md"
  "docs/agent-experience-assets.md"
  "docs/mcp-build-resolution.md"
  "docs/model-allocation.md"
  "docs/skill-lifecycle-promotion.md"
  "docs/agentlas-cloud-runtime.md"
  "docs/agentlas-career-graph-redesign-plan.md"
  "docs/robustness-protocol.md"
  "docs/robustness-eval.md"
  "docs/builder-interview-research-gate.md"
  "docs/builder-quality-research-basis.md"
  "docs/super-ontology-candidate-contract.md"
  "docs/hephaestus-agentlas-gateway-architecture.md"
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
  "modes/ontology-backed-agent.md"
  ".agentlas/contract-injection-map.json"
  "examples/ontology-proposal-agent/README.md"
  "examples/ontology-proposal-agent/agent.md"
  "examples/ontology-proposal-agent/verify.sh"
  "examples/ontology-proposal-agent/.agentlas/injected-contracts.json"
  "scripts/sync-adapters.sh"
  "scripts/install-memory-hooks.py"
  "scripts/build-model2vec-asset.py"
  "hooks/claude/hooks.json"
  "hooks/codex/hooks.json"
  "scripts/verify-team-package.sh"
  "scripts/verify-mcp-surface.sh"
  "scripts/verify-builder-quality-contract.sh"
  "scripts/verify-experience-assets-contract.sh"
  "scripts/verify-workforce-bundle-digest-v4.mjs"
  "scripts/verify-workforce-capability-binding-v1.mjs"
  ".agents/agentlas-core-engine-meta-agent/agent.md"
  ".agents/plugins/marketplace.json"
  ".agentlas/mode-map.json"
  ".agentlas/agent-card.json"
  ".agentlas/company-blueprint.json"
  ".agentlas/sitemap.json"
  ".agentlas/global-commands.json"
  ".agentlas/memory-map.json"
  ".agentlas/memory-tickets.jsonl"
  ".agentlas/vault-references.json"
  ".agentlas/mcp-policy.json"
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
  ".agentlas/super-ontology-capability-delegation-authority.json"
  ".agentlas/super-ontology-privacy-confidentiality-boundary.json"
  ".agentlas/super-ontology-strategic-incentive-compatibility.json"
  ".agentlas/super-ontology-reflexive-feedback-stability.json"
  ".agentlas/super-ontology-replays.jsonl"
  ".agentlas/super-ontology-evidence.jsonl"
  ".agentlas/super-ontology-memory-bridge.jsonl"
  "schemas/gateway-channel.schema.json"
  "schemas/agentlas-manifest.schema.json"
  "schemas/activation.schema.json"
  "schemas/agent-definition.schema.json"
  "schemas/experience-pack.schema.json"
  "schemas/taste-style-release.schema.json"
  "schemas/pairwise-preference-receipt.schema.json"
  "schemas/agent-loadout.schema.json"
  "schemas/experience-item.schema.json"
  "schemas/experience-bundle.schema.json"
  "schemas/experience-upload-receipt.schema.json"
  "schemas/experience-base-resolution.schema.json"
  "schemas/experience-relation-lineage.schema.json"
  "schemas/agent-variant.schema.json"
  "schemas/run-receipt.schema.json"
  "schemas/model-allocation-decision.schema.json"
  "schemas/model-allocation-receipt.schema.json"
  "schemas/mcp-requirement.schema.json"
  "schemas/mcp-policy.schema.json"
  "schemas/workforce-profile.schema.json"
  "schemas/workforce-work-order.schema.json"
  "schemas/workforce-candidate-set.schema.json"
  "schemas/workforce-selection.schema.json"
  "schemas/workforce-selection-validation.schema.json"
  "schemas/workforce-execution-plan.schema.json"
  "schemas/workforce-execution-receipt.schema.json"
  "schemas/workforce-tool-inventory.schema.json"
  "schemas/workforce-lifecycle-event.schema.json"
  "schemas/workforce-ontology-proposal.schema.json"
  "schemas/rental-resolution-receipt.schema.json"
  "schemas/global-commands.schema.json"
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
  "schemas/super-ontology-capability-delegation-authority.schema.json"
  "schemas/super-ontology-privacy-confidentiality-boundary.schema.json"
  "schemas/super-ontology-strategic-incentive-compatibility.schema.json"
  "schemas/super-ontology-reflexive-feedback-stability.schema.json"
  "schemas/super-ontology-memory-bridge.schema.json"
  "schemas/robustness-eval-result.schema.json"
  "benchmarks/robustness/public-agent-repair.tasks.jsonl"
  "benchmarks/robustness/example-results.jsonl"
  "benchmarks/workforce-ontology/runtime-bundle-digest-v4-vectors.json"
  "benchmarks/workforce-ontology/capability-binding-v1-vectors.json"
  "scripts/score-robustness-eval.py"
  "templates/activation.json.tpl"
  "templates/agentlas.json.tpl"
  "templates/mcp-policy.json.tpl"
  "templates/experience-pack.json.tpl"
  "templates/taste-style-release.json.tpl"
  "templates/pairwise-preference-receipt.json.tpl"
  "templates/agent-loadout.json.tpl"
  "templates/experience-item.json.tpl"
  "templates/experience-bundle.json.tpl"
  "templates/experience-upload-receipt.json.tpl"
  "templates/experience-base-resolution.json.tpl"
  "templates/agent-variant.json.tpl"
  "templates/run-receipt.json.tpl"
  "templates/model-allocation-decision.json.tpl"
  "templates/rental-resolution-receipt.json.tpl"
  "templates/global-commands.json.tpl"
  "templates/antigravity-workflow.md.tpl"
  "templates/skill-registry.json.tpl"
  "templates/builder-interview.md.tpl"
  "templates/research-sources.md.tpl"
  "templates/tool-selection.md.tpl"
  "templates/domain-expert-synthesis.md.tpl"
  "templates/prompt-performance-contract.md.tpl"
  "templates/capability-eval-plan.json.tpl"
  "templates/gateway-channel.json.tpl"
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
  "templates/super-ontology-capability-delegation-authority.json.tpl"
  "templates/super-ontology-privacy-confidentiality-boundary.json.tpl"
  "templates/super-ontology-strategic-incentive-compatibility.json.tpl"
  "templates/super-ontology-reflexive-feedback-stability.json.tpl"
  "templates/super-ontology-memory-bridge.jsonl.tpl"
  "assets/agentlas-agent-lab-banner.svg"
  "assets/agentlas-meta-agent-architecture.svg"
  "assets/install-claude-code-chat.svg"
  "assets/install-claude-cli.svg"
  "assets/install-codex-chat.svg"
  "assets/install-codex-desktop-settings.svg"
  "assets/install-codex-cli.svg"
  "assets/model2vec/potion-base-8M-int8/manifest.json"
  "assets/model2vec/potion-base-8M-int8/embeddings.i8"
  "assets/model2vec/potion-base-8M-int8/scales.f32le"
  "assets/model2vec/potion-base-8M-int8/tokenizer.json"
  "assets/model2vec/potion-base-8M-int8/LICENSE.model.txt"
  "bin/hephaestus"
  "bin/agentlas-memory-hook"
  "agentlas_cloud/__init__.py"
  "agentlas_cloud/__main__.py"
  "agentlas_cloud/cli.py"
  "agentlas_cloud/global_router.py"
  "agentlas_cloud/runtime.py"
  "agentlas_cloud/experience_contracts.py"
  "agentlas_cloud/model_allocation.py"
  "agentlas_cloud/workforce/__init__.py"
  "agentlas_cloud/workforce/compiler.py"
  "agentlas_cloud/workforce/index.py"
  "agentlas_cloud/workforce/selection.py"
  "agentlas_cloud/workforce/execution.py"
  "agentlas_cloud/workforce/lifecycle.py"
  "agentlas_cloud/workforce/governance.py"
  "agentlas_cloud/workforce/ontology_v1.json"
  "agentlas_cloud/memory_hook.py"
  "agentlas_cloud/project_bootstrap.py"
  "CLAUDE.md"
  "GEMINI.md"
  "gemini/extension/commands/hep-build.toml"
  "gemini/extension/commands/hep-network.toml"
  "gemini/extension/commands/hep-cloud.toml"
  "gemini/extension/commands/hep-search.toml"
  "gemini/extension/commands/hep-browser.toml"
  "gemini/extension/commands/hep-call.toml"
  "gemini/extension/commands/hep-upload.toml"
  ".claude-plugin/marketplace.json"
  ".claude/commands/hep-build.md"
  ".claude/commands/hep-network.md"
  ".claude/commands/hep-cloud.md"
  ".claude/commands/hep-search.md"
  ".claude/commands/hep-browser.md"
  ".claude/commands/hep-call.md"
  ".claude/commands/hep-upload.md"
  ".claude/commands/hep-connect.md"
  ".claude/commands/meta-agent.md"
  ".claude/agents/agentlas-core-engine-meta-agent.md"
  ".claude/skills/agentlas-core-engine-meta-agent/SKILL.md"
  "claude/.claude-plugin/marketplace.json"
  "claude/plugins/agentlas-core-engine-meta-agent/.claude-plugin/plugin.json"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-build.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-network.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-cloud.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-search.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-browser.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-call.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-upload.md"
  "claude/plugins/agentlas-core-engine-meta-agent/commands/hep-connect.md"
  "claude/plugins/agentlas-core-engine-meta-agent/bin/hephaestus"
  "claude/plugins/agentlas-core-engine-meta-agent/bin/ontology"
  "claude/plugins/agentlas-core-engine-meta-agent/bin/hep-build"
  "claude/plugins/agentlas-core-engine-meta-agent/bin/hep-network"
  "claude/plugins/agentlas-core-engine-meta-agent/bin/hep-cloud"
  "claude/plugins/agentlas-core-engine-meta-agent/bin/hep-search"
  "claude/plugins/agentlas-core-engine-meta-agent/bin/hep-browser"
  "claude/plugins/agentlas-core-engine-meta-agent/bin/hep-call"
  "claude/plugins/agentlas-core-engine-meta-agent/bin/hep-upload"
  "claude/plugins/agentlas-core-engine-meta-agent/bin/hep-storm"
  "claude/plugins/agentlas-core-engine-meta-agent/bin/hep-global"
  "claude/plugins/agentlas-core-engine-meta-agent/bin/agentlas-memory-hook"
  "claude/plugins/agentlas-core-engine-meta-agent/hooks/hooks.json"
  "claude/plugins/agentlas-core-engine-meta-agent/agentlas_cloud/__main__.py"
  "claude/plugins/agentlas-core-engine-meta-agent/agentlas_cloud/cli.py"
  "claude/plugins/agentlas-core-engine-meta-agent/agentlas_cloud/global_router.py"
  "claude/plugins/agentlas-core-engine-meta-agent/agentlas_cloud/runtime.py"
  "claude/plugins/agentlas-core-engine-meta-agent/ontology/cli.py"
  "claude/plugins/agentlas-core-engine-meta-agent/ontology/runtime.py"
  ".gemini/GEMINI.md"
  ".gemini/commands/hep-build.toml"
  ".gemini/commands/hep-network.toml"
  ".gemini/commands/hep-cloud.toml"
  ".gemini/commands/hep-search.toml"
  ".gemini/commands/hep-browser.toml"
  ".gemini/commands/hep-call.toml"
  ".gemini/commands/hep-upload.toml"
  "codex/plugins/agentlas-core-engine-meta-agent/.codex-plugin/plugin.json"
  "codex/prompts/hep-build.md"
  "codex/prompts/hep-network.md"
  "codex/prompts/hep-cloud.md"
  "codex/prompts/hep-search.md"
  "codex/prompts/hep-browser.md"
  "codex/prompts/hep-call.md"
  "codex/prompts/hep-upload.md"
  "codex/prompts/hep-connect.md"
  ".agents/workflows/hep-connect.md"
  "codex/plugins/agentlas-core-engine-meta-agent/bin/hephaestus"
  "codex/plugins/agentlas-core-engine-meta-agent/bin/ontology"
  "codex/plugins/agentlas-core-engine-meta-agent/bin/hep-build"
  "codex/plugins/agentlas-core-engine-meta-agent/bin/hep-network"
  "codex/plugins/agentlas-core-engine-meta-agent/bin/hep-cloud"
  "codex/plugins/agentlas-core-engine-meta-agent/bin/hep-search"
  "codex/plugins/agentlas-core-engine-meta-agent/bin/hep-browser"
  "codex/plugins/agentlas-core-engine-meta-agent/bin/hep-call"
  "codex/plugins/agentlas-core-engine-meta-agent/bin/hep-upload"
  "codex/plugins/agentlas-core-engine-meta-agent/bin/hep-storm"
  "codex/plugins/agentlas-core-engine-meta-agent/bin/hep-global"
  "codex/plugins/agentlas-core-engine-meta-agent/bin/agentlas-memory-hook"
  "codex/plugins/agentlas-core-engine-meta-agent/hooks/hooks.json"
  "claude/plugins/agentlas-core-engine-meta-agent/assets/model2vec/potion-base-8M-int8/manifest.json"
  "claude/plugins/agentlas-core-engine-meta-agent/assets/model2vec/potion-base-8M-int8/embeddings.i8"
  "claude/plugins/agentlas-core-engine-meta-agent/assets/model2vec/potion-base-8M-int8/scales.f32le"
  "claude/plugins/agentlas-core-engine-meta-agent/assets/model2vec/potion-base-8M-int8/tokenizer.json"
  "claude/plugins/agentlas-core-engine-meta-agent/assets/model2vec/potion-base-8M-int8/LICENSE.model.txt"
  "codex/plugins/agentlas-core-engine-meta-agent/assets/model2vec/potion-base-8M-int8/manifest.json"
  "codex/plugins/agentlas-core-engine-meta-agent/assets/model2vec/potion-base-8M-int8/embeddings.i8"
  "codex/plugins/agentlas-core-engine-meta-agent/assets/model2vec/potion-base-8M-int8/scales.f32le"
  "codex/plugins/agentlas-core-engine-meta-agent/assets/model2vec/potion-base-8M-int8/tokenizer.json"
  "codex/plugins/agentlas-core-engine-meta-agent/assets/model2vec/potion-base-8M-int8/LICENSE.model.txt"
  "bin/hep-storm"
  "bin/hep-global"
  "codex/plugins/agentlas-core-engine-meta-agent/agentlas_cloud/__main__.py"
  "codex/plugins/agentlas-core-engine-meta-agent/agentlas_cloud/cli.py"
  "codex/plugins/agentlas-core-engine-meta-agent/agentlas_cloud/global_router.py"
  "codex/plugins/agentlas-core-engine-meta-agent/agentlas_cloud/runtime.py"
  "codex/plugins/agentlas-core-engine-meta-agent/ontology/cli.py"
  "codex/plugins/agentlas-core-engine-meta-agent/ontology/runtime.py"
  "codex/.agents/plugins/marketplace.json"
  "codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-build/SKILL.md"
  "codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-network/SKILL.md"
  "codex/plugins/agentlas-core-engine-meta-agent/skills/hephaestus-cloud/SKILL.md"
  "skills/hephaestus-network/SKILL.md"
  "skills/hephaestus-cloud/SKILL.md"
  ".agents/skills/hephaestus-network/SKILL.md"
  ".agents/skills/hephaestus-cloud/SKILL.md"
  "gemini/extension/skills/hephaestus-network/SKILL.md"
  "gemini/extension/skills/hephaestus-cloud/SKILL.md"
  "cursor/plugin/.cursor-plugin/plugin.json"
  "cursor/plugin/commands/hep-build.md"
  "cursor/plugin/commands/hep-network.md"
  "cursor/plugin/commands/hep-cloud.md"
  "cursor/plugin/commands/hep-search.md"
  "cursor/plugin/commands/hep-browser.md"
  "cursor/plugin/commands/hep-call.md"
  "cursor/plugin/commands/hep-upload.md"
  "cursor/plugin/skills/hephaestus-network/SKILL.md"
  "cursor/plugin/skills/hephaestus-cloud/SKILL.md"
  "cursor/plugin/rules/hephaestus.mdc"
  "opencode/commands/hep-build.md"
  "opencode/commands/hep-network.md"
  "opencode/commands/hep-cloud.md"
  "opencode/commands/hep-search.md"
  "opencode/commands/hep-browser.md"
  "opencode/commands/hep-call.md"
  "opencode/commands/hep-upload.md"
  "opencode/plugins/agentlas-memory.js"
  "antigravity/hooks/agentlas-memory.json"
  "grok/hooks/agentlas-memory.json"
  "grok/agentlas-memory-rule.md"
  "openclaw/skills/hephaestus-network/SKILL.md"
  "openclaw/skills/hephaestus-cloud/SKILL.md"
  "hermes/skills/hephaestus-network/SKILL.md"
  "hermes/skills/hephaestus-cloud/SKILL.md"
  "agentlas_cloud/mcp_stdio.py"
  "tests/test_mcp_stdio.py"
  "tests/test_experience_contracts.py"
  "tests/test_team_package_gate.py"
  "tests/fixtures/team-valid/.agentlas/company-blueprint.json"
  "tests/fixtures/team-degenerate/agents/10-researcher/agent.md"
  "docs/local-models.md"
  "bin/ontology"
  "bin/career-graph"
  "career_graph/__init__.py"
  "career_graph/__main__.py"
  "career_graph/cli.py"
  "career_graph/runtime.py"
  "career_graph/experience_relations.py"
  "tests/test_career_graph_runtime.py"
  "tests/test_experience_relation_index.py"
  "ontology/__init__.py"
  "ontology/__main__.py"
  "ontology/cli.py"
  "ontology/embeddings.py"
  "ontology/model_assets.py"
  "ontology/parsers.py"
  "ontology/runtime.py"
  "ontology/utils.py"
  "tests/test_ontology_runtime.py"
  "tests/test_model2vec_asset.py"
  "tests/test_memory_hook.py"
  "tests/test_memory_hook_installer.py"
  "scripts/preflight-macos.sh"
  "scripts/install-all-runtimes.sh"
  "scripts/verify-install-docs.sh"
  "scripts/verify-global-command-contract.sh"
  "scripts/verify-builder-quality-contract.sh"
  "scripts/verify-gateway-channel-contract.sh"
  "scripts/verify-one-touch-install.sh"
  "scripts/run-one-touch-terminal.command"
  "scripts/verify-ontology-runtime.sh"
  "examples/ontology-corpus/company.md"
  "examples/ontology-corpus/notes.txt"
  "examples/ontology-corpus/facts.json"
  "examples/ontology-corpus/matrix.csv"
  "examples/ontology-corpus/unsupported.hwp"
)

for path in "${required_files[@]}"; do
  [[ -e "$path" ]] || fail "missing required file: $path"
done

rg -q 'assets/model2vec/potion-base-8M-int8' scripts/install-all-runtimes.sh \
  || fail "one-touch installer does not copy the bundled Model2Vec asset"
rg -q 'models/model2vec/potion-base-8M-int8' scripts/install-all-runtimes.sh \
  || fail "one-touch installer does not target the runtime Model2Vec path"
rg -q -- '-m ontology.model_assets verify' scripts/install-all-runtimes.sh \
  || fail "one-touch installer does not verify the installed Model2Vec asset"
rg -q 'install-memory-hooks.py' scripts/install-all-runtimes.sh \
  || fail "one-touch installer does not activate global host memory hooks"

agent_count="$(find agents -mindepth 2 -maxdepth 2 -name agent.md | wc -l | tr -d ' ')"
[[ "$agent_count" == "3" ]] || fail "expected exactly 3 visible core agents, found $agent_count"

python3 - <<'PY'
import json
from pathlib import Path

public_skill_names = {"hephaestus-build", "hephaestus-network", "hephaestus-cloud", "hephaestus-storm"}
codex_skill_root = Path("codex/plugins/agentlas-core-engine-meta-agent/skills")
actual = {path.parent.name for path in codex_skill_root.glob("*/SKILL.md")}
if actual != public_skill_names:
    raise SystemExit(f"{codex_skill_root} exposes {sorted(actual)}, expected {sorted(public_skill_names)}")

claude_skill_root = Path("claude/plugins/agentlas-core-engine-meta-agent/skills")
claude_skills = sorted(path.parent.name for path in claude_skill_root.glob("*/SKILL.md"))
if claude_skills:
    raise SystemExit(
        "Claude plugin must expose commands only; duplicate SKILL.md files found: "
        + ", ".join(claude_skills)
    )

for path in [
	Path("claude/plugins/agentlas-core-engine-meta-agent/SKILL.md"),
	Path("claude/plugins/agentlas-core-engine-meta-agent/commands/hephaestus.md"),
	Path("claude/plugins/agentlas-core-engine-meta-agent/commands/hephaestus-build.md"),
	Path("claude/plugins/agentlas-core-engine-meta-agent/commands/hephaestus-network.md"),
	Path("claude/plugins/agentlas-core-engine-meta-agent/commands/hephaestus-cloud.md"),
	Path("claude/plugins/agentlas-core-engine-meta-agent/commands/hephaestus-search.md"),
	Path("claude/plugins/agentlas-core-engine-meta-agent/commands/hephaestus-call.md"),
	Path("claude/plugins/agentlas-core-engine-meta-agent/commands/hephaests-network.md"),
	Path("claude/plugins/agentlas-core-engine-meta-agent/bin/hephaestus-build"),
	Path("claude/plugins/agentlas-core-engine-meta-agent/bin/hephaests-network"),
	Path("claude/plugins/agentlas-core-engine-meta-agent/bin/hephaestus-search"),
	Path("claude/plugins/agentlas-core-engine-meta-agent/bin/hephaestus-call"),
	Path("claude/plugins/agentlas-core-engine-meta-agent/bin/hephaestus-storm"),
	Path("codex/prompts/hephaestus.md"),
	Path("codex/prompts/hephaestus-build.md"),
	Path("codex/prompts/hephaestus-network.md"),
	Path("codex/prompts/hephaestus-cloud.md"),
	Path("codex/prompts/hephaestus-search.md"),
	Path("codex/prompts/hephaestus-call.md"),
	Path("codex/prompts/hephaests-network.md"),
	Path("codex/plugins/agentlas-core-engine-meta-agent/bin/hephaestus-build"),
	Path("codex/plugins/agentlas-core-engine-meta-agent/bin/hephaests-network"),
	Path("codex/plugins/agentlas-core-engine-meta-agent/bin/hephaestus-search"),
	Path("codex/plugins/agentlas-core-engine-meta-agent/bin/hephaestus-call"),
	Path("codex/plugins/agentlas-core-engine-meta-agent/bin/hephaestus-storm"),
	Path("gemini/extension/commands/hephaestus.toml"),
	Path("gemini/extension/commands/hephaestus-build.toml"),
	Path("gemini/extension/commands/hephaestus-network.toml"),
	Path("gemini/extension/commands/hephaestus-cloud.toml"),
	Path("gemini/extension/commands/hephaestus-search.toml"),
	Path("gemini/extension/commands/hephaestus-call.toml"),
	Path("gemini/extension/commands/hephaests-network.toml"),
	Path("antigravity/workflows/hephaestus.md"),
	Path("antigravity/workflows/hephaestus-build.md"),
	Path("antigravity/workflows/hephaestus-network.md"),
	Path("antigravity/workflows/hephaestus-cloud.md"),
	Path("antigravity/workflows/hephaestus-search.md"),
	Path("antigravity/workflows/hephaestus-call.md"),
	Path("antigravity/workflows/hephaests-network.md"),
	Path(".agents/workflows/hephaestus.md"),
	Path(".agents/workflows/hephaestus-build.md"),
	Path(".agents/workflows/hephaestus-network.md"),
	Path(".agents/workflows/hephaestus-cloud.md"),
	Path(".agents/workflows/hephaestus-search.md"),
	Path(".agents/workflows/hephaestus-call.md"),
	Path(".agents/workflows/hephaests-network.md"),
	Path("cursor/plugin/commands/hephaestus.md"),
	Path("cursor/plugin/commands/hephaestus-build.md"),
	Path("cursor/plugin/commands/hephaestus-network.md"),
	Path("cursor/plugin/commands/hephaestus-cloud.md"),
	Path("cursor/plugin/commands/hephaestus-search.md"),
	Path("cursor/plugin/commands/hephaestus-call.md"),
	Path("cursor/plugin/commands/hephaests-network.md"),
	Path("opencode/commands/hephaestus.md"),
	Path("opencode/commands/hephaestus-build.md"),
	Path("opencode/commands/hephaestus-network.md"),
	Path("opencode/commands/hephaestus-cloud.md"),
	Path("opencode/commands/hephaestus-search.md"),
	Path("opencode/commands/hephaestus-call.md"),
	Path("opencode/commands/hephaests-network.md"),
]:
    if path.exists():
        raise SystemExit(f"legacy public command/skill surface should be pruned: {path}")

for path in Path(".").rglob("*.json"):
    if ".git" in path.parts:
        continue
    if path.name.startswith("._"):
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
for overlay, payload in mode_map.get("overlays", {}).items():
    if not Path(payload["contract"]).exists():
        raise SystemExit(f"overlay {overlay} references missing contract: {payload['contract']}")
    for base in payload.get("composesWith", []):
        if base not in mode_map["modes"]:
            raise SystemExit(f"overlay {overlay} composes with unknown mode: {base}")

injection = json.loads(Path(".agentlas/contract-injection-map.json").read_text(encoding="utf-8"))
contract_names = set(injection.get("baseline", []))
for trait in injection.get("traits", {}).values():
    contract_names.update(trait["contracts"])
for name in sorted(contract_names):
    tpl = Path("templates") / f"{name}.json.tpl"
    tpl_jsonl = Path("templates") / f"{name}.jsonl.tpl"
    if not tpl.exists() and not tpl_jsonl.exists():
        raise SystemExit(f"contract-injection-map references unknown template: {name}")

# Append-only event ledgers: writers are runtime-gated off on export
# (runtimeGraphWriteEnabled / runtimePromotionAllowed / runtimeFirstClassRecallEnabled
# = false). Their contracts in docs/skill-lifecycle-promotion.md and
# docs/super-ontology-candidate-contract.md require them to be EMPTY on export, so a
# frozen/empty ledger here is the verified-correct state, not a stalled writer. This
# gate enforces that invariant and blocks any real evidence/decision/trial/replay row
# (a privacy + overclaim leak) from being committed into the public-core export.
empty_on_export = [
    ".agentlas/skill-trials.jsonl",
    ".agentlas/curator-decisions.jsonl",
    ".agentlas/super-ontology-evidence.jsonl",
    ".agentlas/super-ontology-replays.jsonl",
]
for rel in empty_on_export:
    records = [ln for ln in Path(rel).read_text(encoding="utf-8").splitlines() if ln.strip()]
    if records:
        raise SystemExit(
            f"append-only ledger must be empty on export (contract: 'Empty on export'): "
            f"{rel} has {len(records)} record(s)"
        )

# Seeded ledgers may carry rows (validation results, schema-visibility bridge seed),
# but every non-empty line must stay well-formed JSON so future appends remain valid.
seeded_jsonl = [
    ".agentlas/validation-ledger.jsonl",
    ".agentlas/memory-tickets.jsonl",
    ".agentlas/super-ontology-memory-bridge.jsonl",
]
for rel in seeded_jsonl:
    for n, ln in enumerate(Path(rel).read_text(encoding="utf-8").splitlines(), start=1):
        if not ln.strip():
            continue
        try:
            json.loads(ln)
        except Exception as exc:
            raise SystemExit(f"malformed jsonl line {n} in {rel}: {exc}")
PY

if grep -R -nE '00-meta|05-mode|10-agent-repo|20-runtime|30-memory|40-pm|50-policy|60-eval|70-sitemap|80-llm' \
  AGENTS.md README.md ARCHITECTURE.md agent.md agents modes docs skills .agents .agentlas templates >/tmp/agentlas-meta-old-ids.txt 2>/dev/null; then
  cat /tmp/agentlas-meta-old-ids.txt >&2
  fail "old concept-agent ids still present"
fi

scripts/verify-install-docs.sh
scripts/verify-global-command-contract.sh
scripts/verify-builder-quality-contract.sh
python3 scripts/test-build-cloud-choice-contract.py
scripts/verify-experience-assets-contract.sh
scripts/verify-gateway-channel-contract.sh
node scripts/verify-workforce-bundle-digest-v4.mjs
node scripts/verify-workforce-capability-binding-v1.mjs
scripts/verify-team-package.sh tests/fixtures/team-valid >/dev/null
if scripts/verify-team-package.sh tests/fixtures/team-degenerate >/tmp/agentlas-team-gate-negative.txt 2>&1; then
  cat /tmp/agentlas-team-gate-negative.txt >&2
  fail "degenerate team fixture unexpectedly passed"
fi
grep -q "degenerate team" /tmp/agentlas-team-gate-negative.txt || fail "degenerate team fixture did not report degenerate team"
scripts/verify-ontology-runtime.sh
python3 scripts/score-robustness-eval.py benchmarks/robustness/example-results.jsonl >/dev/null
scripts/sync-adapters.sh --check
scripts/verify-mcp-surface.sh
examples/ontology-proposal-agent/verify.sh

# Hephaestus Network 2.0 routing-card gate (block stage — the Hub now
# requires and validates routing cards at registration).
if [[ -f ".agentlas/routing-card.json" ]]; then
  scripts/verify-routing-cards.sh . >/dev/null || fail "malformed routing card(s) under $(pwd)"
else
  fail ".agentlas/routing-card.json missing — packages without a routing card are blocked from publishing/registration (run: hephaestus cards migrate <root> --tier local)"
fi

echo "Package verification passed."
