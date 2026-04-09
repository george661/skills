---
name: memory-load
description: Load relevant patterns and anti-patterns from AgentDB at session start
---

# Memory Load Skill

Load successful patterns and anti-patterns from AgentDB to guide command execution. This skill queries past experiences to prevent repeating mistakes and leverage proven approaches.

## When to Use

This skill is invoked by `session-init.skill.md` during Phase 0. Commands don't call this directly - they configure session-init with the appropriate scope.

## Load Scopes

| Scope | What's Loaded | Use Case |
|-------|---------------|----------|
| `issue-only` | Issue-specific memories only | Quick commands (`/fix-pr`) |
| `issue-patterns` | Issue + pattern search (default) | Most commands |
| `full` | Above + recent history + workflows | Orchestrators (`/work`, `/loop:*`) |

## Required Inputs

| Parameter | Required | Description |
|-----------|----------|-------------|
| `issue_key` | Yes | Jira issue key (e.g., `PROJ-123`) |
| `command` | Yes | Command being executed |
| `issue_type` | No | Issue classification (UI_DISPLAY, API_ENDPOINT, etc.) |
| `scope` | No | Load scope (default: `issue-patterns`) |
| `namespace` | No | Memory namespace (default: from TENANT_NAMESPACE) |

## Execution Steps

### Step 1: Get Issue Type (if not provided)

```bash
# Fetch issue to determine type
npx tsx .claude/skills/jira/get_issue.ts '{"issue_key": "${ISSUE_KEY}", "fields": ["summary", "labels", "components"]}'
```

**Issue type classification from labels/components:**
| Contains | Type |
|----------|------|
| `frontend`, `ui`, `component` | UI_DISPLAY |
| `api`, `endpoint`, `rest` | API_ENDPOINT |
| `database`, `migration`, `schema` | DATABASE |
| `auth`, `permission`, `security` | AUTHORIZATION |
| `test`, `coverage`, `playwright` | TESTING |
| `infra`, `deploy`, `pipeline` | INFRASTRUCTURE |
| (default) | BACKEND_LOGIC |

### Step 2: Search Success Patterns

```bash
# Search for patterns matching issue type + command
npx tsx .claude/skills/agentdb/pattern_search.ts '{
  "task": "${ISSUE_TYPE}-${COMMAND}",
  "k": 5
}'
```

**Filter results:**
- Only include patterns with `success_rate >= 0.7`
- Sort by success_rate descending
- Exclude patterns marked as anti-patterns

### Step 3: Search Anti-Patterns

```bash
# Search for anti-patterns (failures to avoid)
npx tsx .claude/skills/agentdb/pattern_search.ts '{
  "task": "${ISSUE_TYPE}-${COMMAND}-AVOID",
  "k": 5
}'
```

**Also search general failures:**
```bash
npx tsx .claude/skills/agentdb/recall_query.ts '{
  "query": "${ISSUE_TYPE} ${COMMAND} failed",
  "k": 5
}'
```

Filter for entries with `reward < 0.5` or `is_anti_pattern: true`.

### Step 4: Load Issue-Specific Context (if scope !== issue-only)

```bash
# Query for prior work on this specific issue
npx tsx .claude/skills/agentdb/recall_query.ts '{
  "query": "${ISSUE_KEY}",
  "k": 10
}'
```

This retrieves:
- Prior implementation attempts
- Previous critique/learnings
- Related session outcomes

### Step 5: Load Recent History (if scope === full)

```bash
# Query recent executions of this command type
npx tsx .claude/skills/agentdb/recall_query.ts '{
  "query": "${COMMAND} recent",
  "k": 10
}'
```

### Step 6: Format Memory Context

Output structured markdown block for command to use:

```markdown
## Memory Context for ${ISSUE_KEY}

### Issue Classification
- **Type:** ${ISSUE_TYPE}
- **Command:** ${COMMAND}

### Successful Patterns (apply these)
| Score | Approach |
|-------|----------|
${SUCCESS_PATTERNS.map(p => `| ${p.success_rate.toFixed(2)} | "${p.approach}" |`).join('\n')}

### Anti-Patterns (avoid these)
| Score | What Failed |
|-------|-------------|
${ANTI_PATTERNS.map(p => `| ${p.success_rate.toFixed(2)} | "${p.approach}" |`).join('\n')}

### Issue History
${ISSUE_CONTEXT.length > 0 ? ISSUE_CONTEXT.map(e => `- ${e.task}: ${e.critique}`).join('\n') : 'No prior work on this issue'}

### Recommendations
1. ${TOP_PATTERN ? `Follow: "${TOP_PATTERN.approach}"` : 'No strong patterns found - document your approach'}
2. ${TOP_ANTI_PATTERN ? `Avoid: "${TOP_ANTI_PATTERN.approach}"` : 'No known anti-patterns for this type'}
```

## Example Output

```markdown
## Memory Context for PROJ-123

### Issue Classification
- **Type:** UI_DISPLAY
- **Command:** implement

### Successful Patterns (apply these)
| Score | Approach |
|-------|----------|
| 0.95 | "Write Playwright test first, use existing design system components" |
| 0.88 | "Check Figma design tokens before custom styles, test mobile viewport" |

### Anti-Patterns (avoid these)
| Score | What Failed |
|-------|-------------|
| 0.15 | "Skipped mobile viewport testing - test timeout on CI" |
| 0.22 | "Used inline styles - accessibility audit failed" |

### Issue History
No prior work on this issue

### Recommendations
1. Follow: "Write Playwright test first, use existing design system components"
2. Avoid: Inline styles (caused failures in similar issues)
```

## Graceful Degradation

If AgentDB is unavailable:

```markdown
## Memory Context for ${ISSUE_KEY}

⚠️ **AgentDB unavailable** - Proceeding without historical patterns.

### Fallback Recommendations
1. Follow TDD approach (write tests first)
2. Use existing patterns in codebase
3. Document your approach for future sessions
```

## Integration with session-init

In `session-init.skill.md`, add memory loading:

```markdown
## 0.1 Memory Context Loading

**Load patterns and anti-patterns for command guidance:**

Invoke memory-load with:
- issue_key: from command args
- command: current command name
- scope: from configuration matrix (see below)

| Command | Scope |
|---------|-------|
| /work, /loop:* | full |
| /implement, /plan | issue-patterns |
| /fix-pr, /resolve-pr | issue-only |
```

## Anti-Patterns

- **Loading without using** - Don't load patterns then ignore them
- **Over-relying on patterns** - They're guidance, not rules
- **Skipping for speed** - Memory load is fast and high value
- **Not classifying issues** - Issue type improves pattern matching
