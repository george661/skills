"""Test replay-form.js uses confirm dialog."""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create test client with temporary database."""
    app = create_app(tmp_path)
    return TestClient(app)


def test_replay_form_uses_confirm_dialog() -> None:
    """Test that replay-form.js invokes the confirm dialog before submission."""
    replay_form_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "replay-form.js"
    content = replay_form_path.read_text()
    
    assert "showConfirmDialog" in content, "replay-form.js must call showConfirmDialog"


def test_replay_form_confirm_tone_is_primary() -> None:
    """Test that replay-form.js uses 'primary' confirmTone (not 'danger')."""
    replay_form_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "replay-form.js"
    content = replay_form_path.read_text()
    
    # Verify confirmTone is 'primary' (matches retry, not cancel)
    assert "confirmTone: 'primary'" in content or 'confirmTone: "primary"' in content, \
        "replay-form.js must use confirmTone: 'primary'"
