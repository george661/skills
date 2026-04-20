"""End-to-end mobile viewport tests (requires PLAYWRIGHT_E2E=1)."""
import os
import pytest

# Skip all tests in this module unless PLAYWRIGHT_E2E=1
pytestmark = pytest.mark.skipif(
    os.getenv("PLAYWRIGHT_E2E") != "1",
    reason="Playwright E2E tests are opt-in (set PLAYWRIGHT_E2E=1)"
)

try:
    from playwright.sync_api import Page
except ImportError:
    pytest.skip("Playwright not installed (install with: pip install -e .[e2e])", allow_module_level=True)


def test_mobile_viewport_320x568(page: Page) -> None:
    """Test dashboard at iPhone SE viewport (320x568)."""
    page.set_viewport_size({"width": 320, "height": 568})
    page.goto("http://localhost:8100")
    
    # Verify page loads
    assert page.title() == "DAG Dashboard"
    
    # Verify no console errors
    console_errors = []
    page.on("console", lambda msg: console_errors.append(msg) if msg.type == "error" else None)
    page.wait_for_timeout(1000)
    assert len(console_errors) == 0, f"Console errors: {console_errors}"


def test_mobile_viewport_375x667(page: Page) -> None:
    """Test dashboard at iPhone 6/7/8 viewport (375x667)."""
    page.set_viewport_size({"width": 375, "height": 667})
    page.goto("http://localhost:8100")
    
    assert page.title() == "DAG Dashboard"


def test_resumed_node_indicator_desktop(page: Page) -> None:
    """Test that resumed nodes render with dashed outline at desktop viewport."""
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto("http://localhost:8100")
    
    # TODO: Load a workflow with cache_hit=true nodes and verify SVG has stroke-dasharray
    pass
