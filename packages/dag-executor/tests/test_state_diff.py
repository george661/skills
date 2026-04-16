"""Tests for state diff capture in NODE_COMPLETED events."""
import asyncio
import pytest
from typing import Any, Dict, List
from dag_executor.executor import WorkflowExecutor
from dag_executor.parser import load_workflow_from_string
from dag_executor.schema import NodeStatus, WorkflowStatus
from dag_executor.events import WorkflowEvent, EventType, EventEmitter


@pytest.fixture
def test_workflow_yaml_simple() -> str:
    """Simple workflow with bash node."""
    return """
name: test-state-diff-simple
config:
  checkpoint_prefix: test
nodes:
  - id: bash_node
    name: Bash Node
    type: bash
    script: echo "test"
"""


@pytest.fixture
def test_workflow_yaml_with_state() -> str:
    """Workflow with state and reducer."""
    return """
name: test-state-diff-with-state
config:
  checkpoint_prefix: test
state:
  output:
    strategy: overwrite
nodes:
  - id: bash_node
    name: Bash Node
    type: bash
    script: 'echo ''{"output": "new_value"}'''
    output_format: json
"""


@pytest.fixture
def capturing_event_emitter() -> tuple[EventEmitter, List[WorkflowEvent]]:
    """An EventEmitter paired with a list that captures all emitted events."""
    captured_events: List[WorkflowEvent] = []
    emitter = EventEmitter()
    emitter.add_listener(lambda e: captured_events.append(e))
    return emitter, captured_events


class TestStateDiff:
    """Test state diff capture in NODE_COMPLETED events."""

    def test_state_diff_metadata_present(
        self, test_workflow_yaml_simple: str, capturing_event_emitter: tuple[EventEmitter, List[WorkflowEvent]]
    ) -> None:
        """NODE_COMPLETED events include state_diff in metadata."""
        workflow_def = load_workflow_from_string(test_workflow_yaml_simple)
        emitter, events = capturing_event_emitter
        
        executor = WorkflowExecutor()
        result = asyncio.run(executor.execute(workflow_def, {}, event_emitter=emitter))
        
        assert result.status == WorkflowStatus.COMPLETED
        
        # Find NODE_COMPLETED event for bash_node
        completed_events = [
            e for e in events 
            if e.event_type == EventType.NODE_COMPLETED and e.node_id == "bash_node"
        ]
        assert len(completed_events) == 1
        
        event = completed_events[0]
        # This test should FAIL because state_diff is not yet implemented
        assert "state_diff" in event.metadata, "state_diff must be present in NODE_COMPLETED event metadata"

    def test_state_diff_captures_state_changes(
        self, test_workflow_yaml_with_state: str, capturing_event_emitter: tuple[EventEmitter, List[WorkflowEvent]]
    ) -> None:
        """State diff captured correctly when state is modified."""
        workflow_def = load_workflow_from_string(test_workflow_yaml_with_state)
        emitter, events = capturing_event_emitter
        
        executor = WorkflowExecutor()
        result = asyncio.run(executor.execute(workflow_def, {}, event_emitter=emitter))
        
        assert result.status == WorkflowStatus.COMPLETED
        
        # Find NODE_COMPLETED event for bash_node
        completed_events = [
            e for e in events 
            if e.event_type == EventType.NODE_COMPLETED and e.node_id == "bash_node"
        ]
        assert len(completed_events) == 1
        
        event = completed_events[0]
        assert "state_diff" in event.metadata
        state_diff = event.metadata["state_diff"]
        
        # Verify state_diff contains the changed key
        assert "output" in state_diff
        assert state_diff["output"] == "new_value"

    def test_state_diff_empty_when_no_changes(
        self, test_workflow_yaml_simple: str, capturing_event_emitter: tuple[EventEmitter, List[WorkflowEvent]]
    ) -> None:
        """State diff is empty dict when node makes no state changes."""
        workflow_def = load_workflow_from_string(test_workflow_yaml_simple)
        emitter, events = capturing_event_emitter
        
        executor = WorkflowExecutor()
        result = asyncio.run(executor.execute(workflow_def, {}, event_emitter=emitter))
        
        assert result.status == WorkflowStatus.COMPLETED
        
        # Find NODE_COMPLETED event
        completed_events = [
            e for e in events 
            if e.event_type == EventType.NODE_COMPLETED and e.node_id == "bash_node"
        ]
        assert len(completed_events) == 1
        
        event = completed_events[0]
        assert "state_diff" in event.metadata
        state_diff = event.metadata["state_diff"]
        
        # Verify state_diff is empty (node didn't modify state)
        assert state_diff == {}
