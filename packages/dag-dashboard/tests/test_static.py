"""Test static file serving."""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create test client with temporary database."""
    app = create_app(tmp_path)
    return TestClient(app)


def test_index_html_served(client: TestClient) -> None:
    """Test that index.html is served at root path."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert b"<!DOCTYPE html>" in response.content or b"<html" in response.content


def test_css_file_served(client: TestClient) -> None:
    """Test that CSS files are served correctly."""
    response = client.get("/css/styles.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]


def test_js_file_served(client: TestClient) -> None:
    """Test that JavaScript files are served correctly."""
    response = client.get("/js/app.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_missing_static_file_404(client: TestClient) -> None:
    """Test that missing static files return 404."""
    response = client.get("/nonexistent.html")
    assert response.status_code == 404


def test_app_js_renders_trigger_source_field() -> None:
    """Test that app.js includes trigger_source field rendering."""
    from pathlib import Path

    app_js_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "app.js"
    content = app_js_path.read_text()

    # Check that trigger_source is referenced
    assert "trigger_source" in content
    assert "trigger-source-badge" in content


def test_trigger_source_column_responsive() -> None:
    """Test that CSS has mobile breakpoint for Source column."""
    from pathlib import Path

    css_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "css" / "styles.css"
    content = css_path.read_text()

    # Check for trigger-source-badge styles
    assert "trigger-source-badge" in content

    # Check for mobile breakpoint hiding Source column
    assert "max-width: 767px" in content or "max-width:767px" in content
    assert "nth-child(5)" in content  # Source is 5th column


def test_node_detail_panel_renders_upstream_context_block() -> None:
    """Test that node-detail-panel.js renders upstream context."""
    from pathlib import Path

    js_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "node-detail-panel.js"
    content = js_path.read_text()

    # Check that upstream_context is referenced
    assert "gate-upstream-context" in content
    assert "node.upstream_context" in content or "upstream_context" in content


def test_node_detail_panel_renders_gate_description() -> None:
    """Test that node-detail-panel.js renders gate description."""
    from pathlib import Path

    js_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "node-detail-panel.js"
    content = js_path.read_text()

    # Check that gate description is referenced
    assert "gate-description" in content
    assert "node.inputs" in content or "inputs.description" in content or "inputs?.description" in content


def test_gate_indicator_meets_44px_touch_target() -> None:
    """Test that .gate-indicator CSS meets 44px touch target requirement."""
    from pathlib import Path

    css_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "css" / "styles.css"
    content = css_path.read_text()

    # Check for .gate-indicator block
    assert ".gate-indicator" in content

    # Check for 44px touch target (both min-width and min-height)
    # The requirement is that the touch target is at least 44px
    assert "min-width: 44px" in content or "min-width:44px" in content
    assert "min-height: 44px" in content or "min-height:44px" in content
