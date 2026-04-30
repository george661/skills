"""Test run detail layout transformation (AC-1 + AC-8)."""
from pathlib import Path


def test_run_graph_split_grid_rules_removed() -> None:
    """Assert the pre-existing CSS grid rules on .run-graph-split are gone.

    ResizableSplit adds `.run-split` to the same DOM element at runtime,
    so the old `.run-graph-split { display: grid; ... }` rules became
    dead code. Removing them avoids two display modes fighting on the
    same element and keeps styles.css readable.
    """
    css_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "css"
        / "styles.css"
    )
    content = css_path.read_text()

    # The class stays as a querySelector hook in app.js, but must not
    # carry a `display: grid` rule anymore.
    assert ".run-graph-split {" not in content, (
        ".run-graph-split must not define its own CSS rules — "
        "layout now comes from .run-split applied by ResizableSplit"
    )
    # And the old @media override that scoped `.run-graph-split` should be gone.
    assert "grid-template-columns: 1fr" not in content or ".run-graph-split" not in content.split(
        "grid-template-columns: 1fr"
    )[0].split("@media")[-1]


def test_resizable_split_has_a_mount_selector() -> None:
    """ResizableSplit must query for *some* mount class in app.js.

    The current run-detail template (3-column grid: canvas + side + chat)
    intentionally has no mount point — ResizableSplit is designed for two
    panes, so mounting it on the 3-column layout would clobber the chat
    column when `_buildStructure` wipes the container. GW-5422 will swap
    the right two columns for a single conversation feed and introduce a
    `.run-pane-split` (or similar) mount class at that point.

    This test just guards that app.js still HAS the `querySelector` wire
    so the dormant init doesn't get accidentally deleted during refactor.
    """
    app_js_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "js"
        / "app.js"
    )
    content = app_js_path.read_text()

    assert "new window.ResizableSplit" in content, (
        "ResizableSplit instantiation must remain in renderRunDetail so it "
        "activates the moment GW-5422 introduces the 2-pane mount class"
    )
    assert "querySelector('.run-pane-split')" in content or \
           "querySelector('.run-graph-split')" in content, (
        "app.js must still look up a split mount point — the mount class "
        "may change with layout iterations, but the wire-up must persist"
    )


def test_new_split_layout_added_to_css() -> None:
    """Test that new split layout classes are added to CSS."""
    css_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "css"
        / "styles.css"
    )
    content = css_path.read_text()

    # New split layout should be present
    assert ".run-split" in content
    assert ".run-split-divider" in content


def test_resizable_split_loaded_before_app_js() -> None:
    """Test that resizable-split.js is loaded before app.js in index.html."""
    html_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "index.html"
    )
    content = html_path.read_text()

    # Check script loading order
    assert "/js/resizable-split.js" in content
    assert "/js/app.js" in content

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
