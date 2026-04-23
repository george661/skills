"""Tests for conversation REST routes."""
from datetime import datetime, timezone, timedelta
import sqlite3

import pytest
from fastapi.testclient import TestClient

from dag_dashboard.server import create_app
from dag_dashboard.database import init_db
from dag_dashboard.queries import insert_run, insert_conversation, insert_chat_message


@pytest.fixture
def test_app(tmp_path):
    """Create test app with test database."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    app = create_app(db_path=db_path, pipe_root=tmp_path / "pipes")
    return TestClient(app), db_path


def link_run_to_conversation(db_path, run_id: str, conversation_id: str):
    """Helper to link a run to a conversation."""
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "UPDATE workflow_runs SET conversation_id = ? WHERE id = ?",
            (conversation_id, run_id)
        )
        conn.commit()
    finally:
        conn.close()


def test_conversation_messages_chronological_across_runs(test_app):
    """GET /api/conversations/{id}/messages should return messages in chronological order across runs."""
    client, db_path = test_app
    
    # Seed conversation
    conv_id = "conv-001"
    now = datetime.now(timezone.utc)
    insert_conversation(db_path, conv_id, "test", now.isoformat())
    
    # Seed two runs linked to this conversation
    run1_time = now - timedelta(hours=2)
    run2_time = now - timedelta(hours=1)
    insert_run(db_path, "run-001", "test-workflow", "completed", run1_time.isoformat())
    insert_run(db_path, "run-002", "test-workflow", "completed", run2_time.isoformat())
    link_run_to_conversation(db_path, "run-001", conv_id)
    link_run_to_conversation(db_path, "run-002", conv_id)
    
    # Insert 4 messages with staggered created_at across both runs
    msg1_time = now - timedelta(hours=2, minutes=30)
    msg2_time = now - timedelta(hours=2, minutes=20)
    msg3_time = now - timedelta(hours=1, minutes=30)
    msg4_time = now - timedelta(hours=1, minutes=20)
    
    insert_chat_message(db_path, execution_id=None, role="user", content="Message 1", created_at=msg1_time.isoformat(), run_id="run-001", conversation_id=conv_id)
    insert_chat_message(db_path, execution_id=None, role="assistant", content="Message 2", created_at=msg2_time.isoformat(), run_id="run-001", conversation_id=conv_id)
    insert_chat_message(db_path, execution_id=None, role="user", content="Message 3", created_at=msg3_time.isoformat(), run_id="run-002", conversation_id=conv_id)
    insert_chat_message(db_path, execution_id=None, role="assistant", content="Message 4", created_at=msg4_time.isoformat(), run_id="run-002", conversation_id=conv_id)
    
    # Request messages
    response = client.get(f"/api/conversations/{conv_id}/messages")
    assert response.status_code == 200
    
    data = response.json()
    assert len(data) == 4
    
    # Verify chronological order
    assert data[0]["content"] == "Message 1"
    assert data[1]["content"] == "Message 2"
    assert data[2]["content"] == "Message 3"
    assert data[3]["content"] == "Message 4"
    
    # Verify each message has required fields
    for msg in data:
        assert "id" in msg
        assert "run_id" in msg
        assert "conversation_id" in msg
        assert msg["conversation_id"] == conv_id
        assert "created_at" in msg
        assert "role" in msg
        assert "content" in msg


def test_conversation_messages_dedup_preserved(test_app):
    """Messages with identical content but distinct IDs should both be returned."""
    client, db_path = test_app
    
    conv_id = "conv-002"
    now = datetime.now(timezone.utc)
    insert_conversation(db_path, conv_id, "test", now.isoformat())
    insert_run(db_path, "run-003", "test-workflow", "completed", now.isoformat())
    link_run_to_conversation(db_path, "run-003", conv_id)
    
    # Insert two messages with identical content
    msg_time = now - timedelta(minutes=10)
    insert_chat_message(db_path, execution_id=None, role="user", content="Duplicate message", created_at=msg_time.isoformat(), run_id="run-003", conversation_id=conv_id)
    insert_chat_message(db_path, execution_id=None, role="user", content="Duplicate message", created_at=msg_time.isoformat(), run_id="run-003", conversation_id=conv_id)
    
    response = client.get(f"/api/conversations/{conv_id}/messages")
    assert response.status_code == 200
    
    data = response.json()
    assert len(data) == 2
    
    # Verify distinct IDs
    ids = [msg["id"] for msg in data]
    assert len(ids) == len(set(ids)), "IDs should be distinct"
    assert data[0]["content"] == "Duplicate message"
    assert data[1]["content"] == "Duplicate message"


def test_conversation_messages_unknown_returns_404(test_app):
    """GET with unknown conversation ID should return 404."""
    client, db_path = test_app
    
    response = client.get("/api/conversations/nonexistent-conv/messages")
    assert response.status_code == 404


def test_conversation_messages_empty_conversation(test_app):
    """Fresh conversation with zero messages should return 200 and empty list."""
    client, db_path = test_app
    
    conv_id = "conv-empty"
    now = datetime.now(timezone.utc)
    insert_conversation(db_path, conv_id, "test", now.isoformat())
    
    response = client.get(f"/api/conversations/{conv_id}/messages")
    assert response.status_code == 200
    
    data = response.json()
    assert data == []


def test_conversation_messages_pagination(test_app):
    """Pagination with limit and offset should return correct slice in chronological order."""
    client, db_path = test_app
    
    conv_id = "conv-paginated"
    now = datetime.now(timezone.utc)
    insert_conversation(db_path, conv_id, "test", now.isoformat())
    insert_run(db_path, "run-page", "test-workflow", "completed", now.isoformat())
    link_run_to_conversation(db_path, "run-page", conv_id)
    
    # Insert 20 messages
    for i in range(20):
        msg_time = now - timedelta(minutes=20-i)
        insert_chat_message(
            db_path,
            execution_id=None,
            role="user",
            content=f"Message {i}",
            created_at=msg_time.isoformat(),
            run_id="run-page",
            conversation_id=conv_id
        )
    
    # Request with offset=5, limit=5
    response = client.get(f"/api/conversations/{conv_id}/messages?limit=5&offset=5")
    assert response.status_code == 200
    
    data = response.json()
    assert len(data) == 5
    
    # Verify correct slice (messages 5-9)
    for i, msg in enumerate(data):
        assert msg["content"] == f"Message {5+i}"
