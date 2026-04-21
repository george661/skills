"""Tests for workflow rerun endpoint."""
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from fastapi.testclient import TestClient
from dag_dashboard.database import init_db
from dag_dashboard.queries import insert_run, get_run
from dag_dashboard.server import create_app


@pytest.fixture
def tmp_client(tmp_path: Path):
    """Create test client with initialized database."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    events_dir = tmp_path / "dag-events"
    events_dir.mkdir(exist_ok=True)

    # Create workflows directory and test workflow file
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    workflow_file = workflows_dir / "test-workflow.yaml"
    workflow_file.write_text("nodes: []")

    app = create_app(db_path=db_path, events_dir=events_dir)
    app.state.workflows_dir = workflows_dir
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def mock_subprocess(mocker):
    """Mock asyncio.create_subprocess_exec to prevent real subprocess spawns in all tests."""
    return mocker.patch("dag_dashboard.routes.asyncio.create_subprocess_exec")


def test_rerun_endpoint_loads_prior_inputs(tmp_client, tmp_path):
    """Test that rerun endpoint loads prior run inputs and creates new run."""
    now = datetime.now(timezone.utc).isoformat()
    db_path = tmp_path / "test.db"
    
    # Create a prior run
    prior_run_id = "prior-run-123"
    insert_run(
        db_path, prior_run_id, "test-workflow", "completed", now,
        inputs={"key": "value", "number": 42}
    )
    
    # Call rerun endpoint
    response = tmp_client.post(
        f"/api/workflows/{prior_run_id}/rerun",
        json={},
    )
    
    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert data["parent_run_id"] == prior_run_id
    
    # Verify new run has same inputs as prior
    new_run = get_run(db_path, data["run_id"])
    assert new_run["inputs"] == {"key": "value", "number": 42}
    assert new_run["parent_run_id"] == prior_run_id


def test_rerun_endpoint_full_replacement_not_merge(tmp_client, tmp_path):
    """Test that rerun endpoint replaces inputs entirely (not merge)."""
    now = datetime.now(timezone.utc).isoformat()
    db_path = tmp_path / "test.db"
    
    # Create a prior run with multiple inputs
    prior_run_id = "prior-run-456"
    insert_run(
        db_path, prior_run_id, "test-workflow", "completed", now,
        inputs={"key1": "old1", "key2": "old2", "key3": "old3"}
    )
    
    # Rerun with partial inputs - should replace entirely
    response = tmp_client.post(
        f"/api/workflows/{prior_run_id}/rerun",
        json={"inputs": {"key1": "new1", "key4": "new4"}},
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify new run has ONLY the provided inputs (not merged)
    new_run = get_run(db_path, data["run_id"])
    new_inputs = new_run["inputs"]
    assert new_inputs == {"key1": "new1", "key4": "new4"}
    assert "key2" not in new_inputs
    assert "key3" not in new_inputs


def test_rerun_endpoint_with_input_override(tmp_client, tmp_path):
    """Test that rerun endpoint accepts input override."""
    now = datetime.now(timezone.utc).isoformat()
    db_path = tmp_path / "test.db"
    
    # Create a prior run
    prior_run_id = "prior-run-789"
    insert_run(
        db_path, prior_run_id, "test-workflow", "completed", now,
        inputs={"key": "old_value"}
    )
    
    # Rerun with overridden inputs
    response = tmp_client.post(
        f"/api/workflows/{prior_run_id}/rerun",
        json={"inputs": {"key": "new_value", "extra": "data"}},
    )
    
    assert response.status_code == 200
    data = response.json()
    
    # Verify new run has overridden inputs
    new_run = get_run(db_path, data["run_id"])
    assert new_run["inputs"] == {"key": "new_value", "extra": "data"}


def test_rerun_endpoint_nonexistent_run(tmp_client):
    """Test that rerun endpoint returns 404 for nonexistent run."""
    response = tmp_client.post(
        "/api/workflows/nonexistent-run-id/rerun",
        json={},
    )
    
    assert response.status_code == 404


def test_rerun_endpoint_creates_subprocess(tmp_client, tmp_path, mock_subprocess):
    """Test that rerun endpoint spawns dag-exec subprocess with --run-id matching pre-inserted row."""
    now = datetime.now(timezone.utc).isoformat()
    db_path = tmp_path / "test.db"

    # Create a prior run
    prior_run_id = "prior-run-subprocess"
    insert_run(
        db_path, prior_run_id, "test-workflow", "completed", now,
        inputs={"key": "value"}
    )

    # Call rerun endpoint
    response = tmp_client.post(
        f"/api/workflows/{prior_run_id}/rerun",
        json={},
    )

    assert response.status_code == 200
    data = response.json()
    new_run_id = data["run_id"]

    # Verify subprocess was spawned with --run-id matching the pre-inserted row
    assert mock_subprocess.called
    call_args = mock_subprocess.call_args[0]
    assert "dag-exec" in call_args[0]
    assert "--run-id" in call_args, "subprocess should receive --run-id flag"
    run_id_index = call_args.index("--run-id")
    subprocess_run_id = call_args[run_id_index + 1]
    assert subprocess_run_id == new_run_id, f"subprocess --run-id should match pre-inserted row"


def test_rerun_maintains_parent_child_chain(tmp_client, tmp_path):
    """Test that rerun can be chained (rerun of a rerun)."""
    now = datetime.now(timezone.utc).isoformat()
    db_path = tmp_path / "test.db"
    
    # Create original run
    original_run_id = "original-run"
    insert_run(
        db_path, original_run_id, "test-workflow", "completed", now,
        inputs={"key": "original"}
    )
    
    # First rerun
    response1 = tmp_client.post(
        f"/api/workflows/{original_run_id}/rerun",
        json={},
    )
    first_rerun_id = response1.json()["run_id"]
    
    # Second rerun (rerun of rerun)
    response2 = tmp_client.post(
        f"/api/workflows/{first_rerun_id}/rerun",
        json={},
    )
    second_rerun_id = response2.json()["run_id"]
    
    # Verify parent chain
    first_rerun = get_run(db_path, first_rerun_id)
    assert first_rerun["parent_run_id"] == original_run_id
    
    second_rerun = get_run(db_path, second_rerun_id)
    assert second_rerun["parent_run_id"] == first_rerun_id
