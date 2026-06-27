---
description: Build, repair, or package Agentlas agents and teams with Hephaestus.
---
Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus build surface


Raw arguments: `$ARGUMENTS`

Use the `hephaestus-network` skill's runner resolution. If the arguments are
`ontology`, run `"$RUNNER" ontology`. Otherwise classify the request as
single-agent-builder, multi-agent-team-builder, or agentlas-packager by
independent ownership boundaries, execute the meta-agent procedure on
`$ARGUMENTS`, and include `global_commands` for the created agent or team in
the final response. If single↔multi is unclear, ask first in plain language:
"이 일을 한 명의 전문가가 처음부터 끝까지 맡으면 되나요, 아니면 조사/분석/검토처럼
여러 전문가가 나눠 맡고 마지막에 합쳐야 하나요?" Do not show
non-technical users internal labels like ownership boundary, memory/context,
synthesis, or produces/consumes.

Before writing substantial package files, run the Builder Interview and
Research Gate from `docs/builder-interview-research-gate.md`: ask an 8-12
question first batch when the request is vague, continue follow-ups until the
functional brief is clear, research official sources, similar agent
repositories or comparables, academic/professional theory, and plugin docs,
compare selected and rejected tools/plugins, synthesize domain-expert behavior,
and create `docs/builder-interview.md`, `docs/research-sources.md`,
`docs/tool-selection.md`, `docs/domain-expert-synthesis.md`,
`docs/prompt-performance-contract.md`, and `.agentlas/capability-eval-plan.json`.
Include `interview_research` evidence in the final response.

After creating or repairing a package, run
`scripts/verify-team-package.sh <package-root>`. If it fails, do not report
`completed`; correct the shape by collapsing to a valid single-agent package or
adding orchestrator/HQ plus company-blueprint topology, then rerun the gate.

This is the clearer build-focused name for the older Hephaestus command.

If a package was created or repaired in the current workspace, register it to
local discovery immediately so it is included in local search:

```bash
if [ -x "./bin/hephaestus" ]; then
  ./bin/hephaestus cards migrate . --tier local --overwrite
fi
```

Include the migration result in `evidence`.
