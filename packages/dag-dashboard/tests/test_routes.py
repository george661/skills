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
    # Create app with the same tmp_path where dashboard.db exists
    app = create_app(tmp_path)
    # Use TestClient with raise_server_exceptions=True for better error messages
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
    # Insert test data
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
    # DESC order - most recent first
    assert data["items"][0]["id"] == "run-1"
    assert data["items"][1]["id"] == "run-3"
    assert data["items"][2]["id"] == "run-2"


def test_get_workflows_invalid_sort_by(client: TestClient):
    """Test GET /api/workflows?sortBy=malicious returns 400."""
    response = client.get("/api/workflows?sort_by=malicious")
    assert response.status_code == 422  # FastAPI validation error


def test_get_workflows_invalid_status(client: TestClient):
    """Test GET /api/workflows with invalid status returns 400."""
    response = client.get("/api/workflows?status=invalid")
    assert response.status_code == 422  # FastAPI validation error


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
