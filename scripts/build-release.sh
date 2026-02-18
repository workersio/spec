#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BINARY="workers-spec"
PACKAGE="workers-spec-cli"

TARGETS=(
  "aarch64-apple-darwin"
  "x86_64-apple-darwin"
  "x86_64-unknown-linux-musl"
  "aarch64-unknown-linux-musl"
)

LINUX_TARGETS=(
  "x86_64-unknown-linux-musl"
  "aarch64-unknown-linux-musl"
)

echo "Building $BINARY for ${#TARGETS[@]} targets..."
echo ""

for target in "${TARGETS[@]}"; do
  echo "→ Building $target"

  if [[ " ${LINUX_TARGETS[*]} " == *" $target "* ]]; then
    cargo zigbuild --release --target "$target" -p "$PACKAGE"
  else
    cargo build --release --target "$target" -p "$PACKAGE"
  fi

  tar czf "${BINARY}-${target}.tar.gz" -C "target/${target}/release" "$BINARY"
  echo "  ✓ ${BINARY}-${target}.tar.gz"
done

echo ""
echo "Done. Release artifacts:"
ls -lh ${BINARY}-*.tar.gz
