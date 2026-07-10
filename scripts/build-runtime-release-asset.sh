#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

tag="${1:-${HEPHAESTUS_REF:-}}"
out_dir="${2:-dist/runtime-release}"

if [[ ! "$tag" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
  echo "usage: scripts/build-runtime-release-asset.sh vX.Y.Z [output-dir]" >&2
  exit 2
fi

git rev-parse --verify "${tag}^{commit}" >/dev/null
manifest_version="$(git show "${tag}:manifest.json" | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])')"
if [[ "v$manifest_version" != "$tag" ]]; then
  echo "release tag $tag does not match manifest.json version $manifest_version at that tag" >&2
  exit 2
fi
mkdir -p "$out_dir"

asset="hephaestus-runtime-${tag}.tar.gz"
archive="$out_dir/$asset"
checksum="$archive.sha256"
tmp="$archive.tmp.$$"
trap 'rm -f "$tmp"' EXIT

git archive \
  --format=tar.gz \
  --prefix="Agentlas-OS-${tag#v}/" \
  --output="$tmp" \
  "$tag"
mv "$tmp" "$archive"

if command -v shasum >/dev/null 2>&1; then
  digest="$(shasum -a 256 "$archive" | awk '{print $1}')"
elif command -v sha256sum >/dev/null 2>&1; then
  digest="$(sha256sum "$archive" | awk '{print $1}')"
else
  digest="$(openssl dgst -sha256 "$archive" | awk '{print $NF}')"
fi

printf '%s  %s\n' "$digest" "$asset" > "$checksum"
tar -tzf "$archive" >/dev/null
printf '%s\n' "$archive" "$checksum"
