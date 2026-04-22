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
