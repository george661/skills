"""Tests for denied events sentinel file tailing."""
import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest


class MockBroadcaster:
    """Mock broadcaster that collects events."""

    def __init__(self):
        self.events: List[Dict[str, Any]] = []

    async def publish(self, run_id: str, event: Dict[str, Any]) -> None:
        """Record broadcasted event."""
        self.events.append(event)


@pytest.fixture
def workspace_dir(tmp_path: Path) -> Path:
    """Create a workspace with .claude directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".claude").mkdir()
    return workspace


@pytest.fixture
def sentinel_file(workspace_dir: Path) -> Path:
    """Create sentinel file."""
    sentinel = workspace_dir / ".claude" / "denied-events.jsonl"
    sentinel.touch()
    return sentinel


def test_tail_broadcasts_new_lines(workspace_dir: Path, sentinel_file: Path):
    """Tail thread should broadcast new deny events as chat_messages."""
    from dag_dashboard.orchestrator_relay import DeniedEventsTail

    broadcaster = MockBroadcaster()
    stop_event = threading.Event()
    loop = asyncio.new_event_loop()

    # Start loop in background thread
    def run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    loop_thread = threading.Thread(target=run_loop, daemon=True)
    loop_thread.start()

    # Start tail
    tail = DeniedEventsTail(
        sentinel_file=sentinel_file,
        conversation_id="test-conv",
        run_id="run-123",
        broadcaster=broadcaster,
        event_loop=loop,
        stop_event=stop_event,
    )
    tail.start()

    try:
        # Give tail time to start and seek to end
        time.sleep(0.1)

        # Write a denied event
        event = {
            "tool_name": "Read",
            "tool_input": {"file_path": "/etc/hosts"},
            "reason": "outside workspace",
            "timestamp": "2026-05-15T12:00:00Z",
        }
        with open(sentinel_file, "a") as f:
            f.write(json.dumps(event) + "\n")

        # Wait for tail to pick it up
        time.sleep(0.5)

        # Should have broadcast one message
        assert len(broadcaster.events) == 1

        msg = broadcaster.events[0]
        assert msg["type"] == "chat_message"
        assert msg["role"] == "system"
        assert msg["kind"] == "permission_denied"
        assert "outside workspace" in msg["content"]
        assert msg["conversation_id"] == "test-conv"
        assert msg["tool_name"] == "Read"
    finally:
        stop_event.set()
        tail.join(timeout=2)
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=2)
        loop.close()


def test_tail_skips_old_lines(workspace_dir: Path, sentinel_file: Path):
    """Tail should not replay old events from before spawn."""
    from dag_dashboard.orchestrator_relay import DeniedEventsTail

    # Write old event before starting tail
    old_event = {
        "tool_name": "Write",
        "tool_input": {"file_path": "/tmp/bad"},
        "reason": "old denial",
        "timestamp": "2026-05-15T11:00:00Z",
    }
    with open(sentinel_file, "a") as f:
        f.write(json.dumps(old_event) + "\n")

    broadcaster = MockBroadcaster()
    stop_event = threading.Event()
    loop = asyncio.new_event_loop()

    # Start loop in background thread
    def run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    loop_thread = threading.Thread(target=run_loop, daemon=True)
    loop_thread.start()

    # Start tail (should seek to end)
    tail = DeniedEventsTail(
        sentinel_file=sentinel_file,
        conversation_id="test-conv",
        run_id="run-123",
        broadcaster=broadcaster,
        event_loop=loop,
        stop_event=stop_event,
    )
    tail.start()

    try:
        # Wait a bit
        time.sleep(0.3)

        # Should NOT have broadcast the old event
        assert len(broadcaster.events) == 0

        # Now write a new event
        new_event = {
            "tool_name": "Edit",
            "tool_input": {"file_path": "/root/file"},
            "reason": "new denial",
            "timestamp": "2026-05-15T12:00:00Z",
        }
        with open(sentinel_file, "a") as f:
            f.write(json.dumps(new_event) + "\n")

        time.sleep(0.5)

        # Should have broadcast only the new event
        assert len(broadcaster.events) == 1
        assert "new denial" in broadcaster.events[0]["content"]
    finally:
        stop_event.set()
        tail.join(timeout=2)
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=2)
        loop.close()


def test_tail_waits_for_missing_file(workspace_dir: Path):
    """Tail should wait patiently if file doesn't exist at spawn."""
    from dag_dashboard.orchestrator_relay import DeniedEventsTail

    sentinel_file = workspace_dir / ".claude" / "denied-events.jsonl"
    # Don't create it yet

    broadcaster = MockBroadcaster()
    stop_event = threading.Event()
    loop = asyncio.new_event_loop()

    # Start loop in background thread
    def run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    loop_thread = threading.Thread(target=run_loop, daemon=True)
    loop_thread.start()

    tail = DeniedEventsTail(
        sentinel_file=sentinel_file,
        conversation_id="test-conv",
        run_id="run-123",
        broadcaster=broadcaster,
        event_loop=loop,
        stop_event=stop_event,
    )
    tail.start()

    try:
        # Wait a bit - shouldn't crash
        time.sleep(0.3)

        # Now create the file and write event
        sentinel_file.parent.mkdir(parents=True, exist_ok=True)
        sentinel_file.touch()
        event = {
            "tool_name": "Bash",
            "tool_input": {"command": "curl evil"},
            "reason": "egress",
            "timestamp": "2026-05-15T12:00:00Z",
        }
        # Give tail time to notice file exists and seek to end
        time.sleep(0.3)

        with open(sentinel_file, "a") as f:
            f.write(json.dumps(event) + "\n")

        time.sleep(0.5)

        # Should have picked it up
        assert len(broadcaster.events) == 1
    finally:
        stop_event.set()
        tail.join(timeout=2)
        loop.call_soon_threadsafe(loop.stop)
        loop_thread.join(timeout=2)
        loop.close()


def test_tail_stops_cleanly(workspace_dir: Path, sentinel_file: Path):
    """stop_event should cleanly shut down the tail thread."""
    from dag_dashboard.orchestrator_relay import DeniedEventsTail

    broadcaster = MockBroadcaster()
    stop_event = threading.Event()
    loop = asyncio.new_event_loop()

    # Start loop in background thread
    def run_loop():
        asyncio.set_event_loop(loop)
        loop.run_forever()

    loop_thread = threading.Thread(target=run_loop, daemon=True)
    loop_thread.start()

    tail = DeniedEventsTail(
        sentinel_file=sentinel_file,
        conversation_id="test-conv",
        run_id="run-123",
        broadcaster=broadcaster,
        event_loop=loop,
        stop_event=stop_event,
    )
    tail.start()

    # Stop it
    stop_event.set()
    tail.join(timeout=2)

    # Should be dead
    assert not tail.is_alive()
    loop.call_soon_threadsafe(loop.stop)
    loop_thread.join(timeout=2)
    loop.close()
