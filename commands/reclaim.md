<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->
<!-- The orchestrator (Opus) reads this directive and delegates. Actual work runs on Haiku. -->

---
description: Clean up errant processes on macOS - kills zombies, orphaned Claude sessions, stale dev servers, and other memory hogs
---

# Reclaim: macOS Process Cleanup

Analyzes running processes and kills orphaned/stale processes to reclaim memory.

## Target Process Categories

### 1. Zombie Processes
Processes in Z state that are defunct but not reaped.

### 2. Playwright/Chromium Test Processes
Orphaned browser instances from test runs:
- `Google Chrome for Testing`
- Playwright-spawned Chromium processes

### 3. Stale Development Servers
Dev servers left running from previous sessions:
- Vite dev servers (`node .*/vite`)
- Esbuild service processes (`esbuild --service`)
- Webpack dev servers

### 4. Orphaned Claude Session Artifacts
Processes spawned by previous Claude Code sessions:
- MCP inspector processes
- Orphaned `tail -f` on task output files
- Stale npx processes

### 5. Stale Terraform Providers
Terraform provider processes that weren't cleaned up:
- `terraform-provider-*`

### 6. Orphaned Test Runners
Test processes that didn't terminate:
- `vitest`
- `jest`
- `playwright`

## Execution Steps

### Step 1: Analyze Current State

Run these commands to assess the situation:

```bash
# System memory overview
top -l 1 -s 0 | head -10

# Count processes by category
echo "=== Zombie processes ===" && ps aux | awk '$8 ~ /Z/ {print}' | wc -l
echo "=== Playwright/Chromium Testing ===" && ps aux | grep -E "(playwright|Google Chrome for Testing)" | grep -v grep | wc -l
echo "=== Vitest ===" && ps aux | grep -i vitest | grep -v grep | wc -l
echo "=== Vite dev servers ===" && ps aux | grep -E "node.*vite" | grep -v grep | wc -l
echo "=== Esbuild services ===" && ps aux | grep -E "esbuild.*service" | grep -v grep | wc -l
echo "=== MCP inspector ===" && ps aux | grep "mcp-inspector" | grep -v grep | wc -l
echo "=== Terraform providers ===" && ps aux | grep "terraform-provider" | grep -v grep | wc -l
echo "=== Orphaned tail ===" && ps aux | grep -E "tail.*claude.*tasks" | grep -v grep | wc -l
```

### Step 2: Show Top Memory Consumers

```bash
ps aux -m | head -25
```

### Step 3: Identify Stale Processes (Older Than Today)

Look for processes started on previous days that are likely orphaned:

```bash
ps aux | grep -E "(node|npx|terraform|tail|esbuild|vite)" | grep -v grep | grep -v "s000" | grep -E "(Mon|Tue|Wed|Thu|Fri|Sat|Sun|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)" | head -30
```

### Step 4: Kill by Category

Execute kills in order of safety (least impactful first):

```bash
# 1. Playwright/Chromium Testing (safe - test artifacts)
pkill -9 -f "Google Chrome for Testing" 2>/dev/null
pkill -9 -f "playwright" 2>/dev/null

# 2. Vitest orphans (safe - test runners)
pkill -f "vitest" 2>/dev/null

# 3. MCP inspector (safe - debug tools)
pkill -f "mcp-inspector" 2>/dev/null

# 4. Orphaned tail processes (safe - monitoring artifacts)
pkill -f "tail.*claude.*tasks" 2>/dev/null

# 5. Terraform providers (careful - check no terraform running)
pkill -f "terraform-provider" 2>/dev/null
```

### Step 5: Handle Stale Dev Servers (Interactive)

For vite/esbuild, ask before killing since they might be intentional:

```bash
# List them first
ps aux | grep -E "(vite|esbuild)" | grep -v grep

# If confirmed stale, kill by PID or pattern
# pkill -f "worktrees.*vite"  # Worktree dev servers
# pkill -f "esbuild.*service" # Esbuild services
```

### Step 6: Verify Cleanup

```bash
echo "=== Remaining processes ==="
ps aux | grep -E "(playwright|vitest|mcp-inspector|terraform-provider)" | grep -v grep | wc -l

echo "=== Memory after cleanup ==="
top -l 1 -s 0 | grep PhysMem
```

## Quick Mode (Non-Interactive)

For immediate cleanup of all safe categories, run the script:

```bash
$PROJECT_ROOT/agents/scripts/reclaim.sh
```

Or with force mode (no prompts):

```bash
$PROJECT_ROOT/agents/scripts/reclaim.sh --force
```

## Output

After running, report:
1. Number of processes killed per category
2. Memory before and after
3. Any processes that couldn't be killed
4. Remaining suspicious processes that need manual review

## Safety Notes

- **Never kill** processes attached to current terminal (s000, s001, etc.)
- **Never kill** the current Claude session processes
- **Ask before** killing vite/esbuild if they might be intentional dev servers
- **Check first** if terraform is actively running before killing providers
