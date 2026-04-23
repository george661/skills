"""Tests for /api/config endpoint exposing UI-relevant settings."""

import pytest
from pathlib import Path
from fastapi.testclient import TestClient

from dag_dashboard.config import Settings
from dag_dashboard.database import init_db
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path):
    """Create test client with default settings."""
    db_dir = tmp_path
    init_db(db_dir / "dashboard.db")
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    app = create_app(db_dir, events_dir=events_dir)
    # Use context manager to trigger lifespan events
    with TestClient(app) as test_client:
        yield test_client


def test_config_endpoint_returns_allow_destructive_false_by_default(client):
    """GET /api/config should return allow_destructive_nodes=false by default."""
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert "allow_destructive_nodes" in data
    assert data["allow_destructive_nodes"] is False


def test_config_endpoint_returns_allow_destructive_true_when_set(tmp_path):
    """GET /api/config should return true when env flag is set."""
    db_dir = tmp_path
    init_db(db_dir / "dashboard.db")
    events_dir = tmp_path / "events"
    events_dir.mkdir()

    # Create settings with allow_destructive_nodes enabled
    settings = Settings(allow_destructive_nodes=True)
    app = create_app(db_dir, events_dir=events_dir, settings=settings)

    with TestClient(app) as client:
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert data["allow_destructive_nodes"] is True


def test_config_endpoint_when_settings_missing(tmp_path):
    """GET /api/config should return default false when settings missing (defensive)."""
    db_dir = tmp_path
    init_db(db_dir / "dashboard.db")
    events_dir = tmp_path / "events"
    events_dir.mkdir()

    # Create app without explicit settings (uses defaults)
    app = create_app(db_dir, events_dir=events_dir)

    with TestClient(app) as client:
        response = client.get("/api/config")
        assert response.status_code == 200
        data = response.json()
        assert data["allow_destructive_nodes"] is False


def test_config_reflects_db_override_after_put(tmp_path):
    """Test that after PUT flips allow_destructive_nodes, GET /api/config reflects the new value."""
    from dag_dashboard.settings_store import put_setting

    db_dir = tmp_path
    db_path = db_dir / "dashboard.db"
    init_db(db_path)
    events_dir = tmp_path / "events"
    events_dir.mkdir()

    # Start with default (False)
    settings = Settings()
    app = create_app(db_dir, events_dir=events_dir, settings=settings)

    with TestClient(app) as client:
        # Verify initial state
        response = client.get("/api/config")
        assert response.status_code == 200
        assert response.json()["allow_destructive_nodes"] is False

        # PUT to flip it to True
        response = client.put("/api/settings", json={"updates": {"allow_destructive_nodes": True}})
        assert response.status_code == 200

        # Verify GET /api/config now returns True (settings reloaded from db)
        response = client.get("/api/config")
        assert response.status_code == 200
        assert response.json()["allow_destructive_nodes"] is True
