"""Test confirm-dialog.js static file."""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create test client with temporary database."""
    app = create_app(tmp_path)
    return TestClient(app)


def test_confirm_dialog_served(client: TestClient) -> None:
    """Test that confirm-dialog.js is served correctly."""
    response = client.get("/js/confirm-dialog.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_confirm_dialog_exports_global() -> None:
    """Test that confirm-dialog.js exports window.showConfirmDialog as a Promise."""
    confirm_dialog_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "confirm-dialog.js"
    content = confirm_dialog_path.read_text()
    
    assert "window.showConfirmDialog" in content
    assert "Promise" in content or "resolve" in content


def test_confirm_dialog_escape_handler() -> None:
    """Test that confirm-dialog.js includes Escape key handler."""
    confirm_dialog_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "confirm-dialog.js"
    content = confirm_dialog_path.read_text()
    
    assert "Escape" in content or "key === 'Escape'" in content


def test_confirm_dialog_focus_trap() -> None:
    """Test that confirm-dialog.js includes focus trap logic."""
    confirm_dialog_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "confirm-dialog.js"
    content = confirm_dialog_path.read_text()
    
    assert "focus()" in content
    # Check for Tab key handling or keydown listener
    assert ("Tab" in content or "keydown" in content)


def test_confirm_dialog_explicit_confirm() -> None:
    """Test that confirm-dialog.js requires explicit button click (no auto-confirm)."""
    confirm_dialog_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "confirm-dialog.js"
    content = confirm_dialog_path.read_text()

    # The dialog should resolve false on overlay click (explicit)
    # Should not auto-confirm on Enter without button click
    # Check for closeDialog(false) pattern which calls resolve internally
    assert "closeDialog(false)" in content
