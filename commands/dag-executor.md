<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Manage DAG executor checkpoint state - replay from checkpoints, inspect history, or view full state snapshots
arguments:
  - name: subcommand
    description: Subcommand to execute (replay|history|inspect)
    required: true
  - name: issue
    description: Issue identifier (e.g., GW-4986)
    required: true
  - name: step
    description: Step/phase name (required for replay and inspect)
    required: false
---

# DAG Executor Checkpoint Management: $ARGUMENTS.subcommand

## Overview

This command provides access to the checkpoint store for workflow state management:
- **replay**: Load a checkpoint and create a new run from that state
- **history**: List all checkpoints for a run with metadata
- **inspect**: View the full state snapshot at a specific checkpoint

All commands use the existing `hooks/checkpoint.py` CLI with AgentDB storage.

## Subcommands

### replay - Restart workflow from a checkpoint

Replay creates a new run-id with `~replay~` suffix, loads the checkpoint state at the specified step, and marks all phases after that step as cleared for re-execution. Original checkpoints are NOT modified (replay is non-destructive).

**Usage:**
```bash
python3 hooks/checkpoint.py replay <issue> <from-step> [--override=key=value ...]
```

**Example:**
```bash
# Replay GW-4986 from validation step
python3 hooks/checkpoint.py replay GW-4986 validation

# Replay with overrides
python3 hooks/checkpoint.py replay GW-4986 implementation --override=branch=feature-v2 --override=retry_count=3
```

**Output:**
```json
{
  "success": true,
  "new_run_id": "GW-4986~replay~20260415-120000",
  "parent_run_id": "GW-4986",
  "replayed_from": "validation",
  "phases_cleared": ["pr-creation", "ci-validation"],
  "overrides_applied": ["branch", "retry_count"]
}
```

### history - List all checkpoints for a run

Shows all saved checkpoints with timestamps, status, content hashes, and age. Sorted newest-first.

**Usage:**
```bash
python3 hooks/checkpoint.py history <issue> [--brief]
```

**Example:**
```bash
# Full history
python3 hooks/checkpoint.py history GW-4986

# Brief mode (no full data)
python3 hooks/checkpoint.py history GW-4986 --brief
```

**Output:**
```json
{
  "issue": "GW-4986",
  "total": 3,
  "checkpoints": [
    {
      "phase": "pr-creation",
      "timestamp": "2026-04-15T12:00:00Z",
      "age_hours": 2.5,
      "status": "running",
      "content_hash": "a1b2c3d4e5f6g7h8",
      "data_keys": ["branch", "pr_url", "ci_status"],
      "data": {...}
    },
    {
      "phase": "validation",
      "timestamp": "2026-04-15T11:00:00Z",
      "age_hours": 3.5,
      "status": "pass",
      "content_hash": "x9y8z7w6v5u4t3s2",
      "data_keys": ["tests_passed", "coverage"],
      "data": {...}
    }
  ]
}
```

### inspect - View full state at a checkpoint

Dumps the complete data snapshot for a specific checkpoint, including content hash and size metrics.

**Usage:**
```bash
python3 hooks/checkpoint.py inspect <issue> <step>
```

**Example:**
```bash
python3 hooks/checkpoint.py inspect GW-4986 validation
```

**Output:**
```json
{
  "issue": "GW-4986",
  "phase": "validation",
  "timestamp": "2026-04-15T11:00:00Z",
  "data": {
    "branch": "GW-4986-feature",
    "tests_passed": true,
    "coverage": 85.5,
    "files_changed": ["src/main.py", "tests/test_main.py"]
  },
  "content_hash": "x9y8z7w6v5u4t3s2q1p0o9n8m7l6k5j4",
  "data_size_bytes": 342,
  "resumable": true
}
```

## Integration with Workflows

These commands are designed for debugging and manual intervention:

1. **When a workflow fails mid-execution**: Use `history` to see which checkpoints exist, then `inspect` to view the state at each checkpoint.
2. **To retry from a specific point**: Use `replay` to create a new run starting from a known-good checkpoint.
3. **To modify workflow state**: Use `replay` with `--override` to inject new values or fix corrupted state.

## Requirements

- AgentDB must be available (no filesystem fallback for these commands)
- Issue must have existing checkpoints (created via `checkpoint.py save`)
- For replay: the specified step must exist in the checkpoint history

## Error Handling

All commands return JSON with an `error` field if the operation fails:
```json
{
  "error": "Checkpoint not found for issue=GW-4986, step=nonexistent"
}
```

Common errors:
- `AgentDB unavailable`: AgentDB connection failed
- `Checkpoint not found`: No checkpoint exists for the specified issue/step
- `Failed to save replay checkpoint`: AgentDB save operation failed during replay

---

**Execution:** When this command is invoked, execute the appropriate `checkpoint.py` subcommand and display the JSON output.
