"""Test node-library.js static file.

Note: Unlike test_search_bar_static.py, this test does NOT assert on a script tag
in index.html. The node-library.js will be imported by the React builder bundle
(GW-5242), not directly by index.html. This boundary is intentional.
"""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create test client with temporary database."""
    app = create_app(tmp_path)
    return TestClient(app)


def test_node_library_js_served(client: TestClient) -> None:
    """Test that node-library.js is served correctly."""
    response = client.get("/js/builder/node-library.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_node_library_has_categories() -> None:
    """Test that node-library.js contains all three category labels."""
    node_library_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "builder" / "node-library.js"
    content = node_library_path.read_text()
    
    # Should have category labels
    assert "Node types" in content or "Node Types" in content
    assert "Commands" in content
    assert "Skills" in content


def test_node_library_has_search_input() -> None:
    """Test that node-library.js has a search input."""
    node_library_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "builder" / "node-library.js"
    content = node_library_path.read_text()
    
    # Should have input for search
    assert 'type="text"' in content or 'type="search"' in content
    assert "placeholder" in content.lower()


def test_node_library_has_draggable_items() -> None:
    """Test that node-library.js marks items as draggable."""
    node_library_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "builder" / "node-library.js"
    content = node_library_path.read_text()
    
    # Should set draggable attribute
    assert "draggable" in content


def test_node_library_uses_drag_data_transfer() -> None:
    """Test that node-library.js uses dataTransfer for drag data."""
    node_library_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "builder" / "node-library.js"
    content = node_library_path.read_text()
    
    # Should use dataTransfer API
    assert "dataTransfer" in content
    assert "setData" in content
    assert "application/x-dag-node" in content


def test_node_library_persists_width_to_localstorage() -> None:
    """Test that node-library.js persists width to localStorage."""
    node_library_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "builder" / "node-library.js"
    content = node_library_path.read_text()
    
    # Should use localStorage for width persistence
    assert "localStorage" in content
    assert "archon-node-library-width" in content


def test_node_library_fetches_definitions() -> None:
    """Test that node-library.js fetches from /api/definitions."""
    node_library_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "builder" / "node-library.js"
    content = node_library_path.read_text()
    
    # Should fetch commands from definitions endpoint
    assert "/api/definitions" in content


def test_node_library_fetches_skills() -> None:
    """Test that node-library.js fetches from /api/skills."""
    node_library_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "builder" / "node-library.js"
    content = node_library_path.read_text()
    
    # Should fetch skills from skills endpoint
    assert "/api/skills" in content


def test_node_library_has_resize_handle() -> None:
    """Test that node-library.js has a resize handle."""
    node_library_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "builder" / "node-library.js"
    content = node_library_path.read_text()
    
    # Should have resize handle with mouse event handlers
    assert "onMouseDown" in content or "mousedown" in content
    assert "onMouseMove" in content or "mousemove" in content


def test_node_library_has_six_node_types() -> None:
    """Test that node-library.js defines all 6 runner types."""
    node_library_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "builder" / "node-library.js"
    content = node_library_path.read_text()
    
    # Should have all 6 runner types in a constant or list
    assert "bash" in content
    assert "command" in content
    assert "gate" in content
    assert "interrupt" in content
    assert "prompt" in content
    assert "skill" in content
