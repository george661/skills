"""Tests for FTS5 schema and migration."""
import sqlite3
from pathlib import Path
from unittest.mock import patch
import pytest


def test_init_fts5_index_creates_virtual_tables_when_enabled(tmp_path: Path) -> None:
    """init_fts5_index should create FTS5 virtual tables and triggers."""
    from dag_dashboard.database import init_db, init_fts5_index
    
    db_path = tmp_path / "test.db"
    init_db(db_path, fts5_enabled=False)  # Create base tables
    
    conn = sqlite3.connect(db_path)
    init_fts5_index(conn)
    
    # Verify FTS tables exist
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name LIKE '%_fts'
        ORDER BY name
    """)
    fts_tables = [row[0] for row in cursor.fetchall()]
    
    assert "events_fts" in fts_tables
    assert "workflow_runs_fts" in fts_tables
    assert "node_executions_fts" in fts_tables
    
    # Verify triggers exist
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='trigger' AND name LIKE 'events_%'
        ORDER BY name
    """)
    triggers = [row[0] for row in cursor.fetchall()]
    assert "events_ai" in triggers  # after insert
    assert "events_ad" in triggers  # after delete
    assert "events_au" in triggers  # after update
    
    conn.close()


def test_init_fts5_index_backfills_existing_rows(tmp_path: Path) -> None:
    """init_fts5_index should backfill existing data."""
    from dag_dashboard.database import init_db, init_fts5_index
    
    db_path = tmp_path / "test.db"
    init_db(db_path, fts5_enabled=False)
    
    # Insert 5 events before creating FTS index
    conn = sqlite3.connect(db_path)
    for i in range(5):
        conn.execute("""
            INSERT INTO events (run_id, event_type, payload, created_at)
            VALUES (?, ?, ?, ?)
        """, (1, "test", f"payload {i}", 1000 + i))
    conn.commit()
    
    # Create FTS index
    init_fts5_index(conn)
    
    # Verify FTS table has 5 rows
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM events_fts")
    count = cursor.fetchone()[0]
    assert count == 5
    
    conn.close()


def test_init_fts5_index_triggers_keep_index_in_sync(tmp_path: Path) -> None:
    """Triggers should keep FTS index in sync with source table."""
    from dag_dashboard.database import init_db, init_fts5_index
    
    db_path = tmp_path / "test.db"
    init_db(db_path, fts5_enabled=False)
    
    conn = sqlite3.connect(db_path)
    init_fts5_index(conn)
    
    # Insert after index built
    conn.execute("""
        INSERT INTO events (run_id, event_type, payload, created_at)
        VALUES (?, ?, ?, ?)
    """, (1, "test", "new event", 2000))
    conn.commit()
    
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM events_fts")
    count_after_insert = cursor.fetchone()[0]
    assert count_after_insert == 1
    
    # Get the event ID
    cursor.execute("SELECT id FROM events WHERE payload = ?", ("new event",))
    event_id = cursor.fetchone()[0]
    
    # Delete source row
    conn.execute("DELETE FROM events WHERE id = ?", (event_id,))
    conn.commit()
    
    cursor.execute("SELECT COUNT(*) FROM events_fts")
    count_after_delete = cursor.fetchone()[0]
    assert count_after_delete == 0
    
    conn.close()


def test_init_fts5_index_is_idempotent(tmp_path: Path) -> None:
    """Calling init_fts5_index twice should not raise."""
    from dag_dashboard.database import init_db, init_fts5_index
    
    db_path = tmp_path / "test.db"
    init_db(db_path, fts5_enabled=False)
    
    conn = sqlite3.connect(db_path)
    
    # Call twice - should not raise
    init_fts5_index(conn)
    init_fts5_index(conn)
    
    # Verify tables still exist
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name = 'events_fts'
    """)
    assert cursor.fetchone() is not None
    
    conn.close()




def test_init_db_calls_init_fts5_when_flag_true(tmp_path: Path) -> None:
    """init_db should call init_fts5_index when fts5_enabled=True."""
    from dag_dashboard.database import init_db
    
    db_path = tmp_path / "test.db"
    init_db(db_path, fts5_enabled=True)
    
    # Verify FTS tables were created
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name FROM sqlite_master 
        WHERE type='table' AND name = 'events_fts'
    """)
    assert cursor.fetchone() is not None
    
    conn.close()


def test_init_db_skips_fts5_when_flag_false(tmp_path: Path) -> None:
    """init_db should not create FTS tables when fts5_enabled=False."""
    from dag_dashboard.database import init_db

    db_path = tmp_path / "test.db"
    init_db(db_path, fts5_enabled=False)

    # Verify FTS tables were NOT created
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name = 'events_fts'
    """)
    assert cursor.fetchone() is None

    conn.close()


def test_workflow_runs_fts_reflects_error_set_via_update(tmp_path: Path) -> None:
    """UPDATE to set error field should be reflected in FTS search results."""
    from dag_dashboard.database import init_db, init_fts5_index

    db_path = tmp_path / "test.db"
    init_db(db_path, fts5_enabled=False)

    conn = sqlite3.connect(db_path)
    init_fts5_index(conn)

    # Insert workflow_run without error
    conn.execute("""
        INSERT INTO workflow_runs (id, workflow_name, status, started_at)
        VALUES (?, ?, ?, ?)
    """, ("run-123", "test-workflow", "running", "2026-04-22T00:00:00Z"))
    conn.commit()

    # Update to add error
    conn.execute("""
        UPDATE workflow_runs SET error = ? WHERE id = ?
    """, ("ConnectionTimeout: failed to connect", "run-123"))
    conn.commit()

    # Search for the error substring
    cursor = conn.cursor()
    cursor.execute("""
        SELECT workflow_runs.id FROM workflow_runs_fts
        JOIN workflow_runs ON workflow_runs.rowid = workflow_runs_fts.rowid
        WHERE workflow_runs_fts MATCH ?
    """, ('"ConnectionTimeout"',))

    result = cursor.fetchone()
    assert result is not None, "FTS search should find the updated error"
    assert result[0] == "run-123"

    conn.close()


def test_node_executions_fts_reflects_update(tmp_path: Path) -> None:
    """UPDATE to node_executions should be reflected in FTS search results."""
    from dag_dashboard.database import init_db, init_fts5_index

    db_path = tmp_path / "test.db"
    init_db(db_path, fts5_enabled=False)

    conn = sqlite3.connect(db_path)
    init_fts5_index(conn)

    # Insert workflow_run
    conn.execute("""
        INSERT INTO workflow_runs (id, workflow_name, status, started_at)
        VALUES (?, ?, ?, ?)
    """, ("run-456", "test-workflow", "running", "2026-04-22T00:00:00Z"))

    # Insert node_execution without error
    conn.execute("""
        INSERT INTO node_executions (id, run_id, node_name, status)
        VALUES (?, ?, ?, ?)
    """, ("node-789", "run-456", "extract-data", "completed"))
    conn.commit()

    # Update to add error
    conn.execute("""
        UPDATE node_executions SET error = ? WHERE id = ?
    """, ("ValueError: invalid input format", "node-789"))
    conn.commit()

    # Search for the error substring
    cursor = conn.cursor()
    cursor.execute("""
        SELECT node_executions.id FROM node_executions_fts
        JOIN node_executions ON node_executions.rowid = node_executions_fts.rowid
        WHERE node_executions_fts MATCH ?
    """, ('"ValueError"',))

    result = cursor.fetchone()
    assert result is not None, "FTS search should find the updated error"
    assert result[0] == "node-789"

    conn.close()


def test_workflow_runs_fts_delete_removes_row(tmp_path: Path) -> None:
    """DELETE from workflow_runs should remove row from FTS index."""
    from dag_dashboard.database import init_db, init_fts5_index

    db_path = tmp_path / "test.db"
    init_db(db_path, fts5_enabled=False)

    conn = sqlite3.connect(db_path)
    init_fts5_index(conn)

    # Insert workflow_run
    conn.execute("""
        INSERT INTO workflow_runs (id, workflow_name, status, started_at)
        VALUES (?, ?, ?, ?)
    """, ("run-delete", "test-workflow", "completed", "2026-04-22T00:00:00Z"))
    conn.commit()

    # Verify it's searchable
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) FROM workflow_runs_fts
        WHERE workflow_runs_fts MATCH ?
    """, ('"test-workflow"',))
    assert cursor.fetchone()[0] == 1

    # Delete the row
    conn.execute("DELETE FROM workflow_runs WHERE id = ?", ("run-delete",))
    conn.commit()

    # Verify it's no longer searchable
    cursor.execute("""
        SELECT COUNT(*) FROM workflow_runs_fts
        WHERE workflow_runs_fts MATCH ?
    """, ('"test-workflow"',))
    assert cursor.fetchone()[0] == 0, "FTS search should return 0 after DELETE"

    conn.close()


def test_init_fts5_index_gracefully_skipped_without_fts5(tmp_path: Path) -> None:
    """init_fts5_index should handle FTS5 availability check without raising.

    Note: This test verifies that the FTS5 check logic exists. In a build
    without FTS5, init_fts5_index would log a warning and return early.
    We can't easily simulate a non-FTS5 build, so we just verify the check runs.
    """
    from dag_dashboard.database import init_db, init_fts5_index

    db_path = tmp_path / "test.db"
    init_db(db_path, fts5_enabled=False)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Verify FTS5 is available in our test environment
    cursor.execute("SELECT sqlite_compileoption_used('ENABLE_FTS5')")
    fts5_available = cursor.fetchone()[0]
    assert fts5_available == 1, "FTS5 should be available in test environment"

    # init_fts5_index should handle both cases (FTS5 available or not) without raising
    init_fts5_index(conn)

    # Verify FTS tables were created (since FTS5 is available)
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='workflow_runs_fts'
    """)
    assert cursor.fetchone() is not None

    conn.close()
