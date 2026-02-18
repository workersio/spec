#!/usr/bin/env bash
# Install Claude Code slash commands — errors must never break npm install

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMMANDS_SRC="$SCRIPT_DIR/../commands"
COMMANDS_DST="$HOME/.claude/commands"

mkdir -p "$COMMANDS_DST" 2>/dev/null || true

installed=""
for file in "$COMMANDS_SRC"/*.md; do
  [ -f "$file" ] || continue
  cp "$file" "$COMMANDS_DST/" 2>/dev/null || true
  name="$(basename "$file" .md)"
  if [ -z "$installed" ]; then
    installed="/$name"
  else
    installed="$installed and /$name"
  fi
done

if [ -n "$installed" ]; then
  echo "Installed $installed commands to ~/.claude/commands/"
fi

echo ""
echo "Ready! Use /share in Claude Code to share a session."
echo "Binary will be downloaded on first use."
