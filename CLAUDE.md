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
  - source .venv/bin/activate && pytest packages/dag-dashboard/tests/ -v
  - source .venv/bin/activate && mypy packages/dag-executor/src/
  - source .venv/bin/activate && mypy packages/dag-dashboard/src/
  - ruff check hooks/ --select E,F,W --ignore E501
  - shellcheck hooks/*.sh scripts/*.sh

### Visual Validation (required when a change touches dag-dashboard UI)

A change touches the UI if the PR diff includes any of:
  - `packages/dag-dashboard/src/dag_dashboard/static/**`
  - `packages/dag-dashboard/src/dag_dashboard/*_routes.py` that returns HTML
  - CSS files, templates, or anything that ends up in the served bundle

For any such PR, pipeline-verification alone is NOT sufficient. `/validate` MUST
additionally:

1. **Start the dashboard locally** against a temp DB + seeded run.
   Use `packages/dag-dashboard/e2e/scripts/start-server.sh` (same harness
   Playwright uses) or a hand-rolled invocation of `python -m dag_dashboard`
   with `DAG_DASHBOARD_{HOST,PORT,DB_DIR,EVENTS_DIR,WORKFLOWS_DIR}` set.

2. **Seed a multi-node run** exercising the surfaces the PR changed. At minimum
   one run with a succeeded node, a running node, and an escalated node so the
   DAG, progress cards, and escalation/resume UI all render. `depends_on`
   MUST be a JSON array (e.g. `"[]"`), never NULL — `compute_failure_path`
   iterates it unconditionally and 500s on NULL.

3. **Navigate via two-step hash routing** — goto `/` first, then
   `window.location.hash = '#/workflow/{run_id}'`. Direct navigation to a
   hash URL on first load races the SPA router and lands on `/`.

4. **Run the opt-in Playwright suite** against the live server:
   `cd packages/dag-dashboard/e2e && PLAYWRIGHT_E2E=1 npx playwright test`.
   Non-CI-enforced by design but required pre-merge for UI changes.

5. **Capture and Read screenshots** (full-page PNG) of every affected surface.
   At minimum for run-detail changes: dashboard list, run-detail with the new
   layout visible, StateSlideover opened. Read each PNG to verify page
   heading + layout — never trust file existence or file size alone.

6. **Assert the DOM shape** via `page.evaluate` for every architectural claim
   in the PR description. For the run-detail redesign (GW-5422) the
   MUST-PASS assertions are:
     - `.run-pane-split` exists (exactly 1)
     - `#workflow-feed` exists and contains a `.chat-panel.chat-panel--run`
     - `#workflow-feed .chat-input-form` exists (input surface mounted)
     - `window.TracePanel === undefined`
     - `window.ChatPanel`, `window.WorkflowProgressCard`,
       `window.EventToMessages`, `window.NodeScrollBus`,
       `window.StateSlideover`, `window.ResizableSplit` all defined
     - Zero elements match any of: `#run-chat-section`,
       `#workflow-chat-container`, `.run-graph-3col`, `.run-graph-canvas`,
       `.run-graph-side`, `.run-graph-chat`
     - Every `id` under `.state-slideover` (`channel-state-container`,
       `state-diff-timeline-container`, `run-artifacts-container`) appears
       exactly once in the document (dupe check catches regressions like
       the original Critical #3 from the GW-5422 first-pass review).

7. **Record evidence artifacts** in the validation report: paths to PNGs,
   the DOM-shape JSON, and the Playwright run output. The Phase 4
   evaluator must Read the PNGs and describe what they show, not infer
   success from "screenshot captured" alone.

Any of 1-7 failing → verdict TRANSITION_TODO, not TRANSITION_DONE.
Non-UI PRs (docs, hooks, CI config, executor-only changes) can skip this
block and rely on pipeline-verification only.

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
