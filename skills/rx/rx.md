---
name: rx
description: Workstation readiness diagnostic — validates and fixes developer environment setup
---

# rx — Workstation Readiness Prescription

Diagnoses and auto-fixes workstation configuration for the platform project.

## Usage

```bash
# Direct (from agents)
./scripts/rx.sh

# Via installed skill
npx tsx ~/.claude/skills/rx/rx.ts

# Flags
--dry-run     Report issues without fixing
--json        Output structured JSON instead of human-readable
--verbose     Show additional details
--category    Run only one category (prereqs, brew, repos, etc.)
```

## Check Categories

| Category | Checks |
|----------|--------|
| prereqs | node, npx, git, aws-cli, claude-cli |
| brew | Packages from config/brew-packages.json |
| repos | project repositories from config/repositories.json |
| claude-config | ~/.claude/ structure, settings.json |
| skills | Skill files installed and symlinked |
| commands | Command .md files installed |
| hooks | Hook scripts installed with +x |
| supergateway | MCP servers running |
| plugins | Claude Code plugins installed |
| credentials | AWS profiles, Jira, Bitbucket, AgentDB tokens |
| worktrees | Stale worktrees (report only) |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | All checks pass or were auto-fixed |
| 1 | At least one check failed and could not be fixed |
| 2 | Orchestrator error |

## Log

Action log at `~/.claude/rx/rx-log.jsonl` (JSONL, append-only).
Last run summary at `~/.claude/rx/last-run.json`.

## Smoke Test

1. Dry run (report only):
   ```bash
   ./scripts/rx.sh --dry-run
   ```
   Expected: All categories checked, issues reported but not fixed.

2. Full run (auto-fix):
   ```bash
   ./scripts/rx.sh
   ```
   Expected: Issues found are fixed. Unfixable issues show [FAIL] with instructions.

3. Idempotency:
   ```bash
   ./scripts/rx.sh
   ```
   Expected: Second run shows all [pass] (everything fixed in step 2 stays fixed).

4. JSON output:
   ```bash
   ./scripts/rx.sh --json | jq '.summary'
   ```
   Expected: Valid JSON with total/pass/fixed/fail/skipped counts.

5. Single category:
   ```bash
   ./scripts/rx.sh --category credentials
   ```
   Expected: Only credential checks run.
