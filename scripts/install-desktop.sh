#!/usr/bin/env bash
# Agentlas Desktop — one-line install for macOS and Linux.
#
#   curl -fsSL https://agentlas.cloud/install.sh | bash
#   curl -fsSL https://agentlas.cloud/install.sh | bash -s -- --with-engine
#
# agentlas.cloud/install.sh redirects to this file in the public Agentlas-OS repo.
#
# What it does, in order:
#   1. Reads the latest release metadata (latest-mac.yml / latest-linux.yml) from
#      github.com/agentlas-ai/agentlas-desktop-releases.
#   2. Downloads the build for this OS and CPU and checks its sha512 against that
#      metadata. A mismatch stops the install; nothing is written.
#   3. macOS: unpacks the signed app with ditto (keeps the signature), verifies the
#      signature, and places Agentlas.app in /Applications (or ~/Applications when
#      /Applications is not writable). No sudo.
#      Linux: places the AppImage in ~/.local/opt/agentlas and links
#      ~/.local/bin/agentlas-desktop. No sudo.
#   4. --with-engine also installs Agentlas OS into your agent hosts (Claude Code,
#      Codex, Gemini, Cursor ...) with scripts/install-all-runtimes.sh.
#
# Options:  --with-engine   also install Agentlas OS
#           --no-open       do not launch the app afterwards
# Env:      AGENTLAS_WITH_ENGINE=1         same as --with-engine
#           AGENTLAS_NO_OPEN=1             same as --no-open
#           AGENTLAS_DESKTOP_INSTALL_DIR   install location override
#           AGENTLAS_DESKTOP_RELEASES      owner/repo of the release feed
set -euo pipefail

releases="${AGENTLAS_DESKTOP_RELEASES:-agentlas-ai/agentlas-desktop-releases}"
engine_url="https://raw.githubusercontent.com/agentlas-ai/Agentlas-OS/main/scripts/install-all-runtimes.sh"
with_engine="$([ "${AGENTLAS_WITH_ENGINE:-0}" = 1 ] && echo 1 || echo 0)"
open_after="$([ "${AGENTLAS_NO_OPEN:-0}" = 1 ] && echo 0 || echo 1)"
for arg in "$@"; do
  case "$arg" in
    --with-engine) with_engine=1 ;;
    --no-open) open_after=0 ;;
    -h|--help) sed -n '2,28p' "$0" 2>/dev/null || true; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 64 ;;
  esac
done

say() { printf '==> %s\n' "$*"; }
die() { printf 'Agentlas Desktop install stopped: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "'$1' is required but not installed."; }
need curl

work="$(mktemp -d "${TMPDIR:-/tmp}/agentlas-desktop.XXXXXX")"
trap 'rm -rf "$work"' EXIT

# sha512 in electron-builder metadata is base64 of the raw digest.
sha512_b64() {
  if command -v openssl >/dev/null 2>&1; then
    openssl dgst -sha512 -binary "$1" | base64 | tr -d '\n'
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c 'import sys,hashlib,base64;print(base64.b64encode(hashlib.sha512(open(sys.argv[1],"rb").read()).digest()).decode(),end="")' "$1"
  else
    die "need openssl or python3 to verify the download."
  fi
}

# Print "<file> <sha512>" for the first files: entry whose url matches $2.
pick_asset() {
  awk -v want="$2" '
    /^[[:space:]]*- url:/ { url=$3; next }
    /^[[:space:]]*sha512:/ && url != "" { if (url ~ want) { print url, $2; exit } url="" }
  ' "$1"
}

fetch() { curl -fL --retry 3 --retry-delay 2 -o "$2" "https://github.com/$releases/releases/latest/download/$1"; }

os="$(uname -s)"
case "$os" in
  Darwin)
    arch="$(uname -m)"
    # An Intel shell under Rosetta on Apple silicon still wants the arm64 build.
    if [ "$arch" = "x86_64" ] && [ "$(sysctl -in sysctl.proc_translated 2>/dev/null || echo 0)" = "1" ]; then arch="arm64"; fi
    case "$arch" in
      arm64) pattern='-arm64\.zip$' ;;
      x86_64) pattern='-x64\.zip$' ;;
      *) die "unsupported Mac CPU: $arch" ;;
    esac
    meta="latest-mac.yml"
    ;;
  Linux)
    [ "$(uname -m)" = "x86_64" ] || die "Linux builds are x86_64 only (this machine is $(uname -m))."
    pattern='\.AppImage$'
    meta="latest-linux.yml"
    ;;
  *)
    die "this script is for macOS and Linux. On Windows, paste into PowerShell: irm https://agentlas.cloud/install.ps1 | iex"
    ;;
esac

say "Reading the latest Agentlas Desktop release"
fetch "$meta" "$work/$meta" || die "could not read release metadata ($meta)."
version="$(awk '/^version:/ {print $2; exit}' "$work/$meta")"
read -r asset expected < <(pick_asset "$work/$meta" "$pattern") || true
[ -n "${asset:-}" ] && [ -n "${expected:-}" ] || die "no build for this machine in $meta."

say "Downloading Agentlas Desktop $version ($asset)"
fetch "$asset" "$work/$asset" || die "download failed."
actual="$(sha512_b64 "$work/$asset")"
[ "$actual" = "$expected" ] || die "checksum mismatch for $asset — the download was not installed."
say "Checksum verified (sha512)"

if [ "$os" = "Darwin" ]; then
  need ditto
  mkdir -p "$work/unpacked"
  ditto -x -k "$work/$asset" "$work/unpacked"
  app="$(find "$work/unpacked" -maxdepth 2 -name '*.app' -type d | head -1)"
  [ -n "$app" ] || die "the archive did not contain an app."
  codesign --verify --deep --strict "$app" >/dev/null 2>&1 || die "the app signature did not verify."
  dest="${AGENTLAS_DESKTOP_INSTALL_DIR:-/Applications}"
  if [ -z "${AGENTLAS_DESKTOP_INSTALL_DIR:-}" ] && [ ! -w "$dest" ]; then dest="$HOME/Applications"; fi
  mkdir -p "$dest"
  target="$dest/$(basename "$app")"
  # Swap in place: the old copy is moved aside first so a failed move leaves it intact.
  if [ -e "$target" ]; then mv "$target" "$work/previous.app"; fi
  if ! mv "$app" "$target"; then
    [ -e "$work/previous.app" ] && mv "$work/previous.app" "$target"
    die "could not place the app in $dest."
  fi
  say "Installed $target"
  [ "$open_after" = 1 ] && open "$target" || true
else
  dest="${AGENTLAS_DESKTOP_INSTALL_DIR:-$HOME/.local/opt/agentlas}"
  mkdir -p "$dest" "$HOME/.local/bin"
  install -m 0755 "$work/$asset" "$dest/Agentlas.AppImage"
  ln -sf "$dest/Agentlas.AppImage" "$HOME/.local/bin/agentlas-desktop"
  say "Installed $dest/Agentlas.AppImage (run: agentlas-desktop)"
  if [ "$open_after" = 1 ] && [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]; then
    nohup "$dest/Agentlas.AppImage" >/dev/null 2>&1 &
  fi
fi

if [ "$with_engine" = 1 ]; then
  say "Installing Agentlas OS into your agent hosts"
  curl -fsSL "$engine_url" | bash
fi

say "Done. Agentlas Desktop $version is ready."
