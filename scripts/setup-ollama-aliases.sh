#!/usr/bin/env bash
# setup-ollama-aliases.sh — Create a single Ollama alias for Claude Code dispatch
#
# Claude Code validates model names client-side and rejects non-Claude IDs.
# This creates ONE alias with a Claude-format name that points to whatever local
# model the active profile in model-routing.json resolves to.
#
# The canonical alias name is: us.anthropic.claude-sonnet-4-5-20250929-v1:0
# dispatch-local.py always uses this name with `claude --model`.
#
# Usage: ./setup-ollama-aliases.sh [--model <ollama-model>]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROUTING_CONFIG="${SCRIPT_DIR}/../config/model-routing.json"
INSTALLED_CONFIG="$HOME/.claude/config/model-routing.json"
CONTEXT_LENGTH="${OLLAMA_CONTEXT_LENGTH:-65536}"
ALIAS_NAME="us.anthropic.claude-sonnet-4-5-20250929-v1:0"

# Allow explicit override via --model flag
SOURCE_MODEL=""
if [[ "${1:-}" == "--model" ]] && [[ -n "${2:-}" ]]; then
  SOURCE_MODEL="$2"
fi

# Check Ollama is running
if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "Error: Ollama is not running. Start it with: ollama serve"
  exit 1
fi

# Resolve source model from model-routing.json if not explicitly provided
if [[ -z "$SOURCE_MODEL" ]]; then
  # Prefer installed config, fall back to repo config
  CONFIG_FILE="$INSTALLED_CONFIG"
  [[ -f "$CONFIG_FILE" ]] || CONFIG_FILE="$ROUTING_CONFIG"

  if [[ -f "$CONFIG_FILE" ]]; then
    # Use python3 to resolve: load config, apply active profile, find the
    # most common local model (the one used by /implement or defaults.fallback)
    SOURCE_MODEL=$(python3 -c "
import json, sys
with open('$CONFIG_FILE') as f:
    cfg = json.load(f)
profile = cfg.get('active_profile', 'default')
profiles = cfg.get('profiles', {})
commands = dict(cfg.get('commands', {}))
if profile and profile != 'default' and profile in profiles:
    for cmd, alias in profiles[profile].get('overrides', {}).items():
        if isinstance(alias, str):
            commands.setdefault(cmd, {})['main'] = alias
# Get the model for /implement (most frequently dispatched command)
alias = commands.get('implement', {}).get('main', cfg.get('defaults', {}).get('fallback', ''))
# Resolve alias to actual ollama model name
model_entry = cfg.get('models', {}).get(alias, {})
if isinstance(model_entry, dict):
    print(model_entry.get('model', alias))
else:
    print(alias)
" 2>/dev/null)
  fi

  # Final fallback
  if [[ -z "$SOURCE_MODEL" ]]; then
    SOURCE_MODEL="qwen3-coder:30b"
    echo "Warning: Could not resolve model from config, defaulting to ${SOURCE_MODEL}"
  fi
fi

echo "Setting up Ollama dispatch alias (context: ${CONTEXT_LENGTH})..."
echo "  Active model: ${SOURCE_MODEL}"
echo "  Alias: ${ALIAS_NAME}"

# Check source model exists
if ! ollama list | awk '{print $1}' | grep -q "^${SOURCE_MODEL}$"; then
  echo "Error: Source model ${SOURCE_MODEL} not found. Pull it with: ollama pull ${SOURCE_MODEL}"
  exit 1
fi

# Create the alias
TMPFILE=$(mktemp)
trap 'rm -f "$TMPFILE"' EXIT

cat > "$TMPFILE" <<MODELFILE
FROM ${SOURCE_MODEL}
PARAMETER num_ctx ${CONTEXT_LENGTH}
MODELFILE

ollama create "${ALIAS_NAME}" -f "$TMPFILE"
echo "  ✓ ${ALIAS_NAME} → ${SOURCE_MODEL} (${CONTEXT_LENGTH} ctx)"

# Clean up legacy aliases that are no longer needed
for legacy in "global.anthropic.claude-sonnet-4-20250514-v1:0" "claude-sonnet-4-6"; do
  if ollama list | awk '{print $1}' | grep -q "^${legacy}$"; then
    echo "  Removing legacy alias: ${legacy}"
    ollama rm "${legacy}" 2>/dev/null || true
  fi
done

echo ""
echo "Done. Dispatch will use: ${ALIAS_NAME} → ${SOURCE_MODEL}"
