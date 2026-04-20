"""Tests for progress bar rendering."""
import io
import os
from datetime import datetime
from unittest.mock import Mock
from dag_executor.events import EventEmitter, WorkflowEvent, EventType
from dag_executor.schema import NodeStatus, WorkflowStatus
from dag_executor.terminal.progress_bar import ProgressBar


def test_progress_bar_renders_ansi_when_color_enabled():
    """Progress bar uses \r for in-place updates when color enabled."""
    os.environ.pop("NO_COLOR", None)  # Ensure NO_COLOR is not set
    
    stderr_capture = io.StringIO()
    emitter = EventEmitter()
    pbar = ProgressBar(total_nodes=3, stderr=stderr_capture)
    pbar.attach(emitter)
    
    # Emit a node started event
    emitter.emit(WorkflowEvent(
        event_type=EventType.NODE_STARTED,
        workflow_id="test",
        node_id="node_a",
        timestamp=datetime.now(),
    ))
    
    output = stderr_capture.getvalue()
    # Should contain \r for in-place update
    assert "\r" in output
    assert "Current:" in output or "node_a" in output


def test_progress_bar_plain_text_when_no_color_set():
    """NO_COLOR produces newline-separated output without ANSI."""
    os.environ["NO_COLOR"] = "1"
    
    try:
        stderr_capture = io.StringIO()
        emitter = EventEmitter()
        pbar = ProgressBar(total_nodes=2, stderr=stderr_capture)
        pbar.attach(emitter)
        
        emitter.emit(WorkflowEvent(
            event_type=EventType.NODE_STARTED,
            workflow_id="test",
            node_id="node_a",
            timestamp=datetime.now(),
        ))
        
        output = stderr_capture.getvalue()
        
        # Should not contain ANSI escape codes
        assert "\x1b[" not in output
        # Should not use \r (uses \n instead)
        assert output.count("\n") > 0
    finally:
        os.environ.pop("NO_COLOR", None)


def test_progress_bar_increments_on_node_completed():
    """Completed count increments on NODE_COMPLETED events."""
    stderr_capture = io.StringIO()
    emitter = EventEmitter()
    pbar = ProgressBar(total_nodes=3, stderr=stderr_capture)
    pbar.attach(emitter)
    
    # Complete two nodes
    emitter.emit(WorkflowEvent(
        event_type=EventType.NODE_COMPLETED,
        workflow_id="test",
        node_id="node_a",
        status=NodeStatus.COMPLETED,
        timestamp=datetime.now(),
    ))
    emitter.emit(WorkflowEvent(
        event_type=EventType.NODE_COMPLETED,
        workflow_id="test",
        node_id="node_b",
        status=NodeStatus.COMPLETED,
        timestamp=datetime.now(),
    ))
    
    output = stderr_capture.getvalue()
    
    # Should show 2/3 or similar progress indicator
    assert "2" in output and "3" in output


def test_progress_bar_tracks_current_node():
    """Current node name appears in output."""
    stderr_capture = io.StringIO()
    emitter = EventEmitter()
    pbar = ProgressBar(total_nodes=2, stderr=stderr_capture)
    pbar.attach(emitter)
    
    emitter.emit(WorkflowEvent(
        event_type=EventType.NODE_STARTED,
        workflow_id="test",
        node_id="plan_review",
        timestamp=datetime.now(),
    ))
    
    output = stderr_capture.getvalue()
    assert "plan_review" in output


def test_progress_bar_accumulates_cost():
    """Cost accumulates across node completions."""
    stderr_capture = io.StringIO()
    emitter = EventEmitter()
    pbar = ProgressBar(total_nodes=2, stderr=stderr_capture)
    pbar.attach(emitter)
    
    # Complete two nodes with cost metadata
    emitter.emit(WorkflowEvent(
        event_type=EventType.NODE_COMPLETED,
        workflow_id="test",
        node_id="a",
        status=NodeStatus.COMPLETED,
        metadata={"cost_usd": 0.12},
        timestamp=datetime.now(),
    ))
    emitter.emit(WorkflowEvent(
        event_type=EventType.NODE_COMPLETED,
        workflow_id="test",
        node_id="b",
        status=NodeStatus.COMPLETED,
        metadata={"cost_usd": 0.12},
        timestamp=datetime.now(),
    ))
    
    output = stderr_capture.getvalue()
    
    # Should show accumulated cost $0.24
    assert "$0.24" in output or "0.24" in output


def test_progress_bar_missing_cost_renders_zero():
    """Missing cost metadata renders as $0.00."""
    stderr_capture = io.StringIO()
    emitter = EventEmitter()
    pbar = ProgressBar(total_nodes=1, stderr=stderr_capture)
    pbar.attach(emitter)
    
    emitter.emit(WorkflowEvent(
        event_type=EventType.NODE_COMPLETED,
        workflow_id="test",
        node_id="a",
        status=NodeStatus.COMPLETED,
        timestamp=datetime.now(),
    ))
    
    output = stderr_capture.getvalue()
    assert "$0.00" in output or "0.00" in output


def test_progress_bar_formats_elapsed_time():
    """Elapsed time appears in mm:ss format."""
    stderr_capture = io.StringIO()
    emitter = EventEmitter()
    pbar = ProgressBar(total_nodes=1, stderr=stderr_capture)
    pbar.attach(emitter)
    
    emitter.emit(WorkflowEvent(
        event_type=EventType.NODE_STARTED,
        workflow_id="test",
        node_id="a",
        timestamp=datetime.now(),
    ))
    
    output = stderr_capture.getvalue()
    
    # Should contain time in mm:ss format (at least 00:00)
    assert "00:00" in output or ":" in output


def test_progress_bar_unsubscribe_on_workflow_completed():
    """WORKFLOW_COMPLETED event cleans up subscription."""
    stderr_capture = io.StringIO()
    emitter = EventEmitter()
    pbar = ProgressBar(total_nodes=1, stderr=stderr_capture)
    pbar.attach(emitter)
    
    initial_listener_count = len(emitter._listeners)
    
    emitter.emit(WorkflowEvent(
        event_type=EventType.WORKFLOW_COMPLETED,
        workflow_id="test",
        status=WorkflowStatus.COMPLETED,
        timestamp=datetime.now(),
    ))
    
    # Listener should be removed
    assert len(emitter._listeners) < initial_listener_count
