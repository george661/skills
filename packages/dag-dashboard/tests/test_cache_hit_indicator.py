"""Tests for cache_hit indicator pipeline (executor → event → DB → API → response model)."""
import sqlite3
from pathlib import Path
from dag_dashboard.database import init_db
from dag_dashboard.queries import get_node, list_nodes, insert_run


def test_node_executions_table_has_cache_hit_column(tmp_path: Path) -> None:
    """node_executions table should have cache_hit column."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA table_info(node_executions)")
    columns = {row[1] for row in cursor.fetchall()}
    conn.close()
    
    assert 'cache_hit' in columns


def test_cache_hit_persists_to_db(tmp_path: Path) -> None:
    """When inserting a node with cache_hit=True, it should persist to DB."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    # Insert workflow run
    insert_run(
        db_path=db_path,
        run_id="run-1",
        workflow_name="test-workflow",
        status="running",
        started_at="2026-04-20T12:00:00Z"
    )
    
    # Insert node execution with cache_hit
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO node_executions (id, run_id, node_name, status, cache_hit)
        VALUES (?, ?, ?, ?, ?)
    """, ("exec-1", "run-1", "cached-node", "completed", 1))
    conn.commit()
    conn.close()
    
    # Query DB directly
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT cache_hit FROM node_executions WHERE id = ?", ("exec-1",))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[0] == 1


def test_cache_hit_defaults_to_zero(tmp_path: Path) -> None:
    """When inserting a node without cache_hit, it should default to 0."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    insert_run(
        db_path=db_path,
        run_id="run-2",
        workflow_name="test-workflow",
        status="running",
        started_at="2026-04-20T12:00:00Z"
    )
    
    # Insert node execution without cache_hit field
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO node_executions (id, run_id, node_name, status)
        VALUES (?, ?, ?, ?)
    """, ("exec-2", "run-2", "fresh-node", "completed"))
    conn.commit()
    conn.close()
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT cache_hit FROM node_executions WHERE id = ?", ("exec-2",))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[0] == 0


def test_get_node_returns_cache_hit_field(tmp_path: Path) -> None:
    """get_node should return cache_hit field."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    insert_run(
        db_path=db_path,
        run_id="run-3",
        workflow_name="test-workflow",
        status="running",
        started_at="2026-04-20T12:00:00Z"
    )
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO node_executions (id, run_id, node_name, status, cache_hit)
        VALUES (?, ?, ?, ?, ?)
    """, ("exec-3", "run-3", "node-3", "completed", 1))
    conn.commit()
    conn.close()
    
    result = get_node(db_path, "exec-3")
    
    assert result is not None
    assert "cache_hit" in result
    assert result["cache_hit"] == 1  # SQLite stores bool as int


def test_list_nodes_includes_cache_hit(tmp_path: Path) -> None:
    """list_nodes should include cache_hit in responses."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    insert_run(
        db_path=db_path,
        run_id="run-4",
        workflow_name="test-workflow",
        status="running",
        started_at="2026-04-20T12:00:00Z"
    )
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO node_executions (id, run_id, node_name, status, cache_hit)
        VALUES (?, ?, ?, ?, ?)
    """, ("exec-4", "run-4", "node-4", "completed", 1))
    conn.commit()
    conn.close()
    
    nodes = list_nodes(db_path, "run-4")
    
    assert len(nodes) == 1
    assert "cache_hit" in nodes[0]
    assert nodes[0]["cache_hit"] == 1
