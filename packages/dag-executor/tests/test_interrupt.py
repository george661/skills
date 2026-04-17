"""Integration tests for interrupt/resume functionality."""
import json

from dag_executor import (
    load_workflow, execute_workflow, resume_workflow,
    NodeStatus, WorkflowStatus, CheckpointStore, EventEmitter
)
from dag_executor.schema import InterruptConfig
from dag_executor.events import EventType


def test_interrupt_config_validation():
    """Test InterruptConfig validates required fields."""
    # Valid config
    config = InterruptConfig(
        message="Please approve this action",
        resume_key="approval"
    )
    assert config.message == "Please approve this action"
    assert config.resume_key == "approval"
    assert config.channels == ["terminal"]  # default
    assert config.timeout is None  # optional
    
    # With optional fields
    config2 = InterruptConfig(
        message="Review needed",
        resume_key="review_result",
        channels=["terminal", "slack"],
        timeout=300
    )
    assert config2.channels == ["terminal", "slack"]
    assert config2.timeout == 300


def test_interrupt_node_halts_workflow(tmp_path):
    """Test that interrupt node causes workflow to return PAUSED status."""
    workflow_yaml = """
name: interrupt_test
config:
  checkpoint_prefix: .dag-checkpoints
nodes:
  - id: setup
    name: Setup
    type: bash
    script: echo "setup complete"
  
  - id: interrupt_approval
    name: Wait for Approval
    type: interrupt
    depends_on: [setup]
    message: "Please approve to continue"
    resume_key: "approval"
  
  - id: finish
    name: Finish
    type: bash
    script: echo "workflow completed"
    depends_on: [interrupt_approval]
"""
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(workflow_yaml)
    
    workflow_def = load_workflow(str(workflow_file))
    checkpoint_store = CheckpointStore(str(tmp_path / ".dag-checkpoints"))
    
    result = execute_workflow(
        workflow_def,
        inputs={},
        checkpoint_store=checkpoint_store
    )
    
    # Workflow should be paused
    assert result.status == WorkflowStatus.PAUSED
    
    # Setup node should be completed
    setup_node = next(n for n in result.nodes if n.id == "setup")
    assert setup_node.status == NodeStatus.COMPLETED
    
    # Interrupt node should be interrupted
    interrupt_node = next(n for n in result.nodes if n.id == "interrupt_approval")
    assert interrupt_node.status == NodeStatus.INTERRUPTED
    
    # Finish node should be skipped (workflow interrupted before it could execute)
    finish_node = next(n for n in result.nodes if n.id == "finish")
    assert finish_node.status == NodeStatus.SKIPPED


def test_interrupt_saves_checkpoint(tmp_path):
    """Test that interrupt checkpoint file is written with message, resume_key, state."""
    workflow_yaml = """
name: interrupt_checkpoint_test
config:
  checkpoint_prefix: .dag-checkpoints
nodes:
  - id: interrupt_node
    name: Interrupt Test
    type: interrupt
    message: "Checkpoint test"
    resume_key: "test_value"
    channels: ["terminal", "slack"]
    timeout: 60
"""
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(workflow_yaml)
    
    workflow_def = load_workflow(str(workflow_file))
    checkpoint_store = CheckpointStore(str(tmp_path / ".dag-checkpoints"))
    
    result = execute_workflow(
        workflow_def,
        inputs={},
        checkpoint_store=checkpoint_store
    )
    assert result.status == WorkflowStatus.PAUSED

    # Check interrupt checkpoint file exists
    checkpoint_dir = tmp_path / ".dag-checkpoints" / f"interrupt_checkpoint_test-{result.run_id}"
    interrupt_checkpoint = checkpoint_dir / "interrupt.json"
    assert interrupt_checkpoint.exists()
    
    # Verify checkpoint content
    with open(interrupt_checkpoint) as f:
        checkpoint_data = json.load(f)
    
    assert checkpoint_data["node_id"] == "interrupt_node"
    assert checkpoint_data["message"] == "Checkpoint test"
    assert checkpoint_data["resume_key"] == "test_value"
    assert checkpoint_data["channels"] == ["terminal", "slack"]
    assert checkpoint_data["timeout"] == 60


def test_resume_injects_value_and_continues(tmp_path):
    """Test that resume with value makes interrupted node complete, downstream executes."""
    workflow_yaml = """
name: resume_test
config:
  checkpoint_prefix: .dag-checkpoints
inputs:
  user_approval:
    type: string
    required: false
nodes:
  - id: interrupt_node
    name: Wait for Input
    type: interrupt
    message: "Provide approval"
    resume_key: "user_approval"
  
  - id: process_approval
    name: Process Approval
    type: bash
    depends_on: [interrupt_node]
    script: 'echo "Approval received: $user_approval"'
"""
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(workflow_yaml)
    
    workflow_def = load_workflow(str(workflow_file))
    checkpoint_store = CheckpointStore(str(tmp_path / ".dag-checkpoints"))
    
    # First execution - should pause
    result1 = execute_workflow(
        workflow_def,
        inputs={},
        checkpoint_store=checkpoint_store
    )
    assert result1.status == WorkflowStatus.PAUSED
    run_id = result1.run_id
    
    # Resume with value
    result2 = resume_workflow(
        workflow_name=workflow_def.name,
        run_id=run_id,
        checkpoint_store=checkpoint_store,
        workflow_def=workflow_def,
        resume_values={"user_approval": "APPROVED"}
    )
    
    # Workflow should now complete
    assert result2.status == WorkflowStatus.COMPLETED
    
    # Both nodes should be completed
    interrupt_node = next(n for n in result2.nodes if n.id == "interrupt_node")
    assert interrupt_node.status == NodeStatus.COMPLETED
    
    process_node = next(n for n in result2.nodes if n.id == "process_approval")
    assert process_node.status == NodeStatus.COMPLETED


def test_interrupt_emits_events(tmp_path):
    """Test that NODE_INTERRUPTED and WORKFLOW_INTERRUPTED events are emitted."""
    workflow_yaml = """
name: event_test
config:
  checkpoint_prefix: .dag-checkpoints
nodes:
  - id: interrupt_node
    name: Interrupt Event Test
    type: interrupt
    message: "Event test"
    resume_key: "test"
"""
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(workflow_yaml)
    
    workflow_def = load_workflow(str(workflow_file))
    checkpoint_store = CheckpointStore(str(tmp_path / ".dag-checkpoints"))
    
    # Capture events
    events = []
    event_emitter = EventEmitter()
    
    def event_listener(event):
        events.append(event)
    
    event_emitter.add_listener(event_listener)
    
    # Execute with event emitter
    from dag_executor.executor import WorkflowExecutor
    import asyncio
    
    executor = WorkflowExecutor()
    result = asyncio.run(
        executor.execute(
            workflow_def, {}, 10,
            event_emitter=event_emitter,
            checkpoint_store=checkpoint_store
        )
    )
    
    assert result.status == WorkflowStatus.PAUSED
    
    # Check for NODE_INTERRUPTED event
    node_interrupted_events = [e for e in events if e.event_type == EventType.NODE_INTERRUPTED]
    assert len(node_interrupted_events) == 1
    assert node_interrupted_events[0].node_id == "interrupt_node"
    
    # Check for WORKFLOW_INTERRUPTED event
    workflow_interrupted_events = [e for e in events if e.event_type == EventType.WORKFLOW_INTERRUPTED]
    assert len(workflow_interrupted_events) == 1


def test_interrupt_with_condition_true(tmp_path):
    """Test that interrupt fires when condition is true."""
    workflow_yaml = """
name: condition_true_test
config:
  checkpoint_prefix: .dag-checkpoints
inputs:
  needs_approval:
    type: boolean
    required: true
nodes:
  - id: conditional_interrupt
    name: Conditional Interrupt
    type: interrupt
    message: "Approval needed"
    resume_key: "approval"
    condition: "needs_approval == True"
"""
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(workflow_yaml)
    
    workflow_def = load_workflow(str(workflow_file))
    checkpoint_store = CheckpointStore(str(tmp_path / ".dag-checkpoints"))
    
    result = execute_workflow(
        workflow_def,
        inputs={"needs_approval": True},
        checkpoint_store=checkpoint_store
    )
    
    # Should be paused because condition is true
    assert result.status == WorkflowStatus.PAUSED
    node = next(n for n in result.nodes if n.id == "conditional_interrupt")
    assert node.status == NodeStatus.INTERRUPTED


def test_interrupt_with_condition_false(tmp_path):
    """Test that interrupt is skipped (node completes) when condition is false."""
    workflow_yaml = """
name: condition_false_test
config:
  checkpoint_prefix: .dag-checkpoints
inputs:
  needs_approval:
    type: boolean
    required: true
nodes:
  - id: conditional_interrupt
    name: Conditional Interrupt
    type: interrupt
    message: "Approval needed"
    resume_key: "approval"
    condition: "needs_approval == True"
"""
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(workflow_yaml)
    
    workflow_def = load_workflow(str(workflow_file))
    checkpoint_store = CheckpointStore(str(tmp_path / ".dag-checkpoints"))
    
    result = execute_workflow(
        workflow_def,
        inputs={"needs_approval": False},
        checkpoint_store=checkpoint_store
    )
    
    # Should complete because condition is false (auto-approved)
    assert result.status == WorkflowStatus.COMPLETED
    node = next(n for n in result.nodes if n.id == "conditional_interrupt")
    assert node.status == NodeStatus.COMPLETED


def test_interrupt_timeout_field(tmp_path):
    """Test that timeout field is parsed and stored in checkpoint."""
    workflow_yaml = """
name: timeout_test
config:
  checkpoint_prefix: .dag-checkpoints
nodes:
  - id: interrupt_with_timeout
    name: Interrupt With Timeout
    type: interrupt
    message: "Timeout test"
    resume_key: "value"
    timeout: 120
"""
    workflow_file = tmp_path / "workflow.yaml"
    workflow_file.write_text(workflow_yaml)
    
    workflow_def = load_workflow(str(workflow_file))
    checkpoint_store = CheckpointStore(str(tmp_path / ".dag-checkpoints"))
    
    result = execute_workflow(
        workflow_def,
        inputs={},
        checkpoint_store=checkpoint_store
    )
    assert result.status == WorkflowStatus.PAUSED

    # Verify timeout in checkpoint
    checkpoint_dir = tmp_path / ".dag-checkpoints" / f"timeout_test-{result.run_id}"
    interrupt_checkpoint = checkpoint_dir / "interrupt.json"
    
    with open(interrupt_checkpoint) as f:
        checkpoint_data = json.load(f)
    
    assert checkpoint_data["timeout"] == 120
