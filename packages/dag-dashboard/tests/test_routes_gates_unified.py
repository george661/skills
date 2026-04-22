"""Tests for unified gate approval endpoints."""
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dag_dashboard.server import create_app
from dag_dashboard.database import init_db


@pytest.fixture
def test_app():
    """Create test app with temp database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        events_dir = Path(tmpdir) / "events"
        events_dir.mkdir()
        checkpoint_dir = Path(tmpdir) / "checkpoints"
        checkpoint_dir.mkdir()
        
        # Initialize database
        init_db(db_path)
        
        yield db_path, events_dir, checkpoint_dir


def insert_test_run(db_path, run_id, workflow_name="test-workflow", workflow_definition="name: test-workflow\nnodes: []"):
    """Insert a test workflow run."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at, workflow_definition) VALUES (?, ?, ?, ?, ?)",
        (run_id, workflow_name, "running", "2026-04-22T12:00:00Z", workflow_definition)
    )
    conn.commit()
    conn.close()


def insert_test_node(db_path, node_id, run_id, node_name, status="interrupted"):
    """Insert a test node execution."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO node_executions (id, run_id, node_name, status, started_at) VALUES (?, ?, ?, ?, ?)",
        (node_id, run_id, node_name, status, "2026-04-22T12:00:00Z")
    )
    conn.commit()
    conn.close()


def test_approve_emits_both_gate_decided_and_approval_resolved(test_app):
    """POST approve should emit both gate.decided and approval_resolved."""
    db_path, events_dir, checkpoint_dir = test_app
    
    # Setup: insert a workflow run with an interrupted node
    run_id = "test-run-1"
    workflow_def = """name: test-workflow
nodes:
  - id: test-gate
    type: interrupt
    message: "Approve?"
"""
    
    insert_test_run(db_path, run_id, workflow_definition=workflow_def)
    node_id = f"{run_id}:test-gate"
    insert_test_node(db_path, node_id, run_id, "test-gate")
    
    # Create app and client
    app = create_app(db_path=db_path, events_dir=events_dir, checkpoint_dir_fallback=checkpoint_dir)
    client = TestClient(app)
    
    # Call approve endpoint
    response = client.post(
        f"/api/workflows/{run_id}/gates/test-gate/approve",
        json={"comment": "LGTM"},
    )
    
    assert response.status_code == 200
    
    # Read NDJSON events
    event_file = events_dir / f"{run_id}.ndjson"
    assert event_file.exists()
    
    with open(event_file) as f:
        events = [json.loads(line) for line in f]
    
    # Should have both events
    assert len(events) == 2
    
    # First event: gate.decided (backward compat)
    gate_decided = events[0]
    assert gate_decided["event_type"] == "gate.decided"
    
    # Second event: approval_resolved (new canonical)
    approval_resolved = events[1]
    assert approval_resolved["event_type"] == "approval_resolved"
    assert approval_resolved["payload"]["run_id"] == run_id
    assert approval_resolved["payload"]["node_id"] == "test-gate"
    assert approval_resolved["payload"]["decision"] == "approved"
    assert approval_resolved["payload"]["source"] == "api"
    assert approval_resolved["payload"]["comment"] == "LGTM"


def test_reject_emits_both_events(test_app):
    """POST reject should emit both gate.decided and approval_resolved."""
    db_path, events_dir, checkpoint_dir = test_app
    
    # Setup
    run_id = "test-run-2"
    workflow_def = "name: test-workflow\nnodes:\n  - id: test-gate\n    type: interrupt"
    
    insert_test_run(db_path, run_id, workflow_definition=workflow_def)
    node_id = f"{run_id}:test-gate"
    insert_test_node(db_path, node_id, run_id, "test-gate")
    
    # Create app and client
    app = create_app(db_path=db_path, events_dir=events_dir, checkpoint_dir_fallback=checkpoint_dir)
    client = TestClient(app)
    
    # Call reject endpoint
    response = client.post(
        f"/api/workflows/{run_id}/gates/test-gate/reject",
        json={"comment": "Needs work"},
    )
    
    assert response.status_code == 200
    
    # Read NDJSON events
    event_file = events_dir / f"{run_id}.ndjson"
    with open(event_file) as f:
        events = [json.loads(line) for line in f]
    
    # Should have both events
    assert len(events) == 2
    assert events[0]["event_type"] == "gate.decided"
    assert events[1]["event_type"] == "approval_resolved"
    assert events[1]["payload"]["decision"] == "rejected"


def test_approve_interrupt_node_saves_resume_values(test_app):
    """For interrupt nodes, approve should save resume_values to checkpoint."""
    db_path, events_dir, checkpoint_dir = test_app
    
    # Setup with interrupt node
    run_id = "test-run-3"
    workflow_def = f"""name: test-workflow
config:
  checkpoint_prefix: {checkpoint_dir}
nodes:
  - id: approval-gate
    type: interrupt
    message: "Approve deployment?"
"""
    
    insert_test_run(db_path, run_id, workflow_definition=workflow_def)
    node_id = f"{run_id}:approval-gate"
    insert_test_node(db_path, node_id, run_id, "approval-gate")
    
    # Create interrupt checkpoint with resume_key
    from dag_executor.checkpoint import CheckpointStore, InterruptCheckpoint
    store = CheckpointStore(str(checkpoint_dir))
    interrupt_checkpoint = InterruptCheckpoint(
        node_id="approval-gate",
        resume_key="deployment_approved",
        message="Approve deployment?",
        channels=["terminal"],
    )
    store.save_interrupt("test-workflow", run_id, interrupt_checkpoint)
    
    # Create app and client
    app = create_app(db_path=db_path, events_dir=events_dir, checkpoint_dir_fallback=checkpoint_dir)
    client = TestClient(app)
    
    # Call approve endpoint
    response = client.post(
        f"/api/workflows/{run_id}/gates/approval-gate/approve",
        json={},
    )
    
    assert response.status_code == 200
    
    # Verify resume_values were saved
    resume_values = store.load_resume_values("test-workflow", run_id)
    assert resume_values is not None
    assert resume_values["deployment_approved"] is True


def test_event_shape_matches_cli(test_app):
    """CLI and API should emit identical event shape (except source field)."""
    from dag_executor.gates import build_approval_resolved_event
    
    # Build CLI event
    cli_event = build_approval_resolved_event(
        run_id="test-run",
        node_id="test-node",
        decision="approved",
        decided_by="cli-user",
        source="cli",
        resume_key="test-key",
        resume_value=True,
        comment="test",
    )
    
    # Build API event
    api_event = build_approval_resolved_event(
        run_id="test-run",
        node_id="test-node",
        decision="approved",
        decided_by="api-user",
        source="api",
        resume_key="test-key",
        resume_value=True,
        comment="test",
    )
    
    # Shape should match (same keys, same types)
    assert cli_event.keys() == api_event.keys()
    assert cli_event["event_type"] == api_event["event_type"]
    assert cli_event["payload"].keys() == api_event["payload"].keys()
    
    # Only source should differ
    assert cli_event["payload"]["source"] == "cli"
    assert api_event["payload"]["source"] == "api"


def test_get_workflow_gates_returns_scoped_list(test_app):
    """GET /workflows/{run_id}/gates should return pending gates for that run."""
    db_path, events_dir, checkpoint_dir = test_app
    
    # Setup: two runs, one with pending gate
    run_id_1 = "run-with-gate"
    run_id_2 = "run-without-gate"
    
    for run_id in [run_id_1, run_id_2]:
        insert_test_run(db_path, run_id)
    
    # Only run_id_1 has interrupted node
    node_id = f"{run_id_1}:gate-1"
    insert_test_node(db_path, node_id, run_id_1, "gate-1")
    
    # Create app and client
    app = create_app(db_path=db_path, events_dir=events_dir, checkpoint_dir_fallback=checkpoint_dir)
    client = TestClient(app)
    
    # Call new scoped endpoint
    response = client.get(f"/api/workflows/{run_id_1}/gates")
    
    assert response.status_code == 200
    data = response.json()
    
    # Should return only gate-1
    assert len(data["gates"]) == 1
    assert data["gates"][0]["node_name"] == "gate-1"
    assert data["gates"][0]["run_id"] == run_id_1
