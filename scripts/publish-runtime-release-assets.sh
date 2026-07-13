#!/usr/bin/env bash
set -euo pipefail

# Reconcile the deterministic runtime archive and its checksum with an existing
# GitHub Release without replacing published bytes. Existing assets are skipped
# only when GitHub's digest matches the local file; a mismatch fails before any
# missing asset is uploaded.

tag="${1:-}"
archive="${2:-}"
checksum="${3:-}"
repo="${GITHUB_REPOSITORY:-}"

if [[ ! "$tag" =~ ^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$ ]]; then
  echo "usage: scripts/publish-runtime-release-assets.sh vX.Y.Z <archive> <checksum>" >&2
  exit 2
fi
if [[ ! "$repo" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
  echo "GITHUB_REPOSITORY must be an owner/repository pair" >&2
  exit 2
fi
if [[ ! -f "$archive" || ! -f "$checksum" ]]; then
  echo "runtime release assets are missing: archive=$archive checksum=$checksum" >&2
  exit 2
fi

expected_archive_name="hephaestus-runtime-${tag}.tar.gz"
archive_name="$(basename "$archive")"
checksum_name="$(basename "$checksum")"
if [[ "$archive_name" != "$expected_archive_name" || "$checksum_name" != "${expected_archive_name}.sha256" ]]; then
  echo "runtime release asset names do not match tag $tag: archive=$archive_name checksum=$checksum_name" >&2
  exit 2
fi

sha256_file() {
  local file="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$file" | awk '{ print tolower($1) }'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$file" | awk '{ print tolower($1) }'
  else
    openssl dgst -sha256 "$file" | awk '{ print tolower($NF) }'
  fi
}

archive_sha="$(sha256_file "$archive")"
checksum_sha="$(sha256_file "$checksum")"
declared_sha=""
declared_name=""
read -r declared_sha declared_name _ < "$checksum" || true
declared_sha="$(printf '%s' "$declared_sha" | tr '[:upper:]' '[:lower:]')"
if [[ ! "$declared_sha" =~ ^[0-9a-f]{64}$ || "$declared_sha" != "$archive_sha" || "$declared_name" != "$archive_name" ]]; then
  echo "runtime checksum does not describe $archive_name: declared=${declared_sha:-missing} actual=$archive_sha name=${declared_name:-missing}" >&2
  exit 2
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
release_json="$tmp_dir/release.json"
release_err="$tmp_dir/release.err"

fetch_release() {
  gh api "repos/${repo}/releases/tags/${tag}" > "$release_json" 2> "$release_err"
}

if ! fetch_release; then
  if grep -Eqi 'HTTP 404' "$release_err"; then
    echo "release $tag is missing; creating it with both verified assets"
    # `gh release create` stages asset uploads before publishing, which also
    # works when GitHub immutable releases are enabled. If one of those API
    # calls fails after creating a partial release, read it back and reconcile
    # only the missing asset below.
    if ! gh release create "$tag" "$archive" "$checksum" \
      --repo "$repo" --verify-tag --generate-notes \
      > "$tmp_dir/create.out" 2> "$tmp_dir/create.err"; then
      if ! fetch_release; then
        cat "$tmp_dir/create.err" >&2
        cat "$release_err" >&2
        echo "failed to create or recover release $tag" >&2
        exit 1
      fi
      echo "release creation was partial; reconciling its existing assets"
    elif ! fetch_release; then
      cat "$release_err" >&2
      echo "created release $tag but could not read it back" >&2
      exit 1
    fi
  else
    cat "$release_err" >&2
    echo "could not inspect release $tag" >&2
    exit 1
  fi
fi

asset_state() {
  local name="$1"
  python3 - "$release_json" "$name" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    release = json.load(handle)
matches = [asset for asset in release.get("assets", []) if asset.get("name") == sys.argv[2]]
digest = matches[0].get("digest") if len(matches) == 1 else ""
print(f"{len(matches)}\t{digest or ''}")
PY
}

declare -a asset_paths=("$archive" "$checksum")
declare -a asset_names=("$archive_name" "$checksum_name")
declare -a asset_digests=("sha256:$archive_sha" "sha256:$checksum_sha")
declare -a missing_paths=()

# Preflight the complete release before mutating it. This prevents a checksum
# mismatch from being discovered only after another missing asset was uploaded.
for index in "${!asset_paths[@]}"; do
  IFS=$'\t' read -r count actual < <(asset_state "${asset_names[$index]}")
  if [[ "$count" == "0" ]]; then
    missing_paths+=("${asset_paths[$index]}")
    continue
  fi
  if [[ "$count" != "1" ]]; then
    echo "release asset name is ambiguous: ${asset_names[$index]} appears $count times" >&2
    exit 1
  fi
  if [[ "$actual" != "${asset_digests[$index]}" ]]; then
    echo "release asset digest mismatch for ${asset_names[$index]}: expected=${asset_digests[$index]} actual=${actual:-missing}" >&2
    exit 1
  fi
  echo "release asset already verified; skipping ${asset_names[$index]} (${asset_digests[$index]})"
done

if (( ${#missing_paths[@]} > 0 )); then
  for path in "${missing_paths[@]}"; do
    name="$(basename "$path")"
    echo "uploading missing release asset $name"
    if ! gh release upload "$tag" "$path" --repo "$repo" > "$tmp_dir/upload.out" 2> "$tmp_dir/upload.err"; then
      # A concurrent rerun may have uploaded the same immutable bytes after our
      # preflight. Accept that race only if the newly visible digest is identical.
      if fetch_release; then
        IFS=$'\t' read -r count actual < <(asset_state "$name")
        expected=""
        for index in "${!asset_names[@]}"; do
          [[ "${asset_names[$index]}" == "$name" ]] && expected="${asset_digests[$index]}"
        done
        if [[ "$count" == "1" && -n "$expected" && "$actual" == "$expected" ]]; then
          echo "release asset was uploaded concurrently; verified $name ($actual)"
          continue
        fi
      fi
      cat "$tmp_dir/upload.err" >&2
      echo "failed to upload missing release asset $name" >&2
      exit 1
    fi
  done
fi

if ! fetch_release; then
  cat "$release_err" >&2
  echo "could not verify release $tag after upload" >&2
  exit 1
fi

for index in "${!asset_names[@]}"; do
  IFS=$'\t' read -r count actual < <(asset_state "${asset_names[$index]}")
  if [[ "$count" != "1" || "$actual" != "${asset_digests[$index]}" ]]; then
    echo "release asset verification failed for ${asset_names[$index]}: expected=${asset_digests[$index]} actual=${actual:-missing} count=$count" >&2
    exit 1
  fi
done

echo "release $tag runtime assets are complete and digest-verified"
