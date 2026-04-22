"""Test retry-button.js static file."""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create test client with temporary database."""
    app = create_app(tmp_path)
    return TestClient(app)


def test_retry_button_served(client: TestClient) -> None:
    """Test that retry-button.js is served correctly."""
    response = client.get("/js/retry-button.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_retry_button_api_path_and_tone() -> None:
    """Test that retry-button.js contains correct API path and confirmTone."""
    retry_button_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "retry-button.js"
    content = retry_button_path.read_text()
    
    assert "/api/workflows/" in content
    assert "/retry" in content
    assert "POST" in content or "post" in content
    # Verify confirmTone is 'primary' (not 'danger' like cancel)
    assert "confirmTone: 'primary'" in content or 'confirmTone: "primary"' in content


def test_retry_button_shown_when_failed() -> None:
    """Test that retry-button.js includes logic to show when run is failed."""
    retry_button_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "retry-button.js"
    content = retry_button_path.read_text()
    
    assert "failed" in content


def test_retry_button_uses_confirm_dialog() -> None:
    """Test that retry-button.js invokes the confirm dialog."""
    retry_button_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "retry-button.js"
    content = retry_button_path.read_text()
    
    assert "showConfirmDialog" in content
