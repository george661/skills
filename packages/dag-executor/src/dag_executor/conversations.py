"""Conversation and session management service layer.

This module provides a service-layer API for managing conversations and sessions
in the DAG workflow system. It wraps database queries from dag_dashboard.queries
and provides Pydantic models for type safety.

Architecture:
- Schema lives in dag-dashboard/database.py
- Low-level queries live in dag-dashboard/queries.py  
- Service layer (this file) lives in dag-executor for CLI access
- Both dashboard and CLI import this module

Immutability contract:
- Session rows are immutable except for the `active` flag
- Transition creates a new session with parent_session_id chain
- No UPDATE statements modify conversation_id, parent_session_id,
  transition_reason, or created_at on sessions
"""

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class Conversation(BaseModel):
    """Conversation grouping for chat messages and workflow runs."""
    
    id: str
    created_at: str
    closed_at: Optional[str] = None
    origin: str  # "cli" | "dashboard" | "sub-workflow"


class Session(BaseModel):
    """Session tracking within a conversation.
    
    Sessions are immutable except for the active flag.
    Transitions create new sessions with parent_session_id chain.
    """
    
    id: str
    conversation_id: str
    parent_session_id: Optional[str] = None
    transition_reason: Optional[str] = None
    created_at: str
    active: bool


class Message(BaseModel):
    """Chat message with optional conversation and session linkage."""
    
    id: int
    execution_id: Optional[str] = None
    run_id: Optional[str] = None
    conversation_id: Optional[str] = None
    session_id: Optional[str] = None
    role: str
    content: str
    created_at: str
    metadata: Optional[Dict[str, Any]] = None


def start_conversation(
    db_path: Path,
    origin: str,
    conversation_id: Optional[str] = None,
) -> Conversation:
    """Start a new conversation or return existing if conversation_id provided.
    
    Args:
        db_path: Path to SQLite database
        origin: Origin of conversation ("cli", "dashboard", "sub-workflow")
        conversation_id: Optional explicit ID for idempotent creation
    
    Returns:
        Conversation model with generated or provided ID
    """
    from dag_dashboard.queries import insert_conversation, get_conversation_row
    
    conv_id = conversation_id or str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    
    # Check if already exists
    existing = get_conversation_row(db_path, conv_id)
    if existing:
        return Conversation(**existing)
    
    # Create new conversation
    insert_conversation(db_path, conv_id, origin, created_at)
    
    return Conversation(
        id=conv_id,
        created_at=created_at,
        closed_at=None,
        origin=origin,
    )


def close_conversation(db_path: Path, conversation_id: str) -> None:
    """Close a conversation by setting closed_at timestamp.
    
    Args:
        db_path: Path to SQLite database
        conversation_id: Conversation ID to close
    """
    from dag_dashboard.queries import update_conversation_closed_at
    
    closed_at = datetime.now(timezone.utc).isoformat()
    update_conversation_closed_at(db_path, conversation_id, closed_at)


def get_conversation(db_path: Path, conversation_id: str) -> Optional[Conversation]:
    """Get conversation by ID.
    
    Args:
        db_path: Path to SQLite database
        conversation_id: Conversation ID to retrieve
    
    Returns:
        Conversation model or None if not found
    """
    from dag_dashboard.queries import get_conversation_row
    
    row = get_conversation_row(db_path, conversation_id)
    return Conversation(**row) if row else None


def mint_session(db_path: Path, conversation_id: str) -> Session:
    """Create a new root session for a conversation.
    
    Args:
        db_path: Path to SQLite database
        conversation_id: Parent conversation ID
    
    Returns:
        Session model with generated ID and active=True
    """
    from dag_dashboard.queries import insert_session_row
    
    session_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    
    insert_session_row(
        db_path,
        session_id,
        conversation_id,
        created_at,
        parent_session_id=None,
        transition_reason=None,
        active=1,
    )
    
    return Session(
        id=session_id,
        conversation_id=conversation_id,
        parent_session_id=None,
        transition_reason=None,
        created_at=created_at,
        active=True,
    )


def transition_session(db_path: Path, old_session_id: str, reason: str) -> Session:
    """Transition to a new session, deactivating the old one.
    
    This performs two operations in a single transaction:
    1. UPDATE sessions SET active=0 WHERE id=old_session_id
    2. INSERT new session with parent_session_id=old_session_id
    
    Args:
        db_path: Path to SQLite database
        old_session_id: Session ID to deactivate
        reason: Reason for transition (e.g., "paused", "resumed", "interrupted")
    
    Returns:
        New session model with active=True
    """
    from dag_dashboard.queries import get_session_row
    
    # Get old session to inherit conversation_id
    old_session_row = get_session_row(db_path, old_session_id)
    if not old_session_row:
        raise ValueError(f"Session {old_session_id} not found")
    
    conversation_id = old_session_row["conversation_id"]
    new_session_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    
    # Single transaction for atomic transition
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        
        # Deactivate old session
        conn.execute("UPDATE sessions SET active = 0 WHERE id = ?", (old_session_id,))
        
        # Create new session
        conn.execute(
            """
            INSERT INTO sessions (id, conversation_id, parent_session_id, transition_reason, created_at, active)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (new_session_id, conversation_id, old_session_id, reason, created_at)
        )
        
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    
    return Session(
        id=new_session_id,
        conversation_id=conversation_id,
        parent_session_id=old_session_id,
        transition_reason=reason,
        created_at=created_at,
        active=True,
    )


def get_active_session(db_path: Path, conversation_id: str) -> Optional[Session]:
    """Get the currently active session for a conversation.
    
    Args:
        db_path: Path to SQLite database
        conversation_id: Conversation ID to query
    
    Returns:
        Active session model or None if no active session
    """
    from dag_dashboard.queries import get_active_session_row
    
    row = get_active_session_row(db_path, conversation_id)
    return Session(**row) if row else None


def get_session_chain(db_path: Path, session_id: str) -> List[Session]:
    """Walk parent_session_id backward from session_id to root.
    
    Args:
        db_path: Path to SQLite database
        session_id: Starting session ID
    
    Returns:
        List of sessions from most recent to root, in order
    """
    from dag_dashboard.queries import get_sessions_in_chain
    
    rows = get_sessions_in_chain(db_path, session_id)
    return [Session(**row) for row in rows]


def append_message(
    db_path: Path,
    role: str,
    content: str,
    conversation_id: Optional[str] = None,
    session_id: Optional[str] = None,
    execution_id: Optional[str] = None,
    run_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    operator_username: Optional[str] = None,
) -> Message:
    """Append a message to the chat history.
    
    Args:
        db_path: Path to SQLite database
        role: Message role (e.g., "user", "assistant", "operator")
        content: Message content
        conversation_id: Optional conversation ID
        session_id: Optional session ID
        execution_id: Optional node execution ID
        run_id: Optional workflow run ID
        metadata: Optional JSON metadata
        operator_username: Optional operator username
    
    Returns:
        Message model with generated ID
    """
    from dag_dashboard.queries import insert_chat_message
    
    created_at = datetime.now(timezone.utc).isoformat()
    
    message_id = insert_chat_message(
        db_path,
        execution_id=execution_id,
        role=role,
        content=content,
        created_at=created_at,
        metadata=metadata,
        run_id=run_id,
        operator_username=operator_username,
        conversation_id=conversation_id,
        session_id=session_id,
    )
    
    return Message(
        id=message_id,
        execution_id=execution_id,
        run_id=run_id,
        conversation_id=conversation_id,
        session_id=session_id,
        role=role,
        content=content,
        created_at=created_at,
        metadata=metadata,
    )


def get_conversation_id_from_parent_run(db_path: Path, parent_run_id: str) -> Optional[str]:
    """Get conversation_id from a parent workflow run for sub-workflow inheritance.

    This is a helper for AC-9: sub-workflows should inherit conversation_id from parent.

    Args:
        db_path: Path to SQLite database
        parent_run_id: Parent workflow run ID

    Returns:
        Conversation ID or None if parent has no conversation_id
    """
    from dag_dashboard.queries import get_conversation_id_from_run

    result: Optional[str] = get_conversation_id_from_run(db_path, parent_run_id)
    return result
