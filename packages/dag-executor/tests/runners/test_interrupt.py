"""Unit tests for InterruptRunner."""
import pytest

from dag_executor.schema import NodeDef, NodeStatus, InterruptConfig
from dag_executor.runners.interrupt import InterruptRunner
from dag_executor.runners.base import RunnerContext


def test_interrupt_runner_returns_interrupted_status():
    """Test that InterruptRunner returns INTERRUPTED status."""
    node_def = NodeDef(
        id="test_interrupt",
        name="Test Interrupt",
        type="interrupt",
        message="Test message",
        resume_key="test_key"
    )
    
    ctx = RunnerContext(
        node_def=node_def,
        resolved_inputs={}
    )
    
    runner = InterruptRunner()
    result = runner.run(ctx)
    
    assert result.status == NodeStatus.INTERRUPTED
    assert result.output is not None
    assert result.output["message"] == "Test message"
    assert result.output["resume_key"] == "test_key"


def test_interrupt_runner_condition_true():
    """Test that InterruptRunner returns INTERRUPTED when condition is true."""
    node_def = NodeDef(
        id="test_interrupt",
        name="Test Interrupt",
        type="interrupt",
        message="Approval needed",
        resume_key="approval",
        condition="needs_approval == True"
    )
    
    ctx = RunnerContext(
        node_def=node_def,
        resolved_inputs={"needs_approval": True}
    )
    
    runner = InterruptRunner()
    result = runner.run(ctx)
    
    assert result.status == NodeStatus.INTERRUPTED
    assert result.output["message"] == "Approval needed"


def test_interrupt_runner_condition_false():
    """Test that InterruptRunner returns COMPLETED when condition is false."""
    node_def = NodeDef(
        id="test_interrupt",
        name="Test Interrupt",
        type="interrupt",
        message="Approval needed",
        resume_key="approval",
        condition="needs_approval == True"
    )
    
    ctx = RunnerContext(
        node_def=node_def,
        resolved_inputs={"needs_approval": False}
    )
    
    runner = InterruptRunner()
    result = runner.run(ctx)
    
    assert result.status == NodeStatus.COMPLETED
    assert result.output["message"] == "Approval needed"
    assert result.output["auto_approved"] is True


def test_interrupt_runner_condition_evaluation():
    """Test that InterruptRunner correctly evaluates condition with resolved_inputs namespace."""
    node_def = NodeDef(
        id="test_interrupt",
        name="Test Interrupt",
        type="interrupt",
        message="Complex condition test",
        resume_key="result",
        condition="count > 5 and status == 'ready'"
    )
    
    # Condition true
    ctx1 = RunnerContext(
        node_def=node_def,
        resolved_inputs={"count": 10, "status": "ready"}
    )
    result1 = InterruptRunner().run(ctx1)
    assert result1.status == NodeStatus.INTERRUPTED
    
    # Condition false
    ctx2 = RunnerContext(
        node_def=node_def,
        resolved_inputs={"count": 3, "status": "ready"}
    )
    result2 = InterruptRunner().run(ctx2)
    assert result2.status == NodeStatus.COMPLETED
    assert result2.output["auto_approved"] is True


def test_interrupt_runner_no_condition():
    """Test that InterruptRunner always interrupts when no condition is set."""
    node_def = NodeDef(
        id="test_interrupt",
        name="Test Interrupt",
        type="interrupt",
        message="Always interrupt",
        resume_key="value"
    )
    
    ctx = RunnerContext(
        node_def=node_def,
        resolved_inputs={"some_var": "some_value"}
    )
    
    runner = InterruptRunner()
    result = runner.run(ctx)
    
    assert result.status == NodeStatus.INTERRUPTED
