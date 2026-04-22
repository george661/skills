"""Tests for search endpoint."""
import pytest
from fastapi.testclient import TestClient
import sqlite3
from pathlib import Path


@pytest.fixture
def app_with_search_disabled(tmp_path):
    """FastAPI app with search_token unset (503 expected)."""
    from dag_dashboard.server import create_app
    from dag_dashboard.config import Settings
    
    settings = Settings(
        db_dir=tmp_path,
        search_token=None  # Explicitly unset
    )
    app = create_app(db_dir=tmp_path, settings=settings)
    return app


@pytest.fixture
def app_with_search(tmp_path):
    """FastAPI app with search enabled."""
    from dag_dashboard.server import create_app
    from dag_dashboard.config import Settings
    from dag_dashboard.database import init_db

    # Create a test database
    db_path = tmp_path / "dashboard.db"
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))

    # Seed test data
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
        ("run_test123", "deploy", "completed", "2026-04-22T10:00:00Z")
    )
    conn.commit()
    conn.close()

    settings = Settings(
        db_dir=tmp_path,
        search_token="test_secret_token_123"
    )
    app = create_app(db_dir=tmp_path, settings=settings)
    return app


def test_search_requires_configured_token(app_with_search_disabled):
    """Test 2: 503 when search_token unset."""
    client = TestClient(app_with_search_disabled)
    response = client.get("/api/search?q=test")
    assert response.status_code == 503
    assert "not configured" in response.json()["detail"].lower()


def test_search_rejects_missing_bearer(app_with_search):
    """Test 3: 401 when Authorization header missing."""
    client = TestClient(app_with_search)
    response = client.get("/api/search?q=test")
    assert response.status_code == 401
    assert "authorization" in response.json()["detail"].lower()


def test_search_rejects_wrong_bearer(app_with_search):
    """Test 4: 401 on wrong token."""
    client = TestClient(app_with_search)
    response = client.get(
        "/api/search?q=test",
        headers={"Authorization": "Bearer wrong_token"}
    )
    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower() or "unauthorized" in response.json()["detail"].lower()


def test_search_run_id_prefix_match(app_with_search):
    """Test 5: Search by run ID substring matches."""
    client = TestClient(app_with_search)
    response = client.get(
        "/api/search?q=test123",
        headers={"Authorization": "Bearer test_secret_token_123"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any(r["run_id"] == "run_test123" for r in data["results"])


def test_search_error_text_match(tmp_path):
    """Test 6: Search for text in error column."""
    from dag_dashboard.server import create_app
    from dag_dashboard.config import Settings
    from dag_dashboard.database import init_db

    # Create database with an error
    db_path = tmp_path / "dashboard.db"
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))

    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at, error) VALUES (?, ?, ?, ?, ?)",
        ("run_error001", "test", "failed", "2026-04-22T10:00:00Z", "ConnectionError: timeout connecting to API")
    )
    conn.commit()
    conn.close()
    
    settings = Settings(db_dir=tmp_path, search_token="test_token")
    app = create_app(db_dir=tmp_path, settings=settings)
    client = TestClient(app)
    
    response = client.get(
        "/api/search?q=Connection",
        headers={"Authorization": "Bearer test_token"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    run_results = [r for r in data["results"] if r["kind"] == "run"]
    assert len(run_results) == 1
    assert run_results[0]["run_id"] == "run_error001"


def test_search_json_input_match(tmp_path):
    """Test 7: Search for text in inputs JSON."""
    from dag_dashboard.server import create_app
    from dag_dashboard.config import Settings
    from dag_dashboard.database import init_db

    # Create database with JSON inputs
    db_path = tmp_path / "dashboard.db"
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))

    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at, inputs) VALUES (?, ?, ?, ?, ?)",
        ("run_json001", "deploy", "completed", "2026-04-22T10:00:00Z", '{"ticket": "ACME-999"}')
    )
    conn.commit()
    conn.close()
    
    settings = Settings(db_dir=tmp_path, search_token="test_token")
    app = create_app(db_dir=tmp_path, settings=settings)
    client = TestClient(app)
    
    response = client.get(
        "/api/search?q=ACME",
        headers={"Authorization": "Bearer test_token"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 1
    assert any(r["run_id"] == "run_json001" and r["kind"] == "run" for r in data["results"])


def test_search_kinds_filter(app_with_search):
    """Test 8: kinds filter returns only specified kinds."""
    client = TestClient(app_with_search)
    response = client.get(
        "/api/search?q=test&kinds=runs",
        headers={"Authorization": "Bearer test_secret_token_123"}
    )
    assert response.status_code == 200
    data = response.json()
    # All results should be kind=run
    assert all(r["kind"] == "run" for r in data["results"])


def test_search_limit_cap(tmp_path):
    """Test 9: Seed 200 matches, expect cap at 50."""
    from dag_dashboard.server import create_app
    from dag_dashboard.config import Settings
    from dag_dashboard.database import init_db

    db_path = tmp_path / "dashboard.db"
    init_db(db_path)
    conn = sqlite3.connect(str(db_path))

    # Insert 200 runs with "test" in workflow_name
    for i in range(200):
        conn.execute(
            "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
            (f"run_{i:04d}", "test_workflow", "completed", "2026-04-22T10:00:00Z")
        )
    conn.commit()
    conn.close()
    
    settings = Settings(db_dir=tmp_path, search_token="test_token")
    app = create_app(db_dir=tmp_path, settings=settings)
    client = TestClient(app)
    
    response = client.get(
        "/api/search?q=test",
        headers={"Authorization": "Bearer test_token"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) == 50  # Hard cap


def test_search_custom_limit(app_with_search):
    """Test 10: limit=10 returns at most 10."""
    client = TestClient(app_with_search)
    response = client.get(
        "/api/search?q=test&limit=10",
        headers={"Authorization": "Bearer test_secret_token_123"}
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["results"]) <= 10


def test_search_rate_limit_429(app_with_search):
    """Test 11: 31st request within 60s from same bearer returns 429."""
    client = TestClient(app_with_search)
    
    # Make 30 requests (should all succeed)
    for i in range(30):
        response = client.get(
            "/api/search?q=test",
            headers={"Authorization": "Bearer test_secret_token_123"}
        )
        assert response.status_code == 200, f"Request {i+1} failed unexpectedly"
    
    # 31st request should return 429
    response = client.get(
        "/api/search?q=test",
        headers={"Authorization": "Bearer test_secret_token_123"}
    )
    assert response.status_code == 429
    assert "rate limit" in response.json()["detail"].lower()
