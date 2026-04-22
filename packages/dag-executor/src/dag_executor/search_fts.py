"""Full-text search using SQLite FTS5."""
import sqlite3
from typing import Any, Dict, List, Optional


def _sanitize_query(query: str) -> str:
    """Sanitize user query to avoid FTS5 syntax errors.
    
    Wraps the query in double quotes to treat special chars literally.
    """
    query = query.strip()
    if not query:
        return ""
    # Escape double quotes in the query
    query = query.replace('"', '""')
    return f'"{query}"'


def search_events_fts(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Search events using FTS5 index.
    
    Args:
        conn: Database connection
        query: Search query string
        limit: Maximum results to return
        
    Returns:
        List of result dicts with keys: kind, run_id, snippet, event_type
    """
    sanitized = _sanitize_query(query)
    if not sanitized:
        return []
    
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            events.id,
            events.run_id,
            events.event_type,
            snippet(events_fts, 0, '', '', '...', 32) as snippet,
            bm25(events_fts) as rank
        FROM events_fts
        JOIN events ON events.id = events_fts.rowid
        WHERE events_fts MATCH ?
        ORDER BY rank
        LIMIT ?
    """, (sanitized, limit))
    
    results = []
    for row in cursor.fetchall():
        _event_id, run_id, event_type, snippet, rank = row
        results.append({
            "kind": "event",
            "run_id": run_id,
            "event_type": event_type,
            "snippet": snippet[:120],  # Truncate to 120 chars
            "relevance": rank,
        })

    return results


def search_runs_fts(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Search workflow_runs using FTS5 index.
    
    Args:
        conn: Database connection
        query: Search query string
        limit: Maximum results to return
        
    Returns:
        List of result dicts with keys: kind, run_id, snippet
    """
    sanitized = _sanitize_query(query)
    if not sanitized:
        return []
    
    cursor = conn.cursor()
    # External content - note: need to join via rowid since FTS doesn't store id column
    cursor.execute("""
        SELECT
            workflow_runs.id,
            workflow_runs.workflow_name,
            COALESCE(workflow_runs.workflow_name, '') || ' ' ||
            COALESCE(workflow_runs.inputs, '') || ' ' ||
            COALESCE(workflow_runs.error, '') as snippet,
            bm25(workflow_runs_fts) as rank
        FROM workflow_runs_fts
        JOIN workflow_runs ON workflow_runs.rowid = workflow_runs_fts.rowid
        WHERE workflow_runs_fts MATCH ?
        ORDER BY rank
        LIMIT ?
    """, (sanitized, limit))
    
    results = []
    for row in cursor.fetchall():
        run_id, workflow_name, snippet, rank = row
        results.append({
            "kind": "run",
            "run_id": run_id,
            "workflow_name": workflow_name,
            "snippet": snippet[:120] if snippet else "",
            "relevance": rank,
        })

    return results


def search_nodes_fts(
    conn: sqlite3.Connection,
    query: str,
    limit: int = 20
) -> List[Dict[str, Any]]:
    """Search node_executions using FTS5 index.
    
    Args:
        conn: Database connection
        query: Search query string
        limit: Maximum results to return
        
    Returns:
        List of result dicts with keys: kind, run_id, node_name, snippet
    """
    sanitized = _sanitize_query(query)
    if not sanitized:
        return []
    
    cursor = conn.cursor()
    # External content - join via rowid
    cursor.execute("""
        SELECT
            node_executions.id,
            node_executions.run_id,
            node_executions.node_name,
            COALESCE(node_executions.node_name, '') || ' ' ||
            COALESCE(node_executions.inputs, '') || ' ' ||
            COALESCE(node_executions.error, '') as snippet,
            bm25(node_executions_fts) as rank
        FROM node_executions_fts
        JOIN node_executions ON node_executions.rowid = node_executions_fts.rowid
        WHERE node_executions_fts MATCH ?
        ORDER BY rank
        LIMIT ?
    """, (sanitized, limit))
    
    results = []
    for row in cursor.fetchall():
        _node_id, run_id, node_name, snippet, rank = row
        results.append({
            "kind": "node",
            "run_id": run_id,
            "node_name": node_name,
            "snippet": snippet[:120] if snippet else "",
            "relevance": rank,
        })

    return results


def search_all_fts(
    conn: sqlite3.Connection,
    query: str,
    kinds: Optional[List[str]] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Search across all tables using FTS5 indexes.

    Args:
        conn: Database connection
        query: Search query string
        kinds: List of kinds to search. Accepts plural forms from the LIKE
            router (``"runs"``, ``"nodes"``, ``"events"``). If None, searches all.
        limit: Maximum total results to return

    Returns:
        Combined list of results from all search surfaces
    """
    if kinds is None:
        kinds = ["runs", "nodes", "events"]

    per_kind_limit = max(limit // len(kinds), 10) if kinds else limit

    results: List[Dict[str, Any]] = []
    if "events" in kinds:
        results.extend(search_events_fts(conn, query, limit=per_kind_limit))
    if "runs" in kinds:
        results.extend(search_runs_fts(conn, query, limit=per_kind_limit))
    if "nodes" in kinds:
        results.extend(search_nodes_fts(conn, query, limit=per_kind_limit))

    return results[:limit]
