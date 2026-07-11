# Builder Quality Research Basis

This file is the baseline research basis for `/hep-build` quality.
Generated agents still need domain-specific research, but every substantial
build must at least use these patterns when turning interview answers and
source research into agent behavior.

## Baseline Sources

| Source | Type | Design implication |
| --- | --- | --- |
| ReAct, arXiv 2210.03629, https://arxiv.org/abs/2210.03629 | academic | Agent prompts should make reasoning, tool use, observation, and next action explicit enough to debug. |
| Reflexion, arXiv 2303.11366, https://arxiv.org/abs/2303.11366 | academic | Agents need evaluation feedback, failure notes, and memory candidates instead of static one-shot prompts. |
| Structured-prompt-programming framework, GitHub | GitHub | Treat prompts as structured modules with signatures, examples, and evaluation pressure, not as loose prose. |
| Durable-state agent orchestration framework, GitHub | GitHub | Long-running agents need durable state, human-in-the-loop checkpoints, memory, and traceable execution. |
| OpenAI Agents SDK guide, https://developers.openai.com/api/docs/guides/agents | official | Agent design should name instructions, tools, handoffs, guardrails, sessions, and structured outputs. |
| OpenAI Agents SDK agents reference, https://openai.github.io/openai-agents-python/agents/ | official | Agent contracts should make tools, handoffs, guardrails, and output types explicit. |
| Anthropic, Building Effective AI Agents, https://www.anthropic.com/engineering/building-effective-agents | professional | Keep agent systems as simple as the task allows; make prompts, tool calls, and responses inspectable. |
| Anthropic, Writing Effective Tools for Agents, https://www.anthropic.com/engineering/writing-tools-for-agents | professional | Tool choice needs prototyping, evaluation, clear namespaces, token-efficient specs, and permission boundaries. |
| Multi-agent conversation framework, industry publication | academic | Multi-agent teams need explicit conversation roles, tool/human integration points, and coordination contracts. |
| Comparable multi-agent orchestration framework, GitHub | GitHub | Comparable agent repos should inform role/task/handoff structure, but not replace domain research. |

## Required Use In Builds

For every substantial single-agent, team, or packager run:

1. Combine this baseline with domain-specific official, GitHub, academic,
   benchmark, legal, professional, and user-provided sources.
2. Compare similar agents, repositories, or mature systems before writing the
   final prompt. If direct comparables do not exist, record the exact search
   terms and the nearest useful patterns.
3. Include at least one academic, standard, legal, or professional theory source
   for the target domain when available. If the domain has no usable source,
   record the failed search and fall back to the baseline agent-theory sources
   above.
4. Convert research into concrete prompt decisions: operating loop, examples,
   anti-examples, domain heuristics, tool policy, memory policy, handoffs,
   evaluation cases, and refusal/escalation behavior.
5. Preserve the source-to-decision chain in `docs/research-sources.md` and
   `docs/domain-expert-synthesis.md`.
