"""GW-5423 AC-7: chat input lock while a prompt node is executing.

Static tests — assert chat-panel.js carries the lock methods, derives the
chat-blocking node set from layout node_type === 'prompt', and the consolidated
styles.css carries the locked-state styles + the exact "Agent is thinking…"
indicator copy.
"""
from pathlib import Path

STATIC_DIR = Path(__file__).parents[1] / "src" / "dag_dashboard" / "static"


def test_chat_panel_has_lock_api() -> None:
    """ChatPanel must expose setInputLocked / setInputUnlocked / setLifecycle."""
    js = (STATIC_DIR / "js" / "chat-panel.js").read_text()
    assert "setInputLocked" in js
    assert "setInputUnlocked" in js
    assert "setLifecycle" in js


def test_chat_panel_builds_blocking_set_from_node_type() -> None:
    """Lock is seeded off node type === 'prompt', not the dispatch field."""
    js = (STATIC_DIR / "js" / "chat-panel.js").read_text()
    assert "chatBlockingNodeIds" in js
    assert "'prompt'" in js
    # Must read from layout node shape (node_data.type) with fallback.
    assert "node_data" in js and "node_type" in js


def test_chat_panel_locks_on_node_started_and_unlocks_on_terminal() -> None:
    """handleWorkflowEvent must drive the lock off node + workflow lifecycle events."""
    js = (STATIC_DIR / "js" / "chat-panel.js").read_text()
    assert "_applyChatLockFromEvent" in js
    # Lock on node_started when blocking
    assert "'node_started'" in js
    # Unlock on any node terminal event
    for ev in ("node_completed", "node_failed", "node_escalated"):
        assert f"'{ev}'" in js, f"Must unlock on {ev}"
    # Unconditional unlock on workflow terminal
    for ev in ("workflow_completed", "workflow_failed", "workflow_cancelled"):
        assert f"'{ev}'" in js, f"Must unlock on {ev}"


def test_chat_panel_passes_nodes_into_constructor() -> None:
    """app.js must forward layoutData.nodes into the ChatPanel constructor."""
    js = (STATIC_DIR / "js" / "app.js").read_text()
    assert "new window.ChatPanel" in js
    # The construction path now uses the options object with nodes.
    assert "layoutData.nodes" in js
    assert "nodes:" in js or "nodes :" in js


def test_styles_css_has_lock_state() -> None:
    """Consolidated styles.css must carry the lock state + indicator styles."""
    styles = (STATIC_DIR / "css" / "styles.css").read_text()
    assert ".chat-input-form--locked" in styles
    assert ".chat-input-lock-indicator" in styles


def test_chat_panel_indicator_copy_is_exact() -> None:
    """Parent AC-7 requires the exact string 'Agent is thinking…'."""
    js = (STATIC_DIR / "js" / "chat-panel.js").read_text()
    assert "Agent is thinking…" in js, "Indicator must use the exact AC-7 copy"
