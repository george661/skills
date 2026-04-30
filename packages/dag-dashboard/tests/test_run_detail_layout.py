"""Test unified feed layout (GW-5422).

These assertions protect the two-pane shape, the deletion of TracePanel /
old 3-column scaffolding, and the wiring of the new WorkflowProgressCard +
StateSlideover + NodeScrollBus + unified ChatPanel feed.
"""
from pathlib import Path


STATIC = Path(__file__).parents[1] / "src" / "dag_dashboard" / "static"
APP_JS = (STATIC / "js" / "app.js").read_text
INDEX = (STATIC / "index.html").read_text
STYLES = (STATIC / "css" / "styles.css").read_text


def test_two_pane_split_layout_exists() -> None:
    """app.js must render a .run-pane-split with .run-split-left-content + .run-split-right-content."""
    content = APP_JS()
    assert '"run-pane-split"' in content, "run-pane-split wrapper must be present"
    assert "run-split-left-content" in content, "Left inner content wrapper must exist"
    assert "run-split-right-content" in content, "Right inner content wrapper must exist"
    assert 'querySelector(\'.run-pane-split\')' in content, \
        "ResizableSplit must target .run-pane-split"


def test_old_three_column_layout_removed_from_app_js() -> None:
    content = APP_JS()
    for cls in (".run-graph-3col", ".run-graph-canvas", ".run-graph-side",
                ".run-graph-chat", "id=\"run-chat-section\"",
                "id=\"workflow-chat-container\"", "id=\"trace-container\""):
        assert cls not in content, f"{cls} must no longer appear in app.js"


def test_old_three_column_layout_removed_from_css() -> None:
    content = STYLES()
    for cls in (".run-graph-3col", ".run-graph-canvas", ".run-graph-side",
                ".run-graph-chat", ".run-chat-section", ".chat-section-rail",
                ".trace-section-rail", ".workflow-chat-container"):
        assert cls not in content, f"{cls} CSS rule must be deleted"


def test_trace_panel_deleted() -> None:
    """trace-panel.js must be deleted and no script tag should reference it."""
    assert not (STATIC / "js" / "trace-panel.js").exists(), \
        "trace-panel.js must be deleted from disk"
    html = INDEX()
    assert "/js/trace-panel.js" not in html, \
        "trace-panel.js script tag must be removed from index.html"
    app_js = APP_JS()
    assert "window.TracePanel" not in app_js, \
        "app.js must not reference window.TracePanel"
    assert "new window.TracePanel" not in app_js, \
        "app.js must not instantiate TracePanel"


def test_trace_css_rules_all_deleted() -> None:
    """No .trace-* CSS rule should remain after the TracePanel sunset."""
    content = STYLES()
    # Grep for any '.trace-' rule selector at the start of a line.
    trace_rule_lines = [
        line for line in content.splitlines()
        if line.lstrip().startswith(".trace-")
    ]
    assert not trace_rule_lines, \
        f"Expected zero .trace-* CSS rules, found {len(trace_rule_lines)}: {trace_rule_lines[:3]}"


def test_workflow_feed_mount_exists() -> None:
    """The right pane must mount a single #workflow-feed that ChatPanel owns."""
    content = APP_JS()
    assert 'id="workflow-feed"' in content, \
        "Right pane must contain #workflow-feed (single unified feed mount)"
    assert "new window.ChatPanel('workflow-feed'" in content, \
        "ChatPanel must be instantiated on #workflow-feed in run mode"


def test_state_slideover_mounted() -> None:
    content = APP_JS()
    assert "window.StateSlideover.mount" in content, \
        "StateSlideover.mount must be called in renderRunDetail"
    assert "state-slideover-mount" in content, \
        "StateSlideover mount point must exist"
    assert 'id="state-slideover-toggle"' in content, \
        "State toggle button must exist in the left pane"


def test_node_scroll_bus_wired_both_ways() -> None:
    """DAG→feed and feed→DAG cross-selection must both be wired in app.js."""
    content = APP_JS()
    # DAG→feed: DAG click handler calls NodeScrollBus.trigger with source='dag'.
    assert "NodeScrollBus.trigger" in content and "'dag'" in content, \
        "DAG click must trigger NodeScrollBus with source='dag'"
    # feed→DAG: subscriber flashes DAG nodes on card-origin triggers.
    assert "NodeScrollBus.subscribe" in content, \
        "Feed→DAG handler must subscribe to NodeScrollBus"


def test_lifecycle_cleans_up_new_components() -> None:
    """lifecycle.destroy must tear down every new component (no timer/subscription leaks)."""
    content = APP_JS()
    assert "chatPanel.destroy" in content, "ChatPanel.destroy must be called in lifecycle"
    assert "StateSlideover.destroy" in content, "StateSlideover.destroy must be called in lifecycle"
    assert "NodeScrollBus.clear" in content, "NodeScrollBus subscribers must be cleared in lifecycle"
    # Keep PR #156's guarantees
    assert "resizableSplit" in content and "destroy()" in content
    assert "cancelAnimationFrame" in content and "animationId" in content


def test_new_scripts_loaded_in_order() -> None:
    """New JS modules must load before chat-panel.js (EventToMessages, NodeScrollBus,
    WorkflowProgressCard are all used from ChatPanel)."""
    content = INDEX()
    for src in ("/js/node-scroll-bus.js", "/js/event-to-messages.js",
                "/js/workflow-progress-card.js", "/js/state-slideover.js"):
        assert src in content, f"{src} must be included"

    chat_idx = content.index("/js/chat-panel.js")
    app_idx = content.index("/js/app.js")
    for src in ("/js/node-scroll-bus.js", "/js/event-to-messages.js",
                "/js/workflow-progress-card.js"):
        assert content.index(src) < chat_idx, \
            f"{src} must load before chat-panel.js (ChatPanel uses it at instantiation time)"
    assert content.index("/js/state-slideover.js") < app_idx, \
        "state-slideover.js must load before app.js"
    assert content.index("/js/resizable-split.js") < app_idx, \
        "resizable-split.js must load before app.js"


def test_unified_feed_css_classes_exist() -> None:
    content = STYLES()
    for cls in (".run-pane-split", ".workflow-feed", ".workflow-progress-card",
                ".workflow-progress-card-head", ".workflow-progress-card-body",
                ".workflow-progress-card--running", ".workflow-progress-card--completed",
                ".workflow-progress-card--escalated", ".workflow-progress-card--interrupted",
                ".state-slideover", ".state-slideover-panel", ".state-slideover--closed",
                ".chat-terminal-banner"):
        assert cls in content, f"Expected CSS rule {cls} to exist"


def test_lifecycle_has_destroy_method() -> None:
    """Preserve PR #156's AC-8 guarantee."""
    content = APP_JS()
    assert "lifecycle" in content and "destroy:" in content
