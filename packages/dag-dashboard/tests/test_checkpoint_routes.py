"""Test checkpoint browsing and replay routes."""
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
    
    # Add a node checkpoint
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
def client_with_checkpoints(tmp_path: Path, checkpoint_dir: Path) -> TestClient:
    """Create test client with checkpoint store configured."""
    app = create_app(db_dir=tmp_path, checkpoint_prefix=checkpoint_dir)
    return TestClient(app)


@pytest.fixture
def client_without_checkpoints(tmp_path: Path) -> TestClient:
    """Create test client without checkpoint store."""
    app = create_app(db_dir=tmp_path, checkpoint_prefix=None)
    return TestClient(app)


def test_list_workflows(client_with_checkpoints: TestClient) -> None:
    """Test GET /api/checkpoints/workflows returns workflow list."""
    response = client_with_checkpoints.get("/api/checkpoints/workflows")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert "test_workflow" in data


def test_list_workflows_not_configured(client_without_checkpoints: TestClient) -> None:
    """Test GET /api/checkpoints/workflows returns 404 when not configured."""
    response = client_without_checkpoints.get("/api/checkpoints/workflows")
    # When checkpoint_prefix is None, the router is not mounted at all, so we get a generic 404
    assert response.status_code == 404


def test_list_runs(client_with_checkpoints: TestClient) -> None:
    """Test GET /api/checkpoints/workflows/{wf}/runs returns run list."""
    response = client_with_checkpoints.get("/api/checkpoints/workflows/test_workflow/runs")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert data[0]["run_id"] == "20260420-120000"
    assert data[0]["status"] == "completed"


def test_get_run_detail(client_with_checkpoints: TestClient) -> None:
    """Test GET /api/checkpoints/workflows/{wf}/runs/{run_id} returns full details."""
    response = client_with_checkpoints.get(
        "/api/checkpoints/workflows/test_workflow/runs/20260420-120000"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["metadata"]["run_id"] == "20260420-120000"
    assert len(data["nodes"]) == 1
    assert data["nodes"][0]["node_id"] == "step1"


def test_get_run_detail_not_found(client_with_checkpoints: TestClient) -> None:
    """Test GET run detail returns 404 for missing run."""
    response = client_with_checkpoints.get(
        "/api/checkpoints/workflows/test_workflow/runs/nonexistent"
    )
    assert response.status_code == 404


def test_get_node_checkpoint(client_with_checkpoints: TestClient) -> None:
    """Test GET /api/checkpoints/workflows/{wf}/runs/{run_id}/nodes/{node_id}."""
    response = client_with_checkpoints.get(
        "/api/checkpoints/workflows/test_workflow/runs/20260420-120000/nodes/step1"
    )
    assert response.status_code == 200
    data = response.json()
    assert data["node_id"] == "step1"
    assert data["status"] == "completed"
    assert "output" in data


def test_get_node_checkpoint_not_found(client_with_checkpoints: TestClient) -> None:
    """Test GET node checkpoint returns 404 for missing node."""
    response = client_with_checkpoints.get(
        "/api/checkpoints/workflows/test_workflow/runs/20260420-120000/nodes/nonexistent"
    )
    assert response.status_code == 404
