"""Test that step logs static assets are served correctly."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from dag_dashboard.database import init_db
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path):
    """Create a test client with initialized database."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    events_dir = tmp_path / "dag-events"
    events_dir.mkdir(exist_ok=True)
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    app = create_app(db_path=db_path, events_dir=events_dir, checkpoint_dir_fallback=str(checkpoint_dir))
    return TestClient(app, raise_server_exceptions=True)


def test_step_logs_js_served(client: TestClient):
    """Test that step-logs.js is served."""
    response = client.get("/js/step-logs.js")
    assert response.status_code == 200
    assert "class StepLogs" in response.text
    assert "_loadHistoricalLogs" in response.text
    assert "_subscribeSSE" in response.text


def test_index_includes_step_logs_script(client: TestClient):
    """Test that index.html includes step-logs.js script."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    
    # Check script is present
    assert "/js/step-logs.js" in html
    
    # Verify order: step-logs.js before node-detail-panel.js
    step_logs_pos = html.find("/js/step-logs.js")
    node_detail_pos = html.find("/js/node-detail-panel.js")
    
    assert step_logs_pos > 0, "step-logs.js script tag not found"
    assert node_detail_pos > 0, "node-detail-panel.js script tag not found"
    assert step_logs_pos < node_detail_pos, \
        "step-logs.js must be loaded before node-detail-panel.js"


def test_step_logs_css_exists(client: TestClient):
    """Test that step-logs CSS styles are in styles.css."""
    response = client.get("/css/styles.css")
    assert response.status_code == 200
    css = response.text
    
    # Check for step-logs specific classes
    assert ".step-logs" in css
    assert ".step-logs-toolbar" in css
    assert ".log-line" in css
    assert ".log-line-stdout" in css
    assert ".log-line-stderr" in css


def test_step_logs_has_stream_filter(client: TestClient):
    """Test that step-logs.js includes stream filtering."""
    response = client.get("/js/step-logs.js")
    assert response.status_code == 200
    assert "_setStreamFilter" in response.text
    assert "streamFilter" in response.text


def test_step_logs_has_auto_scroll(client: TestClient):
    """Test that step-logs.js includes auto-scroll functionality."""
    response = client.get("/js/step-logs.js")
    assert response.status_code == 200
    assert "autoScroll" in response.text
    assert "_onScroll" in response.text
    assert "_resumeFollow" in response.text
