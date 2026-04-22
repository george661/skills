"""Pure query helpers for local search (CLI and dashboard)."""
import sqlite3
from typing import Any, Dict, List


def search_runs(conn: sqlite3.Connection, q: str, limit: int) -> List[Dict[str, Any]]:
    """Search workflow_runs for matching id substring, workflow_name, inputs, or error.

    Returns list of dicts with keys: kind, run_id, workflow_name, snippet, started_at.
    """
    results = []
    
    # Query with parameterized LIKE - use %q% for id too to catch run_<prefix>
    cursor = conn.execute(
        """
        SELECT id, workflow_name, started_at, inputs, error
        FROM workflow_runs
        WHERE id LIKE ? OR workflow_name LIKE ? OR error LIKE ? OR inputs LIKE ?
        LIMIT ?
        """,
        (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%", limit)
    )
    
    for row in cursor.fetchall():
        run_id, workflow_name, started_at, inputs, error = row
        
        # Determine which field matched for snippet
        snippet = ""
        if q in run_id:
            snippet = run_id[:120]
        elif inputs and q in inputs:
            snippet = inputs[:120]
        elif error and q in error:
            snippet = error[:120]
        else:
            snippet = workflow_name[:120]
        
        results.append({
            "kind": "run",
            "run_id": run_id,
            "workflow_name": workflow_name,
            "snippet": snippet,
            "started_at": started_at
        })
    
    return results


def search_nodes(conn: sqlite3.Connection, q: str, limit: int) -> List[Dict[str, Any]]:
    """Search node_executions for matching node_name, inputs, or error.
    
    Returns list of dicts with keys: kind, run_id, node_name, snippet.
    """
    results = []
    
    cursor = conn.execute(
        """
        SELECT id, run_id, node_name, inputs, error
        FROM node_executions
        WHERE node_name LIKE ? OR error LIKE ? OR inputs LIKE ?
        LIMIT ?
        """,
        (f"%{q}%", f"%{q}%", f"%{q}%", limit)
    )
    
    for row in cursor.fetchall():
        node_id, run_id, node_name, inputs, error = row
        
        # Determine which field matched for snippet
        snippet = ""
        if error and q in error:
            snippet = error[:120]
        elif inputs and q in inputs:
            snippet = inputs[:120]
        else:
            snippet = node_name[:120]
        
        results.append({
            "kind": "node",
            "run_id": run_id,
            "node_name": node_name,
            "snippet": snippet
        })
    
    return results


def search_events(conn: sqlite3.Connection, q: str, limit: int) -> List[Dict[str, Any]]:
    """Search events for matching event_type or payload.
    
    Returns list of dicts with keys: kind, run_id, event_type, snippet.
    """
    results = []
    
    cursor = conn.execute(
        """
        SELECT run_id, event_type, payload
        FROM events
        WHERE event_type LIKE ? OR payload LIKE ?
        LIMIT ?
        """,
        (f"%{q}%", f"%{q}%", limit)
    )
    
    for row in cursor.fetchall():
        run_id, event_type, payload = row
        
        # Determine which field matched for snippet
        snippet = ""
        if payload and q in payload:
            snippet = payload[:120]
        else:
            snippet = event_type[:120]
        
        results.append({
            "kind": "event",
            "run_id": run_id,
            "event_type": event_type,
            "snippet": snippet
        })
    
    return results


def search_all(
    conn: sqlite3.Connection,
    q: str,
    kinds: List[str],
    limit: int
) -> List[Dict[str, Any]]:
    """Compose per-kind queries and apply global limit.
    
    Args:
        conn: SQLite connection
        q: Search query string
        kinds: List of kinds to search (e.g., ["runs", "nodes", "events"])
        limit: Maximum total results across all kinds
    
    Returns:
        List of result dicts, capped at limit
    """
    all_results = []
    
    # Query each kind with a per-kind limit of 50 to allow interleaving
    per_kind_limit = 50
    
    if "runs" in kinds:
        all_results.extend(search_runs(conn, q, per_kind_limit))
    
    if "nodes" in kinds:
        all_results.extend(search_nodes(conn, q, per_kind_limit))
    
    if "events" in kinds:
        all_results.extend(search_events(conn, q, per_kind_limit))
    
    # Apply global limit
    return all_results[:limit]
