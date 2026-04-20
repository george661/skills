#!/bin/bash

# Claude Code statusline command
# Installed by scripts/install.sh to ~/.claude/statusline-command.sh
# Shows: model | project (branch) | context % | turn cost | session cost

INPUT=$(cat)

# Parse core fields
MODEL=$(echo "$INPUT" | jq -r '.model.display_name // .model.id // "Claude"')
MODEL_ID=$(echo "$INPUT" | jq -r '.model.id // ""')
CWD=$(echo "$INPUT" | jq -r '.workspace.current_dir // .cwd // "."')
DIR=$(basename "$CWD")
CONTEXT_REMAINING=$(echo "$INPUT" | jq -r '.context_window.remaining_percentage // empty')

# Git branch (if in a repo)
BRANCH=$(cd "$CWD" 2>/dev/null && git -c core.useBuiltinFSMonitor=false branch --show-current 2>/dev/null)

# Context color
CTX_PART=""
if [ -n "$CONTEXT_REMAINING" ]; then
  CTX_INT=$(printf "%.0f" "$CONTEXT_REMAINING" 2>/dev/null || echo 50)
  if [ "$CTX_INT" -lt 20 ] 2>/dev/null; then
    CTX_PART="\033[31m${CONTEXT_REMAINING}%\033[0m"
  elif [ "$CTX_INT" -lt 50 ] 2>/dev/null; then
    CTX_PART="\033[33m${CONTEXT_REMAINING}%\033[0m"
  else
    CTX_PART="\033[32m${CONTEXT_REMAINING}%\033[0m"
  fi
else
  CTX_PART="\033[90m--\033[0m"
fi

# Session cost - use the pre-calculated cost if available
SESS_PART="\033[90m--\033[0m"
SESS_COST=$(echo "$INPUT" | jq -r '.cost.total_cost_usd // empty' 2>/dev/null)
if [ -n "$SESS_COST" ]; then
  SESS_FMT=$(awk -v c="$SESS_COST" 'BEGIN {printf "%.2f", c}' 2>/dev/null)
  SESS_PART="\033[32m\$${SESS_FMT}\033[0m"
fi

# Turn cost - calculate from current usage tokens
TURN_PART="\033[90m--\033[0m"

# Pricing per 1M tokens
case "$MODEL_ID" in
  *opus-4-7*) IN_P=5;    OUT_P=25; CR_P=0.50; CW_P=6.25  ;;
  *opus-4-6*) IN_P=5;    OUT_P=25; CR_P=0.50; CW_P=6.25  ;;
  *opus-4*)   IN_P=15;   OUT_P=75; CR_P=1.50; CW_P=18.75 ;;
  *sonnet*)   IN_P=3;    OUT_P=15; CR_P=0.30; CW_P=3.75  ;;
  *haiku*)    IN_P=0.80; OUT_P=4;  CR_P=0.08; CW_P=1.00  ;;
  *)          IN_P=3;    OUT_P=15; CR_P=0.30; CW_P=3.75  ;;
esac

C_IN=$(echo "$INPUT" | jq -r '.context_window.current_usage.input_tokens // 0' 2>/dev/null)
C_OUT=$(echo "$INPUT" | jq -r '.context_window.current_usage.output_tokens // 0' 2>/dev/null)
C_CR=$(echo "$INPUT" | jq -r '.context_window.current_usage.cache_read_input_tokens // 0' 2>/dev/null)
C_CW=$(echo "$INPUT" | jq -r '.context_window.current_usage.cache_creation_input_tokens // 0' 2>/dev/null)

# Only show turn cost if there are meaningful output tokens
if [ -n "$C_OUT" ] && [ "$C_OUT" != "null" ] && [ "$C_OUT" -gt 0 ] 2>/dev/null; then
  TURN_COST=$(awk -v i="$C_IN" -v o="$C_OUT" -v cr="$C_CR" -v cw="$C_CW" \
    -v ip="$IN_P" -v op="$OUT_P" -v crp="$CR_P" -v cwp="$CW_P" \
    'BEGIN {printf "%.4f", (i*ip + o*op + cr*crp + cw*cwp)/1000000}' 2>/dev/null)
  if [ -n "$TURN_COST" ]; then
    TURN_PART="\033[33m\$${TURN_COST}\033[0m"
  fi
fi

# Build full line as single string, output with single echo
LINE="\033[35m${MODEL}\033[0m | \033[36m${DIR}\033[0m"
[ -n "$BRANCH" ] && LINE="${LINE} \033[1;34m(\033[31m${BRANCH}\033[1;34m)\033[0m"
LINE="${LINE} | Ctx: ${CTX_PART} | Turn: ${TURN_PART} | Sess: ${SESS_PART}"

echo -e "$LINE"
