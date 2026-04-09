# skills

Plug-and-play SDLC workflow skills for Claude Code. 93 commands, 286 skills, 59 hooks, 8 agents, 5 teams, and 18 scripts that give any Claude Code instance a complete software development lifecycle — from issue triage to deployment validation.

Provider-agnostic: configure your issue tracker, VCS, and CI/CD once in `.env` and every command works regardless of which combination you use.

## What You Get

**Issue lifecycle** — `/next` finds priority work, `/work PROJ-123` runs the full cycle (plan → TDD implement → PR → review), `/validate` collects post-deploy evidence.

**Epic planning** — `/plan` writes product requirements, `/groom` breaks them into issues, `/validate-plan` and `/validate-groom` enforce completeness.

**Code quality** — `/review` does inline code review, `/fix-pr` addresses CI failures and review comments, `/resolve-pr` merges when gates pass.

**Backlog automation** — `/garden` analyzes relevancy/accuracy/readiness, `/sequence` determines optimal ordering, `/loop:backlog` processes issues end-to-end.

**CI/CD integration** — `/fix-pipeline` diagnoses build failures, `/release-ready` checks merge readiness, `/deploy-bypass` handles emergency deploys.

**E2E testing** — `/e2e-write` generates Playwright tests, `/e2e-verify-green` and `/e2e-verify-red` validate pass/fail expectations.

**Cost tracking** — Session cost capture, aggregation, projection, and efficiency metrics for model usage across workflows.

**Local AI** — Ollama setup scripts and model configs for local model routing (code review, summarization, classification).

## Supported Providers

| Category | Providers |
|----------|-----------|
| Issue Tracking | Jira, GitHub Issues, Linear |
| Version Control | Bitbucket, GitHub |
| CI/CD | Concourse, GitHub Actions |

## Quick Start

```bash
git clone https://github.com/george661/skills.git
cd skills
cp templates/.env.template .env
# Edit .env — set ISSUE_TRACKER, VCS_PROVIDER, CI_PROVIDER + credentials
python hooks/validate-config.py          # check config
/next                                    # start working
```

See [docs/SETUP.md](docs/SETUP.md) for the full bootstrap guide and [docs/CONFIG.md](docs/CONFIG.md) for the environment variable reference.

## Structure

| Directory | Contents |
|-----------|----------|
| `commands/` | 93 workflow commands (`/work`, `/next`, `/validate`, `/review`, etc.) |
| `skills/` | 286 provider skills + unified routers across 33 skill directories |
| `hooks/` | 59 session lifecycle, validation, and automation hooks |
| `agents/` | 8 agent definitions (coder, reviewer, planner, validator, architect, coordinator, monitor, researcher) |
| `teams/` | 5 multi-agent team compositions (work, review, plan, groom, validate) |
| `scripts/` | 18 scripts — install, migration, cost tracking, ollama setup, smoke tests |
| `config/` | 11 runtime configs — model routing, dispatch routing, cost/pricing, failure signatures |
| `templates/` | `.env.template`, `CLAUDE.md` template |
| `docs/` | Setup guide, config reference |

## Provider Routers

Commands never call provider backends directly. Three routers dispatch based on env vars:

| Router | Env Var | Backends |
|--------|---------|----------|
| `skills/issues/issues-router.ts` | `ISSUE_TRACKER` | `jira/`, `github-issues/`, `linear/` |
| `skills/vcs/vcs-router.ts` | `VCS_PROVIDER` | `bitbucket/`, `github-mcp/` |
| `skills/ci/ci-router.ts` | `CI_PROVIDER` | `concourse/`, `fly/`, `github-actions/` |

## Skill Directories

| Directory | Skills | Purpose |
|-----------|--------|---------|
| `issues/` | 10 | Unified issue operations (get, search, create, transition, comment) |
| `jira/` | 29 | Jira REST API backend |
| `github-issues/` | 10 | GitHub Issues backend |
| `linear/` | 7 | Linear backend |
| `vcs/` | 8 | Unified VCS operations (PR create, merge, diff, comment) |
| `bitbucket/` | varies | Bitbucket REST API backend |
| `github-mcp/` | 11 | GitHub MCP integration backend |
| `ci/` | 4 | Unified CI operations (wait, logs, status) |
| `concourse/` | 24 | Concourse CI backend |
| `fly/` | 29 | Fly CLI operations |
| `github-actions/` | 4 | GitHub Actions backend |
| `slack/` | 2 | Slack notifications |
| `playwright/` | varies | E2E browser testing |
| `discover/` | 5 | Codebase discovery workflows |
| `investigate/` | 1 | Debugging/investigation |
| `smart-commits/` | 1 | Atlassian Smart Commits format |
| `examples/` | 20 | Provider integration examples |

Plus standalone skill docs: `plan.md`, `writing-plans.md`, `loop-pipeline.md`, `loop-state.md`, `model-selection.md`, `result-compression.md`, `fly-operations.md`, `concourse-pipelines.md`, `hurl-testing.skill.md`, `pact-testing.skill.md`, and more.

## Hooks

59 hooks across the full session lifecycle:

| Category | Hooks |
|----------|-------|
| **Session** | `session-start-workflow-prompt`, `session-cleanup`, `session-end`, `session-history-sync` |
| **Command routing** | `hook-loader`, `route-slash-command`, `route-user-prompt`, `load-command-overlays` |
| **Code quality** | `pre-command`, `post-command`, `pre-edit`, `post-edit`, `enforce-worktree`, `pattern-guard` |
| **Testing** | `testing-md-parser`, `failure-detector`, `test_integration_patterns` |
| **CI/CD** | `pre-push-validation`, `stale-pr-detector`, `validate-config` |
| **Cost & metrics** | `cost-capture`, `metrics-agentdb`, `result-compressor` |
| **AI/Model** | `resolve-model`, `ollama-health-check`, `dispatch-local` |
| **Domain** | `domain-context-injection`, `domain-context-skill-hook`, `domain-consistency-check` |
| **Safety** | `EMERGENCY-DISABLE`, `enforce-skill-project-root`, `warn-manual-jira-transition` |

## Scripts

| Script | Purpose |
|--------|---------|
| `install.sh` | Initial setup — installs dependencies, copies templates |
| `update.sh` | Pull latest and re-run setup |
| `smoke-test.sh` | Integration smoke test (4 checks) |
| `migrate-commands.sh` | Bulk migration of command files to use routers |
| `validate-hooks.sh` | Verify all hooks are properly configured |
| `setup-ollama.sh` | Install and configure Ollama for local model routing |
| `setup-ollama-aliases.sh` | Shell aliases for common Ollama operations |
| `sync-repo-list.sh` | Sync repo-vcs.json from git remotes |
| `capture_session_cost.py` | Record per-session token/cost metrics |
| `aggregate_costs.py` | Roll up costs by day/week/command |
| `cost_projection.py` | Forecast spend based on historical usage |
| `efficiency_metrics.py` | Tokens-per-task-completion analysis |
| `backfill_costs.py` | Backfill missing cost records |
| `extract_command_costs.py` | Per-command cost breakdown |

## Key Commands

| Command | Purpose |
|---------|---------|
| `/work PROJ-123` | Full issue lifecycle: plan, implement (TDD), PR, review |
| `/next` | Find next priority issue from backlog |
| `/validate PROJ-123` | Post-deployment validation with evidence |
| `/review repo pr-id` | Code review with inline comments |
| `/plan PROJ-100` | Write product requirements for an epic |
| `/groom PROJ-100` | Break epic into implementation issues |
| `/loop:backlog` | Process entire backlog autonomously |
| `/garden` | Analyze backlog health and readiness |
| `/fix-pipeline` | Diagnose and fix CI/CD failures |
| `/rx` | Readiness check — verify environment setup |
