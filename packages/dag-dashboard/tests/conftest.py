"""Shared pytest fixtures for dag-dashboard tests."""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from dag_dashboard.database import init_db
from dag_dashboard.server import create_app
from dag_dashboard.config import Settings


@pytest.fixture
def client(tmp_path: Path):
    """Create test client with initialized database and builder enabled."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    events_dir = tmp_path / "dag-events"
    events_dir.mkdir(exist_ok=True)
    
    workflows_dir = tmp_path / "workflows"
    workflows_dir.mkdir(exist_ok=True)
    
    # Create settings with builder enabled for validation routes
    settings = Settings(
        events_dir=events_dir,
        workflows_dir=str(workflows_dir),
        builder_enabled=True
    )
    
    app = create_app(db_path=db_path, settings=settings)
    with TestClient(app) as client:
        yield client
