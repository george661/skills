"""Integration tests for chat panel: POST, SSE broadcast, history, rate-limit."""
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dag_dashboard.database import init_db
from dag_dashboard.queries import insert_run
from dag_dashboard.server import create_app


@pytest.fixture
def client(tmp_path: Path):
    """Create test client with initialized database."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    # Create test runs
    now = datetime.now(timezone.utc).isoformat()
    insert_run(db_path, "test-workflow-001", "test-wf", "running", now)
    insert_run(db_path, "test-workflow-002", "test-wf", "running", now)
    insert_run(db_path, "test-workflow-rate-limit", "test-wf", "running", now)
    insert_run(db_path, "test-workflow-max-length", "test-wf", "running", now)
    insert_run(db_path, "test-workflow-metachar", "test-wf", "running", now)
    insert_run(db_path, "test-workflow-sse", "test-wf", "running", now)
    
    events_dir = tmp_path / "dag-events"
    events_dir.mkdir(exist_ok=True)
    checkpoint_dir = tmp_path / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)
    
    app = create_app(db_path=db_path, events_dir=events_dir, checkpoint_dir_fallback=str(checkpoint_dir))
    return TestClient(app, raise_server_exceptions=True)


def test_post_chat_message_persisted(client: TestClient):
    """Test that posting a chat message persists and returns 201."""
    run_id = "test-workflow-001"
    payload = {
        "content": "Hello from operator",
        "operator_username": "test-operator"
    }
    
    response = client.post(f"/api/workflows/{run_id}/chat", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "id" in data
    assert data["content"] == payload["content"]
    assert data["role"] == "operator"
    
    # Verify it's in history
    history_response = client.get(f"/api/workflows/{run_id}/chat/history")
    assert history_response.status_code == 200
    messages = history_response.json()
    assert len(messages) > 0
    assert any(m["content"] == payload["content"] for m in messages)


def test_chat_history_endpoint(client: TestClient):
    """Test GET chat history returns posted messages."""
    run_id = "test-workflow-002"
    
    # Post 3 messages
    for i in range(3):
        client.post(
            f"/api/workflows/{run_id}/chat",
            json={"content": f"Message {i+1}", "operator_username": "test-op"}
        )
    
    # Fetch history
    response = client.get(f"/api/workflows/{run_id}/chat/history?limit=50")
    assert response.status_code == 200
    messages = response.json()
    assert len(messages) == 3
    # Should be chronological
    assert messages[0]["content"] == "Message 1"
    assert messages[2]["content"] == "Message 3"


def test_chat_rate_limit_429_after_10_messages(client: TestClient):
    """Test that 11th message in 60 seconds returns 429."""
    run_id = "test-workflow-rate-limit"
    
    # Post 10 messages rapidly
    for i in range(10):
        response = client.post(
            f"/api/workflows/{run_id}/chat",
            json={"content": f"Msg {i+1}", "operator_username": "rapid-tester"}
        )
        assert response.status_code == 201, f"Message {i+1} failed"
    
    # 11th should be rate-limited
    response = client.post(
        f"/api/workflows/{run_id}/chat",
        json={"content": "Message 11", "operator_username": "rapid-tester"}
    )
    assert response.status_code == 429


def test_chat_max_content_length_rejected(client: TestClient):
    """Test that content > 10000 chars is rejected."""
    run_id = "test-workflow-max-length"
    long_content = "x" * 10001
    
    response = client.post(
        f"/api/workflows/{run_id}/chat",
        json={"content": long_content, "operator_username": "test-op"}
    )
    assert response.status_code in (400, 422)


def test_chat_shell_punctuation_accepted(client: TestClient):
    """Chat content is persisted to SQLite + sanitized by DOMPurify
    client-side; it is never shell-executed. Natural punctuation — which
    earlier builds rejected — must round-trip so the user can paste error
    messages or variable references when asking the orchestrator for help.
    """
    run_id = "test-workflow-metachar"
    content = "hello; what is ${foo}? (help pls)"

    response = client.post(
        f"/api/workflows/{run_id}/chat",
        json={"content": content, "operator_username": "test-op"}
    )
    assert response.status_code == 201


def test_sse_chat_message_response_shape(client: TestClient):
    """Test that chat POST response has fields ChatPanel expects."""
    run_id = "test-workflow-sse"
    
    response = client.post(
        f"/api/workflows/{run_id}/chat",
        json={"content": "Test SSE", "operator_username": "sse-tester"}
    )
    assert response.status_code == 201
    
    # Verify the response has fields ChatPanel needs
    data = response.json()
    required_fields = ["id", "content", "role", "created_at", "operator_username"]
    for field in required_fields:
        assert field in data, f"Missing field: {field}"
    
    # The broadcaster will emit this shape — chat_routes.py handles the SSE broadcast


def _run_event_to_messages_with_sequence(events_json: str) -> list:
    """Execute event-to-messages.js against a sequence of events via Node.

    Returns the flat list of feed messages produced. Shells out to `node` so
    the test exercises the real JavaScript, not a string grep.
    """
    import json
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not available")

    static_dir = Path(__file__).parent.parent / "src" / "dag_dashboard" / "static" / "js"
    script = f"""
const window = {{}};
const src = require('fs').readFileSync({json.dumps(str(static_dir / "event-to-messages.js"))}, 'utf8');
new Function('window', src)(window);
const state = window.EventToMessages.createState();
const events = {events_json};
const out = [];
for (const ev of events) {{
    const msgs = window.EventToMessages.eventToMessages(ev, state);
    for (const m of msgs) {{
        const entry = {{type: m.type}};
        if (m.subtype !== undefined) entry.subtype = m.subtype;
        if (m.nodeId !== undefined) entry.nodeId = m.nodeId;
        if (m.status !== undefined) entry.status = m.status;
        out.push(entry);
    }}
}}
process.stdout.write(JSON.stringify(out));
"""
    result = subprocess.run(
        [node, "-e", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def test_event_to_messages_folds_channel_write_in_order():
    """node_started then channel_updated emits two progress_card messages for the owning node."""
    import json
    events = [
        {"event_type": "node_started", "node_id": "n1", "metadata": {}},
        {"event_type": "channel_updated", "node_id": "n1",
         "metadata": {"writer_node_id": "n1", "channel_key": "seed", "value": "v1"}},
    ]
    out = _run_event_to_messages_with_sequence(json.dumps(events))
    assert out == [
        {"type": "progress_card", "subtype": "node_started", "nodeId": "n1"},
        {"type": "progress_card", "subtype": "channel_updated", "nodeId": "n1"},
    ]


def test_event_to_messages_buffers_out_of_order_channel_write():
    """channel_updated before node_started is buffered; flushed on the owning node_started."""
    import json
    events = [
        # channel_updated arrives first (SSE reconnect backfill)
        {"event_type": "channel_updated", "node_id": None,
         "metadata": {"writer_node_id": "n2", "channel_key": "cls", "value": "v2"}},
        # then node_started for that node — buffered write should flush here
        {"event_type": "node_started", "node_id": "n2", "metadata": {}},
    ]
    out = _run_event_to_messages_with_sequence(json.dumps(events))
    # Expected: nothing emitted for the orphan channel_updated, then both
    # messages emitted when node_started arrives (node_started + folded channel)
    assert out == [
        {"type": "progress_card", "subtype": "node_started", "nodeId": "n2"},
        {"type": "progress_card", "subtype": "channel_updated", "nodeId": "n2"},
    ]


def test_event_to_messages_emits_terminal_for_workflow_end():
    import json
    events = [{"event_type": "workflow_completed", "metadata": {}}]
    out = _run_event_to_messages_with_sequence(json.dumps(events))
    assert out == [{"type": "terminal", "status": "completed"}]


def test_event_to_messages_suppresses_retry_node_progress():
    """node_progress with an attempt counter is handled by the DAG retry overlay,
    not the feed, so it must not produce a progress_card message."""
    import json
    events = [
        {"event_type": "node_started", "node_id": "n3", "metadata": {}},
        # Retry-shaped node_progress — handled separately by setupLiveUpdates
        {"event_type": "node_progress", "node_id": "n3",
         "metadata": {"attempt": 1, "max_attempts": 3}},
    ]
    out = _run_event_to_messages_with_sequence(json.dumps(events))
    assert out == [
        {"type": "progress_card", "subtype": "node_started", "nodeId": "n3"},
    ]
