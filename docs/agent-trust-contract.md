# Agent Trust Contract

> **We are Agent Trust. Your agent is not a program. It is an asset. — Agentlas —**

`Agent Trust` is Agentlas's product and architecture principle. It is not a
claim that Agentlas is a regulated financial trust, legal trustee, custodian,
or fiduciary service.

The principle means that an agent is not treated as a disposable prompt,
chat-session setting, or process owned by one model vendor. An Agentlas agent
is a user-owned package with an inspectable identity, version, execution
boundary, and recovery path.

## Asset Invariants

An Agentlas-compatible agent or team must preserve these invariants wherever
the relevant surface supports them:

1. **Portable package** — roles, entry instructions, tools, memory policy,
   runtime requirements, read boundaries, and public-export policy live in a
   package rather than only in a chat transcript.
2. **Content identity** — the package has a reproducible `packageHash`; restore
   and installation receipts identify the version that was materialized.
3. **Owner-scoped private storage** — packages saved to Agent Cloud remain
   accessible only to the authenticated owner unless the owner separately
   publishes a clean public copy.
4. **Public/private separation** — private Agent Cloud save and public Hub
   publish are different actions, policies, states, and receipts.
5. **Runtime independence** — Agent Cloud stores and retrieves packages. The
   selected supported host and model execute them under that host's permission
   and safety model; Agent Cloud is not the LLM executor.
6. **Machine-local authority** — credentials, local files, granted permissions,
   and host-specific configuration do not silently travel with the package.
7. **Governed learning** — memory and evolution proposals remain candidates
   until the user or the local Memory Curator promotes them. Public base
   packages are not silently mutated by a caller's private learning.
8. **Inspectable history** — build, borrow, save, publish, restore, invoke,
   retry, and rollback paths return enough identity and status to distinguish
   what happened without exposing secret values.
9. **Separate earned experience** — a base agent release and a user's
   Experience Pack are separately owned, versioned, published, withdrawn, and
   restored. A references-only Variant never copies or transfers the base
   package.
10. **Host-resolved tools** — packages declare value-free MCP requirements by
    trusted catalog id. The local host resolves, consents, attaches, degrades,
    and falls back per requirement; borrowed content cannot provide an
    executable command, endpoint, or credential value.
11. **Verified, replay-safe reputation** — official success metrics accept only
    independently verified RunReceipts protected by receipt id, idempotency key,
    and content hash. Self-report remains private evidence, not ranking truth.

## Build, Borrow, Own

Agentlas separates three operations that must not be collapsed into one status:

| Operation | Asset meaning |
| --- | --- |
| **Build** | Create or repair a package the user can inspect, install, save, and run. |
| **Borrow** | Invoke a public Hub package under its distribution contract without claiming ownership of the publisher's private source work. |
| **Own** | Keep a user-created package local or in owner-scoped Agent Cloud and restore it on another supported signed-in host. |

## Product Surface Contract

- **Agentlas Web** is the Hub, Agent Cloud, bookmarks, account, and Desktop
  delivery control plane. It must not imply that Agent Cloud is a server-side
  agent runtime.
- **Agentlas Desktop** is the primary local GUI for building, running,
  inspecting, recovering, and saving agent assets.
- **Agentlas Terminal already exists.** The shipped `agentlas_terminal` is an
  independent local runtime surface. Architecture work must harden and
  regression-test it, not create a replacement Terminal or restore the retired
  Desktop `cli/` mirror. `agentlas cloud list` and `agentlas cloud restore`
  operate on owner-scoped Agent Cloud assets; `agentlas install` and the
  compatibility `agentlas cloud install` operate on public Hub packages. Those
  states and receipts must not be labeled as the same installation source.
- **External LLM hosts** use Agentlas OS / Hephaestus adapters to build, find,
  borrow, retrieve, and run the same portable contracts.
- **Mobile is downstream.** A future Mobile companion may direct paired hosts
  only after asset identity, host identity, run states, receipts, cancellation,
  offline truth, and restore behavior are production-stable.

## Terminology Boundary

`Agent Cloud` means the owner's asset storage and retrieval layer. It does not
mean a hosted Cloud Agent VM. User-facing copy must not promise always-on cloud
execution when the work actually runs on the selected local or self-managed
host.

Every create, repair, package, or team-build surface must finish the local
artifact first and then keep private Cloud storage as a separate consent step.
The portable choice is binary: owner-private **Cloud에 올리기** or
**로컬에만 저장**. No answer and non-interactive execution mean local-only;
public Hub publication is never inferred from either choice. A failed Cloud
save leaves the verified local artifact untouched. A package stored in Agent
Cloud becomes usable on Mobile only through a paired Desktop after that
Desktop restores or installs the package; storage alone is not execution.

`Agent Trust` means trustworthy ownership and portability by contract. It must
not be translated into claims of regulated custody, insured assets, fiduciary
duty, investment trust, or legal title transfer.

## Cross-Surface Acceptance

The contract is not satisfied by documentation alone. A production release
must prove, for every supported path:

- the same package reports the same source, call mode, price, version, and
  availability across Hub search, detail, MCP, Desktop, and Terminal;
- a private save cannot be mistaken for a public publish;
- an owner can restore a package and verify the expected hash;
- another account cannot restore the owner's full private package;
- the installed Desktop and Terminal execute through the selected supported
  host rather than a hidden Agentlas server model;
- stale registries, indexes, caches, policy copy, or fallbacks fail visibly
  instead of fabricating `Live`, `owned`, or `restored` state;
- an Experience Pack owner can differ from the base author without receiving
  base-source ownership, and base/experience/Variant upload states remain
  distinct;
- missing or failed MCPs degrade only affected capabilities or exclude only the
  incompatible Variant, while selection proceeds to an explicit fallback;
- repeated or self-reported RunReceipts cannot inflate verified success;
- fixes leave a replayable regression test, audit rule, or installation
  evidence.

## Links

- [Source of truth](source-of-truth.md)
- [Runtime sync boundaries](runtime-sync-boundaries.md)
- [Agentlas Cloud runtime](agentlas-cloud-runtime.md)
- [Local credential store](local-credential-store.md)
- [Agent experience assets](agent-experience-assets.md)
- [MCP build and resolution](mcp-build-resolution.md)
