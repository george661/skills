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
    trigger_source: Optional[str] = None,
    parent_run_id: Optional[str] = None,
) -> str:
    """Insert a new workflow run."""
    # Validate workflow_name at query level (defense in depth)
    if not re.match(r"^[a-zA-Z0-9-]+$", workflow_name):
        raise ValueError("workflow_name must contain only alphanumeric characters and hyphens")

    conn = get_connection(db_path)
    try:
        conn.execute(
            """
            INSERT INTO workflow_runs (id, workflow_name, status, started_at, inputs, workflow_definition, trigger_source, parent_run_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, workflow_name, status, started_at, json.dumps(inputs) if inputs else None, workflow_definition, trigger_source, parent_run_id)
        )
        conn.commit()
        return run_id
    finally:
        conn.close()


def get_run_for_rerun(db_path: Path, run_id: str) -> Optional[Dict[str, Any]]:
    """Get workflow run data for rerun operation."""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT workflow_name, inputs FROM workflow_runs WHERE id = ?",
            (run_id,)
        )
        row = cursor.fetchone()
        if not row:
            return None

        return {
            "workflow_name": row[0],
            "inputs": json.loads(row[1]) if row[1] else {}
        }
    finally:
        conn.close()


def update_run(
    db_path: Path,
    run_id: str,
    status: Optional[str] = None,
    finished_at: Optional[str] = None,
    outputs: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    cancelled_by: Optional[str] = None,
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
        if cancelled_by is not None:
            fields.append("cancelled_by = ?")
            values.append(cancelled_by)
        
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


def get_nodes_by_names(db_path: Path, run_id: str, names: List[str]) -> Dict[str, Dict[str, Any]]:
    """Get node executions by name within a run.

    Args:
        db_path: Path to the SQLite database.
        run_id: Workflow run ID.
        names: List of node names to retrieve.

    Returns:
        Dict keyed by node_name containing node execution data.
    """
    if not names:
        return {}

    conn = get_connection(db_path)
    try:
        # Build parameterized query with correct number of placeholders
        placeholders = ",".join(["?"] * len(names))
        query = f"SELECT * FROM node_executions WHERE run_id = ? AND node_name IN ({placeholders})"
        cursor = conn.execute(query, [run_id] + names)

        result = {}
        for row in cursor.fetchall():
            node_dict = _row_to_dict(row)
            result[node_dict["node_name"]] = node_dict

        return result
    finally:
        conn.close()


def get_checkpoint_comparison(db_path: Path, run_id: str, node_id: str) -> Optional[Dict[str, Any]]:
    """Get checkpoint version comparison for a node.

    Returns:
        Dict with:
        - content_hash: str
        - input_versions: Dict[str, int] (checkpoint versions)
        - current_versions: Dict[str, int] (current channel versions)
        - mismatches: List[Dict] with channel_key, checkpoint_version, current_version
        Returns None if node has no checkpoint data.
    """
    conn = get_connection(db_path)
    try:
        # Get node checkpoint data
        cursor = conn.execute(
            "SELECT content_hash, input_versions FROM node_executions WHERE id = ?",
            (node_id,)
        )
        row = cursor.fetchone()
        if not row or not row[0]:  # No checkpoint data
            return None

        content_hash, input_versions_json = row
        input_versions = json.loads(input_versions_json) if input_versions_json else {}

        # Get current channel versions for this run
        cursor = conn.execute(
            "SELECT channel_key, version FROM channel_states WHERE run_id = ?",
            (run_id,)
        )
        current_versions = {row[0]: row[1] for row in cursor.fetchall()}

        # Find mismatches
        mismatches = []
        for channel_key, checkpoint_ver in input_versions.items():
            current_ver = current_versions.get(channel_key)
            if current_ver is None:
                mismatches.append({
                    "channel_key": channel_key,
                    "checkpoint_version": checkpoint_ver,
                    "current_version": None,
                    "status": "missing"
                })
            elif current_ver != checkpoint_ver:
                mismatches.append({
                    "channel_key": channel_key,
                    "checkpoint_version": checkpoint_ver,
                    "current_version": current_ver,
                    "status": "mismatch"
                })

        # Check for extra channels in current state
        for channel_key, current_ver in current_versions.items():
            if channel_key not in input_versions:
                mismatches.append({
                    "channel_key": channel_key,
                    "checkpoint_version": None,
                    "current_version": current_ver,
                    "status": "extra"
                })

        return {
            "content_hash": content_hash,
            "input_versions": input_versions,
            "current_versions": current_versions,
            "mismatches": mismatches
        }
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
    from dag_executor.checkpoint import CheckpointStore  # type: ignore[import-untyped]

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


def get_channel_states(db_path: Path, run_id: str) -> List[Dict[str, Any]]:
    """Get all channel states for a workflow run.

    Args:
        db_path: Path to SQLite database
        run_id: Workflow run ID

    Returns:
        List of channel state dicts with deserialized JSON fields, sorted by channel_key
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT run_id, channel_key, channel_type, reducer_strategy,
                   value_json, version, writers_json, conflict_json, updated_at
            FROM channel_states
            WHERE run_id = ?
            ORDER BY channel_key
            """,
            (run_id,)
        )
        rows = cursor.fetchall()

        # Deserialize JSON fields
        result = []
        for row in rows:
            state = dict(row)
            # Parse JSON columns
            if state.get("value_json"):
                state["value"] = json.loads(state["value_json"])
                del state["value_json"]
            else:
                state["value"] = None
                del state["value_json"]

            if state.get("writers_json"):
                state["writers"] = json.loads(state["writers_json"])
                del state["writers_json"]
            else:
                state["writers"] = []
                del state["writers_json"]

            if state.get("conflict_json"):
                state["conflict"] = json.loads(state["conflict_json"])
                del state["conflict_json"]
            else:
                state["conflict"] = None
                del state["conflict_json"]

            result.append(state)

        return result
    finally:
        conn.close()


def get_state_diff_timeline(db_path: Path, run_id: str) -> List[Dict[str, Any]]:
    """
    Get state diff timeline for a workflow run.

    Reconstructs running state by folding state_diff values from NODE_COMPLETED events
    in chronological order. For each node, compares its state_diff against the running
    state to classify changes as added/changed/removed.

    Args:
        db_path: Path to SQLite database
        run_id: Workflow run ID

    Returns:
        List of dicts with shape:
        {
            "node_name": str,
            "node_id": str,
            "started_at": str,
            "finished_at": str,
            "changes": [
                {
                    "key": str,
                    "change_type": "added"|"changed"|"removed",
                    "before": Any|None,
                    "after": Any|None
                }
            ]
        }

        Ordered by created_at (chronological).
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT
                e.payload,
                e.created_at,
                ne.node_name,
                ne.started_at,
                ne.finished_at
            FROM events e
            LEFT JOIN node_executions ne ON json_extract(e.payload, '$.node_id') = ne.id
            WHERE e.run_id = ? AND e.event_type = 'node_completed'
            ORDER BY e.created_at
            """,
            (run_id,)
        )
        rows = cursor.fetchall()

        timeline = []
        running_state: Dict[str, Any] = {}

        for row in rows:
            payload_str = row[0]
            payload = json.loads(payload_str)

            # WorkflowEvent shape: node_id, metadata, timestamp
            node_id = payload.get("node_id", "unknown")
            metadata = payload.get("metadata", {})
            state_diff = metadata.get("state_diff", {})

            # Get node_name and timestamps from node_executions JOIN
            node_name = row[2] if row[2] else "unknown"
            started_at = row[3]
            finished_at = row[4]

            # Build changes list for this node
            changes = []
            for key, after_value in state_diff.items():
                before_value = running_state.get(key)

                # Determine change type
                # NOTE: Executor contract treats state_diff[key]=None as "key was removed",
                # not "key was set to Python None value". This is a semantic convention
                # where state_diff encodes delta operations, not literal new values.
                if key not in running_state:
                    # Key not in prior state
                    if after_value is None:
                        # Executor says "remove this key" but it never existed.
                        # Edge case: treat as "removed" to match executor semantics,
                        # even though logically it's removing from empty state.
                        change_type = "removed"
                    else:
                        change_type = "added"
                elif after_value is None:
                    # Key was in prior state, executor says "remove it"
                    change_type = "removed"
                else:
                    # Key was in prior state, has non-None value -> changed
                    change_type = "changed"

                changes.append({
                    "key": key,
                    "change_type": change_type,
                    "before": before_value,
                    "after": after_value
                })

                # Update running state
                if after_value is None:
                    # Remove from running state
                    running_state.pop(key, None)
                else:
                    running_state[key] = after_value

            # Add node entry to timeline
            timeline.append({
                "node_name": node_name,
                "node_id": node_id,
                "started_at": started_at,
                "finished_at": finished_at,
                "changes": changes
            })

        return timeline
    finally:
        conn.close()


def list_run_artifacts(db_path: Path, run_id: str) -> List[Dict[str, Any]]:
    """List all artifacts for a workflow run, joined to node_name.

    Ordered by created_at ascending.
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT a.id, a.execution_id, a.name, a.artifact_type,
                   a.path, a.content, a.created_at, a.url,
                   ne.node_name
            FROM artifacts a
            JOIN node_executions ne ON ne.id = a.execution_id
            WHERE ne.run_id = ?
            ORDER BY a.created_at
            """,
            (run_id,)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def get_node_logs(
    db_path: Path,
    run_id: str,
    node_id: str,
    limit: int = 1000,
    offset: int = 0
) -> List[Dict[str, Any]]:
    """
    Retrieve log lines for a specific node in a workflow run.

    Args:
        db_path: Path to SQLite database
        run_id: Workflow run ID
        node_id: Node ID
        limit: Maximum number of log lines to return (default 1000)
        offset: Number of log lines to skip (default 0)

    Returns:
        List of log line dicts with keys: run_id, node_id, stream, sequence, line, created_at
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT run_id, node_id, stream, sequence, line, created_at
            FROM node_logs
            WHERE run_id = ? AND node_id = ?
            ORDER BY sequence
            LIMIT ? OFFSET ?
            """,
            (run_id, node_id, limit, offset)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()
