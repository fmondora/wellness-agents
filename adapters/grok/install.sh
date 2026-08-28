#!/usr/bin/env zsh
# Adapter Grok: materializza le skill dei plugin per Grok Build/TUI
# sostituendo ${CLAUDE_PLUGIN_ROOT} con il path reale del plugin.
# Uso: ./install.sh <grok-skills-dir>
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
DEST="${1:?Uso: install.sh <grok-skills-dir>}"
for plugin in "$REPO"/*/skills/*/SKILL.md; do
  name="$(basename "$(dirname "$plugin")")"
  plugin_root="$(cd "$(dirname "$plugin")/../.." && pwd)"
  mkdir -p "$DEST/$name"
  sed "s|\${CLAUDE_PLUGIN_ROOT}|$plugin_root|g" "$plugin" > "$DEST/$name/SKILL.md"
  echo "installata: $name → $DEST/$name"
done
