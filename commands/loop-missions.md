---
description: Loop through all 27 remaining platform missions and enrich each one sequentially
---

# Loop: Enrich All Missions

This command runs `/enrich-mission` for every mission in `project-docs/features/missions/` that still has `[FILL]` markers in its delta.md.

## Pre-flight Check

```bash
# Find missions needing enrichment
grep -rl "\[FILL\]" $PROJECT_ROOT/project-docs/features/missions/*/delta.md | sed 's|.*/\(MISSION-[0-9]*\)/.*|\1|' | sort
```

## Loop

For each mission ID found above, run:

```
/enrich-mission {MISSION_ID}
```

After each mission completes:
1. Verify zero `[FILL]` markers remain in that mission's delta.md:
   ```bash
   grep -c "\[FILL\]" $PROJECT_ROOT/project-docs/features/missions/{MISSION_ID}/delta.md
   ```
   Expected: 0
2. Verify the commit was created
3. Continue to next mission

## Completion Criteria

All 27 missions (MISSION-01 through MISSION-28 excluding MISSION-11) have:
- [ ] Zero `[FILL]` markers in delta.md
- [ ] Non-empty dataset_ids or gaps in mis.json for at least 50% of steps
- [ ] Numeric token cost estimates (not "unknown")
- [ ] One git commit per mission

## After All Missions Complete

Run:
```
/generate-mothership-roadmap
```
