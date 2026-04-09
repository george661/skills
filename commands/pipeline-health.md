<!-- MODEL_TIER: haiku -->
<!-- DISPATCH: Spawn a Task subagent with model: "haiku" to execute this command. -->

---
description: Show deploy/validate job health across all production Concourse pipelines
---

# Pipeline Health Dashboard

## Step 1: Fetch Pipeline Health

```bash
npx tsx .claude/skills/ci/get_build_status.ts '{}'
```

## Step 2: Present Results

Parse the JSON array and display a formatted summary.

### Status Icons

| status | Icon |
|--------|------|
| succeeded | ✅ |
| started | 🔄 |
| failed | ❌ |
| errored | ❌ |
| aborted | ⚠️ |
| no_build | ⚫ |

### Classification

- `deploy_jobs` — jobs that deploy or validate to production; these drive health scoring
- `pr_gate_jobs` — PR-validation jobs; shown as advisory only
- `in_flight_count` — jobs currently running across all types
- Pipelines with `paused: true` show ⏸️ and are excluded from health scoring

### Output Format

```
Pipeline Health  ({prod_count} prod, e2e-tests gate)
══════════════════════════════════════════════════

❌ FAILURES ({count} pipelines)

  [{pipeline}]
    {job_name}  ❌ {status}  {url}
    {job_name}  ✅ succeeded

  ...

⏸️ PAUSED ({count} pipelines — excluded from scoring)
  {pipeline}  ...

✅ ALL GREEN ({count} pipelines)
  lambda-functions  frontend-app  auth-service  core-infra  migrations
  sdk  mcp-server  dashboard  bootstrap
  query-proxy  go-common

e2e-tests  (Gate 4)
  {job_name}  ✅/❌  {url}
  ...

──────────────────────────────────────────────────
Summary: {blocked} blocked, {degraded} degraded, {all_green} all green, {paused} paused
```

Where:
- **blocked** = 2+ deploy jobs failed in the same pipeline, or terraform-apply-prod / promote-to-prod failed
- **degraded** = exactly 1 deploy job failed
- **all_green** = all deploy jobs succeeded or are in-flight

If no failures, output the summary line only: "All {count} pipelines green."
```
