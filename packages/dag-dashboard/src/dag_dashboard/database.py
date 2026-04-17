"""Database initialization and schema management."""
import os
import sqlite3
from pathlib import Path


SCHEMA = """
-- 1. workflow_runs: Top-level workflow execution tracking
CREATE TABLE IF NOT EXISTS workflow_runs (
    id TEXT PRIMARY KEY,
    workflow_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    inputs TEXT,
    outputs TEXT,
    error TEXT
);

-- 2. node_executions: Per-node execution within a workflow run
CREATE TABLE IF NOT EXISTS node_executions (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES workflow_runs(id),
    node_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    started_at TEXT,
    finished_at TEXT,
    inputs TEXT,
    outputs TEXT,
    error TEXT
);

-- 3. chat_messages: LLM chat messages per node execution
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL REFERENCES node_executions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata TEXT
);

-- 4. gate_decisions: Human-in-the-loop gate outcomes
CREATE TABLE IF NOT EXISTS gate_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES workflow_runs(id),
    node_name TEXT NOT NULL,
    decision TEXT NOT NULL,
    decided_by TEXT,
    decided_at TEXT NOT NULL,
    reason TEXT
);

-- 5. artifacts: Files/outputs produced by node executions
CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT NOT NULL REFERENCES node_executions(id),
    name TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    path TEXT,
    content TEXT,
    created_at TEXT NOT NULL
);

-- 6. events: Workflow-level event log
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES workflow_runs(id),
    event_type TEXT NOT NULL,
    payload TEXT,
    created_at TEXT NOT NULL
);

-- 7. slack_threads: Slack thread references for notifications
CREATE TABLE IF NOT EXISTS slack_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES workflow_runs(id),
    channel_id TEXT NOT NULL,
    thread_ts TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def ensure_dir(path: Path) -> None:
    """Create directory with 0700 permissions if it doesn't exist."""
    if not path.exists():
        path.mkdir(parents=True, mode=0o700)


def init_db(db_path: Path) -> None:
    """Initialize database with schema and security settings."""
    # Connect and create schema
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()

        # Enable WAL mode for concurrent reads (persistent)
        cursor.execute("PRAGMA journal_mode=WAL")

        # Enable foreign key constraints (must be set on EACH connection)
        # Note: Unlike WAL mode, this pragma is not persistent and must be
        # reapplied when opening the database in production code.
        cursor.execute("PRAGMA foreign_keys=ON")

        # Execute schema
        cursor.executescript(SCHEMA)

        conn.commit()
    finally:
        conn.close()

    # Set file permissions to 0600 (user read/write only)
    os.chmod(db_path, 0o600)
