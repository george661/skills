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
    """Copy a fixture JSONL workflow into the events directory.
    
    Args:
        events_dir: Destination directory (watched by dashboard)
        fixture_name: Name of fixture (without .jsonl extension)
        fixtures_dir: Source fixtures directory
    """
    fixture_path = fixtures_dir / f"{fixture_name}.jsonl"
    if not fixture_path.exists():
        raise FileNotFoundError(f"Fixture not found: {fixture_path}")
    
    dest_path = events_dir / f"{fixture_name}.jsonl"
    shutil.copy(fixture_path, dest_path)


def get_console_errors(page: Page) -> list[str]:
    """Capture console error messages from the page.
    
    Returns:
        List of error message strings.
    """
    errors: list[str] = []
    
    def on_console(msg: Any) -> None:
        if msg.type == "error":
            errors.append(msg.text)
    
    page.on("console", on_console)
    return errors
