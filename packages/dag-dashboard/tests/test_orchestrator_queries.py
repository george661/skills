"""Tests for orchestrator_sessions query helpers."""
import pytest
from pathlib import Path
from datetime import datetime, timezone
from dag_dashboard.database import init_db
from dag_dashboard.queries import (
    upsert_orchestrator_session,
    get_orchestrator_session,
    delete_orchestrator_session,
)


def test_upsert_orchestrator_session_insert(tmp_path: Path):
    """Test inserting a new orchestrator session."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    now = datetime.now(timezone.utc).isoformat()
    upsert_orchestrator_session(
        db_path=db_path,
        conversation_id="conv-123",
        session_uuid="sess-abc",
        last_active=now,
        status="alive",
        model="claude-opus-4-7",
        created_at=now,
    )
    
    session = get_orchestrator_session(db_path, "conv-123")
    assert session is not None
    assert session["conversation_id"] == "conv-123"
    assert session["session_uuid"] == "sess-abc"
    assert session["status"] == "alive"
    assert session["model"] == "claude-opus-4-7"


def test_upsert_orchestrator_session_update(tmp_path: Path):
    """Test updating an existing orchestrator session."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    now = datetime.now(timezone.utc).isoformat()
    upsert_orchestrator_session(
        db_path=db_path,
        conversation_id="conv-123",
        session_uuid="sess-abc",
        last_active=now,
        status="alive",
        model="claude-opus-4-7",
        created_at=now,
    )
    
    # Update status
    later = datetime.now(timezone.utc).isoformat()
    upsert_orchestrator_session(
        db_path=db_path,
        conversation_id="conv-123",
        session_uuid="sess-abc",
        last_active=later,
        status="idle",
        model="claude-opus-4-7",
        created_at=now,
    )
    
    session = get_orchestrator_session(db_path, "conv-123")
    assert session is not None
    assert session["status"] == "idle"
    assert session["last_active"] == later


def test_get_orchestrator_session_not_found(tmp_path: Path):
    """Test getting a non-existent session returns None."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    session = get_orchestrator_session(db_path, "conv-nonexistent")
    assert session is None


def test_delete_orchestrator_session(tmp_path: Path):
    """Test deleting an orchestrator session."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    
    now = datetime.now(timezone.utc).isoformat()
    upsert_orchestrator_session(
        db_path=db_path,
        conversation_id="conv-123",
        session_uuid="sess-abc",
        last_active=now,
        status="alive",
        model="claude-opus-4-7",
        created_at=now,
    )
    
    # Verify exists
    session = get_orchestrator_session(db_path, "conv-123")
    assert session is not None
    
    # Delete
    delete_orchestrator_session(db_path, "conv-123")
    
    # Verify deleted
    session = get_orchestrator_session(db_path, "conv-123")
    assert session is None
