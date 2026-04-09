# skills

Plug-and-play SDLC workflow skills for Claude Code. 78 commands, 75 skills, 59 hooks, and 11 agent configs that give any Claude Code instance a complete software development lifecycle — from issue triage to deployment validation.

Provider-agnostic: configure your issue tracker, VCS, and CI/CD once in `.env` and every command works regardless of which combination you use.

## What You Get

**Issue lifecycle** — `/next` finds priority work, `/work PROJ-123` runs the full cycle (plan → TDD implement → PR → review), `/validate` collects post-deploy evidence.

**Epic planning** — `/plan` writes product requirements, `/groom` breaks them into issues, `/validate-plan` and `/validate-groom` enforce completeness.

**Code quality** — `/review` does inline code review, `/fix-pr` addresses CI failures and review comments, `/resolve-pr` merges when gates pass.

**Backlog automation** — `/garden` analyzes relevancy/accuracy/readiness, `/sequence` determines optimal ordering, `/loop:backlog` processes issues end-to-end.

**CI/CD integration** — `/fix-pipeline` diagnoses build failures, `/release-ready` checks merge readiness, `/deploy-bypass` handles emergency deploys.

**E2E testing** — `/e2e-write` generates Playwright tests, `/e2e-verify-green` and `/e2e-verify-red` validate pass/fail expectations.

## Supported Providers

| Category | Providers |
|----------|-----------|
| Issue Tracking | Jira, GitHub Issues, Linear |
| Version Control | Bitbucket, GitHub |
| CI/CD | Concourse, GitHub Actions |

## Quick Start

```bash
git clone <your-agents-repo>
cd <your-agents-repo>
git submodule update --init --recursive
cp base/templates/.env.template .env
# Edit .env — set ISSUE_TRACKER, VCS_PROVIDER, CI_PROVIDER + credentials
python hooks/validate-config.py          # check config
/next                                    # start working
```

See [docs/SETUP.md](docs/SETUP.md) for the full bootstrap guide and [docs/CONFIG.md](docs/CONFIG.md) for the environment variable reference.

## Structure

| Directory | Contents |
|-----------|----------|
| `commands/` | 78 workflow commands (`/work`, `/next`, `/validate`, `/review`, etc.) |
| `skills/` | 75 provider skills + unified routers (`issues/`, `vcs/`, `ci/`) |
| `hooks/` | 59 session lifecycle, validation, and automation hooks |
| `agents/` | 11 agent configurations and team definitions |
| `templates/` | `.env.template`, `CLAUDE.md` template |
| `scripts/` | Install, migration, and smoke test scripts |
| `docs/` | Setup guide, config reference |

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
