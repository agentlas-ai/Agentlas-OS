#!/usr/bin/env bash
# The `host` permission mode contract (commit 26d5025a, 2026-09-05) must not
# silently drift: a package that declares no tool ceiling relies on the host
# runtime deciding at execution time, and Desktop's enforcement receipt for
# such a row (enforcementMode "native-sandbox", sandboxMode "host-native",
# toolInventory "policy-filtered") is the only evidence that decision was
# actually enforced instead of merely claimed. `tests/` is gitignored in this
# repo, so a check that lives only there never runs in CI — this gate is
# tracked and calls the real workforce functions (host_permission_policy,
# deny_all_permission_policy, validate_permission_policy,
# _capability_assignment_policy_issue, _invocation) rather than matching
# source strings, and it proves it can fail closed by asserting a
# no-authority-sandbox receipt carrying approvals is rejected.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 scripts/host_authority_contract.py
