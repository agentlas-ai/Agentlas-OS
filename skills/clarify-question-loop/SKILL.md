---
name: clarify-question-loop
description: "Use when a meta-agent request is too ambiguous to safely generate, package, publish, or adapt without one to five targeted questions."
---

# Clarify Question Loop

Ask only questions that change the generated package, runtime adapter, safety
boundary, or public/private release decision.

## Procedure

1. Classify the current best mode.
2. Identify missing facts that would change files or safety.
3. Ask one to five short questions, preferably three.
4. Do not ask for secrets. Ask for secret names or setup boundaries instead.
5. After answers arrive, re-run mode classification if needed.
6. Generate or repair the package using the answers and list assumptions.

## Default Questions

- Which runtime targets should be supported?
- Is this local-only, private-team, public open-source, or marketplace output?
- What tools, APIs, files, or services must it use?
- What should count as success?
- What must it never read, write, publish, or spend?

## Reference

See `docs/clarify-question-loop.md`.
