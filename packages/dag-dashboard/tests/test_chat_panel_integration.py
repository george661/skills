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
