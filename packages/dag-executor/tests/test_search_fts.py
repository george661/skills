"""Tests for FTS5 full-text search functionality."""
import sqlite3
from pathlib import Path
import pytest


def test_search_events_fts_returns_payload_matches(tmp_path: Path) -> None:
    """FTS query should return events matching payload tokens."""
    from dag_executor.search_fts import search_events_fts
    
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    
    # Create tables and FTS index
    conn.execute("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            run_id INTEGER,
            event_type TEXT,
            payload TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE events_fts USING fts5(
            payload, event_type, run_id UNINDEXED,
            content='events', content_rowid='id'
        )
    """)
    conn.execute("""
        INSERT INTO events (run_id, event_type, payload) VALUES
        (1, 'workflow.start', 'Starting workflow with rate_limit config'),
        (2, 'node.complete', 'Process finished successfully'),
        (3, 'error', 'rate_limit exceeded for API call')
    """)
    conn.execute("""
        INSERT INTO events_fts(rowid, payload, event_type)
        SELECT id, payload, event_type FROM events
    """)
    conn.commit()
    
    # Search for "rate_limit"
    results = search_events_fts(conn, "rate_limit", limit=10)
    
    assert len(results) == 2
    assert all(r["kind"] == "event" for r in results)
    run_ids = [r["run_id"] for r in results]
    assert 1 in run_ids
    assert 3 in run_ids
    
    conn.close()


def test_search_events_fts_relevance_ordering(tmp_path: Path) -> None:
    """Events with repeated tokens should rank higher (BM25)."""
    from dag_executor.search_fts import search_events_fts
    
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    
    conn.execute("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            run_id INTEGER,
            event_type TEXT,
            payload TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE events_fts USING fts5(
            payload, event_type,
            content='events', content_rowid='id'
        )
    """)
    conn.execute("""
        INSERT INTO events (run_id, event_type, payload) VALUES
        (1, 'error', 'timeout once'),
        (2, 'error', 'timeout timeout timeout multiple times')
    """)
    conn.execute("""
        INSERT INTO events_fts(rowid, payload, event_type)
        SELECT id, payload, event_type FROM events
    """)
    conn.commit()
    
    results = search_events_fts(conn, "timeout", limit=10)
    
    assert len(results) == 2
    # The event with repeated "timeout" should rank first
    assert results[0]["run_id"] == 2
    assert results[1]["run_id"] == 1
    
    conn.close()


def test_search_events_fts_snippet_truncated(tmp_path: Path) -> None:
    """Snippets should be truncated to reasonable length."""
    from dag_executor.search_fts import search_events_fts
    
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    
    conn.execute("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            run_id INTEGER,
            event_type TEXT,
            payload TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE events_fts USING fts5(
            payload, event_type,
            content='events', content_rowid='id'
        )
    """)
    
    long_payload = "x " * 200 + " needle " + "y " * 200
    conn.execute(
        "INSERT INTO events (run_id, event_type, payload) VALUES (?, ?, ?)",
        (1, "test", long_payload)
    )
    conn.execute("""
        INSERT INTO events_fts(rowid, payload, event_type)
        SELECT id, payload, event_type FROM events
    """)
    conn.commit()
    
    results = search_events_fts(conn, "needle", limit=10)
    
    assert len(results) == 1
    snippet = results[0]["snippet"]
    assert len(snippet) <= 120
    assert "needle" in snippet.lower()
    
    conn.close()


def test_search_runs_fts_matches_name_and_error(tmp_path: Path) -> None:
    """FTS should search across workflow_name, inputs, and error."""
    from dag_executor.search_fts import search_runs_fts
    
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    
    conn.execute("""
        CREATE TABLE workflow_runs (
            id INTEGER PRIMARY KEY,
            workflow_name TEXT,
            inputs TEXT,
            error TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE workflow_runs_fts USING fts5(
            workflow_name, inputs, error, id UNINDEXED,
            content='workflow_runs', content_rowid='id'
        )
    """)
    conn.execute("""
        INSERT INTO workflow_runs (workflow_name, inputs, error) VALUES
        ('process_data', 'file=data.csv', NULL),
        ('validate', 'schema=v2', 'validation failed'),
        ('export', 'format=json', NULL)
    """)
    conn.execute("""
        INSERT INTO workflow_runs_fts(rowid, workflow_name, inputs, error)
        SELECT id, workflow_name, inputs, error FROM workflow_runs
    """)
    conn.commit()
    
    results = search_runs_fts(conn, "validation", limit=10)
    
    assert len(results) == 1
    assert results[0]["kind"] == "run"
    assert results[0]["run_id"] == 2
    
    conn.close()


def test_search_nodes_fts_matches_node_name(tmp_path: Path) -> None:
    """FTS should search node_executions."""
    from dag_executor.search_fts import search_nodes_fts
    
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    
    conn.execute("""
        CREATE TABLE node_executions (
            id INTEGER PRIMARY KEY,
            run_id INTEGER,
            node_name TEXT,
            inputs TEXT,
            error TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE node_executions_fts USING fts5(
            node_name, inputs, error, id UNINDEXED, run_id UNINDEXED,
            content='node_executions', content_rowid='id'
        )
    """)
    conn.execute("""
        INSERT INTO node_executions (run_id, node_name, inputs, error) VALUES
        (1, 'fetch_data', 'url=example.com', NULL),
        (1, 'transform', 'operation=filter', NULL),
        (2, 'validate', 'strict=true', 'schema mismatch')
    """)
    conn.execute("""
        INSERT INTO node_executions_fts(rowid, node_name, inputs, error)
        SELECT id, node_name, inputs, error FROM node_executions
    """)
    conn.commit()
    
    results = search_nodes_fts(conn, "schema", limit=10)
    
    assert len(results) == 1
    assert results[0]["kind"] == "node"
    assert results[0]["run_id"] == 2
    
    conn.close()


def test_search_all_fts_composes_and_caps(tmp_path: Path) -> None:
    """search_all_fts should aggregate results and respect limit."""
    from dag_executor.search_fts import search_all_fts
    
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    
    # Create all tables and FTS indexes
    conn.execute("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            run_id INTEGER,
            event_type TEXT,
            payload TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE events_fts USING fts5(
            payload, event_type,
            content='events', content_rowid='id'
        )
    """)
    conn.execute("""
        CREATE TABLE workflow_runs (
            id INTEGER PRIMARY KEY,
            workflow_name TEXT,
            inputs TEXT,
            error TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE workflow_runs_fts USING fts5(
            workflow_name, inputs, error,
            content='workflow_runs', content_rowid='id'
        )
    """)
    conn.execute("""
        CREATE TABLE node_executions (
            id INTEGER PRIMARY KEY,
            run_id INTEGER,
            node_name TEXT,
            inputs TEXT,
            error TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE node_executions_fts USING fts5(
            node_name, inputs, error,
            content='node_executions', content_rowid='id'
        )
    """)
    
    # Insert test data
    conn.execute("INSERT INTO events (run_id, event_type, payload) VALUES (1, 'test', 'error occurred')")
    conn.execute("INSERT INTO events_fts(rowid, payload, event_type) SELECT id, payload, event_type FROM events")
    conn.execute("INSERT INTO workflow_runs (workflow_name, inputs, error) VALUES ('test', 'x=1', 'error here')")
    conn.execute("INSERT INTO workflow_runs_fts(rowid, workflow_name, inputs, error) SELECT id, workflow_name, inputs, error FROM workflow_runs")
    conn.execute("INSERT INTO node_executions (run_id, node_name, inputs, error) VALUES (1, 'test', 'y=2', 'error too')")
    conn.execute("INSERT INTO node_executions_fts(rowid, node_name, inputs, error) SELECT id, node_name, inputs, error FROM node_executions")
    conn.commit()
    
    results = search_all_fts(conn, "error", limit=2)
    
    assert len(results) <= 2
    kinds = {r["kind"] for r in results}
    assert len(kinds) > 0  # At least one kind
    
    conn.close()


def test_search_fts_sanitizes_special_chars(tmp_path: Path) -> None:
    """Special FTS5 chars should be sanitized to avoid syntax errors."""
    from dag_executor.search_fts import search_events_fts
    
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    
    conn.execute("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            run_id INTEGER,
            event_type TEXT,
            payload TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE events_fts USING fts5(
            payload, event_type,
            content='events', content_rowid='id'
        )
    """)
    conn.execute("""
        INSERT INTO events (run_id, event_type, payload) VALUES
        (1, 'test', 'test-case: with (parentheses)')
    """)
    conn.execute("""
        INSERT INTO events_fts(rowid, payload, event_type)
        SELECT id, payload, event_type FROM events
    """)
    conn.commit()
    
    # These queries contain FTS5 special chars and should not raise errors
    try:
        search_events_fts(conn, "test-case", limit=10)
        search_events_fts(conn, "test:case", limit=10)
        search_events_fts(conn, "test (parentheses)", limit=10)
    except Exception as e:
        pytest.fail(f"Query with special chars raised error: {e}")
    
    conn.close()


def test_search_fts_empty_query_returns_empty(tmp_path: Path) -> None:
    """Empty or whitespace-only query should return empty list."""
    from dag_executor.search_fts import search_events_fts
    
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(db_path)
    
    conn.execute("""
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            run_id INTEGER,
            event_type TEXT,
            payload TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE events_fts USING fts5(
            payload, event_type,
            content='events', content_rowid='id'
        )
    """)
    conn.commit()
    
    assert search_events_fts(conn, "", limit=10) == []
    assert search_events_fts(conn, "   ", limit=10) == []
    
    conn.close()
