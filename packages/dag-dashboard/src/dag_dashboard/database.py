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
    error TEXT,
    workflow_definition TEXT
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
    error TEXT,
    depends_on TEXT,
    model TEXT,
    tokens INTEGER,
    cost REAL,
    tokens_input INTEGER,
    tokens_output INTEGER,
    tokens_cache INTEGER
);

-- 3. chat_messages: LLM chat messages per node execution or workflow
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    execution_id TEXT REFERENCES node_executions(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    metadata TEXT,
    run_id TEXT REFERENCES workflow_runs(id),
    operator_username TEXT
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
    created_at TEXT NOT NULL,
    url TEXT
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

-- 8. channel_states: Channel state snapshots per workflow execution
CREATE TABLE IF NOT EXISTS channel_states (
    run_id TEXT NOT NULL REFERENCES workflow_runs(id),
    channel_key TEXT NOT NULL,
    channel_type TEXT NOT NULL,
    reducer_strategy TEXT,
    value_json TEXT,
    version INTEGER NOT NULL DEFAULT 0,
    writers_json TEXT,
    conflict_json TEXT,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (run_id, channel_key)
);
"""


def ensure_dir(path: Path) -> None:
    """Create directory with 0700 permissions if it doesn't exist."""
    if not path.exists():
        path.mkdir(parents=True, mode=0o700)


def init_db(db_path: Path) -> None:
    """Initialize database with schema and security settings.

    Migration strategy: For existing DBs, ALTER TABLE adds new columns.
    For new DBs, CREATE TABLE IF NOT EXISTS includes the columns from the start.
    """
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

        # Execute schema (creates tables if not exist)
        cursor.executescript(SCHEMA)

        # Migration: Add new columns if they don't exist (for existing DBs)
        # SQLite ALTER TABLE ADD COLUMN works for nullable columns
        try:
            cursor.execute("ALTER TABLE workflow_runs ADD COLUMN workflow_definition TEXT")
        except sqlite3.OperationalError:
            # Column already exists
            pass

        try:
            cursor.execute("ALTER TABLE node_executions ADD COLUMN depends_on TEXT")
        except sqlite3.OperationalError:
            # Column already exists
            pass

        try:
            cursor.execute("ALTER TABLE node_executions ADD COLUMN model TEXT")
        except sqlite3.OperationalError:
            # Column already exists
            pass

        try:
            cursor.execute("ALTER TABLE node_executions ADD COLUMN tokens INTEGER")
        except sqlite3.OperationalError:
            # Column already exists
            pass

        try:
            cursor.execute("ALTER TABLE node_executions ADD COLUMN cost REAL")
        except sqlite3.OperationalError:
            # Column already exists
            pass

        try:
            cursor.execute("ALTER TABLE node_executions ADD COLUMN tokens_input INTEGER")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE node_executions ADD COLUMN tokens_output INTEGER")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE node_executions ADD COLUMN tokens_cache INTEGER")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE artifacts ADD COLUMN url TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE chat_messages ADD COLUMN run_id TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE chat_messages ADD COLUMN operator_username TEXT")
        except sqlite3.OperationalError:
            pass

        conn.commit()
    finally:
        conn.close()

    # Set file permissions to 0600 (user read/write only)
    os.chmod(db_path, 0o600)
