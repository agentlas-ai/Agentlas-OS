# MCP Build And Resolution Contract

Agentlas packages declare capabilities they need. They do not carry or own MCP
servers. Before build or execution, the local host resolves those declarations
against its trusted MCP inventory.

## One-Line Runtime Rule

> Resolve MCP requirements from the system-global registry first; recommend and
> attach only user-approved, locally available catalog entries.

The package may name `catalogId`, reason, capabilities, permissions, key
metadata, priority, and ordered alternatives. It must not provide `command`,
`args`, executable paths, working directories, headers, or server endpoints.
The trusted registry owns executable and transport definitions. This prevents a
borrowed package from disguising arbitrary process execution as an MCP request.

## Build Flow

```text
agent capabilities
  -> system-global registry
  -> project-local registry
  -> catalog recommendations
  -> one combined consent screen
  -> local key-presence check
  -> connect approved and available entries
  -> build with per-capability status
```

The consent screen shows each MCP's purpose, requested permissions, whether a
key is needed, whether that key is locally available, and its fallback. It asks
once for the proposed set and still permits select-only or tool-free build.

Credential metadata is value-free. It may contain provider, env-name, allowed
hosts, scope, setup URL, and broker mode. The policy and receipts never contain
an API key, token, cookie, password, service-account body, private key, or
credential-file content. Presence is a boolean observed by the local runtime;
it is not proof that the credential works or is host-bound.

Whenever `credentialMetadata` is present, it is validated even when the MCP is
optional: env names are uppercase and unique; present host/scope lists are
non-empty and unique; hosts are DNS-style hostnames with only an optional `*.`
wildcard and no scheme, path, port, or userinfo; and scopes are compact
1..128-character identifiers rather than free-form instructions. Broker mode
is from the declared enum. `setupUrl` is a value-free HTTPS provider-help page
containing only hostname and path: userinfo, custom port, query, and fragment
are forbidden. OAuth callbacks and executable endpoints remain host-owned.
Reason, capability, permission, alternative, and credential metadata fields
reject secrets, contact PII, customer/account ids, local paths, file URLs, raw
prompt/package markers, opaque encoded blobs, and prompt-injection directives
that ask the runtime to ignore instructions, reveal credentials, exfiltrate
secrets, or disable safety or approval.

## Resolution States

Each requirement advances independently:

```text
recommended -> approved -> connected
                       |-> skipped
                       |-> missing-key
                       |-> failed
                       `-> degraded
```

One failure never creates an agent-wide synthetic shortage. The resolver tries
ordered alternatives, then disables only the affected capability. Other MCPs,
skills, memory, and base-agent behavior continue.

For every requirement, `unavailablePolicy.build` is `degrade`. If the MCP is
required, `unavailablePolicy.rental` is `exclude-variant`: that character is
removed from this rental decision, while other characters and the base-only
path remain eligible. An optional requirement must use `continue-degraded`; if
its absence should exclude a Variant, declare it required instead. Legacy
optional `exclude-variant` records migrate to `continue-degraded` rather than
silently changing the meaning of `required`.

## Policy Defaults

New packages receive `.agentlas/mcp-policy.json` only when it is missing. Setup
never overwrites a user's existing policy. An existing policy is validated
before setup, runtime compilation, and upload. Malformed JSON, unknown fields,
credential values, or package-supplied command/args/endpoint data blocks the
package with a value-free error; the invalid file remains untouched for owner
review. The portable default is:

- registry order uses only system-global, project-local, and catalog
  recommendation, with system-global first;
- one-pass consent;
- package server definitions forbidden;
- credential values forbidden;
- failure isolated per requirement;
- permission widening asks;
- only selected MCP tool schemas are loaded;
- only triggered skills are loaded.

The compiled runtime bundle may carry this validated, compact declared policy
because it contains no discovered registry state, connection status, local
paths, or credential values. Runtime discovery and key presence remain local
and are emitted separately as ephemeral resolution state.

## Prompt Budget

The build and execution runtime enforce:

- always-on/core memory instructions: at most 150 tokens;
- retrieved experience: at most 800 tokens total;
- retrieved experience items: at most eight;
- MCP schemas: selected tools only;
- skills: triggered skills only;
- full Experience Pack injection: forbidden.

Budgets are maximums, not targets. If there is no relevant memory or experience,
the runtime injects none. Resolution and retrieval happen locally before model
context assembly.

## Permission And Update Rules

- A new permission, host, credential scope, paid connector, unsigned package,
  or major version requires approval.
- A registry match is not permission approval.
- A connected status is not a successful tool-call receipt.
- Failed smoke tests keep the prior working lock or leave the capability
  degraded; they do not silently promote a broken update.
- An alternative cannot request broader permissions than the approved primary
  without another consent decision.
- Offline or unavailable Cloud state does not disable already installed local
  agents, local experience, or key-free local MCPs.

## Cross-Surface Ownership

Public Core owns the value-free schemas, templates, defaults, and verification.
Agentlas Web owns account-scoped catalog metadata, moderation, public assets,
and rental resolution. Desktop and the independent Terminal own system registry
inspection, secure key presence, process connection, tool-list smoke tests, and
the user-visible MCP graph. AppBridge remains a route adapter and does not store
MCP keys, experience assets, or receipts.
