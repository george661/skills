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
    workflow_definition TEXT,
    trigger_source TEXT,
    cancelled_by TEXT
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
    tokens_cache INTEGER,
    content_hash TEXT,
    input_versions TEXT,
    cache_hit INTEGER DEFAULT 0
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

-- 9. node_logs: Per-node execution logs (stdout/stderr)
CREATE TABLE IF NOT EXISTS node_logs (
    run_id TEXT NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    node_id TEXT NOT NULL,
    stream TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    line TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_node_logs_run_node_seq
    ON node_logs(run_id, node_id, sequence);

-- 10. dashboard_settings: Operator-editable runtime settings
CREATE TABLE IF NOT EXISTS dashboard_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    is_secret INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    updated_by TEXT
);
"""


def ensure_dir(path: Path) -> None:
    """Create directory with 0700 permissions if it doesn't exist."""
    if not path.exists():
        path.mkdir(parents=True, mode=0o700)


def init_fts5_index(conn: sqlite3.Connection) -> None:
    """Create FTS5 full-text search indexes and triggers.

    This is called conditionally from init_db when fts5_enabled=True.
    Idempotent - safe to call multiple times.

    Args:
        conn: Database connection (must already have base tables)
    """
    import logging
    logger = logging.getLogger(__name__)

    # Check if FTS5 is available
    cursor = conn.cursor()
    cursor.execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')")
    fts5_available = cursor.fetchone()[0]

    if not fts5_available:
        logger.warning(
            "FTS5 not available in this SQLite build. "
            "Search will fall back to LIKE queries."
        )
        return

    # Create FTS5 virtual tables (contentful mode for snippet support)
    # events_fts
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(
            payload, event_type, run_id UNINDEXED,
            content='events', content_rowid='id'
        )
    """)

    # workflow_runs_fts
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS workflow_runs_fts USING fts5(
            workflow_name, inputs, error, id UNINDEXED,
            content='workflow_runs', content_rowid='id'
        )
    """)

    # node_executions_fts
    cursor.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS node_executions_fts USING fts5(
            node_name, inputs, error, id UNINDEXED, run_id UNINDEXED,
            content='node_executions', content_rowid='id'
        )
    """)

    # Create triggers to keep FTS indexes in sync
    # Events triggers
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
            INSERT INTO events_fts(rowid, payload, event_type, run_id)
            VALUES (new.id, new.payload, new.event_type, new.run_id);
        END
    """)

    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
            INSERT INTO events_fts(events_fts, rowid, payload, event_type, run_id)
            VALUES ('delete', old.id, old.payload, old.event_type, old.run_id);
        END
    """)

    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS events_au AFTER UPDATE ON events BEGIN
            INSERT INTO events_fts(events_fts, rowid, payload, event_type, run_id)
            VALUES ('delete', old.id, old.payload, old.event_type, old.run_id);
            INSERT INTO events_fts(rowid, payload, event_type, run_id)
            VALUES (new.id, new.payload, new.event_type, new.run_id);
        END
    """)

    # workflow_runs triggers
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS workflow_runs_ai AFTER INSERT ON workflow_runs BEGIN
            INSERT INTO workflow_runs_fts(rowid, workflow_name, inputs, error, id)
            VALUES (new.id, new.workflow_name, new.inputs, new.error, new.id);
        END
    """)

    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS workflow_runs_ad AFTER DELETE ON workflow_runs BEGIN
            INSERT INTO workflow_runs_fts(workflow_runs_fts, rowid, workflow_name, inputs, error, id)
            VALUES ('delete', old.id, old.workflow_name, old.inputs, old.error, old.id);
        END
    """)

    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS workflow_runs_au AFTER UPDATE ON workflow_runs BEGIN
            INSERT INTO workflow_runs_fts(workflow_runs_fts, rowid, workflow_name, inputs, error, id)
            VALUES ('delete', old.id, old.workflow_name, old.inputs, old.error, old.id);
            INSERT INTO workflow_runs_fts(rowid, workflow_name, inputs, error, id)
            VALUES (new.id, new.workflow_name, new.inputs, new.error, new.id);
        END
    """)

    # node_executions triggers
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS node_executions_ai AFTER INSERT ON node_executions BEGIN
            INSERT INTO node_executions_fts(rowid, node_name, inputs, error, id, run_id)
            VALUES (new.id, new.node_name, new.inputs, new.error, new.id, new.run_id);
        END
    """)

    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS node_executions_ad AFTER DELETE ON node_executions BEGIN
            INSERT INTO node_executions_fts(node_executions_fts, rowid, node_name, inputs, error, id, run_id)
            VALUES ('delete', old.id, old.node_name, old.inputs, old.error, old.id, old.run_id);
        END
    """)

    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS node_executions_au AFTER UPDATE ON node_executions BEGIN
            INSERT INTO node_executions_fts(node_executions_fts, rowid, node_name, inputs, error, id, run_id)
            VALUES ('delete', old.id, old.node_name, old.inputs, old.error, old.id, old.run_id);
            INSERT INTO node_executions_fts(rowid, node_name, inputs, error, id, run_id)
            VALUES (new.id, new.node_name, new.inputs, new.error, new.id, new.run_id);
        END
    """)

    # Backfill existing rows
    cursor.execute("""
        INSERT OR IGNORE INTO events_fts(rowid, payload, event_type, run_id)
        SELECT id, payload, event_type, run_id FROM events
    """)

    cursor.execute("""
        INSERT OR IGNORE INTO workflow_runs_fts(rowid, workflow_name, inputs, error, id)
        SELECT id, workflow_name, inputs, error, id FROM workflow_runs
    """)

    cursor.execute("""
        INSERT OR IGNORE INTO node_executions_fts(rowid, node_name, inputs, error, id, run_id)
        SELECT id, node_name, inputs, error, id, run_id FROM node_executions
    """)

    conn.commit()
    logger.info("FTS5 indexes and triggers created successfully")


def init_db(db_path: Path, fts5_enabled: bool = False) -> None:
    """Initialize database with schema and security settings.

    Migration strategy: For existing DBs, ALTER TABLE adds new columns.
    For new DBs, CREATE TABLE IF NOT EXISTS includes the columns from the start.

    Args:
        db_path: Path to SQLite database file
        fts5_enabled: If True, create FTS5 full-text search indexes
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

        try:
            cursor.execute("ALTER TABLE workflow_runs ADD COLUMN trigger_source TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE workflow_runs ADD COLUMN parent_run_id TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE workflow_runs ADD COLUMN cancelled_by TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE node_executions ADD COLUMN content_hash TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE node_executions ADD COLUMN input_versions TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE node_executions ADD COLUMN cache_hit INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        # Create FTS5 indexes if enabled
        if fts5_enabled:
            init_fts5_index(conn)

        conn.commit()
    finally:
        conn.close()

    # Set file permissions to 0600 (user read/write only)
    os.chmod(db_path, 0o600)
