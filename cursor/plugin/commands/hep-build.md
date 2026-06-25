Update fallback: 자동 업데이트가 안 되면 `hephaestus update`를 한 번 실행하세요. 업데이트하지 않아도 현재 버전 명령은 그대로 동작합니다.

# Hephaestus build surface


Treat everything typed after this command as a Hephaestus build request.
If it is `ontology`, resolve the runner as in the `hephaestus-network` skill
and run `"$RUNNER" ontology`. Otherwise classify the request as
single-agent-builder, multi-agent-team-builder, or agentlas-packager, execute
the meta-agent procedure, and include `global_commands` for the created agent
or team in the final response.

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

Expose this as the public build command next to `/hep-network` and
`/hep-cloud`.

If a package was created or repaired in the current workspace, register it to local
discovery immediately so it is searchable in local routing:

```bash
if [ -x "./bin/hephaestus" ]; then
  ./bin/hephaestus cards migrate . --tier local --overwrite
fi
```

Include the migration result in `evidence`.
