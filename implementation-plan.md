## REVISED IMPLEMENTATION PLAN (v2)

### Changes from v1:

1. **Critical Fix 1 — NDJSON path threading made explicit:** Step 7 expanded from "confirm" to mandatory code changes. Added explicit EventEmitter constructor update in cli.py to write `{events_dir}/{run_id}.ndjson` flat (not nested), added `--events-dir` CLI flag + `DAG_EVENTS_DIR` env var, and updated trigger.py subprocess spawn to pass `settings.events_dir` via env var. Added test case asserting flat NDJSON path appears during workflow execution.

2. **Critical Fix 2 — RunStatus.CANCELLED verification:** Removed instruction to "add RunStatus.CANCELLED to queries.py:147". Replaced with "verify RunStatus.CANCELLED already exists in models.py:23" and "use existing enum in event_collector.py workflow_cancelled handler". Path reference corrected.

3. **Warning 3 addressed — 1s polling included in scope:** Added background asyncio task in Step 21 to poll marker every 1s during any subprocess execution, not just at layer boundaries. This ensures ≤5s transition even for long-running nodes (e.g., 5-minute bash timeout). AC test scoped to universal node durations, not just short nodes.

4. **Warning 4 clarified — skill.py refactor explicit:** Step 16 already covered skill.py, but Known Risks section updated to explicitly note both bash.py:68 and skill.py:49 require subprocess.run → Popen+communicate refactor with TimeoutExpired handling preserved.

**Repository:** skills (george661/skills)  
**Worktree:** `/Users/patrick.henry/dev/gw/worktrees/skills/GW-5186-cancel-endpoint`  
**Branch:** `GW-5186/cancel-endpoint`
