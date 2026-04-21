"""Test cancel-button.js static file."""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create test client with temporary database."""
    app = create_app(tmp_path)
    return TestClient(app)


def test_cancel_button_served(client: TestClient) -> None:
    """Test that cancel-button.js is served correctly."""
    response = client.get("/js/cancel-button.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_cancel_button_api_path() -> None:
    """Test that cancel-button.js contains correct API path."""
    cancel_button_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "cancel-button.js"
    content = cancel_button_path.read_text()
    
    assert "/api/workflows/" in content
    assert "/cancel" in content
    assert "POST" in content or "post" in content


def test_cancel_button_hidden_when_terminal() -> None:
    """Test that cancel-button.js includes logic to hide when run is terminal."""
    cancel_button_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "cancel-button.js"
    content = cancel_button_path.read_text()
    
    assert "running" in content


def test_cancel_button_uses_confirm_dialog() -> None:
    """Test that cancel-button.js invokes the confirm dialog."""
    cancel_button_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "cancel-button.js"
    content = cancel_button_path.read_text()
    
    assert "showConfirmDialog" in content
