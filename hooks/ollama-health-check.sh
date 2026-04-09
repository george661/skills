#!/bin/bash
# SessionStart hook — verify Ollama is running, model available, context configured.
# Lightweight: curl + grep, ~20ms. Outputs warnings to stderr if issues found.

OLLAMA_BASE="http://localhost:11434"
OLLAMA_TAGS="$OLLAMA_BASE/api/tags"
PRIMARY_MODEL="qwen3-coder:30b"

# Quick health check — hit the root endpoint (tiny response, fast)
if ! curl -sf --max-time 1 "$OLLAMA_BASE/" >/dev/null 2>&1; then
    echo "[ollama] Ollama is not running. Start with: OLLAMA_CONTEXT_LENGTH=65536 ollama serve" >&2
    echo '{"continue":true}'
    exit 0
fi

# Check primary model is pulled (tags response can be large with many models)
if ! curl -sf --max-time 3 "$OLLAMA_TAGS" 2>/dev/null | grep -q "$PRIMARY_MODEL"; then
    echo "[ollama] Primary model $PRIMARY_MODEL not found. Run: ollama pull $PRIMARY_MODEL" >&2
fi

# Warn if context length not explicitly configured
# On <24GB VRAM, Ollama defaults to 4k which is too small for agent workflows
if [ -z "$OLLAMA_CONTEXT_LENGTH" ]; then
    echo "[ollama] OLLAMA_CONTEXT_LENGTH not set. For agent tasks, restart with:" >&2
    echo "[ollama]   OLLAMA_CONTEXT_LENGTH=65536 ollama serve" >&2
fi

echo '{"continue":true}'
