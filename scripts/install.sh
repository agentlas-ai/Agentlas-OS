#!/usr/bin/env bash
set -euo pipefail

# This path used to implement a second, partial source installer. Keep the
# tracked entrypoint for callers, but make the one-touch installer the only
# installation authority so both paths have the same payload and failure
# contract.
script_dir="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
canonical_installer="$script_dir/install-all-runtimes.sh"

if [[ ! -f "$canonical_installer" ]]; then
  printf 'install: canonical installer not found: %s\n' "$canonical_installer" >&2
  exit 127
fi

# exec preserves the caller's arguments and environment and propagates the
# canonical installer's exact exit status. This wrapper must never print its
# own success message.
exec bash "$canonical_installer" "$@"
