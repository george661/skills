"""Test confirm-dialog.js load order - must load before dependent forms."""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create test client with temporary database."""
    app = create_app(tmp_path)
    return TestClient(app)


def test_confirm_dialog_loaded_before_forms(client: TestClient) -> None:
    """Test that confirm-dialog.js loads before rerun-form.js and replay-form.js."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text
    
    # Find positions of script tags
    confirm_dialog_pos = html.find('<script src="/js/confirm-dialog.js"></script>')
    rerun_form_pos = html.find('<script src="/js/rerun-form.js"></script>')
    replay_form_pos = html.find('<script src="/js/replay-form.js"></script>')
    
    # All script tags must exist
    assert confirm_dialog_pos != -1, "confirm-dialog.js script tag not found"
    assert rerun_form_pos != -1, "rerun-form.js script tag not found"
    assert replay_form_pos != -1, "replay-form.js script tag not found"
    
    # confirm-dialog.js must load BEFORE the forms that depend on it
    assert confirm_dialog_pos < rerun_form_pos, \
        "confirm-dialog.js must load before rerun-form.js"
    assert confirm_dialog_pos < replay_form_pos, \
        "confirm-dialog.js must load before replay-form.js"
