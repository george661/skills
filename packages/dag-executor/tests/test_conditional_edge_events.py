"""Tests for conditional edge event emission."""
import asyncio
from pathlib import Path
from typing import List

from dag_executor.events import EventEmitter, EventType, WorkflowEvent
from dag_executor.executor import WorkflowExecutor
from dag_executor.parser import load_workflow
from dag_executor.schema import WorkflowStatus


def test_conditional_edge_emits_condition_evaluated():
    """Run workflow with conditional_edges_review.yaml, assert CONDITION_EVALUATED events emitted."""
    fixture_path = Path(__file__).parent / "fixtures" / "conditional_edges_review.yaml"
    workflow_def = load_workflow(str(fixture_path))
    
    # Capture events
    captured_events: List[WorkflowEvent] = []
    
    def event_listener(event: WorkflowEvent) -> None:
        captured_events.append(event)
    
    event_emitter = EventEmitter()
    event_emitter.add_listener(event_listener)

    executor = WorkflowExecutor()
    result = asyncio.run(executor.execute(workflow_def, {}, event_emitter=event_emitter))
    assert result.status == WorkflowStatus.COMPLETED
    
    # Find CONDITION_EVALUATED events
    condition_events = [e for e in captured_events if e.event_type == EventType.CONDITION_EVALUATED]

    # Should have 1 CONDITION_EVALUATED event (for the approve condition)
    # The approve condition evaluates to true, so that gets evaluated and matches (first-match-wins)
    # The revise condition is NOT evaluated because first match already won
    # The default edge is not evaluated (no condition)
    assert len(condition_events) == 1, f"Expected exactly 1 CONDITION_EVALUATED event, got {len(condition_events)}"

    # Check that the approve condition was evaluated
    approve_event = [e for e in condition_events if 'approve' in e.metadata.get('condition', '')]
    assert len(approve_event) == 1
    assert approve_event[0].metadata["evaluated_value"] is True

    # Check event structure
    for event in condition_events:
        assert "source_node_id" in event.metadata
        assert "condition" in event.metadata
        assert "evaluated_value" in event.metadata
        assert isinstance(event.metadata["evaluated_value"], bool)


def test_conditional_edge_emits_edge_traversed_for_taken_path():
    """Assert exactly 1 EDGE_TRAVERSED event for the approve path."""
    fixture_path = Path(__file__).parent / "fixtures" / "conditional_edges_review.yaml"
    workflow_def = load_workflow(str(fixture_path))
    
    # Capture events
    captured_events: List[WorkflowEvent] = []
    
    def event_listener(event: WorkflowEvent) -> None:
        captured_events.append(event)
    
    event_emitter = EventEmitter()
    event_emitter.add_listener(event_listener)

    executor = WorkflowExecutor()
    result = asyncio.run(executor.execute(workflow_def, {}, event_emitter=event_emitter))
    assert result.status == WorkflowStatus.COMPLETED
    
    # Find EDGE_TRAVERSED events
    edge_events = [e for e in captured_events if e.event_type == EventType.EDGE_TRAVERSED]
    
    # Should have exactly 1 EDGE_TRAVERSED event (for review -> merge)
    assert len(edge_events) == 1, f"Expected 1 EDGE_TRAVERSED event, got {len(edge_events)}"
    
    event = edge_events[0]
    assert event.metadata["source_node_id"] == "review"
    assert event.metadata["target_node_id"] == "merge"
    assert event.metadata["taken"] is True
    assert "condition" in event.metadata
    assert "evaluated_value" in event.metadata


def test_default_edge_fires_when_no_condition_matches():
    """Workflow where all conditions are false, assert default edge fires."""
    fixture_path = Path(__file__).parent / "fixtures" / "conditional_edges_review.yaml"
    
    # Modify the YAML to output unknown verdict (triggers default)
    import yaml
    with open(fixture_path) as f:
        workflow_data = yaml.safe_load(f)
    
    # Change review node script to output unknown verdict
    for node in workflow_data["nodes"]:
        if node["id"] == "review":
            node["script"] = 'echo \'{"verdict": "unknown"}\''
    
    # Save to temp file
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
        yaml.dump(workflow_data, tmp)
        tmp_path = tmp.name
    
    try:
        from dag_executor.parser import load_workflow_from_string
        with open(tmp_path) as f:
            workflow_def = load_workflow_from_string(f.read())
        
        # Capture events
        captured_events: List[WorkflowEvent] = []
        
        def event_listener(event: WorkflowEvent) -> None:
            captured_events.append(event)
        
        event_emitter = EventEmitter()
        event_emitter.add_listener(event_listener)
        
        executor = WorkflowExecutor()
        
        result = asyncio.run(executor.execute(workflow_def, {}, event_emitter=event_emitter))
        assert result.status == WorkflowStatus.COMPLETED
        
        # Find EDGE_TRAVERSED events
        edge_events = [e for e in captured_events if e.event_type == EventType.EDGE_TRAVERSED]
        
        # Should have exactly 1 EDGE_TRAVERSED event for the default edge
        assert len(edge_events) == 1
        event = edge_events[0]
        assert event.metadata["source_node_id"] == "review"
        assert event.metadata["target_node_id"] == "escalate"
        assert event.metadata["taken"] is True
        assert event.metadata.get("default") is True
        
    finally:
        import os
        os.unlink(tmp_path)


def test_multi_target_fan_out_emits_one_event_per_target():
    """Edge with targets: [a, b], assert 2 EDGE_TRAVERSED events sharing same edge_group_id."""
    # Create a test workflow with fan-out
    import tempfile
    import yaml
    
    workflow_data = {
        "name": "fan-out-test",
        "config": {"checkpoint_prefix": "test", "worktree": False},
        "nodes": [
            {
                "id": "start",
                "name": "Start",
                "type": "bash",
                "script": 'echo \'{"go": true}\'',
                "output_format": "json",
                "edges": [
                    {"targets": ["task_a", "task_b"], "condition": "start.go"},
                    {"target": "task_a", "default": True}  # Default edge required
                ]
            },
            {
                "id": "task_a",
                "name": "Task A",
                "type": "bash",
                "script": "echo 'Task A'"
            },
            {
                "id": "task_b",
                "name": "Task B",
                "type": "bash",
                "script": "echo 'Task B'"
            }
        ]
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
        yaml.dump(workflow_data, tmp)
        tmp_path = tmp.name
    
    try:
        from dag_executor.parser import load_workflow_from_string
        with open(tmp_path) as f:
            workflow_def = load_workflow_from_string(f.read())
        
        # Capture events
        captured_events: List[WorkflowEvent] = []
        
        def event_listener(event: WorkflowEvent) -> None:
            captured_events.append(event)
        
        event_emitter = EventEmitter()
        event_emitter.add_listener(event_listener)
        
        executor = WorkflowExecutor()
        
        result = asyncio.run(executor.execute(workflow_def, {}, event_emitter=event_emitter))
        assert result.status == WorkflowStatus.COMPLETED
        
        # Find EDGE_TRAVERSED events
        edge_events = [e for e in captured_events if e.event_type == EventType.EDGE_TRAVERSED]
        
        # Should have 2 EDGE_TRAVERSED events (one for each target)
        assert len(edge_events) == 2, f"Expected 2 EDGE_TRAVERSED events for fan-out, got {len(edge_events)}"
        
        # Both should have the same edge_group_id
        edge_group_ids = [e.metadata.get("edge_group_id") for e in edge_events]
        assert edge_group_ids[0] == edge_group_ids[1], "Fan-out edges should share same edge_group_id"
        assert edge_group_ids[0] is not None
        
        # Check targets
        targets = sorted([e.metadata["target_node_id"] for e in edge_events])
        assert targets == ["task_a", "task_b"]
        
    finally:
        import os
        os.unlink(tmp_path)
