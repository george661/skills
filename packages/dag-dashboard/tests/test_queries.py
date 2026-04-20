"""Tests for database query helpers."""
from pathlib import Path

import pytest

from dag_dashboard.database import init_db
from dag_dashboard.queries import (
    get_connection,
    insert_run,
    update_run,
    get_run,
    list_runs,
    get_status_counts,
    insert_node,
    update_node,
    get_node,
    list_nodes,
    insert_chat_message,
    get_chat_messages,
    insert_gate_decision,
    get_gate_decisions,
    insert_artifact,
    get_artifacts,
    get_pending_gates,
    count_pending_gates,
    get_checkpoint_comparison,
)
from dag_dashboard.models import SortBy, RunStatus


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Create an in-memory test database."""
    db = tmp_path / "test.db"
    init_db(db)
    return db


def test_get_connection_enables_foreign_keys(db_path: Path):
    """Test get_connection enables foreign key constraints."""
    conn = get_connection(db_path)
    cursor = conn.cursor()
    result = cursor.execute("PRAGMA foreign_keys").fetchone()
    conn.close()
    assert result[0] == 1


def test_insert_run_and_get_run_roundtrip(db_path: Path):
    """Test inserting and retrieving a workflow run."""
    run_id = insert_run(
        db_path,
        run_id="run-123",
        workflow_name="test-workflow",
        status="running",
        started_at="2026-04-17T12:00:00Z",
        inputs={"key": "value"},
    )
    assert run_id == "run-123"
    
    run = get_run(db_path, "run-123")
    assert run is not None
    assert run["id"] == "run-123"
    assert run["workflow_name"] == "test-workflow"
    assert run["status"] == "running"
    assert run["inputs"] == {"key": "value"}


def test_update_run_status(db_path: Path):
    """Test updating workflow run status."""
    insert_run(
        db_path,
        run_id="run-123",
        workflow_name="test-workflow",
        status="running",
        started_at="2026-04-17T12:00:00Z",
    )
    
    update_run(
        db_path,
        run_id="run-123",
        status="completed",
        finished_at="2026-04-17T12:05:00Z",
        outputs={"result": "success"},
    )
    
    run = get_run(db_path, "run-123")
    assert run["status"] == "completed"
    assert run["finished_at"] == "2026-04-17T12:05:00Z"
    assert run["outputs"] == {"result": "success"}


def test_list_runs_pagination(db_path: Path):
    """Test list_runs with pagination."""
    for i in range(15):
        insert_run(
            db_path,
            run_id=f"run-{i}",
            workflow_name="test-workflow",
            status="running",
            started_at=f"2026-04-17T12:{i:02d}:00Z",
        )
    
    result = list_runs(db_path, limit=10, offset=0)
    assert len(result["items"]) == 10
    assert result["total"] == 15
    assert result["limit"] == 10
    assert result["offset"] == 0
    
    result = list_runs(db_path, limit=10, offset=10)
    assert len(result["items"]) == 5
    assert result["total"] == 15


def test_list_runs_status_filter(db_path: Path):
    """Test list_runs with status filter."""
    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_run(db_path, "run-2", "wf1", "completed", "2026-04-17T12:01:00Z")
    insert_run(db_path, "run-3", "wf1", "failed", "2026-04-17T12:02:00Z")
    insert_run(db_path, "run-4", "wf1", "running", "2026-04-17T12:03:00Z")
    
    result = list_runs(db_path, status=RunStatus.RUNNING)
    assert len(result["items"]) == 2
    assert result["total"] == 2
    
    result = list_runs(db_path, status=RunStatus.COMPLETED)
    assert len(result["items"]) == 1
    assert result["total"] == 1


def test_list_runs_sort_by_started_at(db_path: Path):
    """Test list_runs sorts by started_at."""
    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:02:00Z")
    insert_run(db_path, "run-2", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_run(db_path, "run-3", "wf1", "running", "2026-04-17T12:01:00Z")
    
    result = list_runs(db_path, sort_by=SortBy.STARTED_AT)
    # Default order is DESC (most recent first)
    assert result["items"][0]["id"] == "run-1"
    assert result["items"][1]["id"] == "run-3"
    assert result["items"][2]["id"] == "run-2"


def test_list_runs_sort_by_completed_at(db_path: Path):
    """Test list_runs sorts by finished_at."""
    insert_run(db_path, "run-1", "wf1", "completed", "2026-04-17T12:00:00Z")
    update_run(db_path, "run-1", finished_at="2026-04-17T12:02:00Z")

    insert_run(db_path, "run-2", "wf1", "completed", "2026-04-17T12:01:00Z")
    update_run(db_path, "run-2", finished_at="2026-04-17T12:00:00Z")

    result = list_runs(db_path, sort_by=SortBy.FINISHED_AT)
    # DESC order - most recent finished_at first
    assert result["items"][0]["id"] == "run-1"
    assert result["items"][1]["id"] == "run-2"


def test_insert_node_and_get_node(db_path: Path):
    """Test inserting and retrieving a node execution."""
    insert_run(db_path, "run-123", "wf1", "running", "2026-04-17T12:00:00Z")
    
    node_id = insert_node(
        db_path,
        node_id="node-456",
        run_id="run-123",
        node_name="step-1",
        status="running",
        started_at="2026-04-17T12:00:01Z",
    )
    assert node_id == "node-456"
    
    node = get_node(db_path, "node-456")
    assert node is not None
    assert node["id"] == "node-456"
    assert node["run_id"] == "run-123"
    assert node["node_name"] == "step-1"


def test_update_node_status(db_path: Path):
    """Test updating node execution status."""
    insert_run(db_path, "run-123", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_node(db_path, "node-456", "run-123", "step-1", "running", "2026-04-17T12:00:01Z")
    
    update_node(
        db_path,
        node_id="node-456",
        status="completed",
        finished_at="2026-04-17T12:00:10Z",
        outputs={"result": "ok"},
    )
    
    node = get_node(db_path, "node-456")
    assert node["status"] == "completed"
    assert node["finished_at"] == "2026-04-17T12:00:10Z"


def test_list_nodes_for_run(db_path: Path):
    """Test listing nodes for a specific run."""
    insert_run(db_path, "run-123", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_run(db_path, "run-456", "wf2", "running", "2026-04-17T12:01:00Z")
    
    insert_node(db_path, "node-1", "run-123", "step-1", "running", "2026-04-17T12:00:01Z")
    insert_node(db_path, "node-2", "run-123", "step-2", "pending", "2026-04-17T12:00:02Z")
    insert_node(db_path, "node-3", "run-456", "step-1", "running", "2026-04-17T12:01:01Z")
    
    nodes = list_nodes(db_path, "run-123")
    assert len(nodes) == 2
    assert nodes[0]["id"] == "node-1"
    assert nodes[1]["id"] == "node-2"


def test_insert_and_get_chat_messages(db_path: Path):
    """Test chat message CRUD operations."""
    insert_run(db_path, "run-123", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_node(db_path, "node-456", "run-123", "step-1", "running", "2026-04-17T12:00:01Z")
    
    msg_id = insert_chat_message(
        db_path,
        execution_id="node-456",
        role="user",
        content="Hello",
        created_at="2026-04-17T12:00:05Z",
    )
    assert msg_id is not None
    
    messages = get_chat_messages(db_path, "node-456")
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "Hello"


def test_insert_and_get_gate_decisions(db_path: Path):
    """Test gate decision CRUD operations."""
    insert_run(db_path, "run-123", "wf1", "running", "2026-04-17T12:00:00Z")
    
    decision_id = insert_gate_decision(
        db_path,
        run_id="run-123",
        node_name="approval-gate",
        decision="approved",
        decided_by="user@example.com",
        decided_at="2026-04-17T12:05:00Z",
        reason="LGTM",
    )
    assert decision_id is not None
    
    decisions = get_gate_decisions(db_path, "run-123")
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "approved"
    assert decisions[0]["decided_by"] == "user@example.com"


def test_insert_and_get_artifacts(db_path: Path):
    """Test artifact CRUD operations."""
    insert_run(db_path, "run-123", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_node(db_path, "node-456", "run-123", "step-1", "running", "2026-04-17T12:00:01Z")
    
    artifact_id = insert_artifact(
        db_path,
        execution_id="node-456",
        name="output.json",
        artifact_type="json",
        content='{"result": "ok"}',
        created_at="2026-04-17T12:00:10Z",
    )
    assert artifact_id is not None
    
    artifacts = get_artifacts(db_path, "node-456")
    assert len(artifacts) == 1
    assert artifacts[0]["name"] == "output.json"
    assert artifacts[0]["artifact_type"] == "json"


def test_sql_injection_via_sort_by(db_path: Path):
    """Test SQL injection attempt via sortBy is blocked."""
    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    
    # Should raise ValueError due to enum validation
    with pytest.raises(ValueError):
        list_runs(db_path, sort_by="started_at; DROP TABLE workflow_runs;")


def test_sql_injection_via_status(db_path: Path):
    """Test SQL injection attempt via status is blocked."""
    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    
    # Should raise ValueError due to enum validation
    with pytest.raises(ValueError):
        list_runs(db_path, status="running' OR '1'='1")


def test_workflow_name_injection_blocked(db_path: Path):
    """Test SQL injection via workflow_name is parameterized."""
    # This should NOT raise an error - it's parameterized and safely stored
    malicious_name = "wf'; DROP TABLE workflow_runs; --"
    try:
        insert_run(
            db_path,
            run_id="run-1",
            workflow_name=malicious_name,
            status="running",
            started_at="2026-04-17T12:00:00Z",
        )
        # Should fail at validation level (alphanumeric + hyphens only)
        assert False, "Should have raised validation error"
    except ValueError:
        # Expected - validation should reject this
        pass
    
    # Verify table still exists
    conn = get_connection(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='workflow_runs'")
    result = cursor.fetchone()
    conn.close()
    assert result is not None


def test_get_status_counts_empty(db_path: Path):
    """Test get_status_counts returns zeros when no runs exist."""
    counts = get_status_counts(db_path)
    assert counts["running"] == 0
    assert counts["completed"] == 0
    assert counts["failed"] == 0
    assert counts["pending"] == 0
    assert counts["cancelled"] == 0


def test_get_status_counts_mixed(db_path: Path):
    """Test get_status_counts with mixed workflow statuses."""
    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_run(db_path, "run-2", "wf1", "running", "2026-04-17T12:01:00Z")
    insert_run(db_path, "run-3", "wf1", "completed", "2026-04-17T12:02:00Z")
    insert_run(db_path, "run-4", "wf1", "failed", "2026-04-17T12:03:00Z")
    insert_run(db_path, "run-5", "wf1", "pending", "2026-04-17T12:04:00Z")
    insert_run(db_path, "run-6", "wf1", "completed", "2026-04-17T12:05:00Z")
    insert_run(db_path, "run-7", "wf1", "cancelled", "2026-04-17T12:06:00Z")

    counts = get_status_counts(db_path)
    assert counts["running"] == 2
    assert counts["completed"] == 2
    assert counts["failed"] == 1
    assert counts["pending"] == 1
    assert counts["cancelled"] == 1


def test_list_runs_name_filter(db_path: Path):
    """Test list_runs with name filter."""
    insert_run(db_path, "run-1", "data-pipeline", "running", "2026-04-17T12:00:00Z")
    insert_run(db_path, "run-2", "ml-training", "running", "2026-04-17T12:01:00Z")
    insert_run(db_path, "run-3", "data-export", "completed", "2026-04-17T12:02:00Z")

    # Search for "data" should match data-pipeline and data-export
    result = list_runs(db_path, limit=50, offset=0, name="data")
    assert result["total"] == 2
    assert len(result["items"]) == 2
    workflow_names = [item["workflow_name"] for item in result["items"]]
    assert "data-pipeline" in workflow_names
    assert "data-export" in workflow_names
    assert "ml-training" not in workflow_names


def test_list_runs_date_range_filter(db_path: Path):
    """Test list_runs with date range filter."""
    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T10:00:00Z")
    insert_run(db_path, "run-2", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_run(db_path, "run-3", "wf1", "running", "2026-04-17T14:00:00Z")
    insert_run(db_path, "run-4", "wf1", "running", "2026-04-17T16:00:00Z")

    # Filter for runs between 11:00 and 15:00
    result = list_runs(
        db_path,
        limit=50,
        offset=0,
        started_after="2026-04-17T11:00:00Z",
        started_before="2026-04-17T15:00:00Z",
    )
    assert result["total"] == 2
    assert len(result["items"]) == 2
    run_ids = [item["id"] for item in result["items"]]
    assert "run-2" in run_ids
    assert "run-3" in run_ids


def test_list_runs_date_range_only_after(db_path: Path):
    """Test list_runs with only started_after filter."""
    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T10:00:00Z")
    insert_run(db_path, "run-2", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_run(db_path, "run-3", "wf1", "running", "2026-04-17T14:00:00Z")

    result = list_runs(db_path, limit=50, offset=0, started_after="2026-04-17T11:00:00Z")
    assert result["total"] == 2
    assert len(result["items"]) == 2


def test_list_runs_sort_by_duration(db_path: Path):
    """Test list_runs sorting by duration."""
    # Insert runs with different durations
    insert_run(db_path, "run-1", "wf1", "completed", "2026-04-17T12:00:00Z")
    update_run(db_path, "run-1", finished_at="2026-04-17T12:05:00Z")  # 5 min duration

    insert_run(db_path, "run-2", "wf1", "completed", "2026-04-17T12:10:00Z")
    update_run(db_path, "run-2", finished_at="2026-04-17T12:20:00Z")  # 10 min duration

    insert_run(db_path, "run-3", "wf1", "completed", "2026-04-17T12:30:00Z")
    update_run(db_path, "run-3", finished_at="2026-04-17T12:32:00Z")  # 2 min duration

    # Sort by duration - should be desc (longest first)
    result = list_runs(db_path, sort_by=SortBy.DURATION)
    assert result["items"][0]["id"] == "run-2"  # 10 min
    assert result["items"][1]["id"] == "run-1"  # 5 min
    assert result["items"][2]["id"] == "run-3"  # 2 min


def test_insert_node_with_token_breakdown(db_path: Path):
    """Test inserting node with token breakdown (input/output/cache)."""
    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")

    from dag_dashboard.queries import insert_node
    node_id = insert_node(
        db_path,
        node_id="node-1",
        run_id="run-1",
        node_name="tokenized-node",
        status="completed",
        started_at="2026-04-17T12:00:00Z",
        tokens_input=1500,
        tokens_output=500,
        tokens_cache=200,
        cost=0.0125,
    )

    # Read back and verify breakdown is preserved
    node = get_node(db_path, "node-1")
    assert node is not None
    assert node["tokens_input"] == 1500
    assert node["tokens_output"] == 500
    assert node["tokens_cache"] == 200
    assert node["cost"] == 0.0125


def test_insert_artifact_with_url(db_path: Path):
    """Test inserting artifact with URL."""
    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_node(
        db_path, "node-1", "run-1", "test-node", "completed", "2026-04-17T12:00:00Z"
    )

    artifact_id = insert_artifact(
        db_path,
        execution_id="node-1",
        name="PR #1",
        artifact_type="pull-request",
        created_at="2026-04-17T12:00:00Z",
        url="https://github.com/george661/skills/pull/1",
    )

    artifacts = get_artifacts(db_path, "node-1")
    assert len(artifacts) == 1
    assert artifacts[0]["url"] == "https://github.com/george661/skills/pull/1"


def test_get_workflow_totals_empty(db_path: Path):
    """Test get_workflow_totals returns zeros for unknown run."""
    from dag_dashboard.queries import get_workflow_totals

    totals = get_workflow_totals(db_path, "nonexistent-run")
    assert totals["cost"] == 0.0
    assert totals["tokens_input"] == 0
    assert totals["tokens_output"] == 0
    assert totals["tokens_cache"] == 0
    assert totals["total_tokens"] == 0
    assert totals["failed_nodes"] == 0
    assert totals["skipped_nodes"] == 0


def test_get_workflow_totals_aggregates(db_path: Path):
    """Test get_workflow_totals aggregates costs/tokens and counts statuses."""
    from dag_dashboard.queries import get_workflow_totals

    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")

    # Node 1: completed
    insert_node(
        db_path, "node-1", "run-1", "n1", "completed", "2026-04-17T12:00:00Z",
        tokens_input=1000, tokens_output=200, tokens_cache=100, cost=0.01
    )

    # Node 2: failed
    insert_node(
        db_path, "node-2", "run-1", "n2", "failed", "2026-04-17T12:01:00Z",
        tokens_input=500, tokens_output=50, tokens_cache=0, cost=0.005
    )

    # Node 3: skipped
    insert_node(
        db_path, "node-3", "run-1", "n3", "skipped", "2026-04-17T12:02:00Z",
        tokens_input=0, tokens_output=0, tokens_cache=0, cost=0.0
    )

    totals = get_workflow_totals(db_path, "run-1")

    # Cost total: 0.01 + 0.005 + 0.0 = 0.015
    assert totals["cost"] == 0.015

    # Token totals
    assert totals["tokens_input"] == 1500
    assert totals["tokens_output"] == 250
    assert totals["tokens_cache"] == 100
    assert totals["total_tokens"] == 1850

    # Status counts
    assert totals["failed_nodes"] == 1
    assert totals["skipped_nodes"] == 1


def test_get_workflow_totals_handles_null_cost_and_tokens(db_path: Path):
    """Test get_workflow_totals treats NULL values as 0."""
    from dag_dashboard.queries import get_workflow_totals

    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")

    # Node with no cost or token info
    insert_node(
        db_path, "node-1", "run-1", "n1", "completed", "2026-04-17T12:00:00Z"
    )

    totals = get_workflow_totals(db_path, "run-1")

    assert totals["cost"] == 0.0
    assert totals["tokens_input"] == 0
    assert totals["tokens_output"] == 0
    assert totals["tokens_cache"] == 0
    assert totals["total_tokens"] == 0


def test_get_pending_gates_empty(db_path: Path):
    """Test get_pending_gates returns empty list when no interrupted nodes exist."""
    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_node(db_path, "run-1:node-1", "run-1", "node-1", "completed", started_at="2026-04-17T12:00:00Z")

    pending = get_pending_gates(db_path)
    assert len(pending) == 0


def test_get_pending_gates_finds_interrupted_nodes(db_path: Path):
    """Test get_pending_gates returns nodes with status='interrupted'."""
    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_node(db_path, "run-1:gate-1", "run-1", "gate-1", "interrupted", started_at="2026-04-17T12:00:00Z")
    insert_node(db_path, "run-1:node-2", "run-1", "node-2", "completed", started_at="2026-04-17T12:01:00Z")

    pending = get_pending_gates(db_path)
    assert len(pending) == 1
    assert pending[0]["node_name"] == "gate-1"
    assert pending[0]["status"] == "interrupted"


def test_get_pending_gates_only_running_workflows(db_path: Path):
    """Test get_pending_gates only returns gates from running workflows."""
    # Running workflow with interrupted node
    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_node(db_path, "run-1:gate-1", "run-1", "gate-1", "interrupted", started_at="2026-04-17T12:00:00Z")

    # Completed workflow with interrupted node (should be excluded)
    insert_run(db_path, "run-2", "wf1", "completed", "2026-04-17T11:00:00Z")
    insert_node(db_path, "run-2:gate-2", "run-2", "gate-2", "interrupted", started_at="2026-04-17T11:00:00Z")

    pending = get_pending_gates(db_path)
    assert len(pending) == 1
    assert pending[0]["run_id"] == "run-1"


def test_count_pending_gates_zero(db_path: Path):
    """Test count_pending_gates returns 0 when no interrupted nodes exist."""
    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_node(db_path, "run-1:node-1", "run-1", "node-1", "completed", started_at="2026-04-17T12:00:00Z")

    count = count_pending_gates(db_path)
    assert count == 0


def test_count_pending_gates_multiple(db_path: Path):
    """Test count_pending_gates counts multiple interrupted nodes."""
    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_node(db_path, "run-1:gate-1", "run-1", "gate-1", "interrupted", started_at="2026-04-17T12:00:00Z")
    insert_node(db_path, "run-1:gate-2", "run-1", "gate-2", "interrupted", started_at="2026-04-17T12:01:00Z")

    count = count_pending_gates(db_path)
    assert count == 2


def test_get_interrupt_checkpoint_success(db_path: Path, tmp_path: Path):
    """Test get_interrupt_checkpoint returns checkpoint data."""
    from dag_dashboard.queries import get_interrupt_checkpoint, insert_run
    from dag_executor.checkpoint import CheckpointStore, InterruptCheckpoint
    
    # Create checkpoint
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    store = CheckpointStore(str(checkpoint_dir))
    interrupt_checkpoint = InterruptCheckpoint(
        node_id="run-1:node-1",
        message="Please provide input",
        resume_key="user_input",
        timeout=300,
        channels=["terminal"]
    )
    store.save_interrupt("test-workflow", "run-1", interrupt_checkpoint)
    
    # Insert run with checkpoint_prefix
    workflow_def = f"""
config:
  checkpoint_prefix: {checkpoint_dir}
nodes:
  - name: node-1
    type: interrupt
"""
    insert_run(db_path, "run-1", "test-workflow", "running", "2026-04-17T12:00:00Z", workflow_definition=workflow_def)
    
    result = get_interrupt_checkpoint(db_path, "test-workflow", "run-1", "node-1", None)
    assert result is not None
    assert result["resume_key"] == "user_input"
    assert result["message"] == "Please provide input"
    assert result["timeout"] == 300


def test_get_interrupt_checkpoint_with_fallback(db_path: Path, tmp_path: Path):
    """Test get_interrupt_checkpoint uses fallback when checkpoint_prefix not in YAML."""
    from dag_dashboard.queries import get_interrupt_checkpoint, insert_run
    from dag_executor.checkpoint import CheckpointStore, InterruptCheckpoint
    
    # Create checkpoint in fallback location
    fallback_dir = tmp_path / "fallback"
    fallback_dir.mkdir(exist_ok=True)
    store = CheckpointStore(str(fallback_dir))
    interrupt_checkpoint = InterruptCheckpoint(
        node_id="run-1:node-1",
        message="Fallback test",
        resume_key="input",
        timeout=60,
        channels=["terminal"]
    )
    store.save_interrupt("test-workflow", "run-1", interrupt_checkpoint)
    
    # Insert run without checkpoint_prefix
    workflow_def = """
nodes:
  - name: node-1
    type: interrupt
"""
    insert_run(db_path, "run-1", "test-workflow", "running", "2026-04-17T12:00:00Z", workflow_definition=workflow_def)
    
    result = get_interrupt_checkpoint(db_path, "test-workflow", "run-1", "node-1", str(fallback_dir))
    assert result is not None
    assert result["resume_key"] == "input"
    assert result["message"] == "Fallback test"


def test_get_interrupt_checkpoint_not_found(db_path: Path):
    """Test get_interrupt_checkpoint returns None when run not found."""
    from dag_dashboard.queries import get_interrupt_checkpoint

    result = get_interrupt_checkpoint(db_path, "test-workflow", "nonexistent", "node-1", None)
    assert result is None


def test_get_checkpoint_comparison_exact_match(db_path: Path):
    """Test get_checkpoint_comparison returns empty mismatches when versions match."""
    import json

    # Create run and node with checkpoint data
    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")

    # Insert node with checkpoint data
    conn = get_connection(db_path)
    input_versions = {"channel-a": 5, "channel-b": 10}
    conn.execute(
        "INSERT INTO node_executions (id, run_id, node_name, status, started_at, content_hash, input_versions) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("node-1", "run-1", "step-1", "completed", "2026-04-17T12:00:00Z", "abc123", json.dumps(input_versions))
    )

    # Insert matching channel states
    conn.execute("INSERT INTO channel_states (run_id, channel_key, channel_type, version, updated_at) VALUES (?, ?, ?, ?, ?)",
                 ("run-1", "channel-a", "value", 5, "2026-04-17T12:00:00Z"))
    conn.execute("INSERT INTO channel_states (run_id, channel_key, channel_type, version, updated_at) VALUES (?, ?, ?, ?, ?)",
                 ("run-1", "channel-b", "value", 10, "2026-04-17T12:00:00Z"))
    conn.commit()
    conn.close()

    result = get_checkpoint_comparison(db_path, "run-1", "node-1")

    assert result is not None
    assert result["content_hash"] == "abc123"
    assert result["input_versions"] == {"channel-a": 5, "channel-b": 10}
    assert result["current_versions"] == {"channel-a": 5, "channel-b": 10}
    assert result["mismatches"] == []


def test_get_checkpoint_comparison_version_mismatch(db_path: Path):
    """Test get_checkpoint_comparison returns status=mismatch when versions differ."""
    import json

    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")

    # Insert node with checkpoint version 5
    conn = get_connection(db_path)
    input_versions = {"channel-a": 5}
    conn.execute(
        "INSERT INTO node_executions (id, run_id, node_name, status, started_at, content_hash, input_versions) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("node-1", "run-1", "step-1", "completed", "2026-04-17T12:00:00Z", "abc123", json.dumps(input_versions))
    )

    # Insert current channel state with version 7 (mismatch)
    conn.execute("INSERT INTO channel_states (run_id, channel_key, channel_type, version, updated_at) VALUES (?, ?, ?, ?, ?)",
                 ("run-1", "channel-a", "value", 7, "2026-04-17T12:00:00Z"))
    conn.commit()
    conn.close()

    result = get_checkpoint_comparison(db_path, "run-1", "node-1")

    assert result is not None
    assert len(result["mismatches"]) == 1
    assert result["mismatches"][0] == {
        "channel_key": "channel-a",
        "checkpoint_version": 5,
        "current_version": 7,
        "status": "mismatch"
    }


def test_get_checkpoint_comparison_channel_missing(db_path: Path):
    """Test get_checkpoint_comparison returns status=missing when channel in checkpoint but not current."""
    import json

    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")

    # Insert node with checkpoint data for channel-a
    conn = get_connection(db_path)
    input_versions = {"channel-a": 5}
    conn.execute(
        "INSERT INTO node_executions (id, run_id, node_name, status, started_at, content_hash, input_versions) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("node-1", "run-1", "step-1", "completed", "2026-04-17T12:00:00Z", "abc123", json.dumps(input_versions))
    )

    # No channel_states inserted - channel is missing
    conn.commit()
    conn.close()

    result = get_checkpoint_comparison(db_path, "run-1", "node-1")

    assert result is not None
    assert len(result["mismatches"]) == 1
    assert result["mismatches"][0] == {
        "channel_key": "channel-a",
        "checkpoint_version": 5,
        "current_version": None,
        "status": "missing"
    }


def test_get_checkpoint_comparison_extra_channel(db_path: Path):
    """Test get_checkpoint_comparison returns status=extra when channel in current but not checkpoint."""
    import json

    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")

    # Insert node with empty checkpoint data
    conn = get_connection(db_path)
    input_versions = {}
    conn.execute(
        "INSERT INTO node_executions (id, run_id, node_name, status, started_at, content_hash, input_versions) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("node-1", "run-1", "step-1", "completed", "2026-04-17T12:00:00Z", "abc123", json.dumps(input_versions))
    )

    # Insert channel state that wasn't in checkpoint
    conn.execute("INSERT INTO channel_states (run_id, channel_key, channel_type, version, updated_at) VALUES (?, ?, ?, ?, ?)",
                 ("run-1", "channel-b", "value", 10, "2026-04-17T12:00:00Z"))
    conn.commit()
    conn.close()

    result = get_checkpoint_comparison(db_path, "run-1", "node-1")

    assert result is not None
    assert len(result["mismatches"]) == 1
    assert result["mismatches"][0] == {
        "channel_key": "channel-b",
        "checkpoint_version": None,
        "current_version": 10,
        "status": "extra"
    }


def test_get_checkpoint_comparison_no_checkpoint_data(db_path: Path):
    """Test get_checkpoint_comparison returns None when node has no checkpoint data."""
    insert_run(db_path, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")

    # Insert node without checkpoint data (content_hash is NULL)
    insert_node(db_path, "node-1", "run-1", "step-1", "completed", "2026-04-17T12:00:00Z")

    result = get_checkpoint_comparison(db_path, "run-1", "node-1")

    assert result is None
