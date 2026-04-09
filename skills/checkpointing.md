# Workflow Checkpointing

Filesystem-based checkpointing for resumable workflows.

## Purpose

Save workflow state at key points so work can resume after:
- Session timeouts
- Network failures
- Manual interruptions
- Cost guardrail pauses

## Commands

```bash
# Save checkpoint
python3 .claude/hooks/checkpoint.py save PROJ-123 phase2 '{"branch":"PROJ-123-feature","worktree":"/path","tests_passing":true}'

# Load most recent checkpoint for issue
python3 .claude/hooks/checkpoint.py load PROJ-123

# Load specific phase
python3 .claude/hooks/checkpoint.py load PROJ-123 phase2

# List all checkpoints for issue
python3 .claude/hooks/checkpoint.py list PROJ-123

# Clear checkpoints after completion
python3 .claude/hooks/checkpoint.py clear PROJ-123

# System status
python3 .claude/hooks/checkpoint.py status

# Cleanup expired (>7 days)
python3 .claude/hooks/checkpoint.py cleanup
```

## When to Checkpoint

| Trigger | Phase | Data to Save |
|---------|-------|--------------|
| After plan created | `plan` | issue, repo, branch, plan summary |
| After worktree created | `worktree` | branch, path, base commit |
| After tests written | `tests` | test files, coverage target |
| After implementation | `impl` | changed files, test results |
| After PR created | `pr` | PR number, branch, reviewers |
| After merge | `merged` | merge commit, cleanup status |

## Integration Pattern

### In Command Markdown

```markdown
## Phase 2: Implementation

### Check for Existing Checkpoint
\`\`\`bash
checkpoint=$(python3 .claude/hooks/checkpoint.py load $ISSUE phase2 2>/dev/null)
if echo "$checkpoint" | jq -e '.found == true' > /dev/null; then
  echo "Resuming from checkpoint..."
  branch=$(echo "$checkpoint" | jq -r '.checkpoint.data.branch')
  worktree=$(echo "$checkpoint" | jq -r '.checkpoint.data.worktree')
fi
\`\`\`

### Save Progress
\`\`\`bash
python3 .claude/hooks/checkpoint.py save $ISSUE phase2 "$(jq -n \
  --arg branch "$branch" \
  --arg worktree "$worktree" \
  --arg tests "passing" \
  '{branch: $branch, worktree: $worktree, tests: $tests}'
)"
\`\`\`
```

### In TypeScript/Code

```typescript
// Check for resume point
const checkpoint = await exec(`python3 .claude/hooks/checkpoint.py load ${issue} impl`);
const state = JSON.parse(checkpoint);

if (state.found) {
  console.log(`Resuming from ${state.checkpoint.phase}, age: ${state.age_hours}h`);
  return state.checkpoint.data;
}

// Save checkpoint after expensive operation
await exec(`python3 .claude/hooks/checkpoint.py save ${issue} impl '${JSON.stringify({
  branch,
  files_changed: changedFiles,
  tests_status: 'passing'
})}'`);
```

## Configuration

Environment variables:

```bash
# Checkpoint storage location (default: /tmp/checkpoints)
CHECKPOINT_DIR=/tmp/checkpoints

# Time-to-live in hours (default: 168 = 7 days)
CHECKPOINT_TTL_HOURS=168

# Max checkpoints per issue (default: 10)
MAX_CHECKPOINTS=10
```

## Checkpoint Data Structure

```json
{
  "issue": "PROJ-123",
  "phase": "impl",
  "data": {
    "branch": "PROJ-123-add-feature",
    "worktree": "/path/to/worktree",
    "tests_passing": true,
    "files_changed": ["src/handler.ts", "tests/handler.test.ts"]
  },
  "timestamp": "2025-01-08T11:30:00",
  "resumable": true
}
```

## Best Practices

1. **Checkpoint before external calls** - API calls, git operations, CI triggers
2. **Include enough context to resume** - branch, paths, status flags
3. **Clear after successful completion** - avoid stale state
4. **Check age before resuming** - stale checkpoints may be invalid

## Expected Impact

- **Reduced re-work** after interruptions
- **Faster recovery** from failures
- **Cost savings** by not repeating completed phases
