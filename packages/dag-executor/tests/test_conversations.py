"""Tests for conversation and session management service layer."""
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
import pytest
from dag_executor.conversations import (
    start_conversation,
    close_conversation,
    get_conversation,
    mint_session,
    transition_session,
    get_active_session,
    get_session_chain,
    append_message,
)


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    """Create a temporary test database."""
    db_path = tmp_path / "test.db"
    # Initialize with schema (will be done by init_db in database.py)
    conn = sqlite3.connect(db_path)
    
    # Minimal schema for testing
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            closed_at TEXT,
            origin TEXT NOT NULL
        );
        
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id),
            parent_session_id TEXT REFERENCES sessions(id),
            transition_reason TEXT,
            created_at TEXT NOT NULL,
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_conv ON sessions(conversation_id);
        
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            execution_id TEXT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            metadata TEXT,
            run_id TEXT,
            operator_username TEXT,
            conversation_id TEXT,
            session_id TEXT
        );
        
        CREATE TABLE IF NOT EXISTS workflow_runs (
            id TEXT PRIMARY KEY,
            workflow_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            started_at TEXT NOT NULL,
            finished_at TEXT,
            inputs TEXT,
            outputs TEXT,
            error TEXT,
            workflow_definition TEXT,
            trigger_source TEXT,
            cancelled_by TEXT,
            conversation_id TEXT
        );
    """)
    conn.commit()
    conn.close()
    
    return db_path


def test_start_conversation_creates_row(test_db: Path) -> None:
    """Test that start_conversation creates a conversation row with origin and created_at."""
    conv = start_conversation(test_db, origin="cli")
    
    assert conv.id is not None
    assert conv.origin == "cli"
    assert conv.created_at is not None
    assert conv.closed_at is None
    
    # Verify in database
    conn = sqlite3.connect(test_db)
    cursor = conn.execute("SELECT id, origin, created_at, closed_at FROM conversations WHERE id = ?", (conv.id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row is not None
    assert row[0] == conv.id
    assert row[1] == "cli"
    assert row[2] is not None
    assert row[3] is None


def test_mint_session_links_to_conversation(test_db: Path) -> None:
    """Test that mint_session creates a session linked to conversation with active=1."""
    conv = start_conversation(test_db, origin="dashboard")
    session = mint_session(test_db, conv.id)
    
    assert session.id is not None
    assert session.conversation_id == conv.id
    assert session.active is True
    assert session.parent_session_id is None
    assert session.transition_reason is None
    
    # Verify in database
    conn = sqlite3.connect(test_db)
    cursor = conn.execute("SELECT conversation_id, active FROM sessions WHERE id = ?", (session.id,))
    row = cursor.fetchone()
    conn.close()
    
    assert row[0] == conv.id
    assert row[1] == 1


def test_transition_session_deactivates_old_and_chains(test_db: Path) -> None:
    """Test that transition_session deactivates old session and creates chained new one."""
    conv = start_conversation(test_db, origin="cli")
    old_session = mint_session(test_db, conv.id)
    
    new_session = transition_session(test_db, old_session.id, reason="paused")
    
    # Old session should be deactivated
    old_retrieved = get_active_session(test_db, conv.id)
    assert old_retrieved is not None
    assert old_retrieved.id == new_session.id  # Active session is the new one
    
    # New session should chain to old
    assert new_session.parent_session_id == old_session.id
    assert new_session.transition_reason == "paused"
    assert new_session.active is True
    
    # Verify old session is inactive in DB
    conn = sqlite3.connect(test_db)
    cursor = conn.execute("SELECT active FROM sessions WHERE id = ?", (old_session.id,))
    row = cursor.fetchone()
    conn.close()
    assert row[0] == 0


def test_session_rows_immutable_except_active(test_db: Path) -> None:
    """Test that session row fields (except active) are never updated after creation.
    
    This is a contract test - verifies that the implementation does not have
    any UPDATE statements that modify conversation_id, parent_session_id,
    transition_reason, or created_at.
    """
    # This is a source code inspection test - we verify the implementation
    # only updates the `active` field and never updates other fields
    
    # Read the source file
    source_path = Path(__file__).parent.parent / "src" / "dag_executor" / "conversations.py"
    if source_path.exists():
        source = source_path.read_text()
        
        # Check for problematic UPDATE patterns
        forbidden_updates = [
            "UPDATE sessions SET conversation_id",
            "UPDATE sessions SET parent_session_id",
            "UPDATE sessions SET transition_reason",
            "UPDATE sessions SET created_at",
        ]
        
        for forbidden in forbidden_updates:
            assert forbidden not in source, f"Found forbidden UPDATE: {forbidden}"
    
    # Also do a runtime test: create session, attempt to verify immutability
    conv = start_conversation(test_db, origin="cli")
    session = mint_session(test_db, conv.id)
    
    # Get original values
    conn = sqlite3.connect(test_db)
    cursor = conn.execute(
        "SELECT conversation_id, parent_session_id, transition_reason, created_at FROM sessions WHERE id = ?",
        (session.id,)
    )
    original = cursor.fetchone()
    conn.close()
    
    # Transition the session
    new_session = transition_session(test_db, session.id, reason="resumed")
    
    # Verify old session fields are unchanged (except active)
    conn = sqlite3.connect(test_db)
    cursor = conn.execute(
        "SELECT conversation_id, parent_session_id, transition_reason, created_at FROM sessions WHERE id = ?",
        (session.id,)
    )
    after = cursor.fetchone()
    conn.close()
    
    assert original == after, "Session fields changed after transition"


def test_append_message_persists_conversation_and_session(test_db: Path) -> None:
    """Test that append_message saves conversation_id and session_id to chat_messages."""
    conv = start_conversation(test_db, origin="cli")
    session = mint_session(test_db, conv.id)
    
    message = append_message(
        test_db,
        role="user",
        content="Hello",
        conversation_id=conv.id,
        session_id=session.id
    )
    
    assert message.id is not None
    assert message.conversation_id == conv.id
    assert message.session_id == session.id
    assert message.role == "user"
    assert message.content == "Hello"
    
    # Verify in database
    conn = sqlite3.connect(test_db)
    cursor = conn.execute(
        "SELECT conversation_id, session_id, role, content FROM chat_messages WHERE id = ?",
        (message.id,)
    )
    row = cursor.fetchone()
    conn.close()
    
    assert row[0] == conv.id
    assert row[1] == session.id
    assert row[2] == "user"
    assert row[3] == "Hello"


def test_message_ordering_by_created_at(test_db: Path) -> None:
    """Test that messages are retrieved in created_at order."""
    conv = start_conversation(test_db, origin="cli")
    session = mint_session(test_db, conv.id)
    
    # Append 3 messages
    m1 = append_message(test_db, role="user", content="First", conversation_id=conv.id, session_id=session.id)
    m2 = append_message(test_db, role="assistant", content="Second", conversation_id=conv.id, session_id=session.id)
    m3 = append_message(test_db, role="user", content="Third", conversation_id=conv.id, session_id=session.id)
    
    # Retrieve all messages for this session
    conn = sqlite3.connect(test_db)
    cursor = conn.execute(
        "SELECT id, content FROM chat_messages WHERE session_id = ? ORDER BY created_at",
        (session.id,)
    )
    rows = cursor.fetchall()
    conn.close()
    
    assert len(rows) == 3
    assert rows[0][1] == "First"
    assert rows[1][1] == "Second"
    assert rows[2][1] == "Third"


def test_session_chain_lineage(test_db: Path) -> None:
    """Test that get_session_chain walks parent_session_id to root."""
    conv = start_conversation(test_db, origin="cli")
    s1 = mint_session(test_db, conv.id)
    s2 = transition_session(test_db, s1.id, reason="interrupted")
    s3 = transition_session(test_db, s2.id, reason="resumed")
    
    chain = get_session_chain(test_db, s3.id)
    
    assert len(chain) == 3
    assert chain[0].id == s3.id  # Most recent first
    assert chain[1].id == s2.id
    assert chain[2].id == s1.id  # Root last


def test_sub_workflow_inherits_conversation_id(test_db: Path) -> None:
    """Test AC-9: sub-workflow inherits parent's conversation_id."""
    # This tests the helper function that extracts conversation_id from parent run
    
    conv = start_conversation(test_db, origin="cli")
    
    # Create parent workflow run with conversation_id
    parent_run_id = "parent-run-123"
    conn = sqlite3.connect(test_db)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at, conversation_id) VALUES (?, ?, ?, ?, ?)",
        (parent_run_id, "parent-workflow", "running", datetime.now(timezone.utc).isoformat(), conv.id)
    )
    conn.commit()
    conn.close()
    
    # Import the helper function (will be defined in conversations.py)
    from dag_executor.conversations import get_conversation_id_from_parent_run
    
    # Get conversation_id for child
    inherited_conv_id = get_conversation_id_from_parent_run(test_db, parent_run_id)
    
    assert inherited_conv_id == conv.id


def test_start_conversation_idempotent_with_explicit_id(test_db: Path) -> None:
    """Test that starting a conversation with an explicit ID is idempotent."""
    explicit_id = "conv-explicit-123"
    
    conv1 = start_conversation(test_db, origin="cli", conversation_id=explicit_id)
    assert conv1.id == explicit_id
    
    # Call again with same ID
    conv2 = start_conversation(test_db, origin="cli", conversation_id=explicit_id)
    assert conv2.id == explicit_id
    
    # Verify only one row exists
    conn = sqlite3.connect(test_db)
    cursor = conn.execute("SELECT COUNT(*) FROM conversations WHERE id = ?", (explicit_id,))
    count = cursor.fetchone()[0]
    conn.close()
    
    assert count == 1
