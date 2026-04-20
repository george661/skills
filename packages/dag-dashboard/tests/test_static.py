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
