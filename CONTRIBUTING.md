# Contributing

## Before you open a PR

Run the verification suite. A PR that fails these gets asked to fix them before review:

```bash
scripts/verify-package.sh
scripts/verify-ontology-runtime.sh
scripts/public_safety_check.sh
```

If your change touches routing cards, global commands, or the builder/interview
gate, also run the matching verifier:

```bash
scripts/verify-routing-cards.sh
scripts/verify-global-command-contract.sh
scripts/verify-builder-quality-contract.sh
```

## What's useful to send

- **Adapters**: a new or fixed runtime driver under `.claude/`, `codex/`, `.gemini/`,
  `.agents/` for a host not yet covered, or a fix for one that's out of sync
  with `AGENTS.md` (the canonical route). See
  [docs/runtime-sync-boundaries.md](docs/runtime-sync-boundaries.md).
- **Agent packages**: a new agent or team that follows the directory contract
  in [docs/source-of-truth.md](docs/source-of-truth.md) and passes
  `verify-package.sh`.
- **Docs fixes**: the docs registry in `README.md` (`## Docs By Goal`) lists
  every reference doc — if you fix one, check whether the others need the
  same fix.
- **Bug reports with a repro**: see [SUPPORT.md](SUPPORT.md) for where to file.

## What's out of scope for a PR

Anything that touches hosted Agentlas billing/account logic, production
credentials, or private deployment scripts doesn't belong in this repo at
all — see [SECURITY.md](SECURITY.md) and the "Public Safety Boundary"
section in `README.md`.

## PR process

1. Fork, branch, make the change.
2. Run the verifiers above and paste the output in the PR description.
3. Keep the PR scoped to one change. A routing-card fix and an unrelated
   README rewrite in the same PR will get split before review.
4. If the PR changes behavior a user would notice, add a line to
   `CHANGELOG.md`.

## Reporting a security issue

Don't open a public issue. See [SECURITY.md](SECURITY.md).
