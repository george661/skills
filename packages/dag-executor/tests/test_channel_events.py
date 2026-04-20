"""Tests for channel event emission (CHANNEL_UPDATED and CHANNEL_CONFLICT)."""
import pytest
from typing import List, Dict, Any
from dag_executor.channels import (
    ChannelStore,
    LastValueChannel,
    ReducerChannel,
    BarrierChannel,
    ChannelConflictError,
)
from dag_executor.schema import ReducerDef, ReducerStrategy


class EventRecorder:
    """Helper to record emitted events."""
    
    def __init__(self):
        self.events: List[Dict[str, Any]] = []
    
    def __call__(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Record an event emission."""
        self.events.append({"type": event_type, "payload": payload})


def test_last_value_channel_emits_channel_updated():
    """Emits CHANNEL_UPDATED on LastValueChannel.write with correct payload."""
    recorder = EventRecorder()
    channel = LastValueChannel(key="test_state")
    # Pass emitter to write
    channel.write({"value": 42}, "node_a", emitter=recorder)
    
    assert len(recorder.events) == 1
    event = recorder.events[0]
    assert event["type"] == "CHANNEL_UPDATED"
    payload = event["payload"]
    assert payload["channel_key"] == "test_state"
    assert payload["channel_type"] == "LastValueChannel"
    assert payload["value"] == {"value": 42}
    assert payload["version"] == 1
    assert payload["writer_node_id"] == "node_a"
    assert "reducer_strategy" not in payload  # LastValue has no reducer


def test_reducer_channel_emits_channel_updated_with_strategy():
    """Emits CHANNEL_UPDATED on ReducerChannel.write including reducer_strategy."""
    recorder = EventRecorder()
    reducer_def = ReducerDef(strategy=ReducerStrategy.APPEND)
    channel = ReducerChannel(reducer_def=reducer_def)
    channel.write([1, 2], "node_a", emitter=recorder)
    
    assert len(recorder.events) == 1
    event = recorder.events[0]
    assert event["type"] == "CHANNEL_UPDATED"
    payload = event["payload"]
    assert payload["channel_type"] == "ReducerChannel"
    assert payload["reducer_strategy"] == "append"
    assert payload["version"] == 1


def test_barrier_channel_emits_only_on_release():
    """Emits CHANNEL_UPDATED only when BarrierChannel releases (version increments)."""
    recorder = EventRecorder()
    channel = BarrierChannel(expected_writers=2)
    
    # First write: barrier not yet released, version still 0
    channel.write("data1", "node_a", emitter=recorder)
    assert len(recorder.events) == 0  # No event yet
    
    # Second write: barrier releases, version increments to 1
    channel.write("data2", "node_b", emitter=recorder)
    assert len(recorder.events) == 1
    event = recorder.events[0]
    assert event["type"] == "CHANNEL_UPDATED"
    assert event["payload"]["version"] == 1
    assert event["payload"]["channel_type"] == "BarrierChannel"


def test_channel_conflict_error_emits_before_reraise():
    """Emits CHANNEL_CONFLICT before ChannelConflictError re-raise with all writers."""
    recorder = EventRecorder()
    channel = LastValueChannel(key="conflict_test")
    
    # First write succeeds
    channel.write("value1", "node_a", emitter=recorder)
    recorder.events.clear()
    
    # Second write from different node triggers conflict
    with pytest.raises(ChannelConflictError) as exc_info:
        channel.write("value2", "node_b", emitter=recorder)
    
    # Event was emitted before exception propagated
    assert len(recorder.events) == 1
    event = recorder.events[0]
    assert event["type"] == "CHANNEL_CONFLICT"
    payload = event["payload"]
    assert payload["channel_key"] == "conflict_test"
    assert set(payload["writers"]) == {"node_a", "node_b"}
    assert "conflict" in payload["message"].lower()
    
    # Exception still raised
    assert exc_info.value.channel_key == "conflict_test"


def test_no_events_when_emitter_not_supplied():
    """No events emitted when no emitter supplied (backwards compat)."""
    channel = LastValueChannel(key="no_emitter")
    # Call write without emitter kwarg
    version = channel.write("value", "node_a")
    assert version == 1
    # No exception, just no events
