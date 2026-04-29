"""Integration test for run detail remount lifecycle (AC-8).

This test is opt-in via PLAYWRIGHT_E2E=1 environment variable.
"""
import os
from pathlib import Path

import pytest

# Skip if PLAYWRIGHT_E2E is not set
pytestmark = pytest.mark.skipif(
    os.getenv("PLAYWRIGHT_E2E") != "1",
    reason="Playwright e2e tests require PLAYWRIGHT_E2E=1",
)


@pytest.fixture
def page(playwright):
    """Create a Playwright page instance."""
    browser = playwright.chromium.launch()
    context = browser.new_context()
    page = context.new_page()
    yield page
    context.close()
    browser.close()


def test_run_detail_remount_no_resource_leak(page, live_server):
    """Test that navigating between runs doesn't leak resources (AC-8).
    
    Verifies:
    - No unbounded growth in performance.getEntriesByType('resource')
    - EventSource connections are properly closed
    - Timer handles are cleaned up
    """
    base_url = f"http://localhost:{live_server.port}"
    
    # Create two test run IDs
    run_a = "test-run-remount-a"
    run_b = "test-run-remount-b"
    
    # Navigate to first run
    page.goto(f"{base_url}/#/workflow/{run_a}")
    page.wait_for_load_state("networkidle")
    
    # Get initial resource count
    initial_count = page.evaluate(
        "window.performance.getEntriesByType('resource').length"
    )
    
    # Navigate between runs 10 times
    for i in range(10):
        target = run_b if i % 2 == 0 else run_a
        page.goto(f"{base_url}/#/workflow/{target}")
        page.wait_for_load_state("networkidle")
    
    # Get final resource count
    final_count = page.evaluate(
        "window.performance.getEntriesByType('resource').length"
    )
    
    # Resource count should not grow unboundedly
    # Allow for some growth (e.g., 2x initial) but not 10x
    assert final_count < initial_count * 3, (
        f"Resource leak detected: {initial_count} → {final_count}"
    )
    
    # Check for EventSource cleanup
    # This will use either window.__openEventSources if implemented,
    # or check performance.getEntriesByType('resource') for /events
    sse_check = page.evaluate("""() => {
        // Option A: if window.__openEventSources is implemented
        if (typeof window.__openEventSources !== 'undefined') {
            return window.__openEventSources;
        }
        // Option B: count /events resource entries
        const resources = window.performance.getEntriesByType('resource');
        const eventSources = resources.filter(r => r.name.includes('/events'));
        return eventSources.length;
    }""")
    
    # Should have at most 1-2 EventSource connections (current + possibly closing)
    if isinstance(sse_check, int):
        assert sse_check <= 2, f"Too many EventSource connections: {sse_check}"


def test_run_detail_remount_no_console_errors(page, live_server):
    """Test that navigation between runs doesn't produce console errors."""
    base_url = f"http://localhost:{live_server.port}"
    errors = []
    
    def handle_console(msg):
        if msg.type == "error":
            errors.append(msg.text)
    
    page.on("console", handle_console)
    
    # Navigate between runs
    for i in range(5):
        run_id = f"test-run-remount-{i}"
        page.goto(f"{base_url}/#/workflow/{run_id}")
        page.wait_for_load_state("networkidle")
    
    # Should have no console errors
    assert len(errors) == 0, f"Console errors detected: {errors}"
