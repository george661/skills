"""Tests for orchestrator_sessions table schema and migrations."""
import pytest
import sqlite3
from pathlib import Path
from dag_dashboard.database import init_db


def test_orchestrator_sessions_table_created(tmp_path: Path):
    """Test that orchestrator_sessions table is created on fresh DB."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='orchestrator_sessions'"
    )
    result = cursor.fetchone()
    
    assert result is not None, "orchestrator_sessions table should exist"
    
    # Verify schema
    cursor.execute("PRAGMA table_info(orchestrator_sessions)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}
    
    assert "conversation_id" in columns
    assert "session_uuid" in columns
    assert "last_active" in columns
    assert "status" in columns
    assert "model" in columns
    assert "created_at" in columns
    
    # Verify index
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_orch_sessions_last_active'"
    )
    index_result = cursor.fetchone()
    assert index_result is not None, "Index on last_active should exist"


def test_orchestrator_sessions_primary_key(tmp_path: Path):
    """Test that conversation_id is the primary key."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(orchestrator_sessions)")
    columns = list(cursor.fetchall())
    
    # Find conversation_id column (column index 1 is name, index 5 is pk flag)
    conv_id_col = [col for col in columns if col[1] == "conversation_id"][0]
    assert conv_id_col[5] == 1, "conversation_id should be primary key"
