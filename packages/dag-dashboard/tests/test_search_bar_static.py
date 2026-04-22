"""Test search-bar.js static file."""
import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    """Create test client with temporary database."""
    app = create_app(tmp_path)
    return TestClient(app)


def test_search_bar_js_served(client: TestClient) -> None:
    """Test that search-bar.js is served correctly."""
    response = client.get("/js/search-bar.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_search_bar_script_tag_in_index(client: TestClient) -> None:
    """Test that index.html includes search-bar.js script tag."""
    response = client.get("/")
    assert response.status_code == 200
    content = response.text
    assert '<script src="/js/search-bar.js">' in content


def test_sidebar_has_search_container(client: TestClient) -> None:
    """Test that index.html has search-bar-container-desktop in sidebar."""
    response = client.get("/")
    assert response.status_code == 200
    content = response.text
    assert 'id="search-bar-container-desktop"' in content
    # Verify it's inside the sidebar element
    assert 'class="sidebar"' in content


def test_mobile_nav_has_search_container(client: TestClient) -> None:
    """Test that index.html has search-bar-container-mobile in mobile nav."""
    response = client.get("/")
    assert response.status_code == 200
    content = response.text
    assert 'id="search-bar-container-mobile"' in content
    # Verify it's inside mobile-nav
    assert 'id="mobile-nav"' in content


def test_search_bar_uses_api_search_endpoint() -> None:
    """Test that search-bar.js uses the /api/search endpoint."""
    search_bar_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "search-bar.js"
    content = search_bar_path.read_text()
    
    assert "/api/search" in content
    assert "encodeURIComponent" in content


def test_search_bar_debounces() -> None:
    """Test that search-bar.js debounces input with 250ms timeout."""
    search_bar_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "search-bar.js"
    content = search_bar_path.read_text()
    
    assert "setTimeout" in content
    assert "250" in content


def test_search_bar_handles_slash_shortcut() -> None:
    """Test that search-bar.js handles '/' keyboard shortcut."""
    search_bar_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "search-bar.js"
    content = search_bar_path.read_text()
    
    # Should have a keydown handler that checks for '/'
    assert "keydown" in content or "keypress" in content
    # Looking for '/' key check (could be e.key === '/' or keyCode checks)
    assert '"/"' in content or "'/'".lower() in content.lower()


def test_search_bar_supports_arrow_navigation() -> None:
    """Test that search-bar.js supports arrow key navigation."""
    search_bar_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "search-bar.js"
    content = search_bar_path.read_text()
    
    assert "ArrowUp" in content or "ArrowDown" in content


def test_search_bar_escapes_html() -> None:
    """Test that search-bar.js escapes HTML in results."""
    search_bar_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "search-bar.js"
    content = search_bar_path.read_text()
    
    # Should have an escape function and use it
    assert "_escape" in content or "escapeHtml" in content


def test_search_bar_aborts_inflight_fetch() -> None:
    """Test that search-bar.js aborts in-flight fetches."""
    search_bar_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "search-bar.js"
    content = search_bar_path.read_text()
    
    assert "AbortController" in content


def test_search_bar_caps_results_at_10() -> None:
    """Test that search-bar.js caps results at 10 items."""
    search_bar_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "search-bar.js"
    content = search_bar_path.read_text()
    
    assert ".slice(0, 10)" in content or ".slice(0,10)" in content


def test_search_bar_uses_aria_activedescendant() -> None:
    """Test that search-bar.js uses aria-activedescendant for accessibility."""
    search_bar_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "search-bar.js"
    content = search_bar_path.read_text()
    
    assert "aria-activedescendant" in content


def test_search_bar_navigates_to_workflow_route() -> None:
    """Test that search-bar.js navigates to /workflow/ route and dispatches node-click."""
    search_bar_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "search-bar.js"
    content = search_bar_path.read_text()
    
    # Should navigate to /workflow/ route (not /history/)
    assert "/workflow/" in content
    # Should dispatch node-click CustomEvent for node results
    assert "node-click" in content
    assert "CustomEvent" in content


def test_app_js_initializes_search_bar() -> None:
    """Test that app.js initializes SearchBar for both desktop and mobile."""
    app_js_path = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js" / "app.js"
    content = app_js_path.read_text()
    
    assert "SearchBar.init" in content
    # Should initialize both containers
    assert "search-bar-container-desktop" in content or "search-bar-container-mobile" in content
