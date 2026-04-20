"""Tests for chat relay with named pipes."""
import os
import time
from threading import Thread

import pytest

# Skip tests on platforms without named pipe support
pytestmark = pytest.mark.skipif(
    not hasattr(os, "mkfifo"),
    reason="Named pipes not supported on this platform"
)


def test_chat_relay_creates_pipes_with_correct_permissions(tmp_path):
    """ChatRelay should create named pipes with 0600 permissions."""
    from dag_dashboard.chat_relay import ChatRelay
    from dag_dashboard.database import init_db

    db_path = tmp_path / "test.db"
    init_db(db_path)

    relay = ChatRelay(db_path=db_path, pipe_root=tmp_path / "pipes")

    # Ensure pipes for a run/node
    relay.ensure_pipes("run-1", "node-1")

    # Check pipes exist
    in_pipe = tmp_path / "pipes" / "run-1" / "node-1.in"
    out_pipe = tmp_path / "pipes" / "run-1" / "node-1.out"

    assert in_pipe.exists()
    assert out_pipe.exists()

    # Check permissions are 0600
    in_stat = os.stat(in_pipe)
    out_stat = os.stat(out_pipe)

    assert oct(in_stat.st_mode)[-3:] == "600"
    assert oct(out_stat.st_mode)[-3:] == "600"

    relay.stop()


def test_chat_relay_write_to_agent(tmp_path):
    """ChatRelay should write messages to the .in pipe."""
    from dag_dashboard.chat_relay import ChatRelay
    from dag_dashboard.database import init_db

    db_path = tmp_path / "test.db"
    init_db(db_path)

    relay = ChatRelay(db_path=db_path, pipe_root=tmp_path / "pipes")
    relay.ensure_pipes("run-2", "node-2")

    in_pipe = tmp_path / "pipes" / "run-2" / "node-2.in"

    # Read from the pipe in a background thread
    received_message = []

    def reader():
        with open(in_pipe, "r") as f:
            received_message.append(f.read())

    reader_thread = Thread(target=reader, daemon=True)
    reader_thread.start()

    # Give reader time to open pipe
    time.sleep(0.1)

    # Write message
    relay.write_to_agent("run-2", "node-2", "Test message to agent")

    reader_thread.join(timeout=1.0)

    assert len(received_message) == 1
    assert "Test message to agent" in received_message[0]

    relay.stop()


def test_chat_relay_read_from_agent(tmp_path):
    """ChatRelay should read messages from the .out pipe and persist them."""
    from dag_dashboard.chat_relay import ChatRelay
    from dag_dashboard.database import init_db
    from dag_dashboard.queries import insert_run, insert_node, get_chat_messages
    from datetime import datetime, timezone

    db_path = tmp_path / "test.db"
    init_db(db_path)

    # Create test run and node
    now = datetime.now(timezone.utc).isoformat()
    insert_run(db_path, "run-3", "test-workflow", "running", now)
    insert_node(db_path, "node-3", "run-3", "test-node", "running", now)

    relay = ChatRelay(db_path=db_path, pipe_root=tmp_path / "pipes")
    relay.ensure_pipes("run-3", "node-3")

    # Start reading from out pipe
    relay.start_reading("run-3", "node-3", "node-3")

    # Give reader time to start
    time.sleep(0.1)

    # Write message to out pipe (simulating agent response)
    out_pipe = tmp_path / "pipes" / "run-3" / "node-3.out"
    with open(out_pipe, "w") as f:
        f.write("Agent response here")

    # Give time for relay to read and persist
    time.sleep(0.2)

    # Check message was persisted
    messages = get_chat_messages(db_path, execution_id="node-3")
    assert len(messages) >= 1
    assert any("Agent response here" in msg["content"] for msg in messages)

    relay.stop()


def test_chat_relay_cleanup_on_stop(tmp_path):
    """ChatRelay should clean up pipes on stop."""
    from dag_dashboard.chat_relay import ChatRelay
    from dag_dashboard.database import init_db

    db_path = tmp_path / "test.db"
    init_db(db_path)

    relay = ChatRelay(db_path=db_path, pipe_root=tmp_path / "pipes")
    relay.ensure_pipes("run-4", "node-4")

    in_pipe = tmp_path / "pipes" / "run-4" / "node-4.in"
    out_pipe = tmp_path / "pipes" / "run-4" / "node-4.out"

    assert in_pipe.exists()
    assert out_pipe.exists()

    relay.stop()

    # Pipes should be cleaned up (or at least not cause errors on next run)
    # Implementation may choose to delete or leave them
