---
description: Run workstation readiness check — diagnose and fix configuration issues
arguments:
  - name: flags
    description: "Optional: --dry-run, --json, --verbose, --category <name>"
    required: false
---

# Workstation Readiness Check (rx)

Run the rx diagnostic to verify and fix your workstation setup for the platform project.

## Automatic Fixes

The rx command can automatically detect and fix:
- Stuck agent teams with in-process backend bug
- Large debug logs from infinite polling loops
- Merged git worktrees that should be removed
- Missing configuration files
- Outdated dependencies

## Execute

```bash
npx tsx ~/.claude/skills/rx/rx.ts $ARGUMENTS.flags
```

## Post-Check

Review the output. If any checks show `[FAIL]`:
1. Follow the error message instructions
2. Re-run `/rx` to verify the fix
3. Report persistent failures to the team

If all checks pass or are fixed, the workstation is ready for development.
