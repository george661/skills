"""Tests for rerun static assets."""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from dag_dashboard.database import init_db
from dag_dashboard.server import create_app


@pytest.fixture
def tmp_client(tmp_path: Path):
    """Create test client with initialized database."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    events_dir = tmp_path / "dag-events"
    events_dir.mkdir(exist_ok=True)
    
    app = create_app(db_path=db_path, events_dir=events_dir)
    with TestClient(app) as client:
        yield client


def test_rerun_form_script_tag_exists(tmp_client):
    """Test that index.html includes rerun-form.js script tag."""
    response = tmp_client.get("/")
    assert response.status_code == 200
    html = response.text
    # Served HTML appends a ?v=<timestamp> cache-buster to script URLs, so
    # check for the path rather than the exact string.
    assert '/js/rerun-form.js' in html


def test_rerun_form_js_exists(tmp_client):
    """Test that rerun-form.js file is served."""
    response = tmp_client.get("/js/rerun-form.js")
    assert response.status_code == 200
    content_type = response.headers["content-type"]
    # Accept both application/javascript and text/javascript
    assert "javascript" in content_type
