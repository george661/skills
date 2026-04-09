<!-- MODEL_TIER: sonnet -->
---
description: Evaluate release readiness of the platform codebase. Produces a per-repo and aggregate GO/NO-GO determination using confidence scoring across Concourse CI, Bitbucket, and Jira gates.
arguments: []
---

# Release Readiness Assessment

Evaluates whether the platform codebase is safe to deploy to production. Checks all CI gates,
open PRs, and in-flight Jira work per production-deploying repository. Produces a
machine-readable output with a GO/NO-GO determination backed by a confidence score.

**Threshold**: ≥85% confidence = GO. Below = NO-GO.

---

## Production Repository Registry

These are the repos that deploy to production. Every one must be evaluated individually.

| Repo | Concourse Deploy Jobs | Notes |
|------|-----------------------|-------|
| `lambda-functions` | `deploy-*-prod`, `validate-*-prod`, `promote-to-prod` | Lambda functions |
| `frontend-app` | `deploy-prod`, `validate-prod` | Frontend marketplace |
| `auth-service` | `deploy-prod`, `validate-prod` | Auth Lambdas |
| `core-infra` | `terraform-apply-prod`, `promote-to-prod` | Infrastructure |
| `migrations` | `deploy-prod` | Database migrations |
| `sdk` | `publish` | Publisher SDK (npm) |
| `mcp-server` | `deploy-prod`, `validate-prod` | MCP server |
| `dashboard` | `build-and-deploy` | Internal dashboard |
| `bootstrap` | `apply-prod` | Infrastructure bootstrap |
| `query-proxy` | `deploy-dev` (dev-only currently) | Query proxy service |
| `go-common` | `publish-artifact` | Shared Go library |

---

## Phase 0: Gather Data (Run All in Parallel)

Spawn four parallel data-gathering tasks simultaneously using the Agent tool.

### Task A — Concourse Pipeline Status

Single call covering all production pipelines (same script used by `/pipeline-health`):

```bash
npx tsx .claude/skills/ci/get_build_status.ts '{}'
```

Returns a JSON array — one entry per pipeline — with fields already classified:
- `pipeline`, `role` (`prod` or `e2e`), `paused`
- `deploy_jobs[]` — each with `name`, `status`, `started_at`, `finished_at`, `url`
- `pr_gate_jobs[]` — same shape; advisory only, excluded from scoring unless cross-repo blocker
- `in_flight_count` — jobs currently `started` across all types
- `error` — present only if the pipeline was not found

**Post-processing the result:**
1. Skip any entry where `paused: true` — paused pipelines are excluded from health scoring
2. Skip any entry where `error` is set — flag as unknown, not a failure
3. For Gate 1 scoring, evaluate only `deploy_jobs` statuses (`failed`, `errored`, `aborted` = failure)
4. Jobs with status `started` count as in-flight, not failures
5. For Gate 4, use only the entry where `role === "e2e"`

### Task B — Bitbucket PR Status

Run a single call that covers all repos at once (same script used by `/status-prs`):

```bash
npx tsx .claude/skills/bitbucket/pr_status.ts '{}'
```

This returns a JSON array of PRs across all repos. Each entry includes:
- `repo`, `pr_id`, `title`, `draft`, `author`, `source_branch`, `destination_branch`, `url`
- `commits_behind` — how many commits the branch is behind the target
- `build_status` — `SUCCESSFUL`, `FAILED`, `INPROGRESS`, or `NO_BUILDS`
- `build_url` — link to the CI build (if available)

**Post-processing the result:**
1. Filter to only the production repos listed in the registry above
2. Exclude any entry where `draft: true` — draft PRs are ignored entirely
3. Extract Jira issue key(s) from `source_branch` (pattern: `[A-Z]+-\d+`) or `title`
4. Use `build_status` as the CI gate value; `NO_BUILDS` = no CI run, `FAILED` = CI failure
5. Cross-repo dependency check: match extracted Jira keys against in-flight issues from Task C

Also check for zombie pipelines (per production repo):

```bash
npx tsx .claude/skills/bitbucket/list_pipelines.ts '{"repo_slug": "REPO_NAME", "page": 1}'
```

Flag any pipeline stuck in `IN_PROGRESS` for >24 hours.

### Task C — Jira In-Flight Issues

Single call covering both JQL queries (same script used by `/jira-blockers`):

```bash
npx tsx .claude/skills/jira/jira_blockers.ts '{}'
```

Returns a fixed-schema JSON object with four pre-classified lists:
- `critical_in_progress` — Highest/Blocker/Critical issues currently In Progress/In Review/Validation
- `critical_not_started` — Highest/Blocker/Critical issues that exist but are not in progress
- `in_flight_all` — all in-flight issues (any priority); use for the cross-repo PR dependency check
- `needs_human` — subset of in_flight_all labeled `needs-human` or `blocked`

**Gate 3 scoring only considers bugs.** Filter both `critical_in_progress` and `critical_not_started`
to issues where `issuetype = Bug` OR labels contain `bug`, `severity-critical`, or `severity-high`.
Feature work, infrastructure tasks, and planned enhancements in To Do/Backlog/Grooming do NOT count.

- 0 critical bugs in progress + 0 critical bugs not started → 25
- 0 in progress, >0 critical bugs not started (unresolved/open) → 15
- 1 critical bug actively In Progress → 5
- 2+ critical bugs actively In Progress → 0

### Task D — Prod Release Gate Status

Check the `prod-release/check-readiness` job directly:

```bash
fly -t ${CI_TARGET} builds -j prod-release/check-readiness --count 1 2>&1
```

Or via the Concourse API skill:

```bash
npx tsx .claude/skills/ci/get_build_status.ts '{"pipeline": "prod-release", "job": "check-readiness"}'
```

Returns the most recent build for the `check-readiness` job with fields: `status`, `start_time`, `end_time`.

**Post-processing:**
1. Extract the build number from the fly output (column 3, format `pipeline/job/N` — take `N`)
2. Construct the build URL: `https://ci.dev.example.com/teams/main/pipelines/prod-release/jobs/check-readiness/builds/{N}`
3. `status` values: `succeeded`, `failed`, `errored`, `aborted`, `started` (in-flight)
4. If job has never run: treat as `unknown`, score 0 for Gate 6
5. If `status == "started"`: job is running, score 8 for Gate 6
6. If `status == "failed"` or `"errored"`: fetch the build log via `fly -t ${CI_TARGET} watch --job prod-release/check-readiness --build <N>` to identify which repos have missing/invalid BOMs — include this detail in the blocking_issues list
7. Log output format to parse: `REPO STATUS RESULT` table — extract any `FAIL` rows
8. Always emit the constructed URL in the machine-readable block `prod_release_gate.build_url` field

---

## Phase 1: Evaluate Each Production Repo

For each repo in the production registry, determine its individual readiness status.

### Per-Repo Status Criteria

A repo is **READY** when ALL of the following are true:
1. Its deploy and validate jobs all succeeded in the most recent run (or are currently running)
2. There are no open PRs for that repo that contain changes required by another
   in-flight release item (see cross-repo dependency check below)

A repo is **DEGRADED** when:
- 1 deploy or validate job failed in the most recent run

A repo is **BLOCKED** when:
- 2+ deploy or validate jobs failed, OR
- terraform-apply-prod / promote-to-prod failed

**PR-gate jobs (`pr-validate`, `pr-check`, `pr-build-*`) do NOT affect a repo's status
unless a cross-repo dependency exists (see below).**

### Cross-Repo Dependency Check

An open PR becomes a release blocker only when it represents a change that another
repo's release depends on. Evaluate each open PR as follows:

1. **Identify the PR's Jira issue(s)** from the branch name or PR title
2. **Check if the issue is in-flight** (In Progress, Validation, or has `step:implementing`)
3. **Check if any other in-flight issue in another repo depends on this change** —
   e.g., a frontend change that requires a backend field that is still in a PR

If a dependency exists: the open PR is a **cross-repo release blocker** and the
dependent repo is also marked BLOCKED.

If no dependency exists: the open PR is advisory only. The `pr-validate` failure on
that PR does not affect the release readiness score.

---

## Phase 2: Score Each Gate

### Gate 1 — Deploy Pipeline Health (30 points)

Count how many production repos have DEGRADED or BLOCKED deploy/validate job status.
Only evaluate `deploy-*`, `validate-*`, `terraform-apply-*`, `promote-to-*`,
`publish*`, `build-and-deploy`, `apply-*` jobs.

| Condition | Points |
|-----------|--------|
| All production repos: all deploy/validate jobs green | 30 |
| 1 repo has a failed deploy/validate job | 20 |
| 2 repos have failed deploy/validate jobs | 10 |
| 3+ repos have failed deploy/validate jobs | 0 |

Jobs currently `started` do not count as failures.
Paused/deprecated pipelines are excluded.

### Gate 2 — Cross-Repo PR Dependencies (15 points)

Only non-draft PRs are considered. Draft PRs are excluded entirely.

| Condition | Points |
|-----------|--------|
| No open non-draft PRs in any production repo | 15 |
| Open non-draft PRs exist, none are cross-repo release blockers, all have CI passing | 12 |
| Open non-draft PRs exist, none are cross-repo release blockers, some have no CI run | 8 |
| Open non-draft PRs exist, none are cross-repo release blockers, some have CI failures | 4 |
| 1+ open non-draft PRs are cross-repo release blockers | 0 |

### Gate 3 — No Critical Bug Blockers (25 points)

Only **bugs** count for this gate. Filter to issues where `issuetype = Bug` OR labels contain
`bug`, `severity-critical`, or `severity-high`. Feature work, infrastructure tasks, and
planned enhancements (regardless of priority) do NOT affect this gate.

| Condition | Points |
|-----------|--------|
| Zero open Highest/Critical bugs | 25 |
| Open Highest/Critical bugs exist but none actively In Progress | 15 |
| 1 open Highest/Critical bug actively In Progress | 5 |
| 2+ open Highest/Critical bugs actively In Progress | 0 |

Issues labeled `needs-human` or `blocked` in Validation do not count unless
they are bugs carrying Highest/Critical priority.
GROOMING and BACKLOG issues do not count regardless of priority or type.

### Gate 4 — E2E Test Health (15 points)

Check `e2e-tests` Concourse pipeline job statuses.

| Condition | Points |
|-----------|--------|
| All domain test jobs green or currently running | 15 |
| 1-2 domain jobs failing, smoke-test passing | 10 |
| Smoke-test failing or 3+ domain jobs failing/aborted | 0 |

### Gate 5 — Demo Environment Stable (5 points)

Check `core-infra` `terraform-apply-demo` job status. This gate is intentionally weighted lower
because Gate 6 (BOM readiness) provides a more authoritative signal about demo deployment health.

| Condition | Points |
|-----------|--------|
| terraform-apply-demo last build succeeded | 5 |
| terraform-apply-demo currently running | 3 |
| terraform-apply-demo failed with no active retry | 0 |

### Gate 6 — Prod Release Gate (10 points)

Check `prod-release/check-readiness` job. This job reads BOM files for all production repos from
S3 (`deployments/{repo}/demo/latest.json`) and verifies `build.status == "succeeded"` for each.
A failing gate means one or more repos are not demo-deployed and ready for prod.

| Condition | Points |
|-----------|--------|
| check-readiness last build succeeded | 10 |
| check-readiness currently running | 8 |
| check-readiness failed, 1 repo with missing/invalid BOM | 5 |
| check-readiness failed, 2+ repos with missing/invalid BOMs | 0 |
| check-readiness has never run (no builds) | 0 |

**If Gate 6 fails:** include the specific failing repos in `blocking_issues`. Parse the job log
output (from Task D) for `FAIL` rows in the readiness table — each failing repo is a distinct
blocking item that must be resolved before a prod release.

---

## Phase 3: Compute Confidence and Verdict

```
total_score = gate1 + gate2 + gate3 + gate4 + gate5 + gate6  (max 100)
  gate1 max = 30
  gate2 max = 15
  gate3 max = 25
  gate4 max = 15
  gate5 max = 5
  gate6 max = 10
confidence  = total_score / 100.0
```

**Decision rule:**
- `confidence >= 0.85` → **GO**
- `confidence < 0.85`  → **NO-GO**

---

## Phase 4: Emit Structured Output

Output the machine-readable block first, then the human-readable summary.

### Machine-Readable Block

```
RELEASE_READINESS_ASSESSMENT
timestamp: <ISO-8601>
verdict: <GO|NO-GO>
confidence: <0.00-1.00>
repos:
  lambda-functions:
    status: <READY|DEGRADED|BLOCKED>
    deploy_jobs: <all-green|failed: [job names]|running: [job names]>
    open_prs: <none|[PR#, title, ci_status, cross_repo_blocker: true/false]>
  frontend-app:
    status: <READY|DEGRADED|BLOCKED>
    deploy_jobs: <all-green|failed: [job names]|running: [job names]>
    open_prs: <none|[PR#, title, ci_status, cross_repo_blocker: true/false]>
  auth-service:
    status: <READY|DEGRADED|BLOCKED>
    deploy_jobs: <all-green|failed: [job names]|running: [job names]>
    open_prs: <none>
  core-infra:
    status: <READY|DEGRADED|BLOCKED>
    deploy_jobs: <all-green|failed: [job names]|running: [job names]>
    open_prs: <none>
  migrations:
    status: <READY|DEGRADED|BLOCKED>
    deploy_jobs: <all-green|failed: [job names]|running: [job names]>
    open_prs: <none>
  sdk:
    status: <READY|DEGRADED|BLOCKED>
    deploy_jobs: <all-green|failed: [job names]|running: [job names]>
    open_prs: <none>
  mcp-server:
    status: <READY|DEGRADED|BLOCKED>
    deploy_jobs: <all-green|failed: [job names]|running: [job names]>
    open_prs: <none>
  dashboard:
    status: <READY|DEGRADED|BLOCKED>
    deploy_jobs: <all-green|failed: [job names]|running: [job names]>
    open_prs: <none>
  bootstrap:
    status: <READY|DEGRADED|BLOCKED>
    deploy_jobs: <all-green|failed: [job names]|running: [job names]>
    open_prs: <none>
  query-proxy:
    status: <READY|DEGRADED|BLOCKED>
    deploy_jobs: <all-green|failed: [job names]|running: [job names]>
    open_prs: <none>
  go-common:
    status: <READY|DEGRADED|BLOCKED>
    deploy_jobs: <all-green|failed: [job names]|running: [job names]>
    open_prs: <none>
gates:
  deploy_pipeline_health:
    score: <0|10|20|30>
    max: 30
    pass: <true|false>
    degraded_repos: [list]
    blocked_repos: [list]
  cross_repo_pr_dependencies:
    score: <0|5|10|15|20>
    max: 20
    pass: <true|false>
    open_prs: [list of repo/PR# with draft status, ci_status, and cross_repo_blocker flag]
    draft_prs_excluded: [list of draft PRs that were ignored]
  critical_jira_blockers:
    score: <0|5|15|25>
    max: 25
    pass: <true|false>
    blocking_issues: [list of issue keys]
  e2e_health:
    score: <0|10|15>
    max: 15
    pass: <true|false>
    failing_jobs: [list]
    aborted_jobs: [list]
  demo_environment:
    score: <0|3|5>
    max: 5
    pass: <true|false>
    terraform_status: <succeeded|running|failed>
  prod_release_gate:
    score: <0|5|8|10>
    max: 10
    pass: <true|false>
    check_readiness_status: <succeeded|running|failed|unknown>
    failing_repos: [list of repo names with missing or invalid BOMs]
    build_number: <N>
    build_url: <url>
blocking_issues:
  - <specific items that must be resolved before GO>
END_RELEASE_READINESS_ASSESSMENT
```

### Human-Readable Summary

After the machine block, output:

```
## Release Readiness: <GO ✅ | NO-GO ❌>
**Confidence: X%** (threshold: 85%)

### Per-Repo Status

| Repo | Deploy Jobs | Open PRs | Cross-Repo Dep? | Status |
|------|------------|----------|-----------------|--------|
| lambda-functions | ✅ all green | none | — | READY |
| frontend-app | ✅ all green | PR#708 (CI ❌) | no | READY* |
| auth-service | ✅ all green | none | — | READY |
| core-infra | ✅ all green | none | — | READY |
| migrations | ✅ all green | none | — | READY |
| sdk | ✅ all green | none | — | READY |
| mcp-server | ✅ all green | none | — | READY |
| dashboard | ✅ all green | none | — | READY |
| bootstrap | ✅ all green | none | — | READY |
| query-proxy | ✅ all green | none | — | READY |
| go-common | ✅ all green | none | — | READY |

*READY with advisory: open PR exists but is not a release dependency

### Gate Scores

| Gate | Score | Max | Status |
|------|-------|-----|--------|
| Deploy Pipeline Health | X | 30 | ✅/❌ |
| Cross-Repo PR Dependencies | X | 15 | ✅/❌ |
| Critical Jira Blockers | X | 25 | ✅/❌ |
| E2E Test Health | X | 15 | ✅/❌ |
| Demo Environment | X | 5 | ✅/❌ |
| Prod Release Gate | X | 10 | ✅/❌ |
| **Total** | **X** | **100** | **GO/NO-GO** |

### Blocking Items
<bullet list, or "None — all gates passed.">

### Advisory Items (Non-Blocking)
<open PRs with no cross-repo dependency, pr-validate failures, zombie pipelines, stale issues>
```

---

## Notes for Agent Consumers

- Parse between `RELEASE_READINESS_ASSESSMENT` and `END_RELEASE_READINESS_ASSESSMENT`
- `verdict` is the authoritative GO/NO-GO signal
- `repos` block gives per-repo drill-down; check `status` field per repo
- `blocking_issues` is the minimum set of items to resolve for a GO
- Draft PRs are excluded entirely — they do not appear in scoring, advisory, or the
  per-repo table; they are listed only in `draft_prs_excluded` for transparency
- PR-gate failures (`pr-validate`, `pr-check`) appear only in advisory unless
  `cross_repo_blocker: true`; agents should not treat them as blockers otherwise
- `confidence` is a float (0.00–1.00); all gate scores are integers
- Gate 6 (`prod_release_gate`) is the BOM-readiness check: it verifies every repo has a
  `build.status == "succeeded"` BOM at `deployments/{repo}/demo/latest.json` in S3.
  A Gate 6 failure means one or more repos' demo deployment BOMs are missing or malformed.
  Each failing repo is listed in `prod_release_gate.failing_repos` and in `blocking_issues`.
- Gate scores total: gate1(30) + gate2(15) + gate3(25) + gate4(15) + gate5(5) + gate6(10) = 100

---

## Phase 5: Next Step Suggestion

After emitting the human-readable summary, append one of the following based on the verdict:

**When verdict is GO:**

```
---
**Ready to ship.** Run `/release-prod` to trigger the production release pipeline and generate release notes.
```

**When verdict is NO-GO:**

```
---
**Not ready to ship.** Resolve the blocking items above, then re-run `/release-ready` to re-evaluate.
```
