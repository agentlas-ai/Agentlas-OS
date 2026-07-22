## Summary

Describe the user-visible problem and the smallest public change that solves it.

## Change type

- [ ] Core bug fix or provider-neutral Core capability
- [ ] Agentlas public plugin/package
- [ ] Documentation or maintenance
- [ ] Third-party service or connector

## Third-party integration boundary

If this change mentions an external service, provider, hosted endpoint, API key,
OAuth flow, token, connector, or MCP server:

- [ ] I read `PLUGIN_CONTRIBUTIONS.md`.
- [ ] The integration is independently installable, disableable, and removable.
- [ ] This pull request adds no provider-specific Core registry, CLI, loadout,
      credential, diagnostic, ranking, routing, allowlist, or runtime-mirror
      branch.
- [ ] Activation is explicit; the integration is not added to default, full,
      automatic, fallback, or background execution.
- [ ] Capabilities, auth type, hosts, operations, scope, and privacy effects are
      declared without credential values.
- [ ] Missing credentials, denied permissions, offline state, and provider
      failures are bounded and actionable.

If any item above is false, stop this Core pull request and open a Plugin
proposal issue. Existing built-in providers are not precedents for new Core
wiring.

## Public safety and verification

- [ ] I staged only an explicit public allowlist.
- [ ] No secrets, environment files, private paths, logs, tests, fixtures,
      benchmark assets or results, screenshots, or internal plans are included.
- [ ] I ran the relevant verification commands from `README.md`.
- [ ] I listed any intentionally skipped verification and why.

## Verification notes

List the commands run and the observable result. Do not attach excluded private
or benchmark artifacts.
