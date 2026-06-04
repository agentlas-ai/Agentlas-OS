---
name: clarify-question-loop
description: "Use when a meta-agent request lacks details that change package shape, adapters, tools, safety, or public/private boundary."
---

# Clarify Question Loop

Ask one to five short questions, preferably three. Ask only for details that
change the generated files or safety boundary.

Default questions:

- Which runtime targets should be supported?
- Is this local-only, private-team, public open-source, or marketplace output?
- What tools, APIs, files, or services must it use?
- What should count as success?
- What must it never read, write, publish, or spend?

Never ask for secrets. Ask for secret names or setup boundaries instead.
