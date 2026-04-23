"""Smoke tests for conversation CLI subcommand."""
import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from dag_executor.conversation_cli import run_conversation


def test_conversation_append_smoke(tmp_path: Path) -> None:
    """Smoke test: dag-exec conversation append writes message and event.

    Verifies:
    - Row is inserted into chat_messages with supplied fields
    - Canonical conversation_message_appended event is written
    - Exits 0 (pytest raises SystemExit on success)
    """
    # Setup test database with proper schema
    from dag_dashboard.database import init_db
    db_path = tmp_path / "test.db"
    init_db(db_path)

    # Create workflow run for foreign key constraint
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO workflow_runs (id, workflow_name, status, started_at, conversation_id)
        VALUES ('run-789', 'test-workflow', 'running', datetime('now'), 'conv-123')
    """)
    conn.commit()
    conn.close()

    # Setup events directory
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    
    # Run append command
    argv = [
        'append',
        '--db', str(db_path),
        '--conversation-id', 'conv-123',
        '--session-id', 'sess-456',
        '--role', 'user',
        '--content', 'Test message content',
        '--run-id', 'run-789',
        '--node-id', 'test-node',
        '--events-dir', str(events_dir),
        '--transition-reason', 'fresh-context',
        '--parent-session-id', 'sess-old',
    ]
    
    with pytest.raises(SystemExit) as exc_info:
        run_conversation(argv)
    
    assert exc_info.value.code == 0, "Expected exit code 0"
    
    # Verify message was inserted into database
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT conversation_id, session_id, role, content, run_id FROM chat_messages"
    )
    rows = cursor.fetchall()
    conn.close()
    
    assert len(rows) == 1, f"Expected 1 message, got {len(rows)}"
    conv_id, sess_id, role, content, run_id = rows[0]
    assert conv_id == 'conv-123'
    assert sess_id == 'sess-456'
    assert role == 'user'
    assert content == 'Test message content'
    assert run_id == 'run-789'
    
    # Verify event was written
    event_file = events_dir / "run-789.ndjson"
    assert event_file.exists(), f"Event file not found: {event_file}"
    
    event_line = event_file.read_text().strip()
    event = json.loads(event_line)
    
    # Verify canonical event structure
    assert event["event_type"] == "conversation_message_appended"
    payload = event["payload"]
    assert payload["run_id"] == "run-789"
    assert payload["node_id"] == "test-node"
    assert payload["conversation_id"] == "conv-123"
    assert payload["session_id"] == "sess-456"
    assert payload["role"] == "user"
    assert isinstance(payload["message_id"], int)
    assert payload["transition_reason"] == "fresh-context"
    assert payload["parent_session_id"] == "sess-old"
    assert "created_at" in event  # Timestamp at event level, not in payload


def test_conversation_append_missing_db() -> None:
    """Verify append exits 1 when database doesn't exist."""
    argv = [
        'append',
        '--db', '/nonexistent/test.db',
        '--conversation-id', 'conv-123',
        '--session-id', 'sess-456',
        '--role', 'user',
        '--content', 'Test',
    ]
    
    with pytest.raises(SystemExit) as exc_info:
        run_conversation(argv)
    
    assert exc_info.value.code == 1, "Expected exit code 1 for missing database"


def test_conversation_append_without_events_dir(tmp_path: Path) -> None:
    """Verify append works without --events-dir (no event written)."""
    from dag_dashboard.database import init_db
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    argv = [
        'append',
        '--db', str(db_path),
        '--conversation-id', 'conv-123',
        '--session-id', 'sess-456',
        '--role', 'assistant',
        '--content', 'Response text',
    ]
    
    with pytest.raises(SystemExit) as exc_info:
        run_conversation(argv)
    
    assert exc_info.value.code == 0
    
    # Verify message was still inserted
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT role, content FROM chat_messages")
    rows = cursor.fetchall()
    conn.close()
    
    assert len(rows) == 1
    assert rows[0] == ('assistant', 'Response text')
