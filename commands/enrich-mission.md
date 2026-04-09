---
description: Enrich a single mission's delta doc and MIS with dataset gap analysis, HITL logic, and ODEF delta
args:
  - name: MISSION_ID
    required: true
    description: "e.g. MISSION-01"
---

# Mission Enrichment: $MISSION_ID

You are enriching the Mission Integration Sheet and delta documentation for $MISSION_ID.

## Context Files to Read First

1. `$PROJECT_ROOT/project-docs/features/missions/$MISSION_ID/delta.md` — skeleton to fill
2. `$PROJECT_ROOT/project-docs/features/missions/$MISSION_ID/mis.json` — MIS to update
3. `$PROJECT_ROOT/project-docs/features/m11-complete-spike-package.md` — M-11 baseline (dataset mapping pp. 20-46, step contracts pp. 47-82)
4. `$PROJECT_ROOT/project-docs/features/mission-dataset-mapping.md` — platform dataset inventory
5. `$PROJECT_ROOT/project-docs/features/osint_mission_taxonomy.json` — canonical step definitions

## Your Task

For each step in the $MISSION_ID workflow, fill in the `[FILL]` sections of delta.md:

### 1. Dataset Gap Analysis (delta.md — Dataset Source Mapping section)

For each step:
- Which platform datasets (from mission-dataset-mapping.md) serve this step?
- What data sources are missing from the platform inventory?
- What are the closest alternatives available?
- Estimated token cost (low = 0-15 tokens, medium = 15-50, high = 50-100+)

### 2. HITL Decision Logic (delta.md — HITL Decision Logic section)

For each decision point in the MIS:
- When exactly does this fire? (specific trigger condition)
- What data must the decision card display to the user?
- What are the user's options and consequences of each?
- How does the LangGraph routing change based on the decision?

If the mission has no HITL points, mark the section "N/A — no HITL decision points for this mission."

### 3. ODEF Entity Delta (delta.md — ODEF Entity Delta section)

Compare this mission's domain against M-11's entity types (person, organization, location, document, financial):
- What new entity types does this mission discover?
- What new relationship types?
- Examples: M-21 CTI adds domain, ip_address, malware_family, vulnerability, threat_actor

### 4. Platform Gaps Unique to This Mission

Identify gaps that do NOT appear in M-11's gap analysis (Resolution Paths section of spike package).

### 5. Token Cost Model

Estimate total token cost for basic and enhanced tiers based on dataset pricing from mission-dataset-mapping.md.

## Output

1. Edit `$PROJECT_ROOT/project-docs/features/missions/$MISSION_ID/delta.md` — replace ALL `[FILL]` markers with concrete content
2. Edit `$PROJECT_ROOT/project-docs/features/missions/$MISSION_ID/mis.json` — update:
   - `datasets[].dataset_ids` — real dataset IDs from the platform inventory
   - `datasets[].gaps` — list of missing datasets
   - `datasets[].token_cost_estimate` — "low" | "medium" | "high" (not "unknown")
   - `token_estimates.basic_range` and `enhanced_range` — numeric estimates
3. Commit:
```bash
cd $PROJECT_ROOT/project-docs
git add features/missions/$MISSION_ID/
git commit -m "enrich $MISSION_ID: dataset gaps, HITL logic, ODEF delta"
```

## Validation Criteria

Before marking this task complete:
- [ ] Zero `[FILL]` markers remain in delta.md
- [ ] Every step in the MIS has at least one `dataset_id` OR a non-empty `gaps` entry
- [ ] HITL section is filled or explicitly marked N/A
- [ ] ODEF entity delta has concrete entity types (not placeholder text)
- [ ] `token_cost_estimate` values are "low", "medium", or "high" (not "unknown")
- [ ] `token_estimates` basic_range and enhanced_range contain numeric estimates
- [ ] Commit created with the message format above
