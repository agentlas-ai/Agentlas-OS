# Project Soul Memory

## Local Credential Index (read first)

- For deploy, release, store, billing, auth, API, or cloud work, read
  `.agentlas/local-credentials.map.json` before saying a credential is missing.
- Real values may live in `.env`, `.env.local`, `signing/`, `credentials/`,
  local keychain/vault, or project-scoped global env keys like
  `AGENTLAS_PROJECT_<PROJECT>_<ENV_NAME>`.
- Keep this memory value-free: record env names, local relative paths, owner,
  allowed host/scope, broker mode, stale-check notes, and validation commands
  only.

| Need | Look here first | Memory record |
|------|-----------------|---------------|
| Scalar env key | `.env` or `.env.local` | env name only |
| Store/signing file | `signing/` | relative path only |
| App/provider config | `credentials/` | relative path only |
| Shared local env | `AGENTLAS_PROJECT_<PROJECT>_<ENV_NAME>` | project-scoped env name |
| Borrowed agent/plugin key | local keychain/vault or provider OAuth | provider, env name, allowed host, scope, broker mode |

## Intent

{{intent}}

## Audience

{{audience}}

## Current Promise

{{promise}}

## Decisions

- {{decision}}

## Open Loops

- {{open_loop}}

## Acceptance Criteria

- {{acceptance_criterion}}
