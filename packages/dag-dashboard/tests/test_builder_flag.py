"""Tests for builder feature flag configuration and endpoints."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dag_dashboard.database import init_db
from dag_dashboard.server import create_app
from dag_dashboard.config import Settings


@pytest.fixture
def client_with_flag_off(tmp_path: Path):
    """Client with builder_enabled=False (default)."""
    db_dir = tmp_path
    init_db(db_dir / "dashboard.db")
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    # Default settings (builder_enabled=False)
    app = create_app(db_dir, events_dir=events_dir, checkpoint_dir_fallback=str(checkpoint_dir))
    return TestClient(app)


@pytest.fixture
def client_with_flag_on(tmp_path: Path, monkeypatch):
    """Client with builder_enabled=True."""
    # Override settings BEFORE creating settings/app
    monkeypatch.setenv("DAG_DASHBOARD_BUILDER_ENABLED", "true")

    db_dir = tmp_path
    init_db(db_dir / "dashboard.db")
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)

    # Create settings with the env var set
    settings = Settings()
    app = create_app(db_dir, events_dir=events_dir, checkpoint_dir_fallback=str(checkpoint_dir), settings=settings)
    return TestClient(app)


def test_config_endpoint_default_false(client_with_flag_off) -> None:
    """GET /api/config should return builder_enabled: false by default."""
    response = client_with_flag_off.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert data == {"builder_enabled": False}


def test_config_endpoint_respects_env(client_with_flag_on) -> None:
    """GET /api/config should respect DAG_DASHBOARD_BUILDER_ENABLED env var."""
    response = client_with_flag_on.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert data == {"builder_enabled": True}


def test_builder_config_js_reflects_flag_off(client_with_flag_off) -> None:
    """GET /builder-config.js should return false when flag is off."""
    response = client_with_flag_off.get("/builder-config.js")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/javascript"
    assert "window.DAG_DASHBOARD_BUILDER_ENABLED = false;" in response.text


def test_builder_config_js_reflects_flag_on(client_with_flag_on) -> None:
    """GET /builder-config.js should return true when flag is on."""
    response = client_with_flag_on.get("/builder-config.js")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/javascript"
    assert "window.DAG_DASHBOARD_BUILDER_ENABLED = true;" in response.text
