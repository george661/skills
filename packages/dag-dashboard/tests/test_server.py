"""Tests for FastAPI server."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from dag_dashboard.server import create_app


def test_app_creates_successfully(tmp_path: Path) -> None:
    """create_app should return a FastAPI application."""
    app = create_app(db_dir=tmp_path)
    assert app is not None
    assert hasattr(app, "title")


def test_health_endpoint_returns_200(tmp_path: Path) -> None:
    """GET /health should return 200 OK."""
    app = create_app(db_dir=tmp_path)
    client = TestClient(app)
    
    response = client.get("/health")
    
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_initializes_database_on_startup(tmp_path: Path) -> None:
    """App lifespan should initialize database."""
    db_dir = tmp_path / "dashboard-data"
    app = create_app(db_dir=db_dir)
    
    with TestClient(app):
        # Lifespan context manager initializes DB
        db_file = db_dir / "dashboard.db"
        assert db_file.exists()
