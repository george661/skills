#!/usr/bin/env bash
# Starts dag-dashboard with a temp DB + builder enabled, for Playwright.
# Invoked by playwright.config.ts webServer.
set -euo pipefail

PORT="${DAG_DASHBOARD_E2E_PORT:-8123}"
TMPDIR="$(mktemp -d -t dag-dashboard-e2e-XXXXXX)"

# Clean up the temp dir on any exit signal. Playwright sends SIGTERM to the
# webServer when tests finish, so we trap those too — using `exec` would drop
# this shell (and the trap) before the child ever sees a signal.
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT INT TERM

export DAG_DASHBOARD_HOST=127.0.0.1
export DAG_DASHBOARD_PORT="$PORT"
export DAG_DASHBOARD_DB_DIR="$TMPDIR/db"
export DAG_DASHBOARD_EVENTS_DIR="$TMPDIR/events"
export DAG_DASHBOARD_WORKFLOWS_DIR="$TMPDIR/workflows"
export DAG_DASHBOARD_BUILDER_ENABLED=true

mkdir -p "$DAG_DASHBOARD_DB_DIR" "$DAG_DASHBOARD_EVENTS_DIR" "$DAG_DASHBOARD_WORKFLOWS_DIR"

E2E_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PKG_DIR="$(cd "$E2E_DIR/.." && pwd)"
REPO_ROOT="$(cd "$PKG_DIR/../.." && pwd)"

cd "$REPO_ROOT"

# Prefer the repo's .venv if present (local dev); CI sources its own venv
# before launching so `python` resolves correctly there.
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
else
  PY="python"
fi

# Launch server in the background so the trap stays armed, then wait for it.
"$PY" -m dag_dashboard &
SERVER_PID=$!

# Forward signals to the child.
trap 'kill -TERM "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true; cleanup' EXIT INT TERM

wait "$SERVER_PID"
