"""Tests for the replay module (TraceRecorder, ExecutionTrace, TraceReplayer)."""
import json
from datetime import datetime, timezone
from pathlib import Path


from dag_executor.events import EventType, WorkflowEvent, WorkflowStatus
from dag_executor.replay import ExecutionTrace, TraceEvent, TraceRecorder, TraceReplayer
from dag_executor.schema import NodeDef, WorkflowConfig, WorkflowDef


def test_trace_recorder_captures_events():
    """TraceRecorder should capture all events emitted via EventEmitter."""
    recorder = TraceRecorder()
    
    # Emit some events
    event1 = WorkflowEvent(
        event_type=EventType.WORKFLOW_STARTED,
        workflow_id="test_workflow",
        run_id="run-123",
        status=WorkflowStatus.RUNNING,
        timestamp=datetime.now(timezone.utc),
    )
    event2 = WorkflowEvent(
        event_type=EventType.NODE_STARTED,
        workflow_id="test_workflow",
        run_id="run-123",
        node_id="node1",
        status=WorkflowStatus.RUNNING,
        timestamp=datetime.now(timezone.utc),
    )
    
    recorder.capture(event1)
    recorder.capture(event2)
    
    # Build trace and verify events were captured
    trace = recorder.build_trace("run-123", {"input": "test"})
    assert len(trace.events) == 2
    assert trace.events[0].event_type == "workflow_started"
    assert trace.events[1].event_type == "node_started"
    assert trace.events[1].node_id == "node1"


def test_trace_recorder_tracks_node_order():
    """TraceRecorder should track node execution order from NODE_STARTED events."""
    recorder = TraceRecorder()
    
    # Emit NODE_STARTED events for multiple nodes
    for node_id in ["node1", "node2", "node3"]:
        event = WorkflowEvent(
            event_type=EventType.NODE_STARTED,
            workflow_id="test_workflow",
            run_id="run-123",
            node_id=node_id,
            status=WorkflowStatus.RUNNING,
            timestamp=datetime.now(timezone.utc),
        )
        recorder.capture(event)
    
    trace = recorder.build_trace("run-123", {})
    assert trace.node_execution_order == ["node1", "node2", "node3"]


def test_trace_recorder_tracks_node_order_no_duplicates():
    """TraceRecorder should not duplicate nodes if they emit multiple events."""
    recorder = TraceRecorder()
    
    # Emit NODE_STARTED and NODE_COMPLETED for same node
    for event_type in [EventType.NODE_STARTED, EventType.NODE_COMPLETED]:
        event = WorkflowEvent(
            event_type=event_type,
            workflow_id="test_workflow",
            run_id="run-123",
            node_id="node1",
            status=WorkflowStatus.RUNNING if event_type == EventType.NODE_STARTED else WorkflowStatus.COMPLETED,
            timestamp=datetime.now(timezone.utc),
        )
        recorder.capture(event)
    
    trace = recorder.build_trace("run-123", {})
    assert trace.node_execution_order == ["node1"]


def test_trace_recorder_captures_workflow_name():
    """TraceRecorder should capture workflow_name from WORKFLOW_STARTED event."""
    recorder = TraceRecorder()
    
    event = WorkflowEvent(
        event_type=EventType.WORKFLOW_STARTED,
        workflow_id="my_test_workflow",
        run_id="run-123",
        status=WorkflowStatus.RUNNING,
        timestamp=datetime.now(timezone.utc),
    )
    recorder.capture(event)
    
    trace = recorder.build_trace("run-123", {})
    assert trace.workflow_name == "my_test_workflow"


def test_trace_recorder_captures_final_status():
    """TraceRecorder should capture final_status from WORKFLOW_COMPLETED/FAILED events."""
    # Test WORKFLOW_COMPLETED
    recorder1 = TraceRecorder()
    event_completed = WorkflowEvent(
        event_type=EventType.WORKFLOW_COMPLETED,
        workflow_id="test_workflow",
        run_id="run-123",
        status=WorkflowStatus.COMPLETED,
        timestamp=datetime.now(timezone.utc),
    )
    recorder1.capture(event_completed)
    trace1 = recorder1.build_trace("run-123", {})
    assert trace1.final_status == "completed"
    
    # Test WORKFLOW_FAILED
    recorder2 = TraceRecorder()
    event_failed = WorkflowEvent(
        event_type=EventType.WORKFLOW_FAILED,
        workflow_id="test_workflow",
        run_id="run-123",
        status=WorkflowStatus.FAILED,
        timestamp=datetime.now(timezone.utc),
    )
    recorder2.capture(event_failed)
    trace2 = recorder2.build_trace("run-123", {})
    assert trace2.final_status == "failed"


def test_recorder_save_writes_json(tmp_path: Path):
    """recorder.save() should write valid JSON that can be read back."""
    recorder = TraceRecorder()
    
    # Capture some events
    event = WorkflowEvent(
        event_type=EventType.WORKFLOW_STARTED,
        workflow_id="test_workflow",
        run_id="run-123",
        status=WorkflowStatus.RUNNING,
        timestamp=datetime.now(timezone.utc),
    )
    recorder.capture(event)
    
    # Save to file
    trace_path = tmp_path / "trace.json"
    recorder.save(str(trace_path), run_id="run-123", inputs={"key": "value"})
    
    # Verify file exists and contains valid JSON
    assert trace_path.exists()
    data = json.loads(trace_path.read_text())
    assert data["run_id"] == "run-123"
    assert data["workflow_name"] == "test_workflow"
    assert data["inputs"] == {"key": "value"}
    assert len(data["events"]) == 1


def test_execution_trace_roundtrip():
    """ExecutionTrace.to_dict() -> from_dict() should preserve all fields."""
    original = ExecutionTrace(
        workflow_name="test_workflow",
        run_id="run-123",
        inputs={"input1": "value1"},
        events=[
            TraceEvent(
                event_type="node_started",
                node_id="node1",
                status="running",
                timestamp="2026-04-16T14:00:00Z",
                metadata={"key": "value"},
            )
        ],
        node_execution_order=["node1", "node2"],
        final_status="completed",
        recorded_at="2026-04-16T14:05:00Z",
    )
    
    data = original.to_dict()
    restored = ExecutionTrace.from_dict(data)
    
    assert restored.workflow_name == original.workflow_name
    assert restored.run_id == original.run_id
    assert restored.inputs == original.inputs
    assert len(restored.events) == len(original.events)
    assert restored.events[0].event_type == original.events[0].event_type
    assert restored.events[0].metadata == original.events[0].metadata
    assert restored.node_execution_order == original.node_execution_order
    assert restored.final_status == original.final_status


def test_replayer_same_workflow_zero_issues():
    """Replaying a trace against the same workflow should produce zero issues."""
    # Create a workflow
    workflow = WorkflowDef(config=WorkflowConfig(checkpoint_prefix="test"), 
        name="test_workflow",
        nodes=[
            NodeDef(id="node1", name="node1", type="bash", script="echo test", depends_on=[]),
            NodeDef(id="node2", name="node2", type="bash", script="echo test2", depends_on=["node1"]),
        ],
    )
    
    # Create a trace from the workflow
    trace = ExecutionTrace(
        workflow_name="test_workflow",
        run_id="run-123",
        inputs={},
        events=[],
        node_execution_order=["node1", "node2"],
        final_status="completed",
    )
    
    # Replay
    replayer = TraceReplayer()
    issues = replayer.replay_trace(trace, workflow)
    
    assert issues == []


def test_replayer_detects_removed_node():
    """Replaying against a workflow missing a node should detect node_removed."""
    # Create a workflow with only one node
    workflow = WorkflowDef(config=WorkflowConfig(checkpoint_prefix="test"), 
        name="test_workflow",
        nodes=[
            NodeDef(id="node1", name="node1", type="bash", script="echo test", depends_on=[]),
        ],
    )
    
    # Create a trace that includes node2
    trace = ExecutionTrace(
        workflow_name="test_workflow",
        run_id="run-123",
        inputs={},
        events=[],
        node_execution_order=["node1", "node2"],
        final_status="completed",
    )
    
    # Replay
    replayer = TraceReplayer()
    issues = replayer.replay_trace(trace, workflow)
    
    # Should detect node2 was removed
    assert len(issues) == 1
    assert issues[0].severity == "error"
    assert issues[0].code == "node_removed"
    assert issues[0].node_id == "node2"


def test_replayer_detects_added_required_node():
    """Replaying against a workflow with a new required node should detect node_added."""
    # Create a workflow with a new node (on_failure=stop means required)
    workflow = WorkflowDef(config=WorkflowConfig(checkpoint_prefix="test"), 
        name="test_workflow",
        nodes=[
            NodeDef(id="node1", name="node1", type="bash", script="echo test", depends_on=[]),
            NodeDef(id="node2", name="node2", type="bash", script="echo new", depends_on=[], on_failure="stop"),
        ],
    )
    
    # Create a trace that only includes node1
    trace = ExecutionTrace(
        workflow_name="test_workflow",
        run_id="run-123",
        inputs={},
        events=[],
        node_execution_order=["node1"],
        final_status="completed",
    )
    
    # Replay
    replayer = TraceReplayer()
    issues = replayer.replay_trace(trace, workflow)
    
    # Should detect node2 was added
    assert len(issues) == 1
    assert issues[0].severity == "warning"
    assert issues[0].code == "node_added"
    assert issues[0].node_id == "node2"


def test_replayer_detects_broken_dependency():
    """Replaying should detect when a node's dependency doesn't exist."""
    # Create a workflow where node2 depends on non-existent node3
    workflow = WorkflowDef(config=WorkflowConfig(checkpoint_prefix="test"), 
        name="test_workflow",
        nodes=[
            NodeDef(id="node1", name="node1", type="bash", script="echo test", depends_on=[]),
            NodeDef(id="node2", name="node2", type="bash", script="echo test2", depends_on=["node3"]),
        ],
    )
    
    # Create a trace
    trace = ExecutionTrace(
        workflow_name="test_workflow",
        run_id="run-123",
        inputs={},
        events=[],
        node_execution_order=["node1", "node2"],
        final_status="completed",
    )
    
    # Replay
    replayer = TraceReplayer()
    issues = replayer.replay_trace(trace, workflow)
    
    # Should detect broken dependency
    assert any(issue.code == "broken_dependency" for issue in issues)
    broken_dep = next(issue for issue in issues if issue.code == "broken_dependency")
    assert broken_dep.severity == "error"
    assert broken_dep.node_id == "node2"
    assert "node3" in broken_dep.message


def test_replayer_from_file(tmp_path: Path):
    """TraceReplayer.replay() should load trace from JSON file."""
    # Create and save a trace
    trace = ExecutionTrace(
        workflow_name="test_workflow",
        run_id="run-123",
        inputs={},
        events=[],
        node_execution_order=["node1"],
        final_status="completed",
    )
    trace_path = tmp_path / "trace.json"
    trace_path.write_text(json.dumps(trace.to_dict()))
    
    # Create a workflow
    workflow = WorkflowDef(config=WorkflowConfig(checkpoint_prefix="test"), 
        name="test_workflow",
        nodes=[
            NodeDef(id="node1", name="node1", type="bash", script="echo test", depends_on=[]),
        ],
    )
    
    # Replay from file
    replayer = TraceReplayer()
    issues = replayer.replay(str(trace_path), workflow)
    
    assert issues == []
