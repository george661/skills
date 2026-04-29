"""Test run detail layout transformation (AC-1 + AC-8)."""
from pathlib import Path


def test_old_three_column_layout_removed() -> None:
    """Test that the old .run-graph-3col layout is removed from CSS."""
    css_path = (
        Path(__file__).parent.parent
        / "src"
        / "dag_dashboard"
        / "static"
        / "css"
        / "styles.css"
    )
    content = css_path.read_text()

    # Old three-column layout should be gone
    assert ".run-graph-3col" not in content


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
