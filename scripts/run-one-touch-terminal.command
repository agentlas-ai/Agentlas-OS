#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

log="/tmp/hephaestus-one-touch-terminal.log"

clear
echo "Hephaestus one-touch Terminal verification"
echo "repo: $root"
echo "log: $log"
echo

HEPHAESTUS_KEEP_SMOKE_DIR=1 scripts/verify-one-touch-install.sh 2>&1 | tee "$log"

gui_url="$(grep '^GUI: file://' "$log" | tail -1 | sed 's/^GUI: //')"
if [[ -n "$gui_url" ]]; then
  echo
  echo "Opening ontology GUI:"
  echo "$gui_url"
  open "$gui_url"
fi

echo
echo "SCREENSHOT_READY: Hephaestus one-touch install + ontology GUI completed"
echo "Press any key to close this Terminal window."
read -r -n 1 _
