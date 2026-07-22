# Third-Party Plugin Contribution Guide

Agentlas keeps optional providers outside the Core Engine. Search services,
model providers, hosted browsers, SaaS products, data sources, payments, and
other vendor integrations must ship as independently installable Agentlas
plugins.

This rule protects four properties:

- installing one provider does not change every Agentlas installation;
- removing a provider removes its code, credentials, and network access;
- Core releases do not have to carry every vendor's lifecycle and policy;
- users can see and approve an integration before it runs.

## The two accepted plugin shapes

### Third-party connector

Use this for a vendor-owned API, hosted service, OAuth integration, API-key
service, token-backed connector, or external MCP server.

The catalog manifest uses `agentlas.plugin/v1` with the
`third-party-connector` architecture mode. It references the public upstream
source instead of copying the provider implementation into Agentlas Core.

### Agentlas public plugin

Use this for a portable Agentlas capability package that bundles its public
agent intent and skills. It must install without external provider credentials.

The catalog manifest uses `agentlas.plugin/v1` with the
`agentlas-public-plugin` architecture mode and a public package source.

## Required properties

A plugin submission is eligible for review only when all of these are true:

1. **Independent lifecycle:** it can be installed, upgraded, disabled, and
   removed without editing or releasing Agentlas Core.
2. **Explicit activation:** installation does not add it to default, full,
   automatic, fallback, or background execution. The user chooses it before the
   first provider request.
3. **Declared authority:** the manifest states read, write, and interactive
   capabilities; authentication type; allowed network hosts; allowed
   operations; and requested scope.
4. **Value-free credentials:** public files contain credential names and setup
   instructions only. Secret values remain in the host-owned vault or credential
   broker.
5. **Privacy disclosure:** the submission explains what user input or context is
   sent to the provider, why it is sent, and links to the provider's privacy and
   retention terms.
6. **Safe failure:** missing credentials, denied permissions, offline state,
   provider errors, and malformed responses produce bounded, actionable errors
   without exposing secrets or raw provider responses.
7. **Bounded output:** network reads, response sizes, timeouts, and generated
   content are bounded. Citable results preserve source URLs and distinguish
   provider content from Agentlas-generated conclusions.
8. **Public ownership:** the source, license, developer identity, security
   contact, support path, and version are public and reviewable.
9. **Verified surfaces:** every claimed Terminal or Desktop install path has
   been tested. Compatibility is declared only for surfaces that actually work.
10. **Clean removal:** uninstalling removes the plugin registration and stops
    future provider calls. Host-owned credentials are not silently deleted or
    retained by plugin code.

## Core changes that will be rejected

A third-party plugin pull request must not add provider-specific branches to:

- Core adapter registries or hardcoded provider factories;
- CLI provider enums, aliases, hint maps, or flags;
- default, full, automatic, fallback, or background loadouts;
- credential armories, environment-key maps, doctor, or profile logic;
- ranking, routing, safety, or provider classification tables;
- network or execution allowlists;
- canonical Core documentation tables that imply built-in availability;
- Claude, Codex, Gemini, or other generated runtime mirrors.

The number of changed files is not the deciding factor. A small provider branch
in Core is still Core coupling; a larger self-contained package can still be a
valid plugin.

An existing built-in provider is not a template for new integrations. In
particular, duplicating a legacy built-in adapter across every Core touchpoint
does not make a new provider plugin-shaped.

## When a Core extension is justified

A Core pull request may propose a provider-neutral extension point only when it:

- defines a documented, versioned contract without vendor names or endpoints;
- supports at least two independent implementations, or enforces a Core safety
  invariant that plugins cannot enforce themselves;
- preserves existing behavior and adds no default network traffic;
- does not widen permissions or credential access for installed plugins;
- includes lifecycle, failure, compatibility, and security semantics; and
- is proposed and reviewed separately from all vendor implementations.

If the Research Engine needs a new plugin ABI, propose that ABI first. Until a
provider-neutral ABI exists, expose the capability through the existing
plugin/MCP/skill boundary rather than wiring the provider into the engine.

## Submission checklist

Open a
[Plugin proposal issue](https://github.com/agentlas-ai/Agentlas-OS/issues/new?template=plugin-proposal.yml)
before implementation when no public catalog pull-request route has been
provided. Include:

- plugin name, slug, developer, category, and version;
- `third-party-connector` or `agentlas-public-plugin` shape;
- public homepage, source repository, license, security, and support URLs;
- capabilities and whether each operation reads, writes, or acts interactively;
- auth type, credential field names, allowed hosts, operations, and scope;
- data disclosure, privacy, retention, and deletion links;
- Terminal and Desktop install paths that were actually tested;
- disable and uninstall behavior;
- bounded error behavior for no credentials, no permission, offline state, and
  provider failure; and
- confirmation that no Agentlas Core file must change.

Do not add credentials, test fixtures, benchmark prompts or results, logs,
screenshots, local paths, or internal planning documents to this public
repository. Provide only public source and documentation links needed for
review.

## Review and publication flow

1. Maintainers verify the proposal against the independent lifecycle,
   authority, privacy, failure, and removal requirements above.
2. An eligible submission is routed to the current plugin catalog review
   surface. A catalog pull request adds the plugin metadata or public package,
   not provider-specific Agentlas Core code.
3. The catalog emits the `agentlas.plugin/v1` manifest and install surfaces.
4. Maintainers verify the claimed Terminal and Desktop paths and clean removal.
5. The plugin can be accepted, updated, disabled, or removed independently of
   an Agentlas Core release.

## Acceptance rule

Maintainers accept the provider as a plugin only after the package and manifest
satisfy this guide. A pull request that installs a provider by editing Core will
be closed rather than partially merged. The contributor may then resubmit the
same capability through the plugin proposal and catalog review path.
