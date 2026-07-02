---
name: clarify-question-loop
description: "Use when a meta-agent request is too ambiguous to safely generate, package, publish, or adapt without one to five targeted questions."
---

# Clarify Question Loop

Ask only questions that change the generated package, runtime adapter, safety
boundary, or public/private release decision.

For `/hep-build` creation or behavior-changing packaging, this is not a
substitute for the Builder Interview and Research Gate in
`docs/builder-interview-research-gate.md`. Run that gate first: ask an 8-12
question first batch, research similar agent repositories or comparables and
academic/professional theory, then use this clarify loop only for the remaining
narrow ambiguities.

## Procedure

1. Classify the current best mode.
2. If single-agent vs team selection would change the package shape and the
   independent ownership boundaries are unclear, ask before generation. The
   first batch must include this plain-language question: "이 일을 한 명의
   전문가가 처음부터 끝까지 맡으면 되나요, 아니면 조사/분석/검토처럼 여러
   전문가가 나눠 맡고 마지막에 합쳐야 하나요?"
3. Follow up on role count, role-specific tools/permissions, whether outputs
   must be synthesized, and whether artifacts are sequential dependencies or
   independent parallel packets.
4. Identify missing facts that would change files or safety.
5. Ask one to five short questions, preferably three. If more than five
   functional-quality questions remain, return to the Builder Interview and
   Research Gate instead of pretending the package is ready.
6. Do not ask for secrets. Ask for secret names or setup boundaries instead.
7. After answers arrive, re-run mode classification if needed.
8. Generate or repair the package using the answers and list assumptions.

## Budgets and stop rule (briefing interview engine)

This loop shares the briefing interview engine's contract
(`agentlas_cloud/interview/`): a question is only worth asking if the answer
would change execution, not just its phrasing. Respect the surface budget
(chat 3-5 in one batch, stormbreaker <= 8 across two batches, build 8-12 plus
follow-ups). 'decide later' is always a valid answer — record it as deferred,
never re-ask. When answers you auto-confirmed from code/memory reach three in a
row, the next question must go to the human.

## Default Questions

- Which runtime targets should be supported?
- Is this local-only, private-team, public open-source, or marketplace output?
- What tools, APIs, files, or services must it use?
- What should count as success?
- What must it never read, write, publish, or spend?
- 이 일을 한 명의 전문가가 처음부터 끝까지 맡으면 되나요, 아니면
  조사/분석/검토처럼 여러 전문가가 나눠 맡고 마지막에 합쳐야 하나요?

## Plain-Language Question Rule

Never ask non-technical users to choose internal labels such as
`single-agent`, `team-builder`, ownership boundary, memory/context, synthesis,
or produces/consumes. Translate them before asking:

- ownership boundary -> "누가 따로 맡아야 하는 일인지";
- memory/context -> "각자 따로 기억해야 할 자료, 기준, 진행 상황";
- tools/permissions -> "각자 써도 되는 계정, 파일, 웹사이트, 도구";
- synthesis -> "마지막에 결과를 한데 모으는 일";
- sequential dependency -> "앞 사람이 끝낸 결과를 다음 사람이 이어받는 순서".

If a question still sounds technical, split it into two shorter everyday
questions and give examples such as 조사, 분석, 검토, 승인.

## Reference

See `docs/clarify-question-loop.md`.
