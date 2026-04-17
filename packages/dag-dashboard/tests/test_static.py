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
