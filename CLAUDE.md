# skills — SDLC Platform Agent Toolkit

## Project Context

Shared agent workflow components: commands, hooks, skills, agent/team configs, and Python packages.

**GitHub:** george661/skills
**Jira Label:** `repo-base-agents`
**Language:** Python (packages, hooks), Shell (scripts), Markdown (commands/skills), YAML (agents/teams)

## Validation Profile

deploy-strategy: github-actions
validation-type: pipeline-verification
validation-commands:
  - ./scripts/setup-venv.sh
  - source .venv/bin/activate && pytest packages/dag-executor/tests/ -v
  - source .venv/bin/activate && mypy packages/dag-executor/src/
  - ruff check hooks/ --select E,F,W --ignore E501
  - shellcheck hooks/*.sh scripts/*.sh

## Python Dev Environment

Each worktree gets its own `.venv/` (uv-managed) to prevent cross-worktree
shadowing of editable installs. First time in a worktree:

    ./scripts/setup-venv.sh     # creates .venv, editable-installs packages[dev]
    source .venv/bin/activate

Do NOT `pip install -e packages/...` into miniconda or any shared interpreter —
other worktrees on the same machine will start importing from the last one
installed.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on push to main and PRs:

| Job | What | Trigger |
|-----|------|---------|
| `python-packages` | pip install + pytest + mypy per package (3.9 + 3.12 matrix) | `packages/**` |
| `hooks-lint` | py_compile syntax + ruff lint | `hooks/*.py` |
| `shellcheck` | shellcheck --severity=warning | `**/*.sh` |
| `yaml-validate` | yamllint | `agents/`, `teams/` |

## Directory Structure

| Directory | Contents |
|-----------|----------|
| `packages/` | Python packages (dag-executor, future packages) |
| `commands/` | Slash command definitions (markdown) |
| `skills/` | Integration skills (fly, rx, etc.) |
| `hooks/` | Python + shell hooks for agent workflows |
| `scripts/` | Install, setup, utility scripts |
| `agents/` | Agent role definitions (YAML) |
| `teams/` | Team composition configs (YAML) |
| `templates/` | CLAUDE.md template for tenant repos |
| `config/` | Configuration files |
| `docs/` | Documentation |

## Code Standards

- Python packages use src-layout with Pydantic v2
- Python 3.9+ compatibility required
- mypy strict mode for packages
- No files in root directory
