"""Tests for conversation REST routes."""
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List

import pytest
from fastapi.testclient import TestClient

from dag_dashboard import session_transcript
from dag_dashboard.database import init_db
from dag_dashboard.queries import (
    insert_conversation,
    insert_run,
    upsert_orchestrator_session,
)
from dag_dashboard.server import create_app


@pytest.fixture
def test_app(tmp_path, monkeypatch):
    """Create test app with test database AND an isolated claude projects root.

    Conversation history now comes from claude session JSONL, not from the
    chat_messages table. Tests stage fixture JSONL files under a tmp
    projects root via ``_stage_session_transcript``.
    """
    db_path = tmp_path / "test.db"
    init_db(db_path)

    projects_root = tmp_path / "projects"
    projects_root.mkdir()
    monkeypatch.setattr(
        session_transcript, "_projects_root", lambda: projects_root
    )

    app = create_app(db_path=db_path, pipe_root=tmp_path / "pipes")
    return TestClient(app), db_path, projects_root


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


def _stage_session(
    projects_root: Path,
    db_path: Path,
    conversation_id: str,
    session_uuid: str,
    turns: List[dict],
) -> None:
    """Register a conversation -> session_uuid mapping AND write the JSONL.

    ``turns`` is a list of {role: "operator"|"agent", content: str, created_at: str}
    shaped like what /chat/history returns; this helper translates each
    back into a claude-format record before writing.
    """
    created_at = turns[0]["created_at"] if turns else datetime.now(timezone.utc).isoformat()
    upsert_orchestrator_session(
        db_path=db_path,
        conversation_id=conversation_id,
        session_uuid=session_uuid,
        last_active=created_at,
        status="alive",
        model="test-model",
        created_at=created_at,
    )
    project_dir = projects_root / "-Users-someone-dev-test"
    project_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for t in turns:
        if t["role"] == "operator":
            records.append({
                "type": "user",
                "message": {"role": "user", "content": t["content"]},
                "timestamp": t["created_at"],
                "sessionId": session_uuid,
            })
        else:
            records.append({
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": t["content"]}],
                },
                "timestamp": t["created_at"],
                "sessionId": session_uuid,
            })
    (project_dir / f"{session_uuid}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in records) + "\n"
    )


def test_conversation_messages_chronological_across_runs(test_app):
    """/api/conversations/{id}/messages returns the full claude transcript.

    Conversations can span multiple runs (continuation). The session JSONL
    is conversation-scoped — claude appends to the same file across
    --resume invocations — so the endpoint surfaces every turn in order
    regardless of which run wrote it.
    """
    client, db_path, projects_root = test_app

    conv_id = "conv-001"
    now = datetime.now(timezone.utc)
    insert_conversation(db_path, conv_id, "test", now.isoformat())
    insert_run(db_path, "run-001", "test-workflow", "completed", (now - timedelta(hours=2)).isoformat())
    insert_run(db_path, "run-002", "test-workflow", "completed", (now - timedelta(hours=1)).isoformat())
    link_run_to_conversation(db_path, "run-001", conv_id)
    link_run_to_conversation(db_path, "run-002", conv_id)

    # Four turns staged across two runs, chronologically ordered in the JSONL.
    turns = [
        {"role": "operator", "content": "Message 1",
         "created_at": (now - timedelta(hours=2, minutes=30)).isoformat()},
        {"role": "agent", "content": "Message 2",
         "created_at": (now - timedelta(hours=2, minutes=20)).isoformat()},
        {"role": "operator", "content": "Message 3",
         "created_at": (now - timedelta(hours=1, minutes=30)).isoformat()},
        {"role": "agent", "content": "Message 4",
         "created_at": (now - timedelta(hours=1, minutes=20)).isoformat()},
    ]
    _stage_session(projects_root, db_path, conv_id, "session-uuid-001", turns)

    response = client.get(f"/api/conversations/{conv_id}/messages")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 4
    assert [m["content"] for m in data] == ["Message 1", "Message 2", "Message 3", "Message 4"]
    # Required UI fields present. "id" and "run_id" are gone — neither is
    # a concept in the claude transcript.
    for msg in data:
        assert "created_at" in msg
        assert "role" in msg
        assert "content" in msg
        assert "session_id" in msg


def test_conversation_messages_identical_content_both_returned(test_app):
    """Two turns with the same text are both surfaced (no dedup-by-content).

    In the transcript-driven architecture there's no "id" to distinguish
    rows, but claude writes distinct records per turn, so both show up in
    order. This used to be framed as a "dedup preserved" check against
    distinct DB ids; same invariant, new mechanism.
    """
    client, db_path, projects_root = test_app

    conv_id = "conv-002"
    now = datetime.now(timezone.utc)
    insert_conversation(db_path, conv_id, "test", now.isoformat())
    insert_run(db_path, "run-003", "test-workflow", "completed", now.isoformat())
    link_run_to_conversation(db_path, "run-003", conv_id)

    turns = [
        {"role": "operator", "content": "Duplicate message",
         "created_at": (now - timedelta(minutes=10)).isoformat()},
        {"role": "operator", "content": "Duplicate message",
         "created_at": (now - timedelta(minutes=9)).isoformat()},
    ]
    _stage_session(projects_root, db_path, conv_id, "session-uuid-002", turns)

    response = client.get(f"/api/conversations/{conv_id}/messages")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert data[0]["content"] == "Duplicate message"
    assert data[1]["content"] == "Duplicate message"


def test_conversation_messages_unknown_returns_404(test_app):
    """GET with unknown conversation ID should return 404."""
    client, db_path, projects_root = test_app

    response = client.get("/api/conversations/nonexistent-conv/messages")
    assert response.status_code == 404


def test_conversation_messages_empty_conversation(test_app):
    """A conversation that hasn't produced any turns yet returns []."""
    client, db_path, projects_root = test_app

    conv_id = "conv-empty"
    now = datetime.now(timezone.utc)
    insert_conversation(db_path, conv_id, "test", now.isoformat())

    response = client.get(f"/api/conversations/{conv_id}/messages")
    assert response.status_code == 200
    assert response.json() == []


def test_conversation_messages_pagination(test_app):
    """limit + offset slice the transcript in chronological order."""
    client, db_path, projects_root = test_app

    conv_id = "conv-paginated"
    now = datetime.now(timezone.utc)
    insert_conversation(db_path, conv_id, "test", now.isoformat())
    insert_run(db_path, "run-page", "test-workflow", "completed", now.isoformat())
    link_run_to_conversation(db_path, "run-page", conv_id)

    turns = [
        {"role": "operator", "content": f"Message {i}",
         "created_at": (now - timedelta(minutes=20 - i)).isoformat()}
        for i in range(20)
    ]
    _stage_session(projects_root, db_path, conv_id, "session-uuid-page", turns)

    response = client.get(f"/api/conversations/{conv_id}/messages?limit=5&offset=5")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 5
    for i, msg in enumerate(data):
        assert msg["content"] == f"Message {5 + i}"
