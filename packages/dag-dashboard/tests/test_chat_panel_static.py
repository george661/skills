"""Test that chat panel static assets are served correctly."""
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from dag_dashboard.database import init_db
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path):
    """Create a test client with initialized database."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    events_dir = tmp_path / "dag-events"
    events_dir.mkdir(exist_ok=True)
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    app = create_app(db_path=db_path, events_dir=events_dir, checkpoint_dir_fallback=str(checkpoint_dir))
    return TestClient(app, raise_server_exceptions=True)


def test_chat_panel_js_served(client: TestClient):
    """Test that chat-panel.js is served."""
    response = client.get("/js/chat-panel.js")
    assert response.status_code == 200
    assert "class ChatPanel" in response.text
    assert "handleSSEMessage" in response.text


def test_marked_vendor_js_served(client: TestClient):
    """Test that marked.min.js vendor library is served."""
    response = client.get("/js/vendor/marked.min.js")
    assert response.status_code == 200
    # marked lib should have its signature
    assert "marked" in response.text.lower() or "markdown" in response.text.lower()


def test_dompurify_vendor_js_served(client: TestClient):
    """Test that dompurify.min.js vendor library is served."""
    response = client.get("/js/vendor/dompurify.min.js")
    assert response.status_code == 200
    # DOMPurify should have its signature
    assert "DOMPurify" in response.text or "purify" in response.text.lower()


def test_index_includes_chat_scripts(client: TestClient):
    """Test that index.html includes chat scripts in correct order."""
    response = client.get("/")
    assert response.status_code == 200
    html = response.text

    # Check all scripts are present
    assert "/js/vendor/dompurify.min.js" in html
    assert "/js/vendor/marked.min.js" in html
    assert "/js/chat-panel.js" in html

    # Verify order: dompurify before marked, marked before chat-panel, chat-panel before app.js
    dompurify_pos = html.find("/js/vendor/dompurify.min.js")
    marked_pos = html.find("/js/vendor/marked.min.js")
    chat_panel_pos = html.find("/js/chat-panel.js")
    app_js_pos = html.find("/js/app.js")

    assert dompurify_pos < marked_pos < chat_panel_pos < app_js_pos, \
        "Scripts must be in order: dompurify.min.js, marked.min.js, chat-panel.js, app.js"


def test_chat_panel_has_loadhistory(client: TestClient):
    """Test that chat-panel.js includes _loadHistory method."""
    response = client.get("/js/chat-panel.js")
    assert response.status_code == 200
    assert "_loadHistory" in response.text


def test_chat_panel_supports_conversation_mode(client: TestClient):
    """Test that chat-panel.js contains conversation mode strings."""
    response = client.get("/js/chat-panel.js")
    assert response.status_code == 200
    # Check for conversation-related strings
    assert "conversationId" in response.text
    assert "/api/conversations/" in response.text


def test_conversation_mode_disables_send(client: TestClient):
    """Test that chat-panel.js disables send form in conversation mode."""
    response = client.get("/js/chat-panel.js")
    assert response.status_code == 200
    # Check for read-only indicator
    assert "conversation" in response.text.lower()
    # Should have logic to disable/hide send form
    assert "mode" in response.text


def test_app_js_registers_conversation_route(client: TestClient):
    """Test that app.js registers /conversations/ route."""
    response = client.get("/js/app.js")
    assert response.status_code == 200
    assert "/conversations/" in response.text


def test_index_includes_new_unified_feed_scripts(client: TestClient):
    """New GW-5422 modules must be served AND load before chat-panel.js and app.js.

    ChatPanel reads window.EventToMessages and window.WorkflowProgressCard
    at render time, so they must load first. NodeScrollBus is consulted by
    both ChatPanel (subscribe) and app.js (trigger), so it must precede both.
    StateSlideover is consumed only by app.js, so it just has to precede app.js.
    """
    html = client.get("/").text

    assert "/js/node-scroll-bus.js" in html
    assert "/js/event-to-messages.js" in html
    assert "/js/workflow-progress-card.js" in html
    assert "/js/state-slideover.js" in html

    bus_pos = html.find("/js/node-scroll-bus.js")
    events_pos = html.find("/js/event-to-messages.js")
    card_pos = html.find("/js/workflow-progress-card.js")
    slideover_pos = html.find("/js/state-slideover.js")
    chat_pos = html.find("/js/chat-panel.js")
    app_pos = html.find("/js/app.js")

    assert bus_pos < chat_pos, "node-scroll-bus.js must load before chat-panel.js"
    assert events_pos < chat_pos, "event-to-messages.js must load before chat-panel.js"
    assert card_pos < chat_pos, "workflow-progress-card.js must load before chat-panel.js"
    assert slideover_pos < app_pos, "state-slideover.js must load before app.js"


def test_trace_panel_script_tag_removed(client: TestClient):
    """trace-panel.js must not be referenced from index.html (file is deleted)."""
    html = client.get("/").text
    assert "/js/trace-panel.js" not in html


def test_workflow_progress_card_js_served(client: TestClient):
    """workflow-progress-card.js exposes the per-node card class with full lifecycle."""
    text = client.get("/js/workflow-progress-card.js").text
    assert "class WorkflowProgressCard" in text
    # Public API the ChatPanel relies on
    assert "handleEvent" in text
    assert "mount" in text
    assert "destroy" in text
    assert "scrollIntoViewAndFlash" in text
    # Resume form (inline for escalation + interrupt) must be present
    assert "_appendResumeForm" in text
    assert "/interrupts/" in text, "Must POST to the existing interrupts/resume endpoint"
    # Status variants
    for subtype in ("node_started", "node_log_line", "node_stream_token",
                    "channel_updated", "node_completed", "node_failed",
                    "node_escalated", "node_interrupted"):
        assert subtype in text, f"handleEvent must dispatch subtype {subtype}"


def test_event_to_messages_js_served(client: TestClient):
    """event-to-messages.js exports EventToMessages with buffering state."""
    text = client.get("/js/event-to-messages.js").text
    assert "window.EventToMessages" in text
    assert "createState" in text
    assert "eventToMessages" in text
    assert "pendingChannels" in text
    # Correct backend event name — channel_updated (not channel_write)
    assert "'channel_updated'" in text
    # Fold semantic: channel writes route by writer_node_id
    assert "writer_node_id" in text


def test_node_scroll_bus_js_served(client: TestClient):
    """NodeScrollBus is a source-tagged pub/sub module (not a class)."""
    text = client.get("/js/node-scroll-bus.js").text
    assert "window.NodeScrollBus" in text
    assert "trigger" in text
    assert "subscribe" in text
    assert "unsubscribe" in text
    assert "clear" in text


def test_state_slideover_js_served(client: TestClient):
    """StateSlideover eager-mounts the three state containers and handles Esc."""
    text = client.get("/js/state-slideover.js").text
    assert "window.StateSlideover" in text
    assert "mount" in text
    assert "state-slideover--closed" in text
    # Eager-mount: the three ids live inside the slide-over DOM
    for cid in ("channel-state-container", "state-diff-timeline-container",
                "run-artifacts-container"):
        assert f'id="{cid}"' in text, f"{cid} must be inside state-slideover DOM"
    # Esc + backdrop close handlers
    assert "Escape" in text
    assert "backdrop" in text.lower()


def test_chat_panel_supports_run_mode_workflow_events(client: TestClient):
    """ChatPanel.handleWorkflowEvent is the entry point for SSE workflow events."""
    text = client.get("/js/chat-panel.js").text
    assert "handleWorkflowEvent" in text, \
        "ChatPanel must expose handleWorkflowEvent for SSE workflow events"
    # Run mode dispatches to WorkflowProgressCard per node
    assert "WorkflowProgressCard" in text
    # Conversation mode filters out progress_card / terminal types
    assert "'conversation'" in text
    assert "user" in text and "agent" in text
    # mode constructor option
    assert "this.mode" in text
    # Per-node card map + lifecycle cascade
    assert "this.cards" in text
    assert "card.destroy" in text


def test_chat_panel_filters_progress_cards_in_conversation_mode(client: TestClient):
    """Conversation mode must NOT render progress_card / terminal messages."""
    text = client.get("/js/chat-panel.js").text
    # There should be a guard in renderMessage that drops non-chat types in
    # conversation mode. Grep for the comment or logic.
    assert "conversation" in text.lower()
    assert "progress_card" in text, \
        "renderMessage must mention progress_card type to filter it"
