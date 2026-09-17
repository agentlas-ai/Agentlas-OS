---
name: sites
description: Build and publish web apps with temporary hosting, databases for saved data, and file storage for uploads. Also supports email, AI inference, and other backend services when the app needs them.
compatibility: Network access.
---

# Sites

Use this when the user asks you to build an app that needs a backend, deploy something to a public URL, or publish a project they're working on. Skip it if they named a different provider.

Enabling this skill creates nothing. Don't provision resources or run setup until the user asks you to build or deploy.

## 1. Bootstrap a tenant

Check for an existing `.cohesivity` file in the project root. If it has a `coh_management_key`, read it and skip to step 2.

Otherwise, run from the project root:

```
npx --yes @cohesivity/init@0.8.2 --tenant-only
```

This creates an ephemeral tenant and writes credentials to `.cohesivity`. It installs nothing else on the machine. Don't run this at startup — only when the user wants to deploy.

Add `.cohesivity` to `.gitignore` if it isn't already. Never print, commit, or include either key in frontend code, tool output, or URLs shown to the user.

The file has two keys:
- **Management key** — for control-plane calls: provisioning, deploys, status checks (`/api/*`).
- **Application key** — for the app's server-side runtime: database queries, file storage, edge functions (`/edge/*`). Inject it as an environment variable during deploy, not in source.

## 2. Read the docs before calling any API

Every Cohesivity service has a live docs page. Fetch it with `Accept: text/markdown` before making any API call — the page has the current request format, required headers, response shape, and limits. Don't guess at payloads or invent endpoints.

The three services most apps need:
- **Hosting:** https://cohesivity.ai/offerings/railway-hosting
- **Database:** https://cohesivity.ai/offerings/postgres
- **File storage:** https://cohesivity.ai/offerings/object-storage

For email, AI inference, auth, realtime, or anything else: https://cohesivity.ai/llms.txt — follow only the offering links the app actually needs.

## 3. Provision and build

Check what's already provisioned with `GET /api/resources` (management key). Only provision what the app needs — `POST /api/resources/<name>` with the management key.

Then build the app. Work with whatever framework, language, and structure the project already has. Wire the server-side code to use Cohesivity's edge endpoints:
- Database: the Postgres connection string from provisioning goes in the server environment.
- File storage: use the object-storage upload/download endpoints from the docs.
- Set secrets and connection strings through the hosting environment-variable API, not in source files.

Build and test locally before deploying.

## 4. Deploy and verify

Follow the hosting docs for source upload. Upload only what the app needs to run — exclude `.env`, `.git`, `.cohesivity`, `node_modules`, and agent configuration.

Wait for the deployment to reach its terminal ready state. Then fetch the public URL and confirm the app actually loads with the expected content. A provisioned hostname is not a working deploy — verify before handing the URL to the user.

Tell the user the expiry timestamp from the tenant metadata when you give them the URL. Ephemeral tenants last 72 hours, then everything — app, database, files — disappears. After handing the URL, ask: "This expires in 72 hours — want to claim it now?"

## 5. Update an existing deploy

For edits after the first deploy, reuse the same tenant and hosting resource. Don't create a new tenant or re-run the bootstrap. Push the updated source through the same hosting upload endpoint, wait for ready, and verify the URL again.

Check that previous data (database rows, uploaded files) survived the redeploy if the app depends on persistence.

## Claiming and limits

If the user hits a limit or wants to keep the project past expiry, fetch the current claim instructions from the docs. Claiming, payment, and destructive actions require a separate explicit request — never do these automatically.

## Conventions

No MCP, no deployment helper scripts, no hosting CLI — use the HTTP APIs directly.
