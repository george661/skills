"""Test rerun-form.js uses confirm dialog."""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create test client with temporary database."""
    app = create_app(tmp_path)
    return TestClient(app)


def test_rerun_form_uses_confirm_dialog() -> None:
    """Test that rerun-form.js invokes the confirm dialog before submission."""
    rerun_form_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "rerun-form.js"
    content = rerun_form_path.read_text()
    
    assert "showConfirmDialog" in content, "rerun-form.js must call showConfirmDialog"


def test_rerun_form_confirm_tone_is_primary() -> None:
    """Test that rerun-form.js uses 'primary' confirmTone (not 'danger')."""
    rerun_form_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "rerun-form.js"
    content = rerun_form_path.read_text()
    
    # Verify confirmTone is 'primary' (matches retry, not cancel)
    assert "confirmTone: 'primary'" in content or 'confirmTone: "primary"' in content, \
        "rerun-form.js must use confirmTone: 'primary'"
