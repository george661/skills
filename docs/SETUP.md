# Setup Guide

Bootstrap guide for adding skills to a new project.

## 1. Prerequisites

| Tool | Version | Required |
|------|---------|----------|
| Node.js | 18+ | Yes |
| Python | 3.10+ | Yes |
| git | 2.30+ | Yes |
| AWS CLI | 2.x | Optional (for AgentDB, Concourse) |
| tsx | latest | Yes (`npm i -g tsx`) |

## 2. Installation

Clone the repo and install dependencies:

    git clone <your-agents-repo>
    cd <your-agents-repo>
    git submodule update --init --recursive   # pulls skills as base/
    cp base/templates/.env.template .env
    ./scripts/install.sh

## 3. Choose Your Toolchain

Pick the combination that matches your project:

### GitHub-native

    ISSUE_TRACKER=github
    VCS_PROVIDER=github
    CI_PROVIDER=github_actions
    GITHUB_TOKEN=ghp_...
    GITHUB_OWNER=your-org

### Atlassian

    ISSUE_TRACKER=jira
    VCS_PROVIDER=bitbucket
    CI_PROVIDER=concourse
    JIRA_HOST=your-org.atlassian.net
    JIRA_USERNAME=you@company.com
    JIRA_API_TOKEN=...
    BITBUCKET_WORKSPACE=your-org
    BITBUCKET_USERNAME=your-user
    BITBUCKET_TOKEN=...

### Mixed (Linear + GitHub)

    ISSUE_TRACKER=linear
    VCS_PROVIDER=github
    CI_PROVIDER=github_actions
    LINEAR_API_KEY=lin_api_...
    GITHUB_TOKEN=ghp_...
    GITHUB_OWNER=your-org

## 4. Configure `.env`

Open `.env` and fill in credentials for your chosen providers.
See [CONFIG.md](CONFIG.md) for the full variable reference.

Required for all setups:

    TENANT_PROJECT=YOUR-PROJECT-KEY
    PROJECT_ROOT=/path/to/your/project

## 5. Verify Setup

Run the config validator to check your environment:

    python hooks/validate-config.py

Or use the readiness check:

    /rx

The validator prints a table showing which variables are set, missing,
or optional. Fix any MISSING entries before proceeding.

For connectivity verification:

    python hooks/validate-config.py --check-connectivity

## 6. First Workflow

Find available work:

    /next

Start working on an issue:

    /work PROJ-123

This runs the full cycle: plan, implement (TDD), create PR, review.
