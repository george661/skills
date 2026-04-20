"""Tests for chat message query functions."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dag_dashboard.database import init_db
from dag_dashboard.queries import (
    insert_chat_message,
    get_chat_messages,
    get_workflow_chat_history,
    check_rate_limit,
    insert_run,
    insert_node,
)


@pytest.fixture
def test_db(tmp_path):
    """Create a test database with test workflow runs and executions."""
    db_path = tmp_path / "test.db"
    init_db(db_path)

    # Create test workflow runs
    now = datetime.now(timezone.utc).isoformat()
    insert_run(db_path, "run-123", "test-workflow", "running", now)
    insert_run(db_path, "run-456", "test-workflow", "running", now)
    insert_run(db_path, "run-789", "test-workflow", "running", now)
    insert_run(db_path, "run-limit", "test-workflow", "running", now)
    insert_run(db_path, "run-limit-2", "test-workflow", "running", now)
    insert_run(db_path, "run-1", "test-workflow", "running", now)
    insert_run(db_path, "run-2", "test-workflow", "running", now)

    # Create test node executions
    insert_node(db_path, "exec-1", "run-123", "test-node", "running", now)

    return db_path


def test_insert_chat_message_with_run_id(test_db):
    """insert_chat_message should accept optional run_id parameter."""
    now = datetime.now(timezone.utc).isoformat()
    
    msg_id = insert_chat_message(
        test_db,
        execution_id="exec-1",
        role="operator",
        content="Hello from operator",
        created_at=now,
        run_id="run-123",
        operator_username="alice"
    )
    
    assert msg_id is not None
    
    # Verify it was stored
    messages = get_chat_messages(test_db, execution_id="exec-1")
    assert len(messages) == 1
    assert messages[0]["content"] == "Hello from operator"
    assert messages[0]["run_id"] == "run-123"
    assert messages[0]["operator_username"] == "alice"


def test_insert_chat_message_workflow_level(test_db):
    """Workflow-level messages should have run_id but no execution_id."""
    now = datetime.now(timezone.utc).isoformat()
    
    msg_id = insert_chat_message(
        test_db,
        execution_id=None,
        role="operator",
        content="Workflow-level message",
        created_at=now,
        run_id="run-456",
        operator_username="bob"
    )
    
    assert msg_id is not None


def test_get_workflow_chat_history(test_db):
    """get_workflow_chat_history should return paginated workflow messages."""
    now = datetime.now(timezone.utc).isoformat()
    
    # Insert workflow-level messages
    for i in range(15):
        insert_chat_message(
            test_db,
            execution_id=None,
            role="operator" if i % 2 == 0 else "agent",
            content=f"Message {i}",
            created_at=now,
            run_id="run-789",
            operator_username="alice" if i % 2 == 0 else None
        )
    
    # Get first page
    messages = get_workflow_chat_history(test_db, run_id="run-789", limit=10, offset=0)
    assert len(messages) == 10
    
    # Get second page
    messages_p2 = get_workflow_chat_history(test_db, run_id="run-789", limit=10, offset=10)
    assert len(messages_p2) == 5


def test_check_rate_limit_under_limit(test_db):
    """check_rate_limit should return False when under limit."""
    now = datetime.now(timezone.utc).isoformat()
    
    # Insert 5 messages (under the 10 msg/min limit)
    for i in range(5):
        insert_chat_message(
            test_db,
            execution_id=None,
            role="operator",
            content=f"Message {i}",
            created_at=now,
            run_id="run-limit",
            operator_username="alice"
        )
    
    # Should not be rate limited
    is_limited = check_rate_limit(test_db, run_id="run-limit", window_seconds=60, max_messages=10)
    assert is_limited is False


def test_check_rate_limit_over_limit(test_db):
    """check_rate_limit should return True when over limit."""
    now = datetime.now(timezone.utc).isoformat()
    
    # Insert 11 messages (over the 10 msg/min limit)
    for i in range(11):
        insert_chat_message(
            test_db,
            execution_id=None,
            role="operator",
            content=f"Message {i}",
            created_at=now,
            run_id="run-limit-2",
            operator_username="alice"
        )
    
    # Should be rate limited
    is_limited = check_rate_limit(test_db, run_id="run-limit-2", window_seconds=60, max_messages=10)
    assert is_limited is True


def test_get_chat_messages_with_run_id_filter(test_db):
    """get_chat_messages should filter by run_id when provided."""
    now = datetime.now(timezone.utc).isoformat()
    
    # Insert messages for run-1
    insert_chat_message(
        test_db,
        execution_id=None,
        role="operator",
        content="Run 1 message",
        created_at=now,
        run_id="run-1",
        operator_username="alice"
    )
    
    # Insert messages for run-2
    insert_chat_message(
        test_db,
        execution_id=None,
        role="operator",
        content="Run 2 message",
        created_at=now,
        run_id="run-2",
        operator_username="bob"
    )
    
    # Get messages for run-1 only
    messages = get_chat_messages(test_db, execution_id=None, run_id="run-1")
    assert len(messages) == 1
    assert messages[0]["content"] == "Run 1 message"
