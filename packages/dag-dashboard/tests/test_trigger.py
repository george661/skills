"""Tests for webhook trigger endpoint."""
import json
from pathlib import Path
from unittest.mock import Mock, patch, AsyncMock
import pytest
from fastapi.testclient import TestClient

from dag_dashboard.database import init_db
from dag_dashboard.server import create_app
from dag_dashboard.queries import get_run


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
def workflows_dir(tmp_path: Path) -> Path:
    """Create a test workflows directory with a sample workflow."""
    workflows = tmp_path / "workflows"
    workflows.mkdir(exist_ok=True)
    
    # Create a sample workflow file
    workflow_file = workflows / "test-workflow.yaml"
    workflow_file.write_text("""
name: test-workflow
inputs:
  issue_key:
    type: string
    required: true
  optional_param:
    type: string
    required: false
    default: "default_value"
nodes:
  - id: test-node
    type: command
    command: echo "test"
""")
    return workflows


@pytest.fixture
def client(tmp_path: Path, test_db: Path, events_dir: Path, workflows_dir: Path) -> TestClient:
    """Create a test client with trigger endpoint enabled."""
    from dag_dashboard.config import Settings

    # Create settings with trigger enabled
    settings = Settings(
        trigger_enabled=True,
        workflows_dir=workflows_dir
    )

    app = create_app(tmp_path, events_dir=events_dir, settings=settings)
    return TestClient(app, raise_server_exceptions=True)


def test_trigger_endpoint_spawns_subprocess_returns_run_id(client: TestClient, test_db: Path):
    """Test POST /api/trigger spawns dag-executor subprocess and returns run_id non-blocking."""
    with patch("dag_dashboard.trigger.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_subprocess:
        # Mock the subprocess to return immediately
        mock_process = AsyncMock()
        mock_process.pid = 12345
        mock_subprocess.return_value = mock_process
        
        response = client.post(
            "/api/trigger",
            json={
                "workflow": "test-workflow",
                "inputs": {"issue_key": "TEST-123"},
                "source": "github-webhook"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "run_id" in data
        assert isinstance(data["run_id"], str)
        
        # Verify subprocess was spawned
        mock_subprocess.assert_called_once()
        
        # Verify run was persisted with trigger_source
        run = get_run(test_db, data["run_id"])
        assert run is not None
        assert run["trigger_source"] == "github-webhook"


def test_trigger_returns_400_for_missing_workflow_file(client: TestClient):
    """Test POST /api/trigger returns 400 when workflow file doesn't exist."""
    response = client.post(
        "/api/trigger",
        json={
            "workflow": "nonexistent-workflow",
            "inputs": {"issue_key": "TEST-123"},
            "source": "test"
        }
    )
    assert response.status_code == 400
    assert "workflow" in response.json()["detail"].lower()


def test_trigger_returns_400_for_invalid_workflow_name_pattern(client: TestClient):
    """Test POST /api/trigger returns 400 for invalid workflow name."""
    response = client.post(
        "/api/trigger",
        json={
            "workflow": "../etc/passwd",
            "inputs": {},
            "source": "test"
        }
    )
    assert response.status_code == 400


def test_trigger_returns_400_for_missing_required_input(client: TestClient):
    """Test POST /api/trigger returns 400 when required input is missing."""
    response = client.post(
        "/api/trigger",
        json={
            "workflow": "test-workflow",
            "inputs": {},  # Missing required 'issue_key'
            "source": "test"
        }
    )
    assert response.status_code == 400
    assert "issue_key" in response.json()["detail"]


def test_trigger_returns_400_for_wrong_input_type(client: TestClient):
    """Test POST /api/trigger returns 400 for wrong input type."""
    response = client.post(
        "/api/trigger",
        json={
            "workflow": "test-workflow",
            "inputs": {"issue_key": 123},  # Should be string
            "source": "test"
        }
    )
    assert response.status_code == 400


def test_trigger_returns_404_when_trigger_disabled(tmp_path: Path, test_db: Path, events_dir: Path, workflows_dir: Path):
    """Test POST /api/trigger returns 404 when trigger endpoint is disabled."""
    from dag_dashboard.config import Settings

    # Create settings with trigger DISABLED
    settings = Settings(trigger_enabled=False)

    app = create_app(tmp_path, events_dir=events_dir, settings=settings)
    client_disabled = TestClient(app, raise_server_exceptions=False)

    response = client_disabled.post(
        "/api/trigger",
        json={
            "workflow": "test-workflow",
            "inputs": {"issue_key": "TEST-123"},
            "source": "test"
        }
    )
    assert response.status_code == 404


def test_trigger_rejects_workflow_path_traversal(client: TestClient):
    """Test POST /api/trigger rejects workflow names with path traversal."""
    response = client.post(
        "/api/trigger",
        json={
            "workflow": "../../../etc/passwd",
            "inputs": {},
            "source": "test"
        }
    )
    assert response.status_code == 400
    assert "path" in response.json()["detail"].lower()


def test_trigger_rejects_workflow_with_slashes(client: TestClient):
    """Test POST /api/trigger rejects workflow names containing slashes."""
    response = client.post(
        "/api/trigger",
        json={
            "workflow": "foo/bar",
            "inputs": {},
            "source": "test"
        }
    )
    assert response.status_code == 400
