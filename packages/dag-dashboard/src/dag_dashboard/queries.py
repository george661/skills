"""Database query helpers with pagination and filtering."""
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import SortBy, RunStatus


# JSON columns that need deserialization when reading from SQLite
JSON_COLUMNS = {"inputs", "outputs", "metadata", "depends_on"}


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    """Convert sqlite3.Row to dict, deserializing JSON columns."""
    d = dict(row)
    for col in JSON_COLUMNS:
        if col in d and d[col] is not None:
            d[col] = json.loads(d[col])
    return d


def get_connection(db_path: Path) -> sqlite3.Connection:
    """Get database connection with foreign keys enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    # Foreign key constraints must be enabled on each connection
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def insert_run(
    db_path: Path,
    run_id: str,
    workflow_name: str,
    status: str,
    started_at: str,
    inputs: Optional[Dict[str, Any]] = None,
    workflow_definition: Optional[str] = None,
) -> str:
    """Insert a new workflow run."""
    # Validate workflow_name at query level (defense in depth)
    if not re.match(r"^[a-zA-Z0-9-]+$", workflow_name):
        raise ValueError("workflow_name must contain only alphanumeric characters and hyphens")

    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO workflow_runs (id, workflow_name, status, started_at, inputs, workflow_definition)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, workflow_name, status, started_at, json.dumps(inputs) if inputs else None, workflow_definition)
        )
        conn.commit()
        return run_id
    finally:
        conn.close()


def update_run(
    db_path: Path,
    run_id: str,
    status: Optional[str] = None,
    finished_at: Optional[str] = None,
    outputs: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    """Update workflow run fields."""
    conn = get_connection(db_path)
    try:
        # Build dynamic update query based on provided fields
        fields = []
        values = []
        
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if finished_at is not None:
            fields.append("finished_at = ?")
            values.append(finished_at)
        if outputs is not None:
            fields.append("outputs = ?")
            values.append(json.dumps(outputs))
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        
        if not fields:
            return
        
        values.append(run_id)
        query = f"UPDATE workflow_runs SET {', '.join(fields)} WHERE id = ?"
        conn.execute(query, values)
        conn.commit()
    finally:
        conn.close()


def get_run(db_path: Path, run_id: str) -> Optional[Dict[str, Any]]:
    """Get a single workflow run by ID."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT * FROM workflow_runs WHERE id = ?",
            (run_id,)
        )
        row = cursor.fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def list_runs(
    db_path: Path,
    limit: int = 50,
    offset: int = 0,
    status: Optional[RunStatus] = None,
    sort_by: SortBy = SortBy.STARTED_AT,
    name: Optional[str] = None,
    started_after: Optional[str] = None,
    started_before: Optional[str] = None,
) -> Dict[str, Any]:
    """List workflow runs with pagination and filtering."""
    # Validate sort_by is from whitelist enum
    if isinstance(sort_by, str):
        try:
            sort_by = SortBy(sort_by)
        except ValueError:
            raise ValueError(f"Invalid sort_by value. Must be one of: {[e.value for e in SortBy]}")

    # Validate status is from whitelist enum if provided
    if status is not None and isinstance(status, str):
        try:
            status = RunStatus(status)
        except ValueError:
            raise ValueError(f"Invalid status value. Must be one of: {[e.value for e in RunStatus]}")

    conn = get_connection(db_path)
    try:
        # Build WHERE clause
        where_clauses: List[str] = []
        params: List[Any] = []

        if status is not None:
            where_clauses.append("status = ?")
            params.append(status.value if isinstance(status, RunStatus) else status)

        if name is not None:
            where_clauses.append("workflow_name LIKE ?")
            params.append(f"%{name}%")

        if started_after is not None:
            where_clauses.append("started_at >= ?")
            params.append(started_after)

        if started_before is not None:
            where_clauses.append("started_at < ?")
            params.append(started_before)

        where_clause = ""
        if where_clauses:
            where_clause = "WHERE " + " AND ".join(where_clauses)

        # Get total count
        count_query = f"SELECT COUNT(*) FROM workflow_runs {where_clause}"
        cursor = conn.execute(count_query, params)
        total = cursor.fetchone()[0]

        # Build ORDER BY clause using whitelisted enum value
        # Safe to interpolate because sort_by is validated enum
        if sort_by == SortBy.DURATION:
            # Compute duration as julianday difference
            order_clause = "ORDER BY (julianday(finished_at) - julianday(started_at)) DESC"
        else:
            order_column = sort_by.value
            order_clause = f"ORDER BY {order_column} DESC"

        # Get paginated items
        items_query = f"""
            SELECT * FROM workflow_runs
            {where_clause}
            {order_clause}
            LIMIT ? OFFSET ?
        """
        cursor = conn.execute(items_query, params + [limit, offset])
        items = [_row_to_dict(row) for row in cursor.fetchall()]

        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": offset,
        }
    finally:
        conn.close()


def get_status_counts(db_path: Path) -> Dict[str, int]:
    """Get counts of workflow runs by status."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute("""
            SELECT status, COUNT(*) as count
            FROM workflow_runs
            GROUP BY status
        """)
        counts_dict = {row["status"]: row["count"] for row in cursor.fetchall()}

        # Ensure all statuses are present with 0 for missing ones
        return {
            "running": counts_dict.get("running", 0),
            "completed": counts_dict.get("completed", 0),
            "failed": counts_dict.get("failed", 0),
            "pending": counts_dict.get("pending", 0),
            "cancelled": counts_dict.get("cancelled", 0),
        }
    finally:
        conn.close()


def insert_node(
    db_path: Path,
    node_id: str,
    run_id: str,
    node_name: str,
    status: str,
    started_at: str,
    inputs: Optional[Dict[str, Any]] = None,
    depends_on: Optional[List[str]] = None,
    model: Optional[str] = None,
    tokens: Optional[int] = None,
    cost: Optional[float] = None,
    tokens_input: Optional[int] = None,
    tokens_output: Optional[int] = None,
    tokens_cache: Optional[int] = None,
) -> str:
    """Insert a new node execution."""
    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO node_executions (id, run_id, node_name, status, started_at, inputs, depends_on, model, tokens, cost, tokens_input, tokens_output, tokens_cache)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (node_id, run_id, node_name, status, started_at,
             json.dumps(inputs) if inputs else None,
             json.dumps(depends_on) if depends_on else None,
             model, tokens, cost, tokens_input, tokens_output, tokens_cache)
        )
        conn.commit()
        return node_id
    finally:
        conn.close()


def update_node(
    db_path: Path,
    node_id: str,
    status: Optional[str] = None,
    finished_at: Optional[str] = None,
    outputs: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
) -> None:
    """Update node execution fields."""
    conn = get_connection(db_path)
    try:
        fields = []
        values = []
        
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if finished_at is not None:
            fields.append("finished_at = ?")
            values.append(finished_at)
        if outputs is not None:
            fields.append("outputs = ?")
            values.append(json.dumps(outputs))
        if error is not None:
            fields.append("error = ?")
            values.append(error)
        
        if not fields:
            return
        
        values.append(node_id)
        query = f"UPDATE node_executions SET {', '.join(fields)} WHERE id = ?"
        conn.execute(query, values)
        conn.commit()
    finally:
        conn.close()


def get_node(db_path: Path, node_id: str) -> Optional[Dict[str, Any]]:
    """Get a single node execution by ID."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT * FROM node_executions WHERE id = ?",
            (node_id,)
        )
        row = cursor.fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def list_nodes(db_path: Path, run_id: str) -> List[Dict[str, Any]]:
    """List all node executions for a workflow run."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT * FROM node_executions WHERE run_id = ? ORDER BY started_at",
            (run_id,)
        )
        return [_row_to_dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def insert_chat_message(
    db_path: Path,
    execution_id: Optional[str] = None,
    role: str = "operator",
    content: str = "",
    created_at: str = "",
    metadata: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
    operator_username: Optional[str] = None,
) -> Optional[int]:
    """Insert a chat message for a node execution or workflow.

    Args:
        execution_id: Optional node execution ID (None for workflow-level messages)
        role: Message role (operator, agent, system)
        content: Message content
        created_at: ISO timestamp
        metadata: Optional JSON metadata
        run_id: Optional workflow run ID (for workflow-level messages)
        operator_username: Optional username of operator who sent message
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO chat_messages (execution_id, role, content, created_at, metadata, run_id, operator_username)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                execution_id,
                role,
                content,
                created_at,
                json.dumps(metadata) if metadata else None,
                run_id,
                operator_username
            )
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_chat_messages(
    db_path: Path,
    execution_id: Optional[str] = None,
    run_id: Optional[str] = None
) -> List[Dict[str, Any]]:
    """Get all chat messages for a node execution or workflow run.

    Args:
        execution_id: Optional node execution ID
        run_id: Optional workflow run ID

    Returns:
        List of chat messages ordered by created_at
    """
    conn = get_connection(db_path)
    try:
        if execution_id:
            cursor = conn.execute(
                "SELECT * FROM chat_messages WHERE execution_id = ? ORDER BY created_at",
                (execution_id,)
            )
        elif run_id:
            cursor = conn.execute(
                "SELECT * FROM chat_messages WHERE run_id = ? ORDER BY created_at",
                (run_id,)
            )
        else:
            # Return empty list if neither parameter provided
            return []
        return [_row_to_dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def insert_gate_decision(
    db_path: Path,
    run_id: str,
    node_name: str,
    decision: str,
    decided_by: str,
    decided_at: str,
    reason: Optional[str] = None,
) -> Optional[int]:
    """Insert a gate decision for a workflow run."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO gate_decisions (run_id, node_name, decision, decided_by, decided_at, reason)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, node_name, decision, decided_by, decided_at, reason)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_gate_decisions(db_path: Path, run_id: str) -> List[Dict[str, Any]]:
    """Get all gate decisions for a workflow run."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT * FROM gate_decisions WHERE run_id = ? ORDER BY decided_at",
            (run_id,)
        )
        return [_row_to_dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def insert_artifact(
    db_path: Path,
    execution_id: str,
    name: str,
    artifact_type: str,
    created_at: str,
    path: Optional[str] = None,
    content: Optional[str] = None,
    url: Optional[str] = None,
) -> Optional[int]:
    """Insert an artifact for a node execution."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            INSERT INTO artifacts (execution_id, name, artifact_type, path, content, created_at, url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (execution_id, name, artifact_type, path, content, created_at, url)
        )
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def get_artifacts(db_path: Path, execution_id: str) -> List[Dict[str, Any]]:
    """Get all artifacts for a node execution."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT * FROM artifacts WHERE execution_id = ? ORDER BY created_at",
            (execution_id,)
        )
        return [_row_to_dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_workflow_totals(db_path: Path, run_id: str) -> Dict[str, Any]:
    """Get aggregated totals for a workflow run.

    Returns:
        Dict with keys: cost, tokens_input, tokens_output, tokens_cache,
        total_tokens, failed_nodes, skipped_nodes
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT
                COALESCE(SUM(cost), 0.0) as total_cost,
                COALESCE(SUM(tokens_input), 0) as total_tokens_input,
                COALESCE(SUM(tokens_output), 0) as total_tokens_output,
                COALESCE(SUM(tokens_cache), 0) as total_tokens_cache,
                COALESCE(SUM(COALESCE(tokens_input, 0) + COALESCE(tokens_output, 0) + COALESCE(tokens_cache, 0)), 0) as total_all_tokens,
                COUNT(CASE WHEN status = 'failed' THEN 1 END) as failed_count,
                COUNT(CASE WHEN status = 'skipped' THEN 1 END) as skipped_count
            FROM node_executions
            WHERE run_id = ?
            """,
            (run_id,)
        )
        row = cursor.fetchone()
        if row:
            return {
                "cost": float(row[0]),
                "tokens_input": int(row[1]),
                "tokens_output": int(row[2]),
                "tokens_cache": int(row[3]),
                "total_tokens": int(row[4]),
                "failed_nodes": int(row[5]),
                "skipped_nodes": int(row[6]),
            }
        else:
            return {
                "cost": 0.0,
                "tokens_input": 0,
                "tokens_output": 0,
                "tokens_cache": 0,
                "total_tokens": 0,
                "failed_nodes": 0,
                "skipped_nodes": 0,
            }
    finally:
        conn.close()


def get_workflow_chat_history(
    db_path: Path,
    run_id: str,
    limit: int = 50,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """Get paginated chat history for a workflow run.

    Args:
        db_path: Path to SQLite database
        run_id: Workflow run ID
        limit: Maximum number of messages to return
        offset: Number of messages to skip

    Returns:
        List of chat messages ordered by created_at
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT * FROM chat_messages
            WHERE run_id = ?
            ORDER BY created_at
            LIMIT ? OFFSET ?
            """,
            (run_id, limit, offset)
        )
        return [_row_to_dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def check_rate_limit(
    db_path: Path,
    run_id: str,
    window_seconds: int = 60,
    max_messages: int = 10
) -> bool:
    """Check if rate limit has been exceeded for a workflow run.

    Args:
        db_path: Path to SQLite database
        run_id: Workflow run ID
        window_seconds: Time window in seconds (default 60 for 1 minute)
        max_messages: Maximum messages allowed in the window

    Returns:
        True if rate limit exceeded, False otherwise
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT COUNT(*) as count FROM chat_messages
            WHERE run_id = ?
            AND datetime(created_at) >= datetime('now', '-' || ? || ' seconds')
            """,
            (run_id, window_seconds)
        )
        result = cursor.fetchone()
        count = result["count"] if result else 0
        return count >= max_messages
    finally:
        conn.close()


def get_pending_gates(db_path: Path) -> List[Dict[str, Any]]:
    """Get all interrupted nodes in running workflows (pending gate approvals)."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT ne.*
            FROM node_executions ne
            JOIN workflow_runs wr ON ne.run_id = wr.id
            WHERE ne.status = 'interrupted'
            AND wr.status = 'running'
            ORDER BY ne.started_at
            """
        )
        return [_row_to_dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def count_pending_gates(db_path: Path) -> int:
    """Count the number of pending gate approvals (interrupted nodes in running workflows)."""
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT COUNT(*)
            FROM node_executions ne
            JOIN workflow_runs wr ON ne.run_id = wr.id
            WHERE ne.status = 'interrupted'
            AND wr.status = 'running'
            """
        )
        result = cursor.fetchone()
        return int(result[0]) if result else 0
    finally:
        conn.close()


def get_interrupt_checkpoint(
    db_path: Path,
    workflow_name: str,
    run_id: str,
    node_name: str,
    checkpoint_dir_fallback: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Get interrupt checkpoint for a specific node.

    Args:
        db_path: Path to dashboard database
        workflow_name: Name of the workflow
        run_id: Run identifier
        node_name: Node name
        checkpoint_dir_fallback: Fallback checkpoint directory (from DAG_CHECKPOINT_DIR env)

    Returns:
        Dict with interrupt checkpoint fields, or None if not found
    """
    import os
    import yaml
    from dag_executor.checkpoint import CheckpointStore

    conn = get_connection(db_path)
    try:
        # Query workflow_runs for workflow_definition YAML
        cursor = conn.execute(
            """
            SELECT workflow_definition
            FROM workflow_runs
            WHERE id = ?
            """,
            (run_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None

        workflow_def_yaml = row["workflow_definition"]

        # Parse checkpoint_prefix from YAML
        workflow_def = yaml.safe_load(workflow_def_yaml)
        checkpoint_prefix = workflow_def.get("config", {}).get("checkpoint_prefix")

        # Use fallback if not specified in YAML
        if not checkpoint_prefix:
            checkpoint_prefix = checkpoint_dir_fallback or os.path.expanduser(
                "~/.dag-executor/checkpoints"
            )

        # Load interrupt checkpoint via CheckpointStore
        store = CheckpointStore(checkpoint_prefix)
        interrupt_checkpoint = store.load_interrupt(workflow_name, run_id)

        if not interrupt_checkpoint:
            return None

        # Return as dict for API serialization
        result: Dict[str, Any] = interrupt_checkpoint.model_dump()
        return result

    finally:
        conn.close()
