#!/usr/bin/env bash
# The install instructions stay where an AI handed only the repo URL will find them.
#
# WHY THIS EXISTS
#   The product's first step is a user typing "{github url} 설치해줘" to whatever
#   model they already have open. That model fetches the repo and reads the top
#   of the README — and until 2026-09-13 the top of the README was banners and
#   badges, with "Paste to Install" 57 lines down. Worse, a model that reads
#   AGENTS.md first (many do) landed in the contributor constitution, which says
#   nothing about installing and a great deal about not creating branches.
#
#   A cautious model with no visible instructions and a curl-pipe-bash in its
#   future does the reasonable thing: it stalls or refuses. So the install block
#   goes first, it explains what the script writes and where, and this gate keeps
#   it there.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

GATE="[verify-install-entry]"
MARKER="AGENTLAS-INSTALL-ENTRY"
# Far enough to allow a comment and a little framing; near enough that no banner
# block can push it below the fold again.
MAX_LINE=12

READMES=(README.md README.ko.md README.zh-CN.md README.ja.md README.hi.md)
POINTERS=(AGENTS.md CLAUDE.md)

failures=0
checked=0

fail() {
  printf '%s   - %s\n' "$GATE" "$1"
  failures=$((failures + 1))
}

for file in "${READMES[@]}"; do
  checked=$((checked + 1))
  if [ ! -f "$file" ]; then
    fail "$file is missing — every translated README ships the install entry"
    continue
  fi
  line="$(grep -n "$MARKER" "$file" | head -1 | cut -d: -f1 || true)"
  if [ -z "$line" ]; then
    fail "$file has no $MARKER block: a model given only the repo URL reads the top of this file"
    continue
  fi
  if [ "$line" -gt "$MAX_LINE" ]; then
    fail "$file has the install entry at line $line, below the $MAX_LINE-line fold — something was prepended above it"
  fi
  # The reassurance is the point: a bare curl-pipe-bash with no statement of
  # what it writes is what makes a careful model refuse.
  for needed in "install-all-runtimes.sh" '~/.agentlas' '~/.local/bin'; do
    grep -qF "$needed" "$file" || fail "$file install entry never mentions $needed"
  done
done

for file in "${POINTERS[@]}"; do
  checked=$((checked + 1))
  if [ ! -f "$file" ]; then
    fail "$file is missing"
    continue
  fi
  grep -qF "$MARKER" "$file" \
    || fail "$file has no $MARKER pointer — a model that reads it first lands in contributor rules with no way to the installer"
done

if [ "$failures" -gt 0 ]; then
  printf '%s FAIL — %d problem(s), %d file(s) checked\n' "$GATE" "$failures" "$checked"
  exit 1
fi
printf '%s PASS — install entry present and above the fold in %d file(s)\n' "$GATE" "$checked"
