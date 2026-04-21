"""Test that node detail chat static assets are served correctly."""
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


def test_node_detail_panel_has_chat_tab(client: TestClient):
    """Test that node-detail-panel.js contains Chat tab marker."""
    response = client.get("/js/node-detail-panel.js")
    assert response.status_code == 200
    assert 'data-tab="chat"' in response.text


def test_node_detail_panel_has_renderchat_method(client: TestClient):
    """Test that node-detail-panel.js contains renderChat method."""
    response = client.get("/js/node-detail-panel.js")
    assert response.status_code == 200
    assert "renderChat(" in response.text


def test_node_detail_panel_has_send_handler(client: TestClient):
    """Test that node-detail-panel.js contains handleSendNodeMessage handler."""
    response = client.get("/js/node-detail-panel.js")
    assert response.status_code == 200
    assert "handleSendNodeMessage" in response.text


def test_node_detail_panel_gates_input_on_running(client: TestClient):
    """Test that node-detail-panel.js gates input based on node.status === 'running'."""
    response = client.get("/js/node-detail-panel.js")
    assert response.status_code == 200
    # Check for the status gate in the renderChat logic
    assert "node.status === 'running'" in response.text or "node.status===\"running\"" in response.text


def test_node_detail_panel_shows_model_in_chat_header(client: TestClient):
    """Test that node-detail-panel.js shows model name in chat header."""
    response = client.get("/js/node-detail-panel.js")
    assert response.status_code == 200
    # Check for model header element (class or id)
    assert "node-chat-model" in response.text or "node.model" in response.text


def test_node_detail_panel_dedupes_chat_messages(client: TestClient):
    """Test that node-detail-panel.js dedupes chat messages via this.chatMessages.has check."""
    response = client.get("/js/node-detail-panel.js")
    assert response.status_code == 200
    assert "this.chatMessages.has" in response.text
