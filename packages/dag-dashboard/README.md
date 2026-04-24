# dag-dashboard

Web dashboard for monitoring DAG workflow execution in real-time. Ingests JSONL event files emitted by `dag-executor`, stores them in SQLite, and serves a FastAPI application with Server-Sent Events for live updates.

## Quick Start

```bash
pip install -e packages/dag-dashboard

# Start the dashboard (default: http://127.0.0.1:8100)
dag-dashboard
```

The dashboard watches an events directory for JSONL files produced by `dag-executor`'s `EventEmitter` and populates a local SQLite database. Open a browser to see workflow runs, node execution timelines, and streaming status updates.

## Features

### Checkpoint Resume Indicator

Nodes that were restored from a checkpoint (cache hit) are displayed with a dashed outline and a "↻ resumed" badge. This visual indicator helps distinguish between freshly executed nodes and those skipped due to content-hash matching.

### Mobile Support

The dashboard is fully responsive down to 320px viewport width (iPhone SE). Touch targets meet iOS HIG guidelines (≥44px). Pinch-to-zoom is enabled on the DAG canvas for touch devices.

### Conversation View

The dashboard supports viewing chat messages across multiple workflow runs via conversation ID. Navigate to `/#/conversations/<conversation-id>` to see all messages in a conversation displayed chronologically, regardless of which run they belong to.

**When to use:**
- **Conversation view** (`/#/conversations/<id>`): View the full message history across all runs in a conversation (read-only)
- **Workflow view** (`/#/workflow/<run-id>`): View and send messages for a specific workflow run (interactive)

The conversation view is read-only — you cannot send messages from this view. To send new messages, navigate to the workflow run detail page for the active run.

### Production Build Verification

To verify that the package includes all static assets and the server starts correctly:

```bash
./packages/dag-dashboard/scripts/verify_production_build.sh
```

This script:
- Installs the package into a clean environment
- Verifies the `dag-dashboard` CLI command works
- Checks that static assets (HTML/CSS/JS) are packaged correctly
- Starts the server and tests HTTP endpoints (`/health`, `/`, `/css/styles.css`, `/js/app.js`)

## Builder UI

The dag-dashboard includes a visual workflow builder for creating and editing DAG workflow YAML files. The builder provides a drag-and-drop canvas, real-time validation, and integrated version management via drafts.

> **Note:** Screenshots of the canvas, inspector, and version drawer are tracked as a follow-up once the Builder React bootstrap is hardened (current main still requires inlined React globals). See PRP-PLAT-008 Tier F follow-up.

### Enabling the Builder

Set the `DAG_DASHBOARD_BUILDER_ENABLED` environment variable to enable the builder UI:

```bash
DAG_DASHBOARD_BUILDER_ENABLED=true dag-dashboard
```

When enabled:
- The feature flag is exposed via `/api/config` as `window.DAG_DASHBOARD_BUILDER_ENABLED`
- Builder routes are mounted at `/#/builder/*`
- The builder interface becomes accessible from the dashboard navigation

### Drafts Lifecycle

The builder uses a drafts system to manage workflow edits without overwriting the canonical workflow file until explicitly published. Drafts are stored in `<workflows_dir>/.drafts/<workflow_name>/` with timestamp-based filenames.

**Lifecycle stages:**

1. **Autosave** — Changes are automatically saved every 30 seconds to a draft file (format: `YYYYMMDD_HHMMSS.yaml`)
2. **Save** — Manual save via `Cmd+S` (Mac) / `Ctrl+S` (Windows/Linux) bypasses the autosave debounce and immediately writes a timestamped draft
3. **Current pointer** — A `.current` pointer file tracks the active draft being edited
4. **Publish** — Promotes the current draft to the canonical `workflow.yaml` file via atomic rename (see Publish Flow below)

Drafts are pruned to keep the most recent 50 per workflow. Old drafts can be restored or compared using the version drawer or CLI.

### Publish Flow

Clicking **Publish** in the builder toolbar triggers the following steps:

1. **Validation** — The draft is validated against the workflow schema (node types, required fields, edge connectivity)
2. **Temporary write** — If validation passes, the content is written to `<workflow_name>.yaml.tmp` in the same directory
3. **Atomic rename** — `os.replace()` renames the `.tmp` file to `<workflow_name>.yaml`, ensuring readers never see a partial file

This atomic rename guarantees that:
- Concurrent readers see either the old or new version, never a half-written file
- The publish operation is idempotent and crash-safe
- No manual locking or coordination is required

### Destructive Node Editing (builder.allow_destructive_nodes)

By default, the builder restricts editing of certain "destructive" node types to prevent accidental code execution or side effects. When `allow_destructive_nodes=False` (default), the flag applies a card-level read-only visual state (dimmed appearance + not-allowed cursor) to destructive node types. Per-field editing lockdowns for bash/skill/command node internals are in-progress under FR-8 and will land in a follow-up.

**Rationale:** The builder is commonly used by multiple operators in shared environments. Fields that execute arbitrary code or shell commands can introduce security risks (e.g., unintentional data deletion, credential leakage). The default read-only mode ensures safe editing of workflow structure while preventing foot-guns.

**To enable destructive field editing:**

Set `allow_destructive_nodes=True` in the dashboard configuration:

```bash
DAG_DASHBOARD_ALLOW_DESTRUCTIVE_NODES=true dag-dashboard
```

Enable this setting only when:
- The operator population is trusted
- Workflow security is managed via external controls (e.g., code review, RBAC)
- Destructive editing is required for legitimate workflow design tasks

### Keyboard Shortcuts

The builder supports keyboard shortcuts for common actions. All shortcuts use `Cmd` on macOS and `Ctrl` on Windows/Linux (referred to as `mod` below). Shortcuts are suppressed when typing in text inputs, textareas, or contenteditable elements.

| Shortcut | Action |
|----------|--------|
| `mod+s` | Force save (bypasses autosave debounce) |
| `mod+z` | Undo |
| `mod+shift+z` | Redo |
| `mod+/` | Toggle YAML code view |
| `mod+.` | Toggle validation panel |
| `mod+enter` | Run workflow |
| `mod+l` | Toggle node library |
| `mod+d` | Duplicate selected node |
| `delete` / `backspace` | Delete selected node or edge |

### dag-exec drafts CLI

The `dag-executor` package provides a `dag-exec drafts` subcommand for managing workflow drafts from the command line. This is useful for scripting, CI/CD pipelines, or debugging draft state outside the UI.

**Subcommands:**

```bash
# List all drafts for a workflow (local mode)
dag-exec drafts list <workflow_name> [--json]

# Show diff between two drafts, or between a draft and canonical
dag-exec drafts diff <workflow_name> <timestamp_a> [<timestamp_b>]

# Restore a draft as the canonical workflow (atomic rename)
dag-exec drafts restore <workflow_name> <timestamp> [--yes]

# Publish a draft (same as UI Publish button: validate + atomic rename)
dag-exec drafts publish <workflow_name> <timestamp>

# Delete a specific draft
dag-exec drafts delete <workflow_name> <timestamp> [--yes]
```

**Local mode** (default) reads/writes drafts directly from the filesystem:
- Use `--workflows-dir <path>` to specify the workflows directory
- Or set `$DAG_DASHBOARD_WORKFLOWS_DIR` environment variable
- Defaults to current directory if neither is set

**Remote mode** sends HTTP requests to a running dashboard API:
- Use `--remote <url>` to specify the dashboard base URL (e.g., `http://localhost:8100`)
- Provide authentication via `--token <bearer_token>` or `$DAG_EXEC_DRAFTS_TOKEN` environment variable
- Useful for managing drafts on a remote dashboard instance without filesystem access

**Examples:**

```bash
# List drafts for 'work' workflow
dag-exec drafts list work --json

# Compare current draft to canonical workflow
dag-exec drafts diff work 20260423_143022

# Compare two drafts
dag-exec drafts diff work 20260423_143022 20260423_150133

# Restore a specific draft (prompts for confirmation unless --yes)
dag-exec drafts restore work 20260423_143022 --yes

# Publish a draft (runs validation first)
dag-exec drafts publish work 20260423_143022

# Delete an old draft
dag-exec drafts delete work 20260420_091533 --yes

# Remote mode: list drafts on a remote dashboard
dag-exec drafts list work --remote http://dashboard.example.com:8100 --token $MY_TOKEN
```

## Configuration

All settings are configured via environment variables with the `DAG_DASHBOARD_` prefix:

| Variable | Default | Purpose |
|----------|---------|---------|
| `DAG_DASHBOARD_HOST` | `127.0.0.1` | Bind address |
| `DAG_DASHBOARD_PORT` | `8100` | Listen port |
| `DAG_DASHBOARD_DB_DIR` | `~/.dag-dashboard` | SQLite database directory |
| `DAG_DASHBOARD_EVENTS_DIR` | `dag-events` | Directory to watch for JSONL event files |
| `DAG_DASHBOARD_MAX_SSE_CONNECTIONS` | `50` | Maximum concurrent SSE subscribers |
| `DAG_DASHBOARD_DASHBOARD_URL` | `http://127.0.0.1:8100` | Base URL used in Slack card action buttons |
| `DAG_DASHBOARD_TRIGGER_ENABLED` | `false` | Enable webhook trigger endpoint (POST /api/trigger) |
| `DAG_DASHBOARD_TRIGGER_SECRET` | — | Optional HMAC secret for webhook signature verification |
| `DAG_DASHBOARD_TRIGGER_RATE_LIMIT_PER_MIN` | `10` | Rate limit per source (requests/minute) |
| `DAG_DASHBOARD_WORKFLOWS_DIR` | `workflows` | Directory containing workflow YAML files |
| `DAG_DASHBOARD_SLACK_ENABLED` | `false` | Turn Slack notifications on |
| `DAG_DASHBOARD_SLACK_WEBHOOK_URL` | — | Slack incoming webhook (mutually exclusive with bot token) |
| `DAG_DASHBOARD_SLACK_BOT_TOKEN` | — | Slack bot token `xoxb-...` (enables threaded replies) |
| `DAG_DASHBOARD_SLACK_CHANNEL_ID` | — | Slack channel id (required when using bot token) |

```bash
DAG_DASHBOARD_PORT=9000 DAG_DASHBOARD_EVENTS_DIR=.dag-checkpoints dag-dashboard
```

### Slack notifications

Set `DAG_DASHBOARD_SLACK_ENABLED=true` and configure exactly one transport:

- **Webhook**: set `DAG_DASHBOARD_SLACK_WEBHOOK_URL`. Simpler to set up; each event is a separate top-level message (webhooks cannot return a thread ts).
- **Bot token**: set `DAG_DASHBOARD_SLACK_BOT_TOKEN` and `DAG_DASHBOARD_SLACK_CHANNEL_ID`. All events for a given workflow run are posted in a single thread.

Cards are emitted for `workflow_started`, `workflow_completed`, `workflow_failed`, and `gate_pending` events and include a "View in Dashboard" button linking to `{DAG_DASHBOARD_DASHBOARD_URL}/runs/{run_id}`. Failure cards include the first 200 codepoints of the error message.

## API Endpoints

### Workflow Runs

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/workflows` | List runs (paginated, filterable by status, sortable) |
| `GET` | `/api/workflows/{run_id}` | Get run details with node executions |

**Query parameters** for `GET /api/workflows`:

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int (1-100) | 50 | Page size |
| `offset` | int | 0 | Pagination offset |
| `status` | `running` / `completed` / `failed` / `cancelled` | — | Filter by status |
| `sort_by` | `started_at` / `finished_at` | `started_at` | Sort order |

### Node Executions

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/workflows/{run_id}/nodes/{node_id}` | Get node execution details |

### Webhook Trigger (Optional)

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/trigger` | Trigger workflow execution via webhook |

**Enable webhook triggers:**
```bash
DAG_DASHBOARD_TRIGGER_ENABLED=true DAG_DASHBOARD_WORKFLOWS_DIR=./workflows dag-dashboard
```

**Request body:**
```json
{
  "workflow": "work",
  "inputs": {
    "issue_key": "GW-5139"
  },
  "source": "github-webhook"
}
```

**Response:**
```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000"
}
```

**Behavior:**
- Validates workflow file exists (`{workflows_dir}/{workflow}.yaml`)
- Validates inputs match workflow's declared input schema (type, required fields)
- Spawns `dag-exec` subprocess asynchronously (non-blocking response)
- Persists `trigger_source` in workflow_runs table for audit
- Triggered runs appear in dashboard with source indicator

**Optional HMAC verification (GitHub webhook pattern):**
```bash
DAG_DASHBOARD_TRIGGER_SECRET="your-secret-key"
```

When a secret is configured, all POST /api/trigger requests must include an `X-Hub-Signature-256` header with HMAC-SHA256 signature:
```
X-Hub-Signature-256: sha256=<hex-digest>
```

**Rate limiting:**
- Default: 10 requests/minute per source
- Configure: `DAG_DASHBOARD_TRIGGER_RATE_LIMIT_PER_MIN=20`
- Exceeding limit returns 429

**Security:**
- Workflow names must be alphanumeric + hyphens only (no path traversal)
- Resolved paths must be under `workflows_dir`
- Spawned subprocesses are detached (survive dashboard restart)

### Real-time Events

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/events` | SSE stream of workflow execution updates |

Connect to the SSE endpoint to receive live events as workflows execute:

```javascript
const events = new EventSource("/api/events");
events.onmessage = (e) => {
  const data = JSON.parse(e.data);
  console.log(data.type, data);
};
```

### Health

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Readiness check |

## How It Works

1. `dag-executor` writes JSONL event files to a checkpoint directory during workflow execution
2. The `EventCollector` watches the configured events directory using `watchdog`
3. New events are parsed, inserted into SQLite tables, and broadcast to SSE subscribers
4. The FastAPI app serves the REST API and static frontend assets
5. Browser clients connect to `/api/events` for live streaming updates

### Database Schema

SQLite tables:

| Table | Purpose |
|-------|---------|
| `workflow_runs` | Workflow run metadata (id, name, status, timestamps, inputs/outputs) |
| `node_executions` | Per-node execution records (id, run_id, name, status, timestamps, I/O) |
| `chat_messages` | Chat/interrupt messages from human-in-the-loop nodes |
| `gate_decisions` | Gate node evaluation results |
| `artifacts` | File artifacts produced during execution |

## Architecture

```
src/dag_dashboard/
  __init__.py          Public API exports
  __main__.py          Entry point (dag-dashboard command)
  server.py            FastAPI app factory with lifespan management
  config.py            Pydantic settings (env var configuration)
  routes.py            REST API route handlers
  models.py            Pydantic response models
  database.py          SQLite schema initialization
  queries.py           Parameterized database queries (SQL injection safe)
  event_collector.py   File watcher that ingests JSONL events into SQLite
  broadcast.py         In-memory SSE broadcaster
  sse.py               SSE router for /api/events stream
  static/              CSS and JavaScript for web UI
```

## Integration with dag-executor

The dashboard reads the same JSONL event files that `dag-executor` writes during execution. Point `DAG_DASHBOARD_EVENTS_DIR` at your workflow's checkpoint prefix:

```bash
# Executor writes events to .dag-checkpoints/
dag-exec workflow.yaml --stream user_id=U123

# Dashboard watches the same directory
DAG_DASHBOARD_EVENTS_DIR=.dag-checkpoints dag-dashboard
```

## Development

```bash
pip install -e packages/dag-dashboard[dev]
pytest packages/dag-dashboard/tests/ -v
mypy packages/dag-dashboard/src/
```

Requires Python 3.9+. Dependencies: `fastapi`, `uvicorn`, `pydantic>=2.0`, `pydantic-settings`, `watchdog`.
