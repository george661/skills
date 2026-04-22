"""Tests for pure query helpers used by both CLI and dashboard."""
import sqlite3
import pytest
from pathlib import Path


@pytest.fixture
def tmp_db(tmp_path):
    """Create a temporary database with seeded test data."""
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    
    # Create tables
    conn.execute("""
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id TEXT PRIMARY KEY,
            workflow_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TEXT NOT NULL,
            finished_at TEXT,
            inputs TEXT,
            outputs TEXT,
            error TEXT
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS node_executions (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            node_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TEXT,
            finished_at TEXT,
            inputs TEXT,
            outputs TEXT,
            error TEXT
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT,
            created_at TEXT NOT NULL
        )
    """)
    
    # Seed test data
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at, inputs) VALUES (?, ?, ?, ?, ?)",
        ("run_abc123", "deploy", "completed", "2026-04-22T10:00:00Z", '{"ticket": "ACME-123"}')
    )
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at, error) VALUES (?, ?, ?, ?, ?)",
        ("run_xyz789", "test", "failed", "2026-04-22T10:05:00Z", "ConnectionError: timeout")
    )
    conn.execute(
        "INSERT INTO node_executions (id, run_id, node_name, status, started_at, inputs, error) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("node_001", "run_abc123", "plan", "completed", "2026-04-22T10:01:00Z", '{"env": "prod"}', None)
    )
    conn.execute(
        "INSERT INTO events (run_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
        ("run_abc123", "error", '{"message": "API rate limit"}', "2026-04-22T10:02:00Z")
    )
    
    conn.commit()
    yield conn
    conn.close()


def test_search_all_composes_and_caps(tmp_db):
    """Test 13: search_all composes per-kind queries and applies global limit of 50."""
    from dag_executor.search_local import search_all
    
    # Search for "abc" - should match run_abc123
    results = search_all(tmp_db, q="abc", kinds=["runs", "nodes", "events"], limit=50)
    
    assert len(results) <= 50
    assert len(results) >= 1
    
    # Check that we got a run result
    run_results = [r for r in results if r["kind"] == "run"]
    assert len(run_results) == 1
    assert run_results[0]["run_id"] == "run_abc123"
    assert run_results[0]["workflow_name"] == "deploy"
    
    # Search for "ConnectionError" - should match the failed run's error
    results = search_all(tmp_db, q="Connection", kinds=["runs"], limit=10)
    assert len(results) == 1
    assert results[0]["kind"] == "run"
    assert results[0]["run_id"] == "run_xyz789"
    
    # Search with kinds filter - only runs
    results = search_all(tmp_db, q="abc", kinds=["runs"], limit=50)
    assert all(r["kind"] == "run" for r in results)
    
    # Test limit enforcement
    results = search_all(tmp_db, q="abc", kinds=["runs", "nodes", "events"], limit=1)
    assert len(results) <= 1
