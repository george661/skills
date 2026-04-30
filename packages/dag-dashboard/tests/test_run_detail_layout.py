"""Test unified feed layout (GW-5422)."""
from pathlib import Path


def test_two_pane_split_layout_exists() -> None:
    """Assert the new two-pane split layout is present in app.js."""
    app_js_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "js"
        / "app.js"
    )
    content = app_js_path.read_text()

    # Two-pane split mount class must exist
    assert ".run-pane-split" in content, (
        "New two-pane layout must use .run-pane-split mount class"
    )

    # ResizableSplit should be instantiated
    assert "new window.ResizableSplit" in content, (
        "ResizableSplit must be instantiated for the two-pane layout"
    )


def test_workflow_progress_card_initialized() -> None:
    """Assert WorkflowProgressCard is initialized in app.js."""
    app_js_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "js"
        / "app.js"
    )
    content = app_js_path.read_text()

    assert "window.WorkflowProgressCard" in content, (
        "WorkflowProgressCard must be initialized in renderRunDetail"
    )
    assert "workflow-progress-card-container" in content, (
        "WorkflowProgressCard container must be present"
    )


def test_state_slideover_mounted() -> None:
    """Assert StateSlideover is mounted (eager mount) in app.js."""
    app_js_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "js"
        / "app.js"
    )
    content = app_js_path.read_text()

    assert "window.StateSlideover" in content, (
        "StateSlideover must be mounted in renderRunDetail"
    )
    assert "state-slideover-mount" in content, (
        "StateSlideover mount point must exist"
    )


def test_old_three_column_layout_removed() -> None:
    """Assert the old 3-column grid layout is removed from app.js."""
    app_js_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "js"
        / "app.js"
    )
    content = app_js_path.read_text()

    # Old 3-column grid class should be gone
    assert ".run-graph-3col" not in content, (
        "Old three-column grid layout must be removed"
    )


def test_unified_feed_css_classes_exist() -> None:
    """Test that unified feed CSS classes are present in styles.css."""
    css_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "css"
        / "styles.css"
    )
    content = css_path.read_text()

    # New layout classes
    assert ".run-pane-split" in content
    assert ".run-pane-left" in content
    assert ".run-pane-right" in content

    # Progress card classes
    assert ".workflow-progress-card-container" in content
    assert ".progress-card-item" in content

    # State slideover classes
    assert ".state-slideover" in content
    assert ".state-slideover-panel" in content
    assert ".state-slideover--closed" in content


def test_new_scripts_loaded_in_order() -> None:
    """Test that new JS modules are loaded in correct order in index.html."""
    html_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "index.html"
    )
    content = html_path.read_text()

    # All new scripts must be present
    assert "/js/node-scroll-bus.js" in content
    assert "/js/event-to-messages.js" in content
    assert "/js/workflow-progress-card.js" in content
    assert "/js/state-slideover.js" in content

    # Must be loaded before app.js
    app_idx = content.index("/js/app.js")
    bus_idx = content.index("/js/node-scroll-bus.js")
    events_idx = content.index("/js/event-to-messages.js")
    card_idx = content.index("/js/workflow-progress-card.js")
    slideover_idx = content.index("/js/state-slideover.js")

    assert bus_idx < app_idx, "node-scroll-bus.js must load before app.js"
    assert events_idx < app_idx, "event-to-messages.js must load before app.js"
    assert card_idx < app_idx, "workflow-progress-card.js must load before app.js"
    assert slideover_idx < app_idx, "state-slideover.js must load before app.js"

    # Verify order
    split_pos = content.find("/js/resizable-split.js")
    app_pos = content.find("/js/app.js")
    assert split_pos < app_pos, "resizable-split.js must load before app.js"


def test_app_js_creates_split_instance() -> None:
    """Test that app.js creates a ResizableSplit instance."""
    app_js_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "js"
        / "app.js"
    )
    content = app_js_path.read_text()

    # Check for split instantiation
    assert "ResizableSplit" in content
    assert "new " in content or "new(" in content


def test_lifecycle_has_destroy_method() -> None:
    """Test that app.js implements lifecycle.destroy() (AC-8)."""
    app_js_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "js"
        / "app.js"
    )
    content = app_js_path.read_text()

    # Check that lifecycle object with destroy method exists
    assert "lifecycle" in content and "destroy:" in content


def test_split_destroy_called() -> None:
    """Test that app.js destroys the split instance on cleanup (AC-8)."""
    app_js_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "js"
        / "app.js"
    )
    content = app_js_path.read_text()

    # Check that resizableSplit.destroy() is called in lifecycle
    assert "resizableSplit" in content and "destroy()" in content


def test_animation_frame_cleanup() -> None:
    """Test that requestAnimationFrame is cancelled on cleanup (AC-8 - fixes existing leak)."""
    app_js_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "js"
        / "app.js"
    )
    content = app_js_path.read_text()

    # Check for cancelAnimationFrame call
    assert "cancelAnimationFrame" in content
    assert "animationId" in content
