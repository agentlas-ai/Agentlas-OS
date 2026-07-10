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

# Path to the Agentlas Web InstallGuide.tsx (ONE_TOUCH_CMD pin). The web app lives
# in a SIBLING repo, so default to that layout; AGENTLAS_WEB_INSTALL_GUIDE overrides.
# It must be defaulted (not left empty) — a release that forgets to export it is how
# the web pin first fell behind and then got stuck.
web_file="${AGENTLAS_WEB_INSTALL_GUIDE:-../agentlas/AgentsAtlas/app/src/components/install/InstallGuide.tsx}"

# Tag form (vX.Y.Z) in shell scripts + docs; quoted plain form ("X.Y.Z") in JSON manifests.
# NOTE: the web file is handled separately below (pattern replace, not literal old→new)
# so a web pin that is several releases behind still snaps forward instead of sticking.
targets="$(grep -rl -e "v${old_re}" -e "\"${old_re}\"" \
  --include='*.sh' --include='*.py' --include='*.md' --include='*.json' --include='*.toml' --include='*.command' --include='*.svg' \
  . 2>/dev/null | grep -v node_modules | grep -v '^\./vendor/' | grep -v '^\./\.git/' \
  | grep -v '^\./CHANGELOG\.md$' | grep -v 'scripts/bump-version\.sh' || true)"

# --- Web ONE_TOUCH_CMD pin (sibling repo) -----------------------------------
# Pattern replace, NOT literal old→new: the web app's install one-liner pins the
# Hephaestus tag in a curl URL. Match the URL shape and snap whatever version it
# carries to the new tag, so a web file that skipped past releases (and is now
# several versions behind) still catches up instead of sticking forever.
web_synced=""
web_pat='(Agentlas-OS|Hephaestus)/v[0-9]+\.[0-9]+\.[0-9]+/scripts/install-all-runtimes\.sh'
if [[ -f "$web_file" ]] && grep -qE "$web_pat" "$web_file"; then
  cur="$(sed -nE 's#.*(Agentlas-OS|Hephaestus)/(v[0-9]+\.[0-9]+\.[0-9]+)/scripts/install-all-runtimes\.sh.*#\2#p' "$web_file" | head -1)"
  if [[ "$dry" == "--dry-run" ]]; then
    echo "$web_file  (web ONE_TOUCH_CMD ${cur:-?} → ${new})"
  elif [[ "$cur" != "$new" ]]; then
    sed -i '' -E "s#((Agentlas-OS|Hephaestus)/)v[0-9]+\.[0-9]+\.[0-9]+(/scripts/install-all-runtimes\.sh)#\1${new}\3#g" "$web_file"
    echo "synced $web_file  (web ONE_TOUCH_CMD ${cur:-?} → ${new})"
    web_synced=1
  else
    echo "web ONE_TOUCH_CMD already at ${new}: $web_file"
  fi
fi

if [[ -z "${targets// /}" ]]; then
  if [[ -n "$web_synced" ]]; then
    echo "done: web pin moved to $new (no in-repo files still pinned $old)"
    echo "NOTE: web ONE_TOUCH_CMD updated — deploy AgentsAtlas/app for it to go live."
    exit 0
  fi
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
  # Straggler check: any occurrence of the release we just replaced is a bug
  # waiting to bite. Historical changelog entries and unrelated test versions
  # are intentionally outside this check.
  stragglers="$(grep -rn -e "v${old_re}" -e "\"${old_re}\"" \
    --include='*.sh' --include='*.py' --include='*.md' --include='*.json' --include='*.toml' --include='*.command' --include='*.svg' \
    . 2>/dev/null | grep -v node_modules | grep -v '^\./vendor/' | grep -v '^\./\.git/' \
    | grep -v '^\./CHANGELOG\.md:' | grep -v 'scripts/bump-version\.sh' || true)"
  if [[ -n "$stragglers" ]]; then
    echo ""
    echo "WARN: version pins that did NOT move (fix or confirm intentional):"
    printf '%s\n' "$stragglers"
  fi
  if [[ -n "$web_synced" ]]; then
    echo "NOTE: web ONE_TOUCH_CMD updated — deploy AgentsAtlas/app for it to go live."
  fi
  echo "NOTE: tag and push the release: git tag $new && git push origin $new"
fi
