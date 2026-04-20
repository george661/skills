# dag-dashboard

Web dashboard for monitoring DAG workflow execution in real-time. Ingests JSONL event files emitted by `dag-executor`, stores them in SQLite, and serves a FastAPI application with Server-Sent Events for live updates.

## Quick Start

```bash
pip install -e packages/dag-dashboard

# Start the dashboard (default: http://127.0.0.1:8100)
dag-dashboard
```

The dashboard watches an events directory for JSONL files produced by `dag-executor`'s `EventEmitter` and populates a local SQLite database. Open a browser to see workflow runs, node execution timelines, and streaming status updates.

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
