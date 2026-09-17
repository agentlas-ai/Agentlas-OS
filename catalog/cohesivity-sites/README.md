# Cohesivity Sites — Agentlas Plugin

Temporary backends for agent-built apps. When the user asks an Agentlas agent to
build and deploy a web app, this skill provisions hosting, a Postgres database,
object storage, and other services through Cohesivity's HTTP API, then deploys the
app to a public URL.

No account creation, no OAuth, no CLI. The agent bootstraps an ephemeral tenant
with one `npx` command, reads live docs, and calls the API directly. Everything
expires after 72 hours unless the user claims it.

## Install

Copy `skills/sites/SKILL.md` into the agent's skill directory. The skill creates
nothing until the user explicitly asks to deploy.

## Requires

- Network access (HTTP to `cohesivity.ai` and `*.cohesivity.app`)
- Node.js (for the one-time `npx` bootstrap)

## Links

- Cohesivity: https://cohesivity.ai
- Offerings: https://cohesivity.ai/llms.txt
- Privacy: https://cohesivity.ai/privacy
- Terms: https://cohesivity.ai/terms
