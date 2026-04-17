"""Tests for workflow event system."""
import json
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List

from dag_executor.events import (
    EventEmitter,
    EventType,
    StreamMode,
    WorkflowEvent,
)
from dag_executor.schema import NodeStatus


class TestEventType:
    """Test EventType enum."""

    def test_enum_values(self) -> None:
        """Verify all expected enum values exist."""
        assert EventType.WORKFLOW_STARTED == "workflow_started"
        assert EventType.WORKFLOW_COMPLETED == "workflow_completed"
        assert EventType.WORKFLOW_FAILED == "workflow_failed"
        assert EventType.NODE_STARTED == "node_started"
        assert EventType.NODE_COMPLETED == "node_completed"
        assert EventType.NODE_FAILED == "node_failed"

    def test_new_streaming_event_types(self) -> None:
        """Verify new streaming event types exist."""
        assert EventType.NODE_STREAM_TOKEN == "node_stream_token"
        assert EventType.NODE_PROGRESS == "node_progress"


class TestStreamMode:
    """Test StreamMode enum."""

    def test_stream_mode_values(self) -> None:
        """Verify all stream mode values exist."""
        assert StreamMode.ALL == "all"
        assert StreamMode.STATE_UPDATES == "state_updates"
        assert StreamMode.DEBUG == "debug"


class TestWorkflowEvent:
    """Test WorkflowEvent Pydantic model."""
    
    def test_minimal_workflow_event(self) -> None:
        """Test creating a minimal workflow event."""
        event = WorkflowEvent(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id="wf-123",
            timestamp=datetime(2026, 4, 14, 12, 0, 0)
        )
        assert event.event_type == EventType.WORKFLOW_STARTED
        assert event.workflow_id == "wf-123"
        assert event.node_id is None
        assert event.status is None
        assert event.metadata == {}
    
    def test_node_event_with_all_fields(self) -> None:
        """Test creating a node event with all fields."""
        event = WorkflowEvent(
            event_type=EventType.NODE_COMPLETED,
            workflow_id="wf-123",
            node_id="node-1",
            status=NodeStatus.COMPLETED,
            metadata={"duration_ms": 1500},
            timestamp=datetime(2026, 4, 14, 12, 0, 0)
        )
        assert event.event_type == EventType.NODE_COMPLETED
        assert event.workflow_id == "wf-123"
        assert event.node_id == "node-1"
        assert event.status == NodeStatus.COMPLETED
        assert event.metadata["duration_ms"] == 1500
    
    def test_event_serialization(self) -> None:
        """Test that events can be serialized to JSON."""
        event = WorkflowEvent(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id="wf-123",
            timestamp=datetime(2026, 4, 14, 12, 0, 0)
        )
        json_str = event.model_dump_json()
        assert "workflow_started" in json_str
        assert "wf-123" in json_str
        
        # Verify it can be deserialized
        parsed = WorkflowEvent.model_validate_json(json_str)
        assert parsed.event_type == event.event_type
        assert parsed.workflow_id == event.workflow_id


class TestEventEmitter:
    """Test EventEmitter functionality."""
    
    def test_create_emitter(self) -> None:
        """Test creating an event emitter."""
        emitter = EventEmitter()
        assert emitter is not None
    
    def test_add_listener(self) -> None:
        """Test adding event listeners."""
        emitter = EventEmitter()
        events_received: List[WorkflowEvent] = []
        
        def listener(event: WorkflowEvent) -> None:
            events_received.append(event)
        
        emitter.add_listener(listener)
        
        # Emit event and verify listener received it
        event = WorkflowEvent(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id="wf-123",
            timestamp=datetime(2026, 4, 14, 12, 0, 0)
        )
        emitter.emit(event)
        
        assert len(events_received) == 1
        assert events_received[0].workflow_id == "wf-123"
    
    def test_multiple_listeners(self) -> None:
        """Test that multiple listeners all receive events."""
        emitter = EventEmitter()
        events1: List[WorkflowEvent] = []
        events2: List[WorkflowEvent] = []
        
        emitter.add_listener(lambda e: events1.append(e))
        emitter.add_listener(lambda e: events2.append(e))
        
        event = WorkflowEvent(
            event_type=EventType.NODE_STARTED,
            workflow_id="wf-123",
            node_id="node-1",
            timestamp=datetime(2026, 4, 14, 12, 0, 0)
        )
        emitter.emit(event)
        
        assert len(events1) == 1
        assert len(events2) == 1
        assert events1[0].node_id == "node-1"
        assert events2[0].node_id == "node-1"
    
    def test_remove_listener(self) -> None:
        """Test removing event listeners."""
        emitter = EventEmitter()
        events_received: List[WorkflowEvent] = []
        
        def listener(event: WorkflowEvent) -> None:
            events_received.append(event)
        
        emitter.add_listener(listener)
        emitter.remove_listener(listener)
        
        # Emit event - should not be received
        event = WorkflowEvent(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id="wf-123",
            timestamp=datetime(2026, 4, 14, 12, 0, 0)
        )
        emitter.emit(event)
        
        assert len(events_received) == 0
    
    def test_emit_without_listeners(self) -> None:
        """Test that emitting without listeners doesn't error."""
        emitter = EventEmitter()
        event = WorkflowEvent(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id="wf-123",
            timestamp=datetime(2026, 4, 14, 12, 0, 0)
        )
        # Should not raise an exception
        emitter.emit(event)
    
    def test_listener_exception_handling(self) -> None:
        """Test that exceptions in listeners don't break emission."""
        emitter = EventEmitter()
        events_received: List[WorkflowEvent] = []
        
        def bad_listener(event: WorkflowEvent) -> None:
            raise ValueError("Test error")
        
        def good_listener(event: WorkflowEvent) -> None:
            events_received.append(event)
        
        emitter.add_listener(bad_listener)
        emitter.add_listener(good_listener)
        
        event = WorkflowEvent(
            event_type=EventType.WORKFLOW_STARTED,
            workflow_id="wf-123",
            timestamp=datetime(2026, 4, 14, 12, 0, 0)
        )
        emitter.emit(event)
        
        # Good listener should still receive the event
        assert len(events_received) == 1
    
    def test_jsonl_logging(self) -> None:
        """Test JSONL logging to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "events.jsonl"
            emitter = EventEmitter(log_file=str(log_path))
            
            # Emit events
            event1 = WorkflowEvent(
                event_type=EventType.WORKFLOW_STARTED,
                workflow_id="wf-123",
                timestamp=datetime(2026, 4, 14, 12, 0, 0)
            )
            event2 = WorkflowEvent(
                event_type=EventType.NODE_STARTED,
                workflow_id="wf-123",
                node_id="node-1",
                timestamp=datetime(2026, 4, 14, 12, 0, 1)
            )
            
            emitter.emit(event1)
            emitter.emit(event2)
            
            # Read and verify JSONL file
            lines = log_path.read_text().strip().split('\n')
            assert len(lines) == 2
            
            log1 = json.loads(lines[0])
            assert log1["event_type"] == "workflow_started"
            assert log1["workflow_id"] == "wf-123"
            
            log2 = json.loads(lines[1])
            assert log2["event_type"] == "node_started"
            assert log2["node_id"] == "node-1"
    
    def test_thread_safe_listener_access(self) -> None:
        """Test that listener list is thread-safe."""
        import threading
        
        emitter = EventEmitter()
        events_received: List[WorkflowEvent] = []
        lock = threading.Lock()
        
        def listener(event: WorkflowEvent) -> None:
            with lock:
                events_received.append(event)
        
        emitter.add_listener(listener)
        
        # Emit from multiple threads
        def emit_event(i: int) -> None:
            event = WorkflowEvent(
                event_type=EventType.NODE_STARTED,
                workflow_id=f"wf-{i}",
                timestamp=datetime(2026, 4, 14, 12, 0, 0)
            )
            emitter.emit(event)
        
        threads = [threading.Thread(target=emit_event, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        assert len(events_received) == 10

    def test_subscribe_with_all_mode(self) -> None:
        """Test subscribe with ALL mode receives all events."""
        emitter = EventEmitter()
        events_received: List[WorkflowEvent] = []

        def listener(event: WorkflowEvent) -> None:
            events_received.append(event)

        emitter.subscribe(listener, StreamMode.ALL)

        # Emit various event types
        emitter.emit(WorkflowEvent(
            event_type=EventType.NODE_STARTED,
            workflow_id="wf-1",
            timestamp=datetime.now()
        ))
        emitter.emit(WorkflowEvent(
            event_type=EventType.NODE_STREAM_TOKEN,
            workflow_id="wf-1",
            node_id="node-1",
            metadata={"token": "hello"},
            timestamp=datetime.now()
        ))
        emitter.emit(WorkflowEvent(
            event_type=EventType.NODE_PROGRESS,
            workflow_id="wf-1",
            node_id="node-1",
            metadata={"message": "50% complete", "percent": 50},
            timestamp=datetime.now()
        ))

        # ALL mode should receive everything
        assert len(events_received) == 3

    def test_subscribe_with_state_updates_mode(self) -> None:
        """Test subscribe with STATE_UPDATES mode filters out stream tokens and progress."""
        emitter = EventEmitter()
        events_received: List[WorkflowEvent] = []

        def listener(event: WorkflowEvent) -> None:
            events_received.append(event)

        emitter.subscribe(listener, StreamMode.STATE_UPDATES)

        # Emit various event types
        emitter.emit(WorkflowEvent(
            event_type=EventType.NODE_STARTED,
            workflow_id="wf-1",
            node_id="node-1",
            timestamp=datetime.now()
        ))
        emitter.emit(WorkflowEvent(
            event_type=EventType.NODE_STREAM_TOKEN,
            workflow_id="wf-1",
            node_id="node-1",
            metadata={"token": "hello"},
            timestamp=datetime.now()
        ))
        emitter.emit(WorkflowEvent(
            event_type=EventType.NODE_PROGRESS,
            workflow_id="wf-1",
            node_id="node-1",
            metadata={"message": "50% complete"},
            timestamp=datetime.now()
        ))
        emitter.emit(WorkflowEvent(
            event_type=EventType.NODE_COMPLETED,
            workflow_id="wf-1",
            node_id="node-1",
            status=NodeStatus.COMPLETED,
            timestamp=datetime.now()
        ))

        # STATE_UPDATES mode should filter out stream tokens and progress
        assert len(events_received) == 2
        assert events_received[0].event_type == EventType.NODE_STARTED
        assert events_received[1].event_type == EventType.NODE_COMPLETED

    def test_subscribe_with_debug_mode(self) -> None:
        """Test subscribe with DEBUG mode receives everything (superset of ALL)."""
        emitter = EventEmitter()
        events_received: List[WorkflowEvent] = []

        def listener(event: WorkflowEvent) -> None:
            events_received.append(event)

        emitter.subscribe(listener, StreamMode.DEBUG)

        # Emit various event types
        emitter.emit(WorkflowEvent(
            event_type=EventType.NODE_STARTED,
            workflow_id="wf-1",
            timestamp=datetime.now()
        ))
        emitter.emit(WorkflowEvent(
            event_type=EventType.NODE_STREAM_TOKEN,
            workflow_id="wf-1",
            node_id="node-1",
            metadata={"token": "hello"},
            timestamp=datetime.now()
        ))

        # DEBUG mode should receive everything (same as ALL for now)
        assert len(events_received) == 2

    def test_add_listener_backward_compatibility(self) -> None:
        """Test that add_listener still works and receives all events (backward compat)."""
        emitter = EventEmitter()
        events_received: List[WorkflowEvent] = []

        def listener(event: WorkflowEvent) -> None:
            events_received.append(event)

        # Use old add_listener API
        emitter.add_listener(listener)

        # Emit various event types
        emitter.emit(WorkflowEvent(
            event_type=EventType.NODE_STARTED,
            workflow_id="wf-1",
            timestamp=datetime.now()
        ))
        emitter.emit(WorkflowEvent(
            event_type=EventType.NODE_STREAM_TOKEN,
            workflow_id="wf-1",
            node_id="node-1",
            metadata={"token": "hello"},
            timestamp=datetime.now()
        ))

        # add_listener should receive everything (unfiltered)
        assert len(events_received) == 2

    def test_new_event_types_serialization(self) -> None:
        """Test that new event types can be serialized to JSON."""
        # Test NODE_STREAM_TOKEN
        token_event = WorkflowEvent(
            event_type=EventType.NODE_STREAM_TOKEN,
            workflow_id="wf-123",
            node_id="node-1",
            metadata={"token": "hello world"},
            timestamp=datetime(2026, 4, 14, 12, 0, 0)
        )
        json_str = token_event.model_dump_json()
        assert "node_stream_token" in json_str
        assert "hello world" in json_str

        # Test NODE_PROGRESS
        progress_event = WorkflowEvent(
            event_type=EventType.NODE_PROGRESS,
            workflow_id="wf-123",
            node_id="node-1",
            metadata={"message": "Processing file 3/10", "current": 3, "total": 10},
            timestamp=datetime(2026, 4, 14, 12, 0, 0)
        )
        json_str = progress_event.model_dump_json()
        assert "node_progress" in json_str
        assert "Processing file 3/10" in json_str
