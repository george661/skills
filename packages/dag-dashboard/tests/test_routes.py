"""Tests for REST API routes."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dag_dashboard.database import init_db
from dag_dashboard.queries import insert_run, insert_node, get_node, get_gate_decisions, get_connection, insert_artifact
from dag_dashboard.server import create_app


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    """Create a test database at the expected location."""
    db_path = tmp_path / "dashboard.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def events_dir(tmp_path: Path) -> Path:
    """Create a test events directory."""
    events = tmp_path / "dag-events"
    events.mkdir(exist_ok=True)
    return events


@pytest.fixture
def client(tmp_path: Path, test_db: Path, events_dir: Path) -> TestClient:
    """Create a test client with initialized database."""
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    app = create_app(tmp_path, events_dir=events_dir, checkpoint_dir_fallback=str(checkpoint_dir))
    return TestClient(app, raise_server_exceptions=True)


def test_get_workflows_empty(client: TestClient):
    """Test GET /api/workflows returns empty paginated response."""
    response = client.get("/api/workflows")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["limit"] == 50
    assert data["offset"] == 0


def test_get_workflows_paginated(client: TestClient, test_db: Path):
    """Test GET /api/workflows returns paginated JSON."""
    for i in range(5):
        insert_run(test_db, f"run-{i}", "test-workflow", "running", f"2026-04-17T12:{i:02d}:00Z")

    response = client.get("/api/workflows")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 5
    assert data["total"] == 5
    assert data["limit"] == 50
    assert data["offset"] == 0


def test_get_workflows_with_limit(client: TestClient, test_db: Path):
    """Test GET /api/workflows with custom limit."""
    for i in range(10):
        insert_run(test_db, f"run-{i}", "test-workflow", "running", f"2026-04-17T12:{i:02d}:00Z")

    response = client.get("/api/workflows?limit=3")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 3
    assert data["total"] == 10
    assert data["limit"] == 3


def test_get_workflows_with_offset(client: TestClient, test_db: Path):
    """Test GET /api/workflows with offset."""
    for i in range(5):
        insert_run(test_db, f"run-{i}", "test-workflow", "running", f"2026-04-17T12:{i:02d}:00Z")

    response = client.get("/api/workflows?limit=2&offset=2")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["offset"] == 2


def test_get_workflows_filter_by_status(client: TestClient, test_db: Path):
    """Test GET /api/workflows?status=running filters correctly."""
    insert_run(test_db, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_run(test_db, "run-2", "wf1", "completed", "2026-04-17T12:01:00Z")
    insert_run(test_db, "run-3", "wf1", "running", "2026-04-17T12:02:00Z")

    response = client.get("/api/workflows?status=running")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["total"] == 2


def test_get_workflows_sort_by_started_at(client: TestClient, test_db: Path):
    """Test GET /api/workflows?sortBy=started_at sorts correctly."""
    insert_run(test_db, "run-1", "wf1", "running", "2026-04-17T12:02:00Z")
    insert_run(test_db, "run-2", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_run(test_db, "run-3", "wf1", "running", "2026-04-17T12:01:00Z")

    response = client.get("/api/workflows?sort_by=started_at")
    assert response.status_code == 200
    data = response.json()
    assert data["items"][0]["id"] == "run-1"
    assert data["items"][1]["id"] == "run-3"
    assert data["items"][2]["id"] == "run-2"


def test_get_workflows_invalid_sort_by(client: TestClient):
    """Test GET /api/workflows?sortBy=malicious returns 400."""
    response = client.get("/api/workflows?sort_by=malicious")
    assert response.status_code == 422


def test_get_workflows_invalid_status(client: TestClient):
    """Test GET /api/workflows with invalid status returns 400."""
    response = client.get("/api/workflows?status=invalid")
    assert response.status_code == 422


def test_get_workflow_by_id(client: TestClient, test_db: Path):
    """Test GET /api/workflows/{run_id} returns single workflow."""
    insert_run(test_db, "run-123", "test-workflow", "running", "2026-04-17T12:00:00Z")
    insert_node(test_db, "node-1", "run-123", "step-1", "completed", "2026-04-17T12:00:01Z")
    insert_node(test_db, "node-2", "run-123", "step-2", "running", "2026-04-17T12:00:05Z")

    response = client.get("/api/workflows/run-123")
    assert response.status_code == 200
    data = response.json()
    assert data["run"]["id"] == "run-123"
    assert data["run"]["workflow_name"] == "test-workflow"
    assert len(data["nodes"]) == 2


def test_get_workflow_not_found(client: TestClient):
    """Test GET /api/workflows/{run_id} returns 404 for unknown."""
    response = client.get("/api/workflows/unknown")
    assert response.status_code == 404


def test_get_node_by_id(client: TestClient, test_db: Path):
    """Test GET /api/workflows/{run_id}/nodes/{node_id} returns node detail."""
    insert_run(test_db, "run-123", "test-workflow", "running", "2026-04-17T12:00:00Z")
    insert_node(test_db, "node-456", "run-123", "step-1", "completed", "2026-04-17T12:00:01Z")

    response = client.get("/api/workflows/run-123/nodes/node-456")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "node-456"
    assert data["run_id"] == "run-123"
    assert data["node_name"] == "step-1"


def test_get_node_not_found(client: TestClient, test_db: Path):
    """Test GET /api/workflows/{run_id}/nodes/{node_id} returns 404 for unknown."""
    insert_run(test_db, "run-123", "test-workflow", "running", "2026-04-17T12:00:00Z")

    response = client.get("/api/workflows/run-123/nodes/unknown")
    assert response.status_code == 404


def test_get_workflows_summary_empty(client: TestClient):
    """Test GET /api/workflows/summary returns zeros when no runs exist."""
    response = client.get("/api/workflows/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["running"] == 0
    assert data["completed"] == 0
    assert data["failed"] == 0
    assert data["pending"] == 0
    assert data["cancelled"] == 0


def test_get_workflows_summary_with_data(client: TestClient, test_db: Path):
    """Test GET /api/workflows/summary returns correct counts."""
    insert_run(test_db, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_run(test_db, "run-2", "wf1", "running", "2026-04-17T12:01:00Z")
    insert_run(test_db, "run-3", "wf1", "completed", "2026-04-17T12:02:00Z")
    insert_run(test_db, "run-4", "wf1", "failed", "2026-04-17T12:03:00Z")
    insert_run(test_db, "run-5", "wf1", "pending", "2026-04-17T12:04:00Z")
    insert_run(test_db, "run-6", "wf1", "cancelled", "2026-04-17T12:05:00Z")

    response = client.get("/api/workflows/summary")
    assert response.status_code == 200
    data = response.json()
    assert data["running"] == 2
    assert data["completed"] == 1
    assert data["failed"] == 1
    assert data["pending"] == 1
    assert data["cancelled"] == 1


def test_get_workflows_name_filter(client: TestClient, test_db: Path):
    """Test GET /api/workflows?name=X filters by workflow name."""
    insert_run(test_db, "run-1", "data-pipeline", "running", "2026-04-17T12:00:00Z")
    insert_run(test_db, "run-2", "ml-training", "running", "2026-04-17T12:01:00Z")
    insert_run(test_db, "run-3", "data-export", "completed", "2026-04-17T12:02:00Z")

    response = client.get("/api/workflows?name=data")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["items"]) == 2
    workflow_names = [item["workflow_name"] for item in data["items"]]
    assert "data-pipeline" in workflow_names
    assert "data-export" in workflow_names


def test_get_workflows_date_range_filter(client: TestClient, test_db: Path):
    """Test GET /api/workflows with date range filters."""
    insert_run(test_db, "run-1", "wf1", "running", "2026-04-17T10:00:00Z")
    insert_run(test_db, "run-2", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_run(test_db, "run-3", "wf1", "running", "2026-04-17T14:00:00Z")
    insert_run(test_db, "run-4", "wf1", "running", "2026-04-17T16:00:00Z")

    response = client.get("/api/workflows?started_after=2026-04-17T11:00:00Z&started_before=2026-04-17T15:00:00Z")
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    run_ids = [item["id"] for item in data["items"]]
    assert "run-2" in run_ids
    assert "run-3" in run_ids


def test_get_workflow_includes_totals(client: TestClient, test_db: Path):
    """Test GET /api/workflows/{run_id} returns totals object."""
    insert_run(test_db, "run-totals", "test-workflow", "running", "2026-04-17T12:00:00Z")
    insert_node(test_db, "node-1", "run-totals", "step-1", "completed", "2026-04-17T12:00:00Z",
                model="gpt-4", tokens_input=100, tokens_output=50, tokens_cache=25, cost=0.05)
    insert_node(test_db, "node-2", "run-totals", "step-2", "failed", "2026-04-17T12:01:00Z",
                model="gpt-4", tokens_input=200, tokens_output=75, tokens_cache=30, cost=0.08)

    response = client.get("/api/workflows/run-totals")
    assert response.status_code == 200
    data = response.json()

    # Verify totals object exists
    assert "totals" in data
    totals = data["totals"]

    # Verify totals structure
    assert "cost" in totals
    assert "tokens_input" in totals
    assert "tokens_output" in totals
    assert "tokens_cache" in totals
    assert "total_tokens" in totals
    assert "failed_nodes" in totals
    assert "skipped_nodes" in totals

    # Verify aggregated values
    assert totals["tokens_input"] == 300
    assert totals["tokens_output"] == 125
    assert totals["tokens_cache"] == 55
    assert totals["total_tokens"] == 480
    assert totals["cost"] == 0.13
    assert totals["failed_nodes"] == 1


def test_get_workflow_node_returns_token_breakdown(client: TestClient, test_db: Path):
    """Test GET /api/workflows/{run_id}/nodes/{node_id} returns token breakdown fields."""
    insert_run(test_db, "run-tokens", "test-workflow", "running", "2026-04-17T12:00:00Z")
    insert_node(test_db, "node-tokens", "run-tokens", "step-with-tokens", "completed",
                "2026-04-17T12:00:00Z",
                model="gpt-4", tokens_input=500, tokens_output=300, tokens_cache=100, cost=0.15)

    response = client.get("/api/workflows/run-tokens/nodes/node-tokens")
    assert response.status_code == 200
    data = response.json()

    # Verify token breakdown fields are present
    assert "tokens_input" in data
    assert "tokens_output" in data
    assert "tokens_cache" in data

    # Verify values
    assert data["tokens_input"] == 500
    assert data["tokens_output"] == 300
    assert data["tokens_cache"] == 100


def test_get_workflow_node_artifact_url_present(client: TestClient, test_db: Path):
    """Test GET /api/workflows/{run_id}/nodes/{node_id} includes artifact URL in enriched response."""
    from dag_dashboard.queries import insert_artifact

    insert_run(test_db, "run-artifact", "test-workflow", "running", "2026-04-17T12:00:00Z")
    insert_node(test_db, "node-artifact", "run-artifact", "step-with-artifact", "completed",
                "2026-04-17T12:00:00Z")
    insert_artifact(test_db, "node-artifact", "output.json", "application/json",
                    "2026-04-17T12:01:30Z", url="https://example.com/artifacts/output.json")

    response = client.get("/api/workflows/run-artifact/nodes/node-artifact")
    assert response.status_code == 200
    data = response.json()

    # Verify artifacts are present in enriched response
    assert "artifacts" in data
    assert len(data["artifacts"]) > 0

    # Verify URL field is present in artifact
    artifact = data["artifacts"][0]
    assert "url" in artifact
    assert artifact["url"] == "https://example.com/artifacts/output.json"


def test_post_gate_approve_success(client: TestClient, test_db: Path, events_dir: Path):
    """Test POST /api/workflows/{run_id}/gates/{node_name}/approve returns 200 with decision record."""
    insert_run(test_db, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_node(test_db, "run-1:gate-1", "run-1", "gate-1", "interrupted", started_at="2026-04-17T12:00:00Z")

    response = client.post(
        "/api/workflows/run-1/gates/gate-1/approve",
        json={"decided_by": "alice", "comment": "LGTM"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "approved"
    assert data["decided_by"] == "alice"
    assert data["comment"] == "LGTM"

    # Verify node status updated to completed
    node = get_node(test_db, "run-1:gate-1")
    assert node["status"] == "completed"

    # Verify gate decision persisted in DB
    decisions = get_gate_decisions(test_db, "run-1")
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "approved"

    # Verify NDJSON events appended (dual-emit: gate.decided + approval_resolved)
    event_file = events_dir / "run-1.ndjson"
    assert event_file.exists()
    with open(event_file) as f:
        lines = f.readlines()
        assert len(lines) == 2
        events = [json.loads(line) for line in lines]

        # First event: gate.decided
        assert events[0]["event_type"] == "gate.decided"
        payload = json.loads(events[0]["payload"])
        assert payload["node_name"] == "gate-1"
        assert payload["decision"] == "approved"

        # Second event: approval_resolved
        assert events[1]["event_type"] == "approval_resolved"


def test_post_gate_reject_success(client: TestClient, test_db: Path, events_dir: Path):
    """Test POST /api/workflows/{run_id}/gates/{node_name}/reject returns 200 with decision record."""
    insert_run(test_db, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_node(test_db, "run-1:gate-1", "run-1", "gate-1", "interrupted", started_at="2026-04-17T12:00:00Z")

    response = client.post(
        "/api/workflows/run-1/gates/gate-1/reject",
        json={"decided_by": "bob", "comment": "Needs more testing"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["decision"] == "rejected"
    assert data["decided_by"] == "bob"

    # Verify node status updated to failed
    node = get_node(test_db, "run-1:gate-1")
    assert node["status"] == "failed"

    # Verify gate decision persisted
    decisions = get_gate_decisions(test_db, "run-1")
    assert len(decisions) == 1
    assert decisions[0]["decision"] == "rejected"

    # Verify NDJSON events appended (dual-emit: gate.decided + approval_resolved)
    event_file = events_dir / "run-1.ndjson"
    assert event_file.exists()
    with open(event_file) as f:
        lines = f.readlines()
        assert len(lines) == 2
        events = [json.loads(line) for line in lines]

        # First event: gate.decided
        assert events[0]["event_type"] == "gate.decided"
        payload = json.loads(events[0]["payload"])
        assert payload["node_name"] == "gate-1"
        assert payload["decision"] == "rejected"

        # Second event: approval_resolved
        assert events[1]["event_type"] == "approval_resolved"


def test_post_gate_approve_run_not_found(client: TestClient, test_db: Path):
    """Test POST approve on non-existent run returns 404."""
    response = client.post(
        "/api/workflows/nonexistent/gates/gate-1/approve",
        json={"decided_by": "alice"}
    )
    assert response.status_code == 404


def test_post_gate_approve_node_not_interrupted(client: TestClient, test_db: Path):
    """Test POST approve on non-interrupted node returns 409."""
    insert_run(test_db, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_node(test_db, "run-1:node-1", "run-1", "node-1", "completed", started_at="2026-04-17T12:00:00Z")

    response = client.post(
        "/api/workflows/run-1/gates/node-1/approve",
        json={"decided_by": "alice"}
    )
    assert response.status_code == 409


def test_get_gates_pending_empty(client: TestClient, test_db: Path):
    """Test GET /api/gates/pending returns empty list when no pending gates."""
    insert_run(test_db, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_node(test_db, "run-1:node-1", "run-1", "node-1", "completed", started_at="2026-04-17T12:00:00Z")

    response = client.get("/api/gates/pending")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 0
    assert data["gates"] == []


def test_get_gates_pending_with_gates(client: TestClient, test_db: Path):
    """Test GET /api/gates/pending returns list of pending gates with count."""
    insert_run(test_db, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_node(test_db, "run-1:gate-1", "run-1", "gate-1", "interrupted", started_at="2026-04-17T12:00:00Z")
    insert_node(test_db, "run-1:gate-2", "run-1", "gate-2", "interrupted", started_at="2026-04-17T12:01:00Z")

    response = client.get("/api/gates/pending")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 2
    assert len(data["gates"]) == 2

def test_get_interrupt_context_success(client: TestClient, test_db: Path, tmp_path: Path):
    """Test GET /api/workflows/{run_id}/nodes/{node_name}/interrupt returns interrupt checkpoint."""
    from dag_executor.checkpoint import CheckpointStore, InterruptCheckpoint
    
    # Create checkpoint directory first
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    workflow_def = f"""
config:
  checkpoint_prefix: {checkpoint_dir}
nodes:
  - name: node-1
    type: interrupt
"""
    
    # Insert run and interrupted node
    insert_run(test_db, "run-1", "test-workflow", "running", "2026-04-17T12:00:00Z", workflow_definition=workflow_def)
    insert_node(test_db, "run-1:node-1", "run-1", "node-1", "interrupted", started_at="2026-04-17T12:00:00Z")
    
    # Create a checkpoint
    store = CheckpointStore(str(checkpoint_dir))
    interrupt_checkpoint = InterruptCheckpoint(
        node_id="run-1:node-1",
        message="Please provide input",
        resume_key="user_input",
        timeout=300,
        channels=["terminal"]
    )
    store.save_interrupt("test-workflow", "run-1", interrupt_checkpoint)
    

    
    response = client.get("/api/workflows/run-1/nodes/node-1/interrupt")
    assert response.status_code == 200
    data = response.json()
    assert data["resume_key"] == "user_input"
    assert data["message"] == "Please provide input"
    assert data["timeout"] == 300


def test_get_interrupt_context_run_not_found(client: TestClient):
    """Test GET interrupt endpoint returns 404 when run not found."""
    response = client.get("/api/workflows/nonexistent/nodes/node-1/interrupt")
    assert response.status_code == 404
    assert "Workflow run not found" in response.json()["detail"]


def test_get_interrupt_context_node_not_found(client: TestClient, test_db: Path):
    """Test GET interrupt endpoint returns 404 when node not found."""
    insert_run(test_db, "run-1", "test-workflow", "running", "2026-04-17T12:00:00Z")
    
    response = client.get("/api/workflows/run-1/nodes/nonexistent/interrupt")
    assert response.status_code == 404
    assert "Node not found" in response.json()["detail"]


def test_get_interrupt_context_node_not_interrupted(client: TestClient, test_db: Path):
    """Test GET interrupt endpoint returns 409 when node is not interrupted."""
    insert_run(test_db, "run-1", "test-workflow", "running", "2026-04-17T12:00:00Z")
    insert_node(test_db, "run-1:node-1", "run-1", "node-1", "completed", started_at="2026-04-17T12:00:00Z")
    
    response = client.get("/api/workflows/run-1/nodes/node-1/interrupt")
    assert response.status_code == 409
    assert "not in interrupted state" in response.json()["detail"]


def test_post_interrupt_resume_success(client: TestClient, test_db: Path, tmp_path: Path):
    """Test POST /api/workflows/{run_id}/interrupts/{node_name}/resume completes node."""
    from dag_executor.checkpoint import CheckpointStore, InterruptCheckpoint
    
    # Create checkpoint directory first
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    workflow_def = f"""
config:
  checkpoint_prefix: {checkpoint_dir}
nodes:
  - name: node-1
    type: interrupt
"""
    
    # Insert run and interrupted node
    insert_run(test_db, "run-1", "test-workflow", "running", "2026-04-17T12:00:00Z", workflow_definition=workflow_def)
    insert_node(test_db, "run-1:node-1", "run-1", "node-1", "interrupted", started_at="2026-04-17T12:00:00Z")
    
    # Create a checkpoint
    store = CheckpointStore(str(checkpoint_dir))
    interrupt_checkpoint = InterruptCheckpoint(
        node_id="run-1:node-1",
        message="Please provide input",
        resume_key="user_input",
        timeout=300,
        channels=["terminal"]
    )
    store.save_interrupt("test-workflow", "run-1", interrupt_checkpoint)
    

    
    response = client.post(
        "/api/workflows/run-1/interrupts/node-1/resume",
        json={
            "resume_value": "user response",
            "decided_by": "test-user",
            "comment": "Resuming workflow"
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == "run-1"
    assert data["node_name"] == "node-1"
    assert data["resumed"] is True
    
    # Verify node status updated
    node = get_node(test_db, "run-1:node-1")
    assert node["status"] == "completed"
    assert node["outputs"]["resume_value"] == "user response"


def test_post_interrupt_resume_with_dict_value(client: TestClient, test_db: Path, tmp_path: Path):
    """Test POST resume with dict resume_value."""
    from dag_executor.checkpoint import CheckpointStore, InterruptCheckpoint
    
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    workflow_def = f"""
config:
  checkpoint_prefix: {checkpoint_dir}
nodes:
  - name: node-1
    type: interrupt
"""
    
    insert_run(test_db, "run-1", "test-workflow", "running", "2026-04-17T12:00:00Z", workflow_definition=workflow_def)
    insert_node(test_db, "run-1:node-1", "run-1", "node-1", "interrupted", started_at="2026-04-17T12:00:00Z")
    
    store = CheckpointStore(str(checkpoint_dir))
    interrupt_checkpoint = InterruptCheckpoint(
        node_id="run-1:node-1",
        message="Provide config",
        resume_key="config",
        timeout=300,
        channels=["terminal"]
    )
    store.save_interrupt("test-workflow", "run-1", interrupt_checkpoint)
    
    response = client.post(
        "/api/workflows/run-1/interrupts/node-1/resume",
        json={
            "resume_value": {"enabled": True, "count": 5},
            "decided_by": "test-user"
        }
    )
    assert response.status_code == 200
    node = get_node(test_db, "run-1:node-1")
    assert node["outputs"]["resume_value"] == {"enabled": True, "count": 5}


def test_post_interrupt_resume_with_list_value(client: TestClient, test_db: Path, tmp_path: Path):
    """Test POST resume with list resume_value."""
    from dag_executor.checkpoint import CheckpointStore, InterruptCheckpoint
    
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    workflow_def = f"""
config:
  checkpoint_prefix: {checkpoint_dir}
nodes:
  - name: node-1
    type: interrupt
"""
    
    insert_run(test_db, "run-1", "test-workflow", "running", "2026-04-17T12:00:00Z", workflow_definition=workflow_def)
    insert_node(test_db, "run-1:node-1", "run-1", "node-1", "interrupted", started_at="2026-04-17T12:00:00Z")
    
    store = CheckpointStore(str(checkpoint_dir))
    interrupt_checkpoint = InterruptCheckpoint(
        node_id="run-1:node-1",
        message="Provide items",
        resume_key="items",
        timeout=300,
        channels=["terminal"]
    )
    store.save_interrupt("test-workflow", "run-1", interrupt_checkpoint)
    
    response = client.post(
        "/api/workflows/run-1/interrupts/node-1/resume",
        json={
            "resume_value": [1, 2, 3, "test"],
            "decided_by": "test-user"
        }
    )
    assert response.status_code == 200
    node = get_node(test_db, "run-1:node-1")
    assert node["outputs"]["resume_value"] == [1, 2, 3, "test"]


def test_post_interrupt_resume_with_number_value(client: TestClient, test_db: Path, tmp_path: Path):
    """Test POST resume with number resume_value."""
    from dag_executor.checkpoint import CheckpointStore, InterruptCheckpoint
    
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    workflow_def = f"""
config:
  checkpoint_prefix: {checkpoint_dir}
nodes:
  - name: node-1
    type: interrupt
"""
    
    insert_run(test_db, "run-1", "test-workflow", "running", "2026-04-17T12:00:00Z", workflow_definition=workflow_def)
    insert_node(test_db, "run-1:node-1", "run-1", "node-1", "interrupted", started_at="2026-04-17T12:00:00Z")
    
    store = CheckpointStore(str(checkpoint_dir))
    interrupt_checkpoint = InterruptCheckpoint(
        node_id="run-1:node-1",
        message="Provide count",
        resume_key="count",
        timeout=300,
        channels=["terminal"]
    )
    store.save_interrupt("test-workflow", "run-1", interrupt_checkpoint)
    
    response = client.post(
        "/api/workflows/run-1/interrupts/node-1/resume",
        json={
            "resume_value": 42,
            "decided_by": "test-user"
        }
    )
    assert response.status_code == 200
    node = get_node(test_db, "run-1:node-1")
    assert node["outputs"]["resume_value"] == 42


def test_post_interrupt_resume_with_bool_value(client: TestClient, test_db: Path, tmp_path: Path):
    """Test POST resume with boolean resume_value."""
    from dag_executor.checkpoint import CheckpointStore, InterruptCheckpoint
    
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    workflow_def = f"""
config:
  checkpoint_prefix: {checkpoint_dir}
nodes:
  - name: node-1
    type: interrupt
"""
    
    insert_run(test_db, "run-1", "test-workflow", "running", "2026-04-17T12:00:00Z", workflow_definition=workflow_def)
    insert_node(test_db, "run-1:node-1", "run-1", "node-1", "interrupted", started_at="2026-04-17T12:00:00Z")
    
    store = CheckpointStore(str(checkpoint_dir))
    interrupt_checkpoint = InterruptCheckpoint(
        node_id="run-1:node-1",
        message="Approve?",
        resume_key="approved",
        timeout=300,
        channels=["terminal"]
    )
    store.save_interrupt("test-workflow", "run-1", interrupt_checkpoint)
    
    response = client.post(
        "/api/workflows/run-1/interrupts/node-1/resume",
        json={
            "resume_value": True,
            "decided_by": "test-user"
        }
    )
    assert response.status_code == 200
    node = get_node(test_db, "run-1:node-1")
    assert node["outputs"]["resume_value"] == True


def test_get_node_checkpoint_returns_comparison_data(client: TestClient, test_db: Path):
    """Test GET /api/workflows/{run_id}/nodes/{node_id}/checkpoint returns 200 with comparison data."""
    # Insert run and node with checkpoint data
    insert_run(test_db, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")

    conn = get_connection(test_db)
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

    response = client.get("/api/workflows/run-1/nodes/node-1/checkpoint")

    assert response.status_code == 200
    data = response.json()
    assert data["content_hash"] == "abc123"
    assert data["input_versions"] == {"channel-a": 5, "channel-b": 10}
    assert data["current_versions"] == {"channel-a": 5, "channel-b": 10}
    assert data["mismatches"] == []


def test_get_node_checkpoint_returns_404_when_node_not_found(client: TestClient, test_db: Path):
    """Test GET /api/workflows/{run_id}/nodes/{node_id}/checkpoint returns 404 when node does not exist."""
    insert_run(test_db, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")

    response = client.get("/api/workflows/run-1/nodes/nonexistent/checkpoint")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_get_node_checkpoint_returns_404_when_no_checkpoint_data(client: TestClient, test_db: Path):
    """Test GET /api/workflows/{run_id}/nodes/{node_id}/checkpoint returns 404 when node has no checkpoint data."""
    insert_run(test_db, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_node(test_db, "node-1", "run-1", "step-1", "completed", "2026-04-17T12:00:00Z")

    response = client.get("/api/workflows/run-1/nodes/node-1/checkpoint")

    assert response.status_code == 404
    assert "checkpoint" in response.json()["detail"].lower()


def test_get_node_includes_content_hash_and_input_versions(client: TestClient, test_db: Path):
    """Test GET /api/workflows/{run_id}/nodes/{node_id} includes content_hash and input_versions fields."""
    insert_run(test_db, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")

    conn = get_connection(test_db)
    input_versions = {"channel-a": 5}
    conn.execute(
        "INSERT INTO node_executions (id, run_id, node_name, status, started_at, content_hash, input_versions) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("node-1", "run-1", "step-1", "completed", "2026-04-17T12:00:00Z", "abc123", json.dumps(input_versions))
    )
    conn.commit()
    conn.close()

    response = client.get("/api/workflows/run-1/nodes/node-1")

    assert response.status_code == 200
    data = response.json()
    assert "content_hash" in data
    assert data["content_hash"] == "abc123"
    assert "input_versions" in data
    assert data["input_versions"] == json.dumps(input_versions)


def test_get_workflow_node_includes_upstream_context_for_gate(client: TestClient, test_db: Path):
    """Test that get_workflow_node includes upstream_context with resolved artifacts."""
    # Insert a run and upstream nodes
    insert_run(test_db, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_node(test_db, "node-upstream-a", "run-1", "upstream-a", "completed", "2026-04-17T12:00:00Z")
    insert_node(test_db, "node-upstream-b", "run-1", "upstream-b", "completed", "2026-04-17T12:00:00Z")
    
    # Insert artifacts for upstream nodes
    insert_artifact(test_db, "node-upstream-a", "result.json", "json", "2026-04-17T12:01:00Z", content='{"data": "a"}')
    insert_artifact(test_db, "node-upstream-b", "output.csv", "csv", "2026-04-17T12:01:00Z", path="/tmp/output.csv")
    
    # Insert gate node with depends_on
    depends_on = json.dumps(["upstream-a", "upstream-b"])
    conn = get_connection(test_db)
    conn.execute(
        "INSERT INTO node_executions (id, run_id, node_name, status, started_at, depends_on) VALUES (?, ?, ?, ?, ?, ?)",
        ("node-gate", "run-1", "gate", "pending", "2026-04-17T12:02:00Z", depends_on)
    )
    conn.commit()
    conn.close()
    
    response = client.get("/api/workflows/run-1/nodes/node-gate")
    
    assert response.status_code == 200
    data = response.json()
    assert "upstream_context" in data
    assert len(data["upstream_context"]) == 2
    
    # Check upstream-a
    upstream_a = next((u for u in data["upstream_context"] if u["node_name"] == "upstream-a"), None)
    assert upstream_a is not None
    assert upstream_a["status"] == "completed"
    assert len(upstream_a["artifacts"]) == 1
    assert upstream_a["artifacts"][0]["name"] == "result.json"
    
    # Check upstream-b
    upstream_b = next((u for u in data["upstream_context"] if u["node_name"] == "upstream-b"), None)
    assert upstream_b is not None
    assert upstream_b["status"] == "completed"
    assert len(upstream_b["artifacts"]) == 1
    assert upstream_b["artifacts"][0]["name"] == "output.csv"


def test_get_workflow_node_upstream_context_empty_when_no_depends_on(client: TestClient, test_db: Path):
    """Test that upstream_context is empty when node has no depends_on."""
    insert_run(test_db, "run-1", "wf1", "running", "2026-04-17T12:00:00Z")
    insert_node(test_db, "node-1", "run-1", "gate", "pending", "2026-04-17T12:00:00Z")
    
    response = client.get("/api/workflows/run-1/nodes/node-1")
    
    assert response.status_code == 200
    data = response.json()
    assert "upstream_context" in data
    assert data["upstream_context"] == []


# --- GW-5197: run grouping by parent_run_id ---------------------------------


def _insert_with_parent(db_path: Path, run_id: str, parent: "str | None", status: str, started_at: str) -> None:
    import sqlite3
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO workflow_runs (id, workflow_name, status, started_at, parent_run_id) VALUES (?, ?, ?, ?, ?)",
            (run_id, "wf", status, started_at, parent),
        )
        conn.commit()
    finally:
        conn.close()


def test_get_workflows_group_by_parent_returns_grouped_response(client: TestClient, test_db: Path):
    """GET /api/workflows?group_by=parent returns items with children and aggregate_status."""
    _insert_with_parent(test_db, "root-a", None, "completed", "2026-04-22T10:00:00Z")
    _insert_with_parent(test_db, "child-1", "root-a", "failed", "2026-04-22T10:01:00Z")
    _insert_with_parent(test_db, "child-2", "root-a", "completed", "2026-04-22T10:02:00Z")

    response = client.get("/api/workflows?group_by=parent")
    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 1
    assert len(data["items"]) == 1
    root = data["items"][0]
    assert root["id"] == "root-a"
    assert "children" in root
    assert len(root["children"]) == 2
    assert root["aggregate_status"] == "failed"  # worst child wins


def test_get_workflows_default_is_flat_backwards_compat(client: TestClient, test_db: Path):
    """GET /api/workflows (no group_by) keeps the existing flat shape — no 'children' key."""
    _insert_with_parent(test_db, "root-a", None, "completed", "2026-04-22T10:00:00Z")
    _insert_with_parent(test_db, "child-1", "root-a", "completed", "2026-04-22T10:01:00Z")

    response = client.get("/api/workflows")
    assert response.status_code == 200
    data = response.json()

    assert data["total"] == 2  # flat: both rows are top-level
    for item in data["items"]:
        assert "children" not in item
        assert "aggregate_status" not in item


# ---------------------------------------------------------------------------
# Escalation endpoint tests (on_failure=escalate)
# ---------------------------------------------------------------------------

def test_get_escalation_returns_checkpoint(client: TestClient, test_db: Path, tmp_path: Path):
    """GET /workflows/{run}/escalations/{node} surfaces the EscalationCheckpoint."""
    from dag_executor.checkpoint import CheckpointStore, EscalationCheckpoint

    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    workflow_def = f"""
name: Test Workflow
config:
  checkpoint_prefix: {checkpoint_dir}
nodes:
  - name: node-1
    type: prompt
"""
    insert_run(
        test_db, "run-e1", "test-workflow", "paused",
        "2026-04-17T12:00:00Z",
        workflow_definition=workflow_def,
    )
    insert_node(
        test_db, "run-e1:node-1", "run-e1", "node-1", "escalated",
        started_at="2026-04-17T12:00:00Z",
    )

    store = CheckpointStore(str(checkpoint_dir))
    store.save_escalation("Test Workflow", "run-e1", EscalationCheckpoint(
        node_id="node-1",
        node_type="prompt",
        error="simulated timeout",
        prompt="Answer in one word.",
        model="local",
        dispatch=None,
        output_format="text",
        writes=["answer"],
    ))

    response = client.get("/api/workflows/run-e1/escalations/node-1")
    assert response.status_code == 200
    payload = response.json()
    assert payload["node_id"] == "node-1"
    assert payload["error"] == "simulated timeout"
    assert payload["writes"] == ["answer"]
    assert payload["prompt"] == "Answer in one word."


def test_post_resume_on_escalated_node_stashes_synthesized_output(
    client: TestClient, test_db: Path, tmp_path: Path
):
    """POST resume on an escalated node saves __escalation_output__."""
    from dag_executor.checkpoint import CheckpointStore, EscalationCheckpoint

    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    workflow_def = f"""
name: Test Workflow
config:
  checkpoint_prefix: {checkpoint_dir}
nodes:
  - name: think
    type: prompt
"""
    insert_run(
        test_db, "run-e2", "test-workflow", "paused",
        "2026-04-17T12:00:00Z",
        workflow_definition=workflow_def,
    )
    insert_node(
        test_db, "run-e2:think", "run-e2", "think", "escalated",
        started_at="2026-04-17T12:00:00Z",
    )

    store = CheckpointStore(str(checkpoint_dir))
    store.save_escalation("Test Workflow", "run-e2", EscalationCheckpoint(
        node_id="think",
        node_type="prompt",
        error="simulated timeout",
        prompt="Answer in one word.",
        output_format="text",
        writes=["answer"],
    ))

    response = client.post(
        "/api/workflows/run-e2/interrupts/think/resume",
        json={
            "resume_value": "SYNTHESIZED-BY-OPUS",
            "decided_by": "test-orchestrator",
            "comment": "escalated from local-timeout",
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["resumed"] is True

    # The synthesized output lands under the magic key — the executor picks
    # it up via __escalation_output__ on resume.
    resume_values = store.load_resume_values("Test Workflow", "run-e2")
    assert resume_values == {"__escalation_output__": "SYNTHESIZED-BY-OPUS"}


def test_post_resume_on_completed_node_rejects(client: TestClient, test_db: Path, tmp_path: Path):
    """Nodes that aren't interrupted/escalated get 409, not 200."""
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    insert_run(
        test_db, "run-e3", "test-workflow", "completed",
        "2026-04-17T12:00:00Z",
        workflow_definition="name: Test\nnodes: []\n",
    )
    insert_node(
        test_db, "run-e3:done", "run-e3", "done", "completed",
        started_at="2026-04-17T12:00:00Z",
    )
    response = client.post(
        "/api/workflows/run-e3/interrupts/done/resume",
        json={"resume_value": "x"},
    )
    assert response.status_code == 409
    assert "status=completed" in response.json()["detail"]
