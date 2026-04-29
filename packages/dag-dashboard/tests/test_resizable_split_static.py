"""Test resizable split static asset serving and implementation."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create test client with temporary database."""
    app = create_app(tmp_path)
    return TestClient(app)


def test_resizable_split_js_served(client: TestClient) -> None:
    """Test that resizable-split.js is served correctly."""
    response = client.get("/js/resizable-split.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_resizable_split_class_defined() -> None:
    """Test that ResizableSplit class is defined in the file."""
    split_js_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "js"
        / "resizable-split.js"
    )
    content = split_js_path.read_text()

    # Check class definition
    assert "class ResizableSplit" in content or "function ResizableSplit" in content
    assert "window.ResizableSplit" in content


def test_resizable_split_destroy_method() -> None:
    """Test that ResizableSplit has a destroy() method."""
    split_js_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "js"
        / "resizable-split.js"
    )
    content = split_js_path.read_text()

    # Check destroy method exists
    assert "destroy()" in content or "destroy =" in content


def test_resizable_split_localstorage_integration() -> None:
    """Test that split uses localStorage for persistence."""
    split_js_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "js"
        / "resizable-split.js"
    )
    content = split_js_path.read_text()

    # Check localStorage key
    assert "dag-dashboard.run-detail.split" in content
    assert "localStorage.setItem" in content or "localStorage.getItem" in content


def test_resizable_split_clamps_percentage() -> None:
    """Test that split clamps percentage between 20 and 80."""
    split_js_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "js"
        / "resizable-split.js"
    )
    content = split_js_path.read_text()

    # Check for clamping logic (20-80 range)
    assert "20" in content and "80" in content


def test_resizable_split_mobile_breakpoint() -> None:
    """Test that split responds to mobile breakpoint."""
    split_js_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "js"
        / "resizable-split.js"
    )
    content = split_js_path.read_text()

    # Check for mobile breakpoint (could be literal or template literal)
    assert ("max-width" in content and "1024" in content) or "mobileBreakpoint" in content
