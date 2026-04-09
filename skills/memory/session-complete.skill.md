---
name: session-complete
description: Record session outcome for cross-agent learning - stores episodes, patterns, and anti-patterns to AgentDB
---

# Session Complete Skill

Store execution outcome for distributed agent learning. This skill calculates reward, stores the episode, and creates patterns/anti-patterns based on thresholds.

## When to Use

Commands invoke this skill at completion to enable cross-agent learning:

- **Tier 1 commands** (high value): Full integration with patterns
- **Tier 2 commands** (medium value): Episode storage only

## Required Inputs

| Parameter | Required | Description |
|-----------|----------|-------------|
| `issue_key` | Yes | Jira issue worked on (e.g., `PROJ-123`) |
| `command` | Yes | Command that executed (e.g., `implement`) |
| `success` | Yes | Boolean - did the command succeed? |
| `result_summary` | Yes | Brief description of what happened |
| `retries` | No | Number of retry attempts (default: 0) |
| `approach_used` | No | Pattern/approach that was followed |
| `failure_reason` | No | Why it failed (if applicable) |
| `ci_passed_first` | No | CI passed on first attempt |
| `under_budget` | No | Completed under token budget |
| `over_budget` | No | Exceeded token budget |
| `required_human` | No | Needed human intervention |
| `issue_type` | No | Issue classification (UI_DISPLAY, API_ENDPOINT, etc.) |

## Execution Steps

### Step 1: Calculate Reward

```bash
# Calculate reward using standardized formula
npx tsx .claude/skills/memory/reward-calculator.ts '{
  "success": ${SUCCESS},
  "retries": ${RETRIES:-0},
  "ci_passed_first": ${CI_PASSED_FIRST:-false},
  "under_budget": ${UNDER_BUDGET:-false},
  "over_budget": ${OVER_BUDGET:-false},
  "required_human": ${REQUIRED_HUMAN:-false}
}'
```

**Reward Thresholds:**
| Reward | Action |
|--------|--------|
| >= 0.9 | Store episode + success pattern |
| 0.5-0.89 | Store episode only |
| < 0.5 | Store episode + anti-pattern |

### Step 2: Build Session ID

Format: `{ISSUE_KEY}-{COMMAND}-{TIMESTAMP}`

```bash
SESSION_ID="${ISSUE_KEY}-${COMMAND}-$(date +%s)"
```

### Step 3: Generate Critique

Build self-reflection based on outcome:

**If success:**
```
Succeeded with ${RETRIES} retries. ${APPROACH_USED ? "Used approach: " + APPROACH_USED : ""}
```

**If failure:**
```
Failed: ${FAILURE_REASON}. ${APPROACH_USED ? "Attempted approach: " + APPROACH_USED : ""}
```

### Step 4: Store Episode (ALWAYS)

```bash
npx tsx .claude/skills/agentdb/reflexion_store_episode.ts '{
  "session_id": "${SESSION_ID}",
  "task": "${COMMAND} for ${ISSUE_KEY} (${ISSUE_TYPE:-UNKNOWN})",
  "input": "${RESULT_SUMMARY}",
  "output": "Command completed with reward ${REWARD}",
  "critique": "${CRITIQUE}",
  "reward": ${REWARD},
  "success": ${SUCCESS}
}'
```

### Step 5: Store Pattern (CONDITIONAL)

**If reward >= 0.9 (success pattern):**

```bash
npx tsx .claude/skills/agentdb/pattern_store.ts '{
  "task_type": "${ISSUE_TYPE:-GENERAL}-${COMMAND}",
  "approach": "${APPROACH_USED}",
  "success_rate": ${REWARD},
  "metadata": {
    "issue_key": "${ISSUE_KEY}",
    "command": "${COMMAND}",
    "session_id": "${SESSION_ID}"
  }
}'
```

**If reward < 0.5 (anti-pattern):**

```bash
npx tsx .claude/skills/agentdb/pattern_store.ts '{
  "task_type": "${ISSUE_TYPE:-GENERAL}-${COMMAND}-AVOID",
  "approach": "${FAILURE_REASON}",
  "success_rate": ${REWARD},
  "metadata": {
    "issue_key": "${ISSUE_KEY}",
    "command": "${COMMAND}",
    "session_id": "${SESSION_ID}",
    "is_anti_pattern": true
  }
}'
```

### Step 6: Report Outcome

Output summary of what was stored:

```markdown
## Memory Storage Complete

| Field | Value |
|-------|-------|
| Session ID | ${SESSION_ID} |
| Reward | ${REWARD} |
| Action | ${STORAGE_ACTION} |

${STORAGE_ACTION === 'success_pattern' ? '✅ Pattern stored for future sessions' : ''}
${STORAGE_ACTION === 'anti_pattern' ? '⚠️ Anti-pattern stored to warn future sessions' : ''}
```

## Example: Successful Implementation

```bash
# At end of /implement command
npx tsx .claude/skills/memory/reward-calculator.ts '{
  "success": true,
  "retries": 1,
  "ci_passed_first": false
}'
# Output: reward = 0.75, action = episode_only

npx tsx .claude/skills/agentdb/reflexion_store_episode.ts '{
  "session_id": "PROJ-123-implement-1706550000",
  "task": "implement for PROJ-123 (UI_DISPLAY)",
  "input": "Add dark mode toggle to settings page",
  "output": "Created DarkModeToggle component, 3 Playwright tests, PR #42",
  "critique": "Succeeded with 1 retry due to lint error. Used design system tokens.",
  "reward": 0.75,
  "success": true
}'
```

## Example: High-Success Pattern

```bash
# Perfect execution
npx tsx .claude/skills/memory/reward-calculator.ts '{
  "success": true,
  "retries": 0,
  "ci_passed_first": true
}'
# Output: reward = 1.0, action = success_pattern

# Store episode
npx tsx .claude/skills/agentdb/reflexion_store_episode.ts '{ ... }'

# Also store pattern
npx tsx .claude/skills/agentdb/pattern_store.ts '{
  "task_type": "UI_DISPLAY-implement",
  "approach": "Write Playwright test first, use design system tokens for theming",
  "success_rate": 1.0,
  "metadata": {
    "issue_key": "PROJ-123",
    "command": "implement",
    "session_id": "PROJ-123-implement-1706550000"
  }
}'
```

## Example: Failed Execution (Anti-Pattern)

```bash
# Failure case
npx tsx .claude/skills/memory/reward-calculator.ts '{
  "success": false,
  "recoverable": true,
  "required_human": true
}'
# Output: reward = 0.05, action = anti_pattern

# Store episode
npx tsx .claude/skills/agentdb/reflexion_store_episode.ts '{
  "session_id": "PROJ-124-implement-1706551000",
  "task": "implement for PROJ-124 (UI_DISPLAY)",
  "input": "Add responsive sidebar",
  "output": "Failed: Test timeout on mobile viewport",
  "critique": "Failed: Skipped mobile viewport testing. Required human to debug.",
  "reward": 0.05,
  "success": false
}'

# Store anti-pattern
npx tsx .claude/skills/agentdb/pattern_store.ts '{
  "task_type": "UI_DISPLAY-implement-AVOID",
  "approach": "Skipped mobile viewport testing - caused test timeout",
  "success_rate": 0.05,
  "metadata": {
    "issue_key": "PROJ-124",
    "command": "implement",
    "session_id": "PROJ-124-implement-1706551000",
    "is_anti_pattern": true
  }
}'
```

## Graceful Degradation

If AgentDB is unavailable:

1. **Log warning** - Don't fail the command
2. **Write to recovery file** - Store in `docs/recovery/` for later sync

```bash
# Fallback when AgentDB unreachable
mkdir -p docs/recovery
cat > docs/recovery/episode-${SESSION_ID}.json << 'EOF'
{
  "session_id": "${SESSION_ID}",
  "task": "${COMMAND} for ${ISSUE_KEY}",
  "reward": ${REWARD},
  "success": ${SUCCESS},
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

echo "⚠️ AgentDB unavailable - episode saved to docs/recovery/ for later sync"
```

## Anti-Patterns

- **Hardcoding reward values** - Always use reward-calculator
- **Skipping episode storage** - Every command completion should store
- **Vague critiques** - Be specific about what worked/failed
- **Missing issue type** - Include for better pattern matching
