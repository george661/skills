"""Tests for REST API routes."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dag_dashboard.database import init_db
from dag_dashboard.queries import insert_run, insert_node
from dag_dashboard.server import create_app


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    """Create a test database at the expected location."""
    db_path = tmp_path / "dashboard.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def client(tmp_path: Path, test_db: Path) -> TestClient:
    """Create a test client with initialized database."""
    app = create_app(tmp_path)
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
                "2026-04-17T12:01:00Z", model="gpt-4", tokens_input=100, tokens_output=50, tokens_cache=25, cost=0.05)
    insert_node(test_db, "node-2", "run-totals", "step-2", "failed", "2026-04-17T12:01:00Z",
                "2026-04-17T12:02:00Z", model="gpt-4", tokens_input=200, tokens_output=75, tokens_cache=30, cost=0.08)

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
                "2026-04-17T12:00:00Z", "2026-04-17T12:01:00Z",
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
                "2026-04-17T12:00:00Z", "2026-04-17T12:01:00Z")
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
