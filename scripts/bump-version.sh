#!/usr/bin/env bash
# Sync the Hephaestus release ref everywhere it is pinned, in one command.
#
#   scripts/bump-version.sh v0.2.13            # apply
#   scripts/bump-version.sh v0.2.13 --dry-run  # show what would change
#
# Updates, in this repo:
#   - scripts/*.sh            (HEPHAESTUS_REF default + curl URLs)
#   - README*.md, */README.md (install one-liners, all languages)
#   - *.json manifests        (marketplace.json, plugin.json, manifest.json,
#                              gemini-extension.json — plain "0.x.y" fields)
# And, if the repo exists on this machine:
#   - AgentsAtlas web ONE_TOUCH_CMD (src/components/install/InstallGuide.tsx)
#     → remember to deploy the web app afterwards.
#
# The current version is read from install-all-runtimes.sh, so running the
# script twice (or back to the old tag) is safe and reversible.
set -euo pipefail

cd "$(dirname "$0")/.."

new="${1:-}"
dry="${2:-}"

if [[ ! "$new" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "usage: scripts/bump-version.sh vX.Y.Z [--dry-run]" >&2
  exit 1
fi

old="$(sed -n 's/.*HEPHAESTUS_REF:-\(v[0-9.]*\)}.*/\1/p' scripts/install-all-runtimes.sh | head -1)"
if [[ -z "$old" ]]; then
  echo "ERROR: could not read current version from scripts/install-all-runtimes.sh" >&2
  exit 1
fi
if [[ "$old" == "$new" ]]; then
  echo "already at $new — nothing to do"
  exit 0
fi

old_plain="${old#v}"
new_plain="${new#v}"
old_re="${old_plain//./\\.}"

# Optional: path to the Agentlas Web InstallGuide.tsx (ONE_TOUCH_CMD pin).
# Set AGENTLAS_WEB_INSTALL_GUIDE locally; unset means the web pin is skipped.
web_file="${AGENTLAS_WEB_INSTALL_GUIDE:-}"

# Tag form (vX.Y.Z) in shell scripts + docs; quoted plain form ("X.Y.Z") in JSON manifests.
targets="$(grep -rl -e "v${old_re}" -e "\"${old_re}\"" \
  --include='*.sh' --include='*.py' --include='*.md' --include='*.json' --include='*.toml' --include='*.command' --include='*.svg' \
  . 2>/dev/null | grep -v node_modules | grep -v '^\./vendor/' | grep -v '^\./\.git/' | grep -v 'scripts/bump-version\.sh' || true)"
if [[ -f "$web_file" ]] && grep -q "v${old_re}" "$web_file"; then
  targets="$targets
$web_file"
fi

if [[ -z "${targets// /}" ]]; then
  echo "no files pin $old — nothing to do"
  exit 0
fi

count=0
while IFS= read -r file; do
  [[ -z "$file" ]] && continue
  hits="$(grep -c -e "v${old_re}" -e "\"${old_re}\"" "$file" || true)"
  if [[ "$dry" == "--dry-run" ]]; then
    printf '%s  (%s pin(s))\n' "$file" "$hits"
  else
    sed -i '' -e "s/v${old_re}/${new}/g" -e "s/\"${old_re}\"/\"${new_plain}\"/g" "$file"
    printf 'synced %s  (%s pin(s))\n' "$file" "$hits"
  fi
  count=$((count + 1))
done <<< "$targets"

if [[ "$dry" == "--dry-run" ]]; then
  echo "dry-run: $count file(s) would move $old → $new"
else
  echo "done: $count file(s) moved $old → $new"
  # Straggler check: any OTHER version pin that this run did not move is a bug
  # waiting to bite (e.g. a README edited by hand to a one-off version).
  stragglers="$(grep -rn "v0\.[0-9]\{1,\}\.[0-9]\{1,\}" \
    --include='*.sh' --include='*.py' --include='*.md' --include='*.json' --include='*.toml' --include='*.command' --include='*.svg' \
    . 2>/dev/null | grep -v node_modules | grep -v '^\./vendor/' | grep -v '^\./\.git/' | grep -v 'scripts/bump-version\.sh' \
    | grep -v "$new" || true)"
  if [[ -n "$stragglers" ]]; then
    echo ""
    echo "WARN: version pins that did NOT move (fix or confirm intentional):"
    printf '%s\n' "$stragglers"
  fi
  if [[ -f "$web_file" ]]; then
    echo "NOTE: web ONE_TOUCH_CMD updated — deploy AgentsAtlas/app for it to go live."
  fi
  echo "NOTE: tag and push the release: git tag $new && git push origin $new"
fi
