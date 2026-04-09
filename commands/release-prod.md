<!-- MODEL_TIER: sonnet -->
---
description: Trigger the prod-release Concourse pipeline to deploy all repositories to production, then generate release notes.
arguments: []
---

# Release to Production

Triggers the `prod-release/release-to-prod` Concourse job, monitors the build to completion, and then invokes `/release-notes` to document the release.

**Only run this command when `/release-ready` has produced a GO ✅ verdict.**

---

## Phase 1: Pre-Flight Check

Before triggering, verify the `prod-release/check-readiness` job last succeeded:

```bash
npx tsx .claude/skills/ci/get_build_status.ts '{"pipeline": "prod-release", "job": "check-readiness"}'
```

If the last `check-readiness` build is not `succeeded`:
- Print: `❌ Pre-flight check failed: prod-release/check-readiness is not green. Run /release-ready to diagnose.`
- **Stop. Do not proceed.**

If `check-readiness` is `succeeded`, print:
```
✅ Pre-flight check passed — check-readiness is green
Triggering prod-release/release-to-prod...
```

---

## Phase 2: Trigger the Release

Trigger the `release-to-prod` job:

```bash
npx tsx .claude/skills/ci/trigger_build.ts '{"pipeline_name": "prod-release", "job_name": "release-to-prod", "watch": false}'
```

Extract the build number from the output (format: `started build N`). Construct the build URL:

```
https://ci.dev.example.com/teams/main/pipelines/prod-release/jobs/release-to-prod/builds/{N}
```

Print:
```
🚀 Release triggered — build #{N}
   URL: {build_url}
   Monitoring...
```

---

## Phase 3: Monitor the Build

Watch the build until completion:

```bash
npx tsx .claude/skills/ci/get_build_logs.ts '{"build_id": {N}}'
```

Stream the output as it arrives. The `release-to-prod` job runs ~15 minutes and deploys all production repositories sequentially.

**On success** (`succeeded`):
```
✅ prod-release/release-to-prod #{N} succeeded
   Deployed at: {timestamp}
   Build: {build_url}
```

**On failure** (`failed`, `errored`, `aborted`):
```
❌ prod-release/release-to-prod #{N} {status}
   Build: {build_url}
```

- Parse the build output for the first failing job/step.
- Print the failing repo and step name.
- Print: `Run /fix-pipeline to diagnose.`
- **Stop. Do not invoke /release-notes.**

---

## Phase 4: Generate Release Notes

Invoke the release notes command to document what shipped:

```
/release-notes
```

The `/release-notes` command will automatically determine the date range from the last release and generate a formatted document in `project-docs/operations/releases/`.
