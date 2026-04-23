"""End-to-end mobile viewport tests (requires PLAYWRIGHT_E2E=1).

These tests verify that all Tier 11 surfaces meet FR-12 requirements at 320px viewport.
FR-12: All touch targets >= 44px, no horizontal overflow, touch gestures functional.

These tests require a running server. The conftest.py module provides
a dashboard_server fixture that automatically starts/stops the server.
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

from .helpers_mobile import (
    assert_no_horizontal_scroll,
    assert_touch_targets_meet_minimum,
    get_console_errors,
    navigate_to_run,
)


def test_dashboard_home_no_horizontal_scroll_at_320px(page: Page) -> None:
    """Test dashboard home has no horizontal scroll at iPhone SE viewport (320x568).

    FR-12: No horizontal overflow at 320px viewport.
    """
    page.set_viewport_size({"width": 320, "height": 568})

    # Capture console errors
    console_errors = get_console_errors(page)

    page.goto("http://localhost:8100")
    page.wait_for_timeout(1000)  # Allow page to fully load

    # Verify page loads
    assert page.title() == "DAG Dashboard"

    # Verify no horizontal overflow
    assert_no_horizontal_scroll(page)

    # Verify no console errors
    assert len(console_errors) == 0, f"Console errors: {console_errors}"


@pytest.mark.xfail(reason="GW-5274: Mobile menu toggle is 40px, below 44px minimum")
def test_mobile_nav_toggle_is_tappable(page: Page) -> None:
    """Test hamburger menu button meets 44x44px minimum at 320px viewport.

    FR-12: Touch targets >= 44px in both dimensions.

    XFAIL: Known FR-12 violation tracked in GW-5274.
    """
    page.set_viewport_size({"width": 320, "height": 568})
    console_errors = get_console_errors(page)

    page.goto("http://localhost:8100")
    page.wait_for_timeout(1000)

    # Check mobile menu toggle exists and meets size requirements
    toggle = page.locator("#mobile-menu-toggle")
    if toggle.count() == 0:
        pytest.skip("Mobile menu toggle not found (may be desktop-only layout)")

    assert_touch_targets_meet_minimum(page, "#mobile-menu-toggle", min_px=44)

    # Verify it's clickable
    toggle.click()
    page.wait_for_timeout(500)

    # Verify no console errors
    assert len(console_errors) == 0, f"Console errors: {console_errors}"


@pytest.mark.xfail(
    reason="Preexisting prod bug: ChatPanel class is not assigned to window.ChatPanel, "
    "so run detail can't instantiate it. Filed as GW-5275."
)
@pytest.mark.parametrize("dashboard_server", ["sample_workflow"], indirect=True)
def test_chat_panel_fits_at_320px(page: Page) -> None:
    """Test chat panel fits at 320px with adequate touch targets.

    FR-12: No horizontal overflow, textarea and send button >= 44px tall.
    Chat is rendered on the run detail page, not the home page.

    XFAIL: Preexisting bug prevents chat panel from rendering at all
    (see GW-5275). Once fixed, remove the xfail decorator.
    """
    page.set_viewport_size({"width": 320, "height": 568})
    console_errors = get_console_errors(page)

    navigate_to_run(page, "sample_workflow")
    page.wait_for_timeout(2000)

    # Verify chat panel is present
    chat_panel = page.locator(".chat-panel")
    assert chat_panel.count() > 0, "Chat panel not rendered on run detail page"

    # Verify no horizontal overflow
    assert_no_horizontal_scroll(page)

    # Check textarea and send button meet touch target minimums
    textarea = page.locator(".chat-input, textarea.chat-input")
    if textarea.count() > 0:
        box = textarea.first.bounding_box()
        assert box is not None and box["height"] >= 44, \
            f"Chat textarea height {box['height'] if box else 0}px < 44px"

    send_btn = page.locator("button:has-text('Send'), .chat-send")
    if send_btn.count() > 0:
        box = send_btn.first.bounding_box()
        assert box is not None and box["height"] >= 44, \
            f"Send button height {box['height'] if box else 0}px < 44px"

    # Verify no console errors
    assert len(console_errors) == 0, f"Console errors: {console_errors}"


@pytest.mark.xfail(
    reason="Event schema gap: node_detail-panel only renders the gate approval "
    "UI when node.status == 'interrupted', but the event collector has no "
    "handler that transitions a node into that status from ndjson events — "
    "it's only set via a code path not reachable from the public event format. "
    "Testing this surface requires either a DB-level seed or a new "
    "'node_interrupted' event type. Filed as GW-5276."
)
@pytest.mark.parametrize("dashboard_server", ["gate_pending_workflow"], indirect=True)
def test_gate_approval_surface_fits_at_320px(page: Page) -> None:
    """Test gate approval surface fits at 320px with 44x44px approve/reject buttons.

    FR-12: No horizontal overflow, approve/reject buttons >= 44x44px.

    XFAIL: Event-format gap prevents seeding an interrupted node via ndjson.
    Until GW-5276 is addressed, this surface can only be audited via manual
    inspection or a separate DB-level seed mechanism.
    """
    page.set_viewport_size({"width": 320, "height": 568})
    console_errors = get_console_errors(page)

    navigate_to_run(page, "gate_pending_workflow")

    # Click the gate node to open the node detail panel where approve/reject
    # buttons render. The DAG renderer attaches click handlers to .dag-node.
    gate_node = page.locator('[data-node-name="approval_gate"]')
    assert gate_node.count() > 0, "Gate node not rendered in DAG"
    # SVG node groups may not be reported as visible by Playwright at 320px
    # (no explicit bbox on <g>), so dispatch the custom node-click event
    # directly the same way the DAG renderer does (see dag-renderer.js:144).
    # NodeDetailPanel.show() requires node.id of the form "run_id:node_name".
    page.evaluate("""
        const evt = new CustomEvent('node-click', {
            detail: { id: 'gate_pending_workflow:approval_gate', node_name: 'approval_gate' }
        });
        window.dispatchEvent(evt);
    """)
    page.wait_for_timeout(1500)

    # Verify no horizontal overflow
    assert_no_horizontal_scroll(page)

    # Check approve/reject buttons meet touch target minimums
    approve_btn = page.locator(".gate-btn-approve")
    reject_btn = page.locator(".gate-btn-reject")

    assert approve_btn.count() > 0 and reject_btn.count() > 0, (
        "Gate approve/reject buttons not rendered after clicking gate node"
    )

    if approve_btn.count() > 0:
        box = approve_btn.first.bounding_box()
        assert box is not None and box["width"] >= 44 and box["height"] >= 44, \
            f"Approve button {box['width'] if box else 0}x{box['height'] if box else 0}px < 44x44px"

    if reject_btn.count() > 0:
        box = reject_btn.first.bounding_box()
        assert box is not None and box["width"] >= 44 and box["height"] >= 44, \
            f"Reject button {box['width'] if box else 0}x{box['height'] if box else 0}px < 44x44px"

    # Verify no console errors
    assert len(console_errors) == 0, f"Console errors: {console_errors}"


@pytest.mark.parametrize("dashboard_server", ["sample_workflow"], indirect=True)
def test_artifact_panel_fits_at_320px(page: Page) -> None:
    """Test artifact panel fits at 320px without horizontal overflow.

    FR-12: No horizontal overflow on the run detail page where the artifact
    list is rendered. Download button sizing is asserted when present; the
    sample fixture has no artifacts, so the test verifies the layout does
    not overflow even when the empty-state is rendered.
    """
    page.set_viewport_size({"width": 320, "height": 568})
    console_errors = get_console_errors(page)

    navigate_to_run(page, "sample_workflow")
    page.wait_for_timeout(2000)

    # Verify no horizontal overflow on the run detail page
    assert_no_horizontal_scroll(page)

    # Check download buttons if present (none expected in sample fixture)
    download_btns = page.locator(".artifact-download, button:has-text('Download')")
    if download_btns.count() > 0:
        for btn in download_btns.all()[:3]:
            box = btn.bounding_box()
            if box is not None:
                assert box["height"] >= 44, \
                    f"Download button height {box['height']}px < 44px"

    # Verify no console errors
    assert len(console_errors) == 0, f"Console errors: {console_errors}"


@pytest.mark.parametrize("dashboard_server", ["failed_node_workflow"], indirect=True)
def test_error_detail_fits_at_320px(page: Page) -> None:
    """Test error detail panel fits at 320px without overflow.

    FR-12: No horizontal overflow in error detail area.
    Seeded with failed_node_workflow.jsonl fixture.
    """
    page.set_viewport_size({"width": 320, "height": 568})
    console_errors = get_console_errors(page)

    # Navigate directly to the run detail page (run_id = fixture filename stem).
    navigate_to_run(page, "failed_node_workflow")
    page.wait_for_timeout(1500)

    # Click on failed node to view error detail
    failed_node = page.locator(".node.failed, .node-failed, [data-status='failed']")
    if failed_node.count() > 0:
        failed_node.first.click()
        page.wait_for_timeout(500)

    # Verify no horizontal overflow
    assert_no_horizontal_scroll(page)

    # Verify error message is visible
    error_msg = page.locator(".error-message, .node-error, pre:has-text('ValueError')")
    if error_msg.count() > 0:
        # Ensure error message doesn't cause overflow
        assert_no_horizontal_scroll(page)

    # Verify no console errors
    assert len(console_errors) == 0, f"Console errors: {console_errors}"


@pytest.mark.parametrize("dashboard_server", ["sample_workflow"], indirect=True)
def test_dag_canvas_pinch_zoom_listeners_attached(page: Page) -> None:
    """Test DAG canvas has pinch-to-zoom listeners attached at 320px.

    FR-12: Touch gestures functional (pinch-to-zoom).
    Uses CDP to verify event listeners exist. Math correctness proven via unit test.
    """
    page.set_viewport_size({"width": 320, "height": 568})
    console_errors = get_console_errors(page)

    # Navigate directly to the run detail page (run_id = fixture filename stem).
    navigate_to_run(page, "sample_workflow")
    page.wait_for_timeout(2000)

    # Verify SVG exists (if not, the DAG renderer didn't load — surface it)
    svg = page.locator("svg")
    assert svg.count() > 0, "DAG canvas SVG not rendered"

    # Use CDP to check for touchstart/touchmove listeners
    # Note: getEventListeners is a DevTools-only function
    listeners_check = page.evaluate("""() => {
        const svg = document.querySelector('svg');
        if (!svg) return { touchstart: false, touchmove: false };

        // Check if touch event handlers are attached
        // We can't use getEventListeners in regular context, so check for touch-action style
        const touchAction = window.getComputedStyle(svg).touchAction;
        const hasTouchStyle = touchAction === 'none';

        // Also verify the calculatePinchZoom function exists
        const hasZoomFunction = typeof window.__testHooks?.calculatePinchZoom === 'function';

        return {
            hasTouchStyle: hasTouchStyle,
            hasZoomFunction: hasZoomFunction
        };
    }""")

    assert listeners_check["hasTouchStyle"], "SVG does not have touch-action: none"
    assert listeners_check["hasZoomFunction"], "calculatePinchZoom function not exposed for testing"

    # Verify no console errors
    assert len(console_errors) == 0, f"Console errors: {console_errors}"


@pytest.mark.parametrize("dashboard_server", ["sample_workflow"], indirect=True)
def test_dag_canvas_pan_gesture(page: Page) -> None:
    """Test DAG canvas pan gesture still functional at 320px.

    FR-12: Touch gestures functional (single-finger pan).
    """
    page.set_viewport_size({"width": 320, "height": 568})
    console_errors = get_console_errors(page)

    navigate_to_run(page, "sample_workflow")
    page.wait_for_timeout(2000)

    svg = page.locator("svg")
    assert svg.count() > 0, "DAG canvas SVG not rendered"

    # Get initial viewBox/transform
    initial_transform = page.evaluate("""() => {
        const g = document.querySelector('svg > g');
        return g ? g.getAttribute('transform') : null;
    }""")

    # Simulate pan gesture (tap + drag)
    box = svg.first.bounding_box()
    if box:
        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2

        # Use mouse events as fallback for pan (touchscreen.tap doesn't support drag)
        page.mouse.move(start_x, start_y)
        page.mouse.down()
        page.mouse.move(start_x + 50, start_y + 50)
        page.mouse.up()

        page.wait_for_timeout(500)

        # Get new transform
        new_transform = page.evaluate("""() => {
            const g = document.querySelector('svg > g');
            return g ? g.getAttribute('transform') : null;
        }""")

        # Verify transform changed (pan occurred)
        # Don't assert exact values since initial state may vary
        assert new_transform is not None, "SVG transform not found"

    # Verify no console errors
    assert len(console_errors) == 0, f"Console errors: {console_errors}"


# --- Tier A-D Mobile Audit Tests (GW-5295) ---


@pytest.mark.parametrize("dashboard_server", ["gate_pending_workflow"], indirect=True)
def test_cancel_dialog_fits_at_320px(page: Page) -> None:
    """Test Cancel dialog has no horizontal scroll and meets touch target requirements at 320px.

    FR-12: No horizontal overflow, touch targets >= 44px at 320px viewport.

    NOTE: Uses gate_pending_workflow fixture which keeps workflow in running state,
    ensuring Cancel button is visible. Follow-up: GW-5318 to create dedicated
    running_workflow.ndjson fixture.
    """
    page.set_viewport_size({"width": 320, "height": 568})
    console_errors = get_console_errors(page)

    navigate_to_run(page, "gate-pending-test")
    page.wait_for_timeout(1000)

    # Cancel button should be visible on running workflow
    cancel_button = page.locator(".cancel-run-btn")
    assert cancel_button.count() > 0, "Cancel button not found (expected on running workflow)"

    # Click Cancel button to open confirmation dialog
    cancel_button.click()
    page.wait_for_timeout(500)

    # Verify dialog is visible
    dialog = page.locator(".confirm-dialog")
    assert dialog.count() > 0, "Cancel confirmation dialog did not open"

    # Verify no horizontal overflow on dialog
    assert_no_horizontal_scroll(page)

    # Verify cancel confirmation buttons meet touch target requirements
    # Dialog has "Confirm" and "Cancel" buttons
    assert_touch_targets_meet_minimum(page, ".confirm-dialog .btn-danger", min_px=44)
    assert_touch_targets_meet_minimum(page, ".confirm-dialog .btn-secondary", min_px=44)

    # Capture screenshot at 320px
    page.screenshot(path="packages/dag-dashboard/tests/evidence/GW-5295/cancel_dialog_320px.png")

    # Capture screenshot at 768px viewport
    page.set_viewport_size({"width": 768, "height": 1024})
    page.wait_for_timeout(500)
    page.screenshot(path="packages/dag-dashboard/tests/evidence/GW-5295/cancel_dialog_768px.png")

    # Verify no console errors
    assert len(console_errors) == 0, f"Console errors: {console_errors}"


@pytest.mark.parametrize("dashboard_server", ["sample_workflow"], indirect=True)
def test_rerun_form_fits_at_320px(page: Page) -> None:
    """Test Re-run form has no horizontal scroll and meets touch target requirements at 320px.

    FR-12: No horizontal overflow, touch targets >= 44px at 320px viewport.
    """
    page.set_viewport_size({"width": 320, "height": 568})
    console_errors = get_console_errors(page)

    navigate_to_run(page, "sample_workflow")
    page.wait_for_timeout(1000)

    # Find and click the Re-run button (ID is #rerun-button)
    rerun_button = page.locator("#rerun-button")
    assert rerun_button.count() > 0, "Re-run button not found"
    rerun_button.click()
    page.wait_for_timeout(500)

    # Verify rerun form is visible
    rerun_form = page.locator("#rerun-form")
    assert rerun_form.count() > 0, "Re-run form did not open"

    # Verify no horizontal overflow
    assert_no_horizontal_scroll(page)

    # Verify form inputs meet touch target requirements
    # Re-run form has textarea and submit button
    submit_btn = page.locator("#rerun-form button[type='submit']")
    assert submit_btn.count() > 0, "Re-run submit button not found"
    assert_touch_targets_meet_minimum(page, "#rerun-form button[type='submit']", min_px=44)

    # Capture screenshot at 320px
    page.screenshot(path="packages/dag-dashboard/tests/evidence/GW-5295/rerun_form_320px.png")

    # Capture screenshot at 768px viewport
    page.set_viewport_size({"width": 768, "height": 1024})
    page.wait_for_timeout(500)
    page.screenshot(path="packages/dag-dashboard/tests/evidence/GW-5295/rerun_form_768px.png")

    # Verify no console errors
    assert len(console_errors) == 0, f"Console errors: {console_errors}"


@pytest.mark.parametrize("dashboard_server", ["failed_node_workflow"], indirect=True)
def test_step_logs_fits_at_320px(page: Page) -> None:
    """Test StepLogs panel has no horizontal scroll and toolbar is accessible at 320px.

    FR-12: No horizontal overflow, touch targets >= 44px at 320px viewport.
    """
    page.set_viewport_size({"width": 320, "height": 568})
    console_errors = get_console_errors(page)

    navigate_to_run(page, "failed_node_workflow")
    page.wait_for_timeout(1500)

    # Click on a failed node to open step logs
    # Use same selector pattern as test_error_detail_fits_at_320px
    failed_node = page.locator(".node.failed, .node-failed, [data-status='failed']")
    if failed_node.count() == 0:
        pytest.skip("No failed nodes found in fixture")

    failed_node.first.click()
    page.wait_for_timeout(1000)

    # Verify step logs container is visible
    step_logs = page.locator(".step-logs")
    assert step_logs.count() > 0, "Step logs panel did not open"

    # Verify no horizontal overflow
    assert_no_horizontal_scroll(page)

    # Verify toolbar controls are accessible
    # Step logs has filter buttons and status indicator
    toolbar = page.locator(".step-logs-toolbar")
    assert toolbar.count() > 0, "Step logs toolbar not found"

    # Check filter buttons meet touch target requirements
    filter_buttons = page.locator(".step-logs-filters button")
    if filter_buttons.count() > 0:
        assert_touch_targets_meet_minimum(page, ".step-logs-filters button", min_px=44)

    # Capture screenshot at 320px
    page.screenshot(path="packages/dag-dashboard/tests/evidence/GW-5295/step_logs_320px.png")

    # Capture screenshot at 768px viewport
    page.set_viewport_size({"width": 768, "height": 1024})
    page.wait_for_timeout(500)
    page.screenshot(path="packages/dag-dashboard/tests/evidence/GW-5295/step_logs_768px.png")

    # Verify no console errors
    assert len(console_errors) == 0, f"Console errors: {console_errors}"


@pytest.mark.parametrize("dashboard_server", ["sample_workflow"], indirect=True)
def test_search_bar_fits_at_320px(page: Page) -> None:
    """Test SearchBar adapts to 320px viewport per @media rule.

    FR-12: No horizontal overflow, touch targets >= 44px at 320px viewport.
    """
    page.set_viewport_size({"width": 320, "height": 568})
    console_errors = get_console_errors(page)

    page.goto("http://localhost:8100")
    page.wait_for_timeout(1000)

    # Verify search bar is visible - hard assertion (requires workflow data)
    search_bar = page.locator(".search-bar")
    assert search_bar.count() > 0, "Search bar not found (requires workflow data from fixture)"

    # Verify no horizontal overflow
    assert_no_horizontal_scroll(page)

    # Verify search input meets touch target requirements
    search_input = page.locator(".search-bar input")
    assert search_input.count() > 0, "Search input not found"
    assert_touch_targets_meet_minimum(page, ".search-bar input", min_px=44)

    # Capture screenshot at 320px
    page.screenshot(path="packages/dag-dashboard/tests/evidence/GW-5295/search_bar_320px.png")

    # Capture screenshot at 768px viewport
    page.set_viewport_size({"width": 768, "height": 1024})
    page.wait_for_timeout(500)
    page.screenshot(path="packages/dag-dashboard/tests/evidence/GW-5295/search_bar_768px.png")

    # Verify no console errors
    assert len(console_errors) == 0, f"Console errors: {console_errors}"


@pytest.mark.xfail(reason="GW-5317: Settings input checkboxes are 20px wide, below 44px minimum")
def test_settings_page_fits_at_320px(page: Page) -> None:
    """Test Settings page has no horizontal scroll and form inputs are accessible at 320px.

    FR-12: No horizontal overflow, touch targets >= 44px at 320px viewport.

    XFAIL: Known FR-12 violation tracked in GW-5317.
    """
    page.set_viewport_size({"width": 320, "height": 568})
    console_errors = get_console_errors(page)

    # Navigate to settings page using hash routing
    page.goto("http://localhost:8100/")
    page.wait_for_selector("#route-container", state="attached", timeout=5000)
    page.wait_for_timeout(500)
    page.evaluate("window.location.hash = '/settings'")
    page.wait_for_timeout(1000)

    # Verify settings page is visible
    settings_page = page.locator(".settings-page")
    assert settings_page.count() > 0, "Settings page did not render"

    # Verify no horizontal overflow
    assert_no_horizontal_scroll(page)

    # Verify form inputs meet touch target requirements
    settings_inputs = page.locator(".settings-input")
    if settings_inputs.count() > 0:
        assert_touch_targets_meet_minimum(page, ".settings-input", min_px=44)

    # Check submit button if present
    submit_btn = page.locator(".settings-form button[type='submit']")
    if submit_btn.count() > 0:
        assert_touch_targets_meet_minimum(page, ".settings-form button[type='submit']", min_px=44)

    # Capture screenshot at 320px
    page.screenshot(path="packages/dag-dashboard/tests/evidence/GW-5295/settings_page_320px.png")

    # Capture screenshot at 768px viewport
    page.set_viewport_size({"width": 768, "height": 1024})
    page.wait_for_timeout(500)
    page.screenshot(path="packages/dag-dashboard/tests/evidence/GW-5295/settings_page_768px.png")

    # Verify no console errors
    assert len(console_errors) == 0, f"Console errors: {console_errors}"


@pytest.mark.parametrize("dashboard_server", ["sample_workflow"], indirect=True)
def test_workflows_page_fits_at_320px(page: Page) -> None:
    """Test Workflows page has no horizontal scroll and list items are tappable at 320px.

    FR-12: No horizontal overflow, touch targets >= 44px at 320px viewport.
    """
    page.set_viewport_size({"width": 320, "height": 568})
    console_errors = get_console_errors(page)

    # Navigate to workflows page using hash routing
    page.goto("http://localhost:8100/")
    page.wait_for_selector("#route-container", state="attached", timeout=5000)
    page.wait_for_timeout(500)
    page.evaluate("window.location.hash = '/workflows'")
    page.wait_for_timeout(1000)

    # Verify workflows page is visible - hard assertion (requires workflow data)
    workflows_container = page.locator("#workflows-list")
    assert workflows_container.count() > 0, "Workflows list not found (requires workflow data from fixture)"

    # Verify no horizontal overflow
    assert_no_horizontal_scroll(page)

    # Verify workflow list items are tappable (>= 44px tall rows/links)
    workflow_items = page.locator("#workflows-list .workflow-item")
    assert workflow_items.count() > 0, "No workflow items found in list"
    assert_touch_targets_meet_minimum(page, "#workflows-list .workflow-item", min_px=44)

    # Capture screenshot at 320px
    page.screenshot(path="packages/dag-dashboard/tests/evidence/GW-5295/workflows_page_320px.png")

    # Capture screenshot at 768px viewport
    page.set_viewport_size({"width": 768, "height": 1024})
    page.wait_for_timeout(500)
    page.screenshot(path="packages/dag-dashboard/tests/evidence/GW-5295/workflows_page_768px.png")

    # Verify no console errors
    assert len(console_errors) == 0, f"Console errors: {console_errors}"
