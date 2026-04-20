"""Integration tests for checkpoint API contract with frontend.

These tests verify the exact JSON shapes that the frontend consumes,
catching contract mismatches before they cause UI failures.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dag_dashboard.server import create_app
from dag_executor.checkpoint import CheckpointMetadata, CheckpointStore
from dag_executor.schema import NodeResult, NodeStatus


@pytest.fixture
def checkpoint_dir(tmp_path: Path) -> Path:
    """Create a temporary checkpoint directory with test data."""
    cp_dir = tmp_path / "checkpoints"
    cp_dir.mkdir()

    store = CheckpointStore(str(cp_dir))

    # Create test workflow run
    workflow_name = "test_workflow"
    run_id = "20260420-120000"

    meta = CheckpointMetadata(
        workflow_name=workflow_name,
        run_id=run_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        inputs={"key": "value"},
        status="completed",
    )
    store.save_metadata(workflow_name, run_id, meta)

    # Add node checkpoints
    result = NodeResult(
        node_id="step1",
        status=NodeStatus.COMPLETED,
        output={"result": "done"},
        error=None,
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
    store.save_node(workflow_name, run_id, "step1", result, "hash123", input_versions={})

    return cp_dir


@pytest.fixture
def client(tmp_path: Path, checkpoint_dir: Path) -> TestClient:
    """Create test client with checkpoint store configured."""
    app = create_app(db_dir=tmp_path, checkpoint_prefix=checkpoint_dir)
    return TestClient(app)


def test_workflows_endpoint_returns_bare_list(client: TestClient) -> None:
    """
    CRITICAL: Frontend expects a bare JSON list of strings.
    
    Frontend code (checkpoint-browser.js line ~42):
        const workflows = Array.isArray(data) ? data : [];
    
    This test would have caught the contract bug if it existed before.
    """
    response = client.get("/api/checkpoints/workflows")
    assert response.status_code == 200

    data = response.json()

    # Must be a bare list, NOT {workflows: [...]}
    assert isinstance(data, list), f"Expected bare list, got: {type(data)}"
    assert len(data) > 0
    assert all(isinstance(wf, str) for wf in data)
    assert "test_workflow" in data


def test_runs_endpoint_returns_bare_list(client: TestClient) -> None:
    """
    CRITICAL: Frontend expects a bare JSON list, NOT {runs: [...]}.
    
    Frontend code (checkpoint-browser.js line ~167):
        const runs = Array.isArray(data) ? data : [];
    
    Each item must have: run_id, workflow_name, started_at, status, node_count, inputs.
    """
    response = client.get("/api/checkpoints/workflows/test_workflow/runs")
    assert response.status_code == 200

    data = response.json()

    # Must be a bare list
    assert isinstance(data, list), f"Expected bare list, got: {type(data)}"
    assert len(data) > 0

    # Check first run has required keys
    run = data[0]
    required_keys = {"run_id", "workflow_name", "started_at", "status", "node_count", "inputs"}
    assert required_keys.issubset(run.keys()), f"Missing keys: {required_keys - run.keys()}"

    # Verify types
    assert isinstance(run["run_id"], str)
    assert isinstance(run["workflow_name"], str)
    assert isinstance(run["started_at"], str)
    assert isinstance(run["status"], str)
    assert isinstance(run["node_count"], int)
    assert isinstance(run["inputs"], dict)


def test_run_detail_endpoint_shape(client: TestClient) -> None:
    """
    CRITICAL: Frontend expects {metadata: {...}, nodes: [...]}.
    
    Each node must have: node_id, status, started_at, completed_at, 
    content_hash, has_error.
    
    Node must NOT have 'timestamp' - that was a bug (line ~313).
    """
    response = client.get("/api/checkpoints/workflows/test_workflow/runs/20260420-120000")
    assert response.status_code == 200

    data = response.json()

    # Must have metadata and nodes keys
    assert "metadata" in data
    assert "nodes" in data
    assert isinstance(data["nodes"], list)

    if len(data["nodes"]) > 0:
        node = data["nodes"][0]
        required_keys = {"node_id", "status", "started_at", "completed_at", "content_hash", "has_error"}
        assert required_keys.issubset(node.keys()), f"Missing keys: {required_keys - node.keys()}"

        # CRITICAL: 'timestamp' must NOT be present (it was a bug)
        assert "timestamp" not in node, "Node should use 'started_at', not 'timestamp'"

        # Verify types
        assert isinstance(node["node_id"], str)
        assert isinstance(node["status"], str)
        assert isinstance(node["started_at"], (str, type(None)))
        assert isinstance(node["completed_at"], (str, type(None)))
        assert isinstance(node["content_hash"], str)
        assert isinstance(node["has_error"], bool)


def test_replay_with_correct_payload_succeeds(client: TestClient, tmp_path: Path) -> None:
    """
    CRITICAL: Backend expects {from_node, overrides, workflow_path}.

    Frontend bug was sending 'state_overrides' instead of 'overrides'.
    This test verifies the schema accepts the correct field names.

    Note: We expect this to fail business logic validation (400) since we're not
    setting up a full workflow, but it should NOT return 422 (schema validation error).
    """
    # Create a dummy workflow file
    workflow_path = tmp_path / "workflow.yaml"
    workflow_path.write_text("nodes:\n  - id: step1\n")

    payload = {
        "from_node": "step1",
        "overrides": {"key": "value"},
        "workflow_path": str(workflow_path),
    }

    response = client.post(
        "/api/checkpoints/workflows/test_workflow/runs/20260420-120000/replay",
        json=payload,
    )

    # Should NOT be 422 (schema validation error) - that would mean the schema rejected our fields
    # It's OK if it's 400 (business logic validation) or 200 (success)
    assert response.status_code != 422, f"Schema validation failed - backend rejected valid fields. Response: {response.text}"


def test_replay_with_wrong_field_name_fails(client: TestClient, tmp_path: Path) -> None:
    """
    CRITICAL: Backend has extra=forbid, so 'state_overrides' must be rejected.
    
    This documents that the old frontend bug (sending state_overrides)
    would have been caught by the backend validation.
    """
    workflow_path = tmp_path / "workflow.yaml"
    workflow_path.write_text("nodes:\n  - id: step1\n")

    # Frontend bug was using 'state_overrides' instead of 'overrides'
    payload = {
        "from_node": "step1",
        "state_overrides": {"key": "value"},  # Wrong field name
        "workflow_path": str(workflow_path),
    }

    response = client.post(
        "/api/checkpoints/workflows/test_workflow/runs/20260420-120000/replay",
        json=payload,
    )

    # Backend should reject with 422 because of extra=forbid
    assert response.status_code == 422, "Backend should reject unknown field 'state_overrides'"


def test_replay_missing_workflow_path_fails(client: TestClient) -> None:
    """
    CRITICAL: workflow_path is required (min_length=1).
    
    Frontend was omitting this field entirely.
    """
    payload = {
        "from_node": "step1",
        # Missing workflow_path
    }

    response = client.post(
        "/api/checkpoints/workflows/test_workflow/runs/20260420-120000/replay",
        json=payload,
    )

    # Backend should reject with 422
    assert response.status_code == 422
