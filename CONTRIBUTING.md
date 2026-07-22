# Contributing to Agentlas OS

Thank you for contributing. Agentlas OS keeps the Core small and treats optional
capabilities as installable plugins.

## Before opening a pull request

1. Search existing issues and pull requests.
2. Keep the change focused on one problem.
3. Read the [third-party plugin contribution guide](PLUGIN_CONTRIBUTIONS.md)
   if the change mentions an external service, provider, API key, OAuth flow,
   hosted endpoint, connector, or MCP server.
4. Run the verification commands listed in [README.md](README.md#contributing-and-verification).
5. Stage only the public files required for the contribution. Do not include
   credentials, environment files, private paths, logs, tests, fixtures,
   benchmark assets or results, screenshots, or internal planning material.

## Core or plugin?

Use a plugin for any optional third-party capability, including search APIs,
model providers, hosted browsers, SaaS connectors, data sources, payments, and
vendor-specific MCP servers.

A plugin must be installable, upgradeable, disableable, and removable without
editing Agentlas Core. It must activate only after an explicit user choice and
must declare its capabilities, authentication, network access, operations, and
privacy effects. Missing credentials or an unavailable service must produce a
safe, actionable failure.

Do not add a provider name, endpoint, environment variable, CLI option, registry
entry, loadout entry, ranking rule, credential check, diagnostic branch, network
allowlist entry, or generated runtime mirror to Core. Mirroring an existing
built-in provider is not an exception.

The only integration-related Core pull requests considered are separate,
provider-neutral proposals for a versioned extension contract that supports
multiple independent plugins or enforces a Core invariant. Such a proposal must
not bundle its first vendor implementation.

## Plugin proposal route

Agentlas plugin catalog entries use the `agentlas.plugin/v1` contract and are
installed through Agentlas Terminal or Agentlas Desktop. Browse the public
[Agentlas plugin catalog](https://agentlas.cloud/plugins) for the distribution
shape. This repository does not vendor third-party connector implementations
into Core.

If no catalog pull-request route has been provided, open a
[Plugin proposal issue](https://github.com/agentlas-ai/Agentlas-OS/issues/new?template=plugin-proposal.yml)
with the public source URL and required permission details. Maintainers will
route an eligible package to the catalog review surface. The resulting catalog
pull request must add only the plugin metadata or package, not provider wiring
to this repository. Do not use a Core pull request as a fallback.

## Review outcome

Maintainers will close third-party integration pull requests that cross the
Core boundary. A closed Core-wiring pull request may be resubmitted through the
plugin proposal route after it satisfies the plugin checklist.

Security vulnerabilities should be reported through the process in
[SECURITY.md](SECURITY.md), not through a public issue.
