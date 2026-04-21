"""Test that chat panel static assets are served correctly."""
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


def test_chat_panel_js_served(client: TestClient):
    """Test that chat-panel.js is served."""
    response = client.get("/js/chat-panel.js")
    assert response.status_code == 200
    assert "class ChatPanel" in response.text
    assert "handleSSEMessage" in response.text


def test_marked_vendor_js_served(client: TestClient):
    """Test that marked.min.js vendor library is served."""
    response = client.get("/js/vendor/marked.min.js")
    assert response.status_code == 200
    # marked lib should have its signature
    assert "marked" in response.text.lower() or "markdown" in response.text.lower()


def test_index_includes_chat_scripts(client: TestClient):
    """Test that index.html includes chat scripts in correct order."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    
    # Check both scripts are present
    assert "/js/vendor/marked.min.js" in html
    assert "/js/chat-panel.js" in html
    
    # Verify order: marked before chat-panel, chat-panel before app.js
    marked_pos = html.find("/js/vendor/marked.min.js")
    chat_panel_pos = html.find("/js/chat-panel.js")
    app_js_pos = html.find("/js/app.js")
    
    assert marked_pos < chat_panel_pos < app_js_pos, \
        "Scripts must be in order: marked.min.js, chat-panel.js, app.js"
