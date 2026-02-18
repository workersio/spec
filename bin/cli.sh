#!/usr/bin/env bash
set -euo pipefail

REPO="workersio/spec"
BINARY_NAME="workers-spec"

# Resolve real path of this script (handles npm symlinks)
resolve_path() {
  local target="$1"
  # Try readlink -f (Linux, newer macOS)
  if command -v readlink >/dev/null 2>&1 && readlink -f "$target" 2>/dev/null; then
    return
  fi
  # Try realpath
  if command -v realpath >/dev/null 2>&1 && realpath "$target" 2>/dev/null; then
    return
  fi
  # Manual resolution (older macOS)
  while [ -L "$target" ]; do
    local dir
    dir="$(cd -P "$(dirname "$target")" && pwd)"
    target="$(readlink "$target")"
    [[ "$target" != /* ]] && target="$dir/$target"
  done
  echo "$(cd -P "$(dirname "$target")" && pwd)/$(basename "$target")"
}

SELF="$(resolve_path "$0")"
PACKAGE_DIR="$(dirname "$(dirname "$SELF")")"
VENDOR_BINARY="$PACKAGE_DIR/vendor/$BINARY_NAME"

# 1. Check vendor dir
if [ -x "$VENDOR_BINARY" ]; then
  exec "$VENDOR_BINARY" "$@"
fi

# 2. Search PATH, skipping npm symlinks back to this script
IFS=':' read -ra DIRS <<< "${PATH:-}"
for dir in "${DIRS[@]}"; do
  candidate="$dir/$BINARY_NAME"
  if [ -x "$candidate" ] 2>/dev/null; then
    real="$(resolve_path "$candidate")"
    # Skip if it resolves back to this script
    [ "$real" = "$SELF" ] && continue
    exec "$candidate" "$@"
  fi
done

# 3. Download from GitHub releases
get_target() {
  local os arch
  os="$(uname -s)"
  arch="$(uname -m)"

  case "$arch" in
    x86_64|amd64) arch="x86_64" ;;
    arm64|aarch64) arch="aarch64" ;;
    *) echo "Unsupported architecture: $arch" >&2; exit 1 ;;
  esac

  case "$os" in
    Linux)  echo "${arch}-unknown-linux-musl" ;;
    Darwin) echo "${arch}-apple-darwin" ;;
    *)      echo "Unsupported platform: $os" >&2; exit 1 ;;
  esac
}

target="$(get_target)"

# Fetch latest release tag (no jq dependency)
api_response="$(curl -fsSL -H "User-Agent: workers-spec-npm" \
  "https://api.github.com/repos/$REPO/releases/latest" 2>/dev/null)" || {
  echo "Error: Failed to fetch latest release from GitHub." >&2
  echo "Install from source:" >&2
  echo "  cargo install --git https://github.com/$REPO workers-spec-cli" >&2
  exit 1
}
version="$(echo "$api_response" | grep '"tag_name"' | sed 's/.*"tag_name": *"\([^"]*\)".*/\1/')"

if [ -z "$version" ]; then
  echo "Error: Could not determine latest version." >&2
  exit 1
fi

url="https://github.com/$REPO/releases/download/$version/$BINARY_NAME-$target.tar.gz"
echo "Downloading $BINARY_NAME $version for $target..."

tmpfile="$(mktemp)"
trap 'rm -f "$tmpfile"' EXIT

curl -fsSL "$url" -o "$tmpfile" || {
  echo "Error: Failed to download $url" >&2
  echo "Install from source:" >&2
  echo "  cargo install --git https://github.com/$REPO workers-spec-cli" >&2
  exit 1
}

mkdir -p "$PACKAGE_DIR/vendor"
tar xzf "$tmpfile" -C "$PACKAGE_DIR/vendor"
chmod 755 "$VENDOR_BINARY"
echo "Installed $BINARY_NAME $version"
echo

exec "$VENDOR_BINARY" "$@"
