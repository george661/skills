"""Tests for database initialization and schema."""
import sqlite3
from pathlib import Path
from dag_dashboard.database import ensure_dir, init_db


def test_ensure_dir_creates_with_0700(tmp_path: Path) -> None:
    """ensure_dir should create directory with 0700 permissions."""
    db_dir = tmp_path / "test-dashboard"
    ensure_dir(db_dir)
    
    assert db_dir.exists()
    assert db_dir.is_dir()
    
    # Check permissions (0700 = user rwx only)
    mode = db_dir.stat().st_mode & 0o777
    assert mode == 0o700


def test_init_db_creates_all_tables(tmp_path: Path) -> None:
    """init_db should create all 7 required tables."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check all 8 tables exist (exclude sqlite_sequence which is auto-created)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]

    expected_tables = [
        'artifacts',
        'channel_states',
        'chat_messages',
        'events',
        'gate_decisions',
        'node_executions',
        'slack_threads',
        'workflow_runs'
    ]
    
    assert tables == expected_tables
    conn.close()


def test_init_db_sets_wal_mode(tmp_path: Path) -> None:
    """init_db should enable WAL mode for concurrent reads."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA journal_mode")
    mode = cursor.fetchone()[0]
    
    assert mode.lower() == "wal"
    conn.close()


def test_init_db_sets_file_permissions(tmp_path: Path) -> None:
    """init_db should set database file permissions to 0600."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    # Check permissions (0600 = user rw only)
    mode = db_path.stat().st_mode & 0o777
    assert mode == 0o600


def test_init_db_is_idempotent(tmp_path: Path) -> None:
    """Running init_db twice should not raise errors."""
    db_path = tmp_path / "test.db"

    # First run
    init_db(db_path)

    # Second run should not error
    init_db(db_path)

    # Verify tables still exist (exclude sqlite_sequence)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name != 'sqlite_sequence'")
    count = cursor.fetchone()[0]
    assert count == 8
    conn.close()


def test_migration_adds_token_breakdown_columns(tmp_path: Path) -> None:
    """Migration should add tokens_input, tokens_output, tokens_cache columns to node_executions."""
    db_path = tmp_path / "old-schema.db"

    # Create a minimal old-schema DB without the new columns
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE node_executions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            node_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            tokens INTEGER,
            cost REAL
        )
    """)
    conn.commit()
    conn.close()

    # Run migration
    init_db(db_path)

    # Verify new columns exist
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(node_executions)")
    columns = {row[1] for row in cursor.fetchall()}

    assert 'tokens_input' in columns
    assert 'tokens_output' in columns
    assert 'tokens_cache' in columns
    # Old tokens column should still exist for back-compat
    assert 'tokens' in columns
    conn.close()


def test_migration_adds_artifact_url_column(tmp_path: Path) -> None:
    """Migration should add url column to artifacts table."""
    db_path = tmp_path / "old-artifacts.db"

    # Create a minimal old-schema DB without the url column
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE artifacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id TEXT NOT NULL,
            name TEXT NOT NULL,
            artifact_type TEXT NOT NULL,
            path TEXT,
            content TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()

    # Run migration
    init_db(db_path)

    # Verify url column exists
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(artifacts)")
    columns = {row[1] for row in cursor.fetchall()}

    assert 'url' in columns
    conn.close()


def test_migration_adds_checkpoint_columns(tmp_path: Path) -> None:
    """Migration should add content_hash and input_versions columns to node_executions."""
    db_path = tmp_path / "old-checkpoint.db"

    # Create a minimal old-schema DB without checkpoint columns
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE node_executions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            node_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        )
    """)
    conn.commit()
    conn.close()

    # Run migration
    init_db(db_path)

    # Verify new columns exist
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(node_executions)")
    columns = {row[1] for row in cursor.fetchall()}

    assert 'content_hash' in columns
    assert 'input_versions' in columns
    conn.close()


def test_init_db_is_idempotent_and_adds_cache_hit_column_to_legacy_db(tmp_path: Path) -> None:
    """init_db should add cache_hit column to legacy DBs and be idempotent."""
    db_path = tmp_path / "legacy.db"

    # Create a legacy DB without cache_hit column
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE node_executions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            node_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        )
    """)
    conn.commit()
    conn.close()

    # Run init_db (should add cache_hit column)
    init_db(db_path)

    # Verify cache_hit column exists
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(node_executions)")
    columns = {row[1] for row in cursor.fetchall()}
    assert 'cache_hit' in columns
    conn.close()

    # Run init_db again (should not error — idempotent)
    init_db(db_path)

    # Verify cache_hit column still exists
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(node_executions)")
    columns = {row[1] for row in cursor.fetchall()}
    assert 'cache_hit' in columns
    conn.close()
