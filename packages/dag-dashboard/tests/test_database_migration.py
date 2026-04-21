"""Tests for database migrations."""
import sqlite3
from pathlib import Path
import tempfile
import pytest
from dag_dashboard.database import init_db


def test_database_cancelled_by_column():
    """Test that cancelled_by column migration works."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        
        # Create DB and initialize
        init_db(db_path)
        
        # Verify the column exists
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Query column info for workflow_runs
        cursor.execute("PRAGMA table_info(workflow_runs)")
        columns = [row[1] for row in cursor.fetchall()]
        
        assert "cancelled_by" in columns, "cancelled_by column should exist after migration"
        
        conn.close()
