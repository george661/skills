"""Integration tests for webhook trigger endpoint."""
from pathlib import Path
from unittest.mock import patch, AsyncMock
import pytest
from fastapi.testclient import TestClient

from dag_dashboard.database import init_db
from dag_dashboard.server import create_app
from dag_dashboard.queries import get_run, list_runs


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
    
    # Create a work.yaml workflow with issue_key input
    workflow_file = workflows / "work.yaml"
    workflow_file.write_text("""
name: work
inputs:
  issue_key:
    type: string
    required: true
nodes:
  - id: test-node
    type: command
    command: echo "Processing {issue_key}"
""")
    return workflows


@pytest.fixture
def client(tmp_path: Path, test_db: Path, events_dir: Path, workflows_dir: Path) -> TestClient:
    """Create a test client with trigger endpoint enabled."""
    from dag_dashboard.config import Settings

    settings = Settings(
        trigger_enabled=True,
        workflows_dir=workflows_dir
    )

    app = create_app(tmp_path, events_dir=events_dir, settings=settings)
    return TestClient(app, raise_server_exceptions=True)


def test_github_webhook_payload_triggers_work_workflow(client: TestClient, test_db: Path):
    """Test GitHub webhook payload can trigger /work workflow."""
    with patch("dag_dashboard.trigger.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_subprocess:
        mock_process = AsyncMock()
        mock_process.pid = 12345
        mock_subprocess.return_value = mock_process

        # Simulate GitHub webhook payload structure
        github_payload = {
            "workflow": "work",
            "inputs": {"issue_key": "GW-5139"},
            "source": "github-webhook"
        }

        response = client.post("/api/trigger", json=github_payload)

        assert response.status_code == 200
        run_id = response.json()["run_id"]

        # Verify run was created with github-webhook source
        run = get_run(test_db, run_id)
        assert run is not None
        assert run["trigger_source"] == "github-webhook"
        assert run["workflow_name"] == "work"


def test_triggered_run_appears_in_workflows_list_with_source(client: TestClient, test_db: Path):
    """Test triggered runs appear in GET /api/workflows with trigger_source field."""
    with patch("dag_dashboard.trigger.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_subprocess:
        mock_process = AsyncMock()
        mock_subprocess.return_value = mock_process

        # Trigger a workflow
        response = client.post(
            "/api/trigger",
            json={
                "workflow": "work",
                "inputs": {"issue_key": "TEST-456"},
                "source": "jira-webhook"
            }
        )
        assert response.status_code == 200

        # Get workflows list
        list_response = client.get("/api/workflows")
        assert list_response.status_code == 200
        data = list_response.json()

        # Verify trigger_source is in response
        assert len(data["items"]) == 1
        assert data["items"][0]["trigger_source"] == "jira-webhook"
