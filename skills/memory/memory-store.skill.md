---
name: memory-store
description: Low-level skill for storing memory entries to AgentDB - episodes, patterns, and key-value data
---

# Memory Store Skill

Low-level skill for direct memory storage operations. Higher-level skills like `session-complete` use this for consistent storage patterns.

## Storage Types

| Type | Purpose | API Endpoint |
|------|---------|--------------|
| Episode | Task execution record with reward | `/api/v1/reflexion/store-episode` |
| Pattern | Reusable approach with success rate | `/api/v1/patterns/store` |
| Key-Value | Arbitrary named data | `/api/v1/memory/store` |

## Episode Storage

### Schema

```typescript
interface Episode {
  session_id: string;    // Unique: "{ISSUE_KEY}-{COMMAND}-{TIMESTAMP}"
  task: string;          // "{command} for {issue} ({type})"
  input: string;         // Context/problem description
  output: string;        // What was done/result
  critique: string;      // Self-reflection on outcome
  reward: number;        // 0.0-1.0 calculated score
  success: boolean;      // Binary outcome
  latency_ms?: number;   // Execution time
  tokens_used?: number;  // Token consumption
}
```

### Store Episode

```bash
npx tsx .claude/skills/agentdb/reflexion_store_episode.ts '{
  "session_id": "PROJ-123-implement-1706550000",
  "task": "implement for PROJ-123 (UI_DISPLAY)",
  "input": "Add dark mode toggle to settings page",
  "output": "Created DarkModeToggle component, 3 tests, PR #42",
  "critique": "Succeeded with 1 retry. Used design system tokens.",
  "reward": 0.85,
  "success": true
}'
```

### Session ID Format

```
{ISSUE_KEY}-{COMMAND}-{UNIX_TIMESTAMP}
```

Examples:
- `PROJ-123-implement-1706550000`
- `PROJ-456-validate-1706551234`
- `PROJ-100-plan-1706552000`

## Pattern Storage

### Schema

```typescript
interface Pattern {
  task_type: string;     // "{ISSUE_TYPE}-{COMMAND}" or "{ISSUE_TYPE}-{COMMAND}-AVOID"
  approach: string;      // Detailed approach description
  success_rate: number;  // 0.0-1.0 effectiveness score
  metadata?: {
    issue_key?: string;
    command?: string;
    session_id?: string;
    is_anti_pattern?: boolean;
  };
}
```

### Store Success Pattern (reward >= 0.9)

```bash
npx tsx .claude/skills/agentdb/pattern_store.ts '{
  "task_type": "UI_DISPLAY-implement",
  "approach": "Write Playwright test first, use design system tokens for theming",
  "success_rate": 0.95,
  "metadata": {
    "issue_key": "PROJ-123",
    "command": "implement",
    "session_id": "PROJ-123-implement-1706550000"
  }
}'
```

### Store Anti-Pattern (reward < 0.5)

```bash
npx tsx .claude/skills/agentdb/pattern_store.ts '{
  "task_type": "UI_DISPLAY-implement-AVOID",
  "approach": "Skipped mobile viewport testing - caused test timeout",
  "success_rate": 0.15,
  "metadata": {
    "issue_key": "PROJ-124",
    "command": "implement",
    "session_id": "PROJ-124-implement-1706551000",
    "is_anti_pattern": true
  }
}'
```

### Task Type Naming

**Success patterns:**
```
{ISSUE_TYPE}-{COMMAND}
```

**Anti-patterns:**
```
{ISSUE_TYPE}-{COMMAND}-AVOID
```

**Issue types:**
- `UI_DISPLAY` - Frontend components, styling
- `API_ENDPOINT` - REST endpoints, controllers
- `DATABASE` - Migrations, queries, schema
- `AUTHORIZATION` - Auth, permissions, security
- `TESTING` - Test coverage, quality
- `INFRASTRUCTURE` - Deploy, CI/CD, config
- `BACKEND_LOGIC` - Business logic (default)
- `GENERAL` - When type unknown

## Key-Value Storage

For arbitrary named data (implementation plans, PR URLs, etc.):

```bash
npx tsx .claude/skills/agentdb/recall_query.ts '{
  "query_id": "impl-PROJ-123",
  "query": "implementation plan for PROJ-123"
}'
```

**Common key patterns:**
| Pattern | Purpose |
|---------|---------|
| `impl-{ISSUE}` | Implementation plan |
| `pr-{ISSUE}` | PR URL and number |
| `done-{ISSUE}` | Completion evidence |
| `loop-state-{ISSUE}` | Loop automation state |

## Batch Storage

When storing multiple related items, batch the calls:

```bash
# Store episode and pattern in parallel (if applicable)
npx tsx .claude/skills/agentdb/reflexion_store_episode.ts '{ ... }' &
npx tsx .claude/skills/agentdb/pattern_store.ts '{ ... }' &
wait
```

## Error Handling

### Check AgentDB Health First

```bash
npx tsx .claude/skills/agentdb/db_get_health.ts
```

Expected output:
```json
{
  "status": "healthy",
  "version": "1.0.0"
}
```

### Fallback to Recovery Files

If AgentDB is unavailable, store to local recovery file:

```bash
mkdir -p docs/recovery

# Store episode for later sync
cat > docs/recovery/episode-${SESSION_ID}.json << 'EOF'
{
  "type": "episode",
  "data": {
    "session_id": "${SESSION_ID}",
    "task": "${TASK}",
    "reward": ${REWARD},
    "success": ${SUCCESS}
  },
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
```

### Recovery File Format

```json
{
  "type": "episode" | "pattern",
  "data": { /* original payload */ },
  "timestamp": "2025-01-29T12:00:00Z"
}
```

## Verification

After storing, verify with recall:

```bash
# Verify episode stored
npx tsx .claude/skills/agentdb/recall_query.ts '{
  "query": "${SESSION_ID}",
  "k": 1
}'

# Verify pattern stored
npx tsx .claude/skills/agentdb/pattern_search.ts '{
  "task": "${TASK_TYPE}",
  "k": 1
}'
```

## Anti-Patterns

- **Missing session_id** - Every episode needs unique identifier
- **Vague task descriptions** - Include issue key and type
- **Skipping critique** - Self-reflection is key for learning
- **Hardcoded rewards** - Always calculate with reward-calculator
- **Silent failures** - Log errors, use recovery files
