"""Unit tests for DAG renderer zoom calculations (requires PLAYWRIGHT_E2E=1).

These tests exercise the calculatePinchZoom function via Playwright's page.evaluate()
since the function is JavaScript. They verify the math is correct without needing
to synthesize actual touch events.
"""
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


@pytest.fixture
def page_with_zoom_function(page: Page):
    """Load page and expose calculatePinchZoom function."""
    page.goto("http://localhost:8100")
    page.wait_for_timeout(1000)

    # Verify function is exposed
    has_function = page.evaluate("typeof window.__testHooks?.calculatePinchZoom === 'function'")
    if not has_function:
        pytest.fail("calculatePinchZoom function not found in window.__testHooks")

    yield page


def test_calculate_pinch_zoom_normal_zoom_in(page_with_zoom_function: Page) -> None:
    """Test zoom in (distance increases)."""
    result = page_with_zoom_function.evaluate(
        "window.__testHooks.calculatePinchZoom(200, 100, 1.0)"
    )
    assert result == 2.0, f"Expected 2.0, got {result}"


def test_calculate_pinch_zoom_normal_zoom_out(page_with_zoom_function: Page) -> None:
    """Test zoom out (distance decreases)."""
    result = page_with_zoom_function.evaluate(
        "window.__testHooks.calculatePinchZoom(50, 100, 1.0)"
    )
    assert result == 0.5, f"Expected 0.5, got {result}"


def test_calculate_pinch_zoom_clamps_minimum(page_with_zoom_function: Page) -> None:
    """Test scale is clamped to minimum 0.5."""
    result = page_with_zoom_function.evaluate(
        "window.__testHooks.calculatePinchZoom(10, 100, 1.0)"
    )
    assert result == 0.5, f"Expected 0.5 (clamped), got {result}"


def test_calculate_pinch_zoom_clamps_maximum(page_with_zoom_function: Page) -> None:
    """Test scale is clamped to maximum 3.0."""
    result = page_with_zoom_function.evaluate(
        "window.__testHooks.calculatePinchZoom(500, 100, 1.0)"
    )
    assert result == 3.0, f"Expected 3.0 (clamped), got {result}"


def test_calculate_pinch_zoom_zero_initial_distance(page_with_zoom_function: Page) -> None:
    """Test zero initial distance returns initial scale unchanged."""
    result = page_with_zoom_function.evaluate(
        "window.__testHooks.calculatePinchZoom(100, 0, 2.5)"
    )
    assert result == 2.5, f"Expected 2.5 (unchanged), got {result}"


def test_calculate_pinch_zoom_negative_initial_distance(page_with_zoom_function: Page) -> None:
    """Test negative initial distance returns initial scale unchanged."""
    result = page_with_zoom_function.evaluate(
        "window.__testHooks.calculatePinchZoom(100, -50, 1.5)"
    )
    assert result == 1.5, f"Expected 1.5 (unchanged), got {result}"


def test_calculate_pinch_zoom_from_scaled_state(page_with_zoom_function: Page) -> None:
    """Test zoom from already-scaled state (initialScale != 1.0)."""
    result = page_with_zoom_function.evaluate(
        "window.__testHooks.calculatePinchZoom(150, 100, 2.0)"
    )
    assert result == 3.0, f"Expected 3.0 (2.0 * 1.5), got {result}"
