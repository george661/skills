"""GW-5423 AC-5: step-logs + workflow-progress-card virtualization + jump-to-bottom.

Static tests — assert the runtime JS contains the required wiring and the
shared virtualizer module is loaded before the consumers that use it.
"""
from pathlib import Path

STATIC_DIR = Path(__file__).parents[1] / "src" / "dag_dashboard" / "static"


def test_virtualized_log_list_module_exists() -> None:
    """The shared windowing helper must exist and expose a window-level class."""
    js_path = STATIC_DIR / "js" / "virtualized-log-list.js"
    assert js_path.exists(), "virtualized-log-list.js must exist (GW-5423 AC-5)"
    js = js_path.read_text()
    assert "class VirtualizedLogList" in js
    assert "window.VirtualizedLogList" in js


def test_index_html_loads_virtualizer_before_consumers() -> None:
    """virtualized-log-list.js must load before step-logs.js and workflow-progress-card.js."""
    html = (STATIC_DIR / "index.html").read_text()
    v_idx = html.find("virtualized-log-list.js")
    sl_idx = html.find("step-logs.js")
    wpc_idx = html.find("workflow-progress-card.js")
    assert v_idx != -1, "virtualized-log-list.js must be linked in index.html"
    assert sl_idx != -1 and wpc_idx != -1
    assert v_idx < sl_idx, "virtualizer must load before step-logs.js"
    assert v_idx < wpc_idx, "virtualizer must load before workflow-progress-card.js"


def test_step_logs_uses_virtualizer_above_threshold() -> None:
    """step-logs.js must route lines through VirtualizedLogList above the threshold."""
    js = (STATIC_DIR / "js" / "step-logs.js").read_text()
    # Threshold is declared as a class field so the test can verify the
    # promoted path exists.
    assert "VIRTUALIZE_THRESHOLD = 200" in js, "Threshold (200) must be declared"
    assert "window.VirtualizedLogList" in js, "step-logs must reference the shared module"
    assert "VirtualizedLogList(" in js, "step-logs must instantiate the virtualizer"


def test_step_logs_has_jump_to_bottom_button() -> None:
    """step-logs.js must render the Jump-to-bottom button and toggle it on scroll."""
    js = (STATIC_DIR / "js" / "step-logs.js").read_text()
    assert "step-logs-jump-bottom" in js, "Jump-to-bottom button class must be present"
    assert "Jump to bottom" in js, "Button copy must be present"
    # The button hides when near the tail; verify the toggle exists.
    assert "_updateJumpButton" in js


def test_workflow_progress_card_virtualizes_log_lines() -> None:
    """workflow-progress-card.js must promote to virtualized rendering above threshold."""
    js = (STATIC_DIR / "js" / "workflow-progress-card.js").read_text()
    assert "VIRTUALIZE_THRESHOLD = 200" in js
    assert "_promoteToVirtualized" in js
    assert "window.VirtualizedLogList" in js


def test_styles_css_has_jump_to_bottom_and_virtualizer_styles() -> None:
    """The consolidated styles.css must carry the new UI styles (GW-5423 v2 plan)."""
    styles = (STATIC_DIR / "css" / "styles.css").read_text()
    assert ".step-logs-jump-bottom" in styles, "Jump button must be styled"
    assert ".virtualized-log-list" in styles, "Virtualizer container must be styled"
