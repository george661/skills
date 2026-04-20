"""Tests for channel_states table schema and migration."""
import sqlite3
import tempfile
from pathlib import Path
import pytest

from dag_dashboard.database import init_db


def test_channel_states_table_created():
    """Database migration adds channel_states table."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        init_db(db_path)
        
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            
            # Check table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='channel_states'"
            )
            result = cursor.fetchone()
            assert result is not None, "channel_states table not found"
            
            # Check expected columns
            cursor.execute("PRAGMA table_info(channel_states)")
            columns = {row[1]: row[2] for row in cursor.fetchall()}
            
            assert "run_id" in columns
            assert "channel_key" in columns
            assert "channel_type" in columns
            assert "reducer_strategy" in columns
            assert "value_json" in columns
            assert "version" in columns
            assert "writers_json" in columns
            assert "conflict_json" in columns
            assert "updated_at" in columns
        finally:
            conn.close()


def test_channel_states_migration_idempotent():
    """Running init_db twice doesn't fail."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        
        # First init
        init_db(db_path)
        
        # Second init (should not raise)
        init_db(db_path)
        
        # Table should still exist with correct schema
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(channel_states)")
            columns = [row[1] for row in cursor.fetchall()]
            assert "run_id" in columns
            assert "channel_key" in columns
        finally:
            conn.close()
