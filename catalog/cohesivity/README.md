# Cohesivity — Agentlas Plugin

Infra and on-the-fly backend for agentic tasks and projects by cohesivity.ai. Offers Postgres, hosting, storage, AI gateway, email inbox, and more through one API/MCP. No account or API key needed to get started.

## Quickstart

```bash
npx --yes @cohesivity/init@0.8.3
```

Creates an ephemeral tenant, writes credentials to `.cohesivity`, and installs the skill. Everything works immediately — no account, no signup. Tenants expire after 72 hours unless claimed.

## Pathways

### HTTP (default)

Bootstrap with `npx @cohesivity/init@0.8.3`, then use the management key from `.cohesivity` as a Bearer token for all API calls:

- `POST /api/resources/<name>` — provision a service
- `GET /api/resources` — list provisioned resources
- `GET /api/status` — tenant lifecycle, limits, notifications
- Deployment, env vars, and other operations per the live docs

### MCP

Cohesivity also offers local and remote MCP servers:

- **Local:** stdio server installed by `npx @cohesivity/init`, provides `create_tenant`, `claim_tenant`, `tenant_status`, `provision_resource`, `give_feedback`
- **Remote:** `https://cohesivity.ai/mcp/manage` — streamable HTTP with OAuth. Guest access auto-creates a 72h identity, no signup needed.

Both paths are documented in the canonical skill.

## Canonical skill

The full workflow lives at `https://cohesivity.ai/skill.md` — bootstrap precedence, provisioning, deploys, consent gates, lifecycle, billing. Self-updating and version-tracked.

## Install

Add `catalog/cohesivity/` to your Agentlas plugin catalog.

## Requires

- Network access (HTTPS to `cohesivity.ai` and `*.cohesivity.app`)
- Node.js (for the one-time `npx` bootstrap)

## Links

- Cohesivity: https://cohesivity.ai
- Offerings: https://cohesivity.ai/llms.txt
- Skill: https://cohesivity.ai/skill.md
- Privacy: https://cohesivity.ai/privacy
- Terms: https://cohesivity.ai/terms
