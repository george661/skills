"""Test checkpoint browser static files are served correctly."""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create test client with temporary database."""
    app = create_app(tmp_path)
    return TestClient(app)


def test_checkpoint_browser_js_served(client: TestClient) -> None:
    """Test checkpoint-browser.js is served by static mount."""
    response = client.get("/js/checkpoint-browser.js")
    assert response.status_code == 200
    assert "renderCheckpointWorkflows" in response.text
    assert "renderCheckpointRuns" in response.text
    assert "renderCheckpointRunDetail" in response.text
    assert "renderCheckpointCompare" in response.text


def test_replay_form_js_served(client: TestClient) -> None:
    """Test replay-form.js is served by static mount."""
    response = client.get("/js/replay-form.js")
    assert response.status_code == 200
    assert "showReplayModal" in response.text
    assert "closeReplayModal" in response.text


def test_index_includes_checkpoint_scripts(client: TestClient) -> None:
    """Test index.html includes checkpoint scripts."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "/js/checkpoint-browser.js" in html
    assert "/js/replay-form.js" in html
    # Ensure they come before app.js
    checkpoint_idx = html.find("/js/checkpoint-browser.js")
    replay_idx = html.find("/js/replay-form.js")
    app_idx = html.find("/js/app.js")
    assert checkpoint_idx < app_idx
    assert replay_idx < app_idx


def test_index_includes_checkpoint_nav(client: TestClient) -> None:
    """Test index.html includes Checkpoints navigation entry."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    assert "Checkpoints" in html
    assert "#/checkpoints" in html
    assert "💾" in html  # checkpoint icon
