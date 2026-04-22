"""Tests for workflow trigger form and model override banner static assets."""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from dag_dashboard.database import init_db
from dag_dashboard.server import create_app


@pytest.fixture
def tmp_client(tmp_path: Path):
    """Create test client with initialized database."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    events_dir = tmp_path / "dag-events"
    events_dir.mkdir(exist_ok=True)
    
    app = create_app(db_path=db_path, events_dir=events_dir)
    with TestClient(app) as client:
        yield client


def test_workflows_js_contains_render_workflow_trigger_form(tmp_client):
    """Test that workflows.js exports renderWorkflowTriggerForm function."""
    response = tmp_client.get("/js/workflows.js")
    assert response.status_code == 200
    js_content = response.text
    assert "window.renderWorkflowTriggerForm" in js_content
    assert "async function renderWorkflowTriggerForm" in js_content


def test_workflows_js_contains_model_override_select(tmp_client):
    """Test that renderWorkflowTriggerForm creates a model_override select element."""
    response = tmp_client.get("/js/workflows.js")
    assert response.status_code == 200
    js_content = response.text
    # Verify form contains model_override select field
    assert '<select name="model_override">' in js_content or 'name="model_override"' in js_content


def test_app_js_contains_workflow_trigger_route(tmp_client):
    """Test that app.js registers /workflow-trigger/:name route."""
    response = tmp_client.get("/js/app.js")
    assert response.status_code == 200
    js_content = response.text
    # Check for route registration
    assert "router.register('/workflow-trigger/:name'" in js_content or \
           'router.register("/workflow-trigger/:name"' in js_content


def test_app_js_contains_workflow_trigger_hash_handler(tmp_client):
    """Test that app.js handles hash starting with /workflow-trigger/."""
    response = tmp_client.get("/js/app.js")
    assert response.status_code == 200
    js_content = response.text
    # Check for hash handler
    assert "hash.startsWith('/workflow-trigger/')" in js_content or \
           'hash.startsWith("/workflow-trigger/")' in js_content


def test_app_js_contains_model_override_banner_logic(tmp_client):
    """Test that renderWorkflowDetail checks for __model_override__ and creates banner."""
    response = tmp_client.get("/js/app.js")
    assert response.status_code == 200
    js_content = response.text
    # Check for model override logic
    assert "__model_override__" in js_content
    assert "model-override-banner" in js_content


def test_styles_css_contains_model_override_banner_class(tmp_client):
    """Test that styles.css contains .model-override-banner class."""
    response = tmp_client.get("/css/styles.css")
    assert response.status_code == 200
    css_content = response.text
    assert ".model-override-banner" in css_content
