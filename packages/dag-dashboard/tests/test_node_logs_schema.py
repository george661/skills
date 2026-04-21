"""Tests for node_logs table schema, migration, and cascade delete."""
import sqlite3
import tempfile
from pathlib import Path
import pytest

from dag_dashboard.database import init_db


def test_node_logs_table_created():
    """Verify node_logs table exists with correct columns."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get table info
        cursor.execute("PRAGMA table_info(node_logs)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}
        
        # Verify expected columns exist
        assert "run_id" in columns
        assert "node_id" in columns
        assert "stream" in columns
        assert "sequence" in columns
        assert "line" in columns
        assert "created_at" in columns
        
        # Verify foreign key constraint
        cursor.execute("PRAGMA foreign_key_list(node_logs)")
        fks = cursor.fetchall()
        assert len(fks) == 1
        assert fks[0][2] == "workflow_runs"  # References workflow_runs table
        assert fks[0][3] == "run_id"  # Foreign key column
        
        conn.close()


def test_node_logs_index_exists():
    """Verify index on (run_id, node_id, sequence) exists."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Check for index in sqlite_master
        cursor.execute("""
            SELECT name FROM sqlite_master
            WHERE type='index' AND name='idx_node_logs_run_node_seq'
        """)
        result = cursor.fetchone()
        
        assert result is not None
        assert result[0] == "idx_node_logs_run_node_seq"
        
        conn.close()


def test_migration_idempotent():
    """Verify init_db can be called multiple times without error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        
        # Call init_db twice
        init_db(db_path)
        init_db(db_path)  # Should not raise
        
        # Verify table still exists
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(node_logs)")
        columns = cursor.fetchall()
        assert len(columns) > 0
        conn.close()


def test_cascade_delete_removes_node_logs():
    """Verify ON DELETE CASCADE removes node_logs when workflow_run is deleted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        
        conn = sqlite3.connect(db_path)
        # Enable foreign keys (required for CASCADE)
        conn.execute("PRAGMA foreign_keys=ON")
        cursor = conn.cursor()
        
        # Insert a workflow run
        run_id = "test-run-123"
        cursor.execute("""
            INSERT INTO workflow_runs (id, workflow_name, status, started_at)
            VALUES (?, ?, ?, ?)
        """, (run_id, "test-workflow", "running", "2026-04-21T12:00:00Z"))
        
        # Insert node logs
        cursor.execute("""
            INSERT INTO node_logs (run_id, node_id, stream, sequence, line, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (run_id, "node-1", "stdout", 1, "Hello", "2026-04-21T12:00:01Z"))
        
        cursor.execute("""
            INSERT INTO node_logs (run_id, node_id, stream, sequence, line, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (run_id, "node-1", "stdout", 2, "World", "2026-04-21T12:00:02Z"))
        
        conn.commit()
        
        # Verify logs exist
        cursor.execute("SELECT COUNT(*) FROM node_logs WHERE run_id = ?", (run_id,))
        assert cursor.fetchone()[0] == 2
        
        # Delete the workflow run
        cursor.execute("DELETE FROM workflow_runs WHERE id = ?", (run_id,))
        conn.commit()
        
        # Verify node_logs are cascaded deleted
        cursor.execute("SELECT COUNT(*) FROM node_logs WHERE run_id = ?", (run_id,))
        assert cursor.fetchone()[0] == 0
        
        conn.close()
