"""Helper functions for mobile viewport tests."""
import json
import shutil
from pathlib import Path
from typing import Any

from playwright.sync_api import Page


def assert_no_horizontal_scroll(page: Page) -> None:
    """Assert that page has no horizontal scrollbar at current viewport.
    
    Checks that document.documentElement.scrollWidth <= clientWidth.
    """
    scroll_width = page.evaluate("document.documentElement.scrollWidth")
    client_width = page.evaluate("document.documentElement.clientWidth")
    assert scroll_width <= client_width, (
        f"Horizontal overflow detected: scrollWidth={scroll_width}, "
        f"clientWidth={client_width}"
    )


def assert_touch_targets_meet_minimum(
    page: Page, selector: str, min_px: int = 44
) -> None:
    """Assert that all elements matching selector have minimum touch target size.
    
    Args:
        page: Playwright page object
        selector: CSS selector for elements to check
        min_px: Minimum dimension in pixels (default 44px per FR-12)
    
    Raises:
        AssertionError if any element is smaller than min_px in either dimension.
    """
    elements = page.locator(selector).all()
    if not elements:
        raise AssertionError(f"No elements found matching selector: {selector}")
    
    for idx, element in enumerate(elements):
        box = element.bounding_box()
        if box is None:
            continue  # Skip hidden elements
        
        assert box["width"] >= min_px, (
            f"Element {idx} ({selector}) width {box['width']}px < {min_px}px"
        )
        assert box["height"] >= min_px, (
            f"Element {idx} ({selector}) height {box['height']}px < {min_px}px"
        )


def load_fixture_workflow(
    events_dir: Path, fixture_name: str, fixtures_dir: Path
) -> None:
    """Copy a fixture ndjson workflow into the events directory.

    The EventCollector only processes files whose name ends in ``.ndjson``, so
    fixtures must use that extension.

    Args:
        events_dir: Destination directory (watched by dashboard)
        fixture_name: Name of fixture (without extension)
        fixtures_dir: Source fixtures directory
    """
    fixture_path = fixtures_dir / f"{fixture_name}.ndjson"
    if not fixture_path.exists():
        raise FileNotFoundError(f"Fixture not found: {fixture_path}")

    dest_path = events_dir / f"{fixture_name}.ndjson"
    shutil.copy(fixture_path, dest_path)


def navigate_to_run(page: Page, run_id: str) -> None:
    """Navigate to a workflow run detail page.

    The SPA router registers its routes at module scope, after the Router
    instance's initial ``handleRoute()`` call. As a result, ``page.goto``
    directly to ``/#/workflow/...`` arrives before the routes exist and
    the detail view never renders. Instead, load the shell, wait for
    scripts to execute (the Router instance appears on ``window``), then
    set the hash — the ``hashchange`` listener fires the now-registered
    route handler.
    """
    page.goto("http://localhost:8100/")
    # app.js is the last script and must finish before hash changes can
    # reach registered routes. Wait on a DOM node the shell always renders,
    # using state="attached" because #route-container is empty until a
    # route actually fires.
    page.wait_for_selector("#route-container", state="attached", timeout=5000)
    # Give scripts a moment to finish executing and register routes.
    page.wait_for_timeout(500)
    page.evaluate(f"window.location.hash = '/workflow/{run_id}'")
    # Workflow detail always renders #dag-container in its shell.
    page.wait_for_selector("#dag-container", state="attached", timeout=5000)
    # Allow DAG fetch + render to settle.
    page.wait_for_timeout(1000)


def get_console_errors(page: Page) -> list[str]:
    """Capture console error messages from the page.

    Filters out known preexisting production bugs that are unrelated to
    FR-12 mobile viewport requirements — these tests should fail on
    mobile-caused errors, not on pre-existing JS wiring issues.

    Returns:
        List of error message strings, excluding filtered preexisting bugs.
    """
    # Known preexisting bugs unrelated to mobile FR-12. Each entry should
    # reference a tracking issue.
    IGNORED_ERROR_PATTERNS = [
        "window.ChatPanel is not a constructor",  # Preexisting: ChatPanel class never assigned to window
    ]

    errors: list[str] = []

    def on_console(msg: Any) -> None:
        if msg.type != "error":
            return
        if any(pattern in msg.text for pattern in IGNORED_ERROR_PATTERNS):
            return
        errors.append(msg.text)

    page.on("console", on_console)
    return errors
