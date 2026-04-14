"""Tests for gate runner."""
import pytest
from dag_executor.schema import NodeDef, NodeStatus
from dag_executor.runners.base import RunnerContext
from dag_executor.runners.gate import GateRunner


@pytest.fixture
def gate_node():
    """Create a gate node definition."""
    return NodeDef(
        id="gate1",
        name="Test Gate",
        type="gate",
        condition="approved == True"
    )


def test_gate_simple_boolean_true(gate_node):
    """Test simple boolean condition that evaluates to true."""
    ctx = RunnerContext(
        node_def=gate_node,
        resolved_inputs={"approved": True}
    )
    
    runner = GateRunner()
    result = runner.run(ctx)
    
    assert result.status == NodeStatus.COMPLETED


def test_gate_simple_boolean_false(gate_node):
    """Test simple boolean condition that evaluates to false."""
    ctx = RunnerContext(
        node_def=gate_node,
        resolved_inputs={"approved": False}
    )
    
    runner = GateRunner()
    result = runner.run(ctx)
    
    assert result.status == NodeStatus.FAILED


def test_gate_comparison_operators():
    """Test comparison operators work."""
    # Greater than
    node = NodeDef(id="g1", name="Gate", type="gate", condition="count > 5")
    ctx = RunnerContext(node_def=node, resolved_inputs={"count": 10})
    assert GateRunner().run(ctx).status == NodeStatus.COMPLETED
    
    ctx.resolved_inputs["count"] = 3
    assert GateRunner().run(ctx).status == NodeStatus.FAILED
    
    # Equality
    node.condition = "status == 'active'"
    ctx.resolved_inputs = {"status": "active"}
    assert GateRunner().run(ctx).status == NodeStatus.COMPLETED


def test_gate_boolean_logic():
    """Test boolean logic operators."""
    node = NodeDef(
        id="g1",
        name="Gate",
        type="gate",
        condition="a == True and b == False"
    )
    
    ctx = RunnerContext(
        node_def=node,
        resolved_inputs={"a": True, "b": False}
    )
    assert GateRunner().run(ctx).status == NodeStatus.COMPLETED
    
    ctx.resolved_inputs["b"] = True
    assert GateRunner().run(ctx).status == NodeStatus.FAILED


def test_gate_rejects_import():
    """Test gate rejects __import__ expressions."""
    node = NodeDef(
        id="g1",
        name="Gate",
        type="gate",
        condition="__import__('os').system('ls')"
    )
    
    ctx = RunnerContext(node_def=node)
    result = GateRunner().run(ctx)
    
    assert result.status == NodeStatus.FAILED
    assert any(word in result.error.lower() for word in ["not permitted", "invalid", "not defined", "evaluation failed"])


def test_gate_rejects_exec():
    """Test gate rejects exec() calls."""
    node = NodeDef(
        id="g1",
        name="Gate",
        type="gate",
        condition="exec('import os')"
    )
    
    ctx = RunnerContext(node_def=node)
    result = GateRunner().run(ctx)
    
    assert result.status == NodeStatus.FAILED


def test_gate_rejects_eval():
    """Test gate rejects eval() calls."""
    node = NodeDef(
        id="g1",
        name="Gate",
        type="gate",
        condition="eval('1+1')"
    )
    
    ctx = RunnerContext(node_def=node)
    result = GateRunner().run(ctx)
    
    assert result.status == NodeStatus.FAILED


def test_gate_rejects_dunder_attributes():
    """Test gate rejects __ attribute access."""
    node = NodeDef(
        id="g1",
        name="Gate",
        type="gate",
        condition="x.__class__.__bases__"
    )
    
    ctx = RunnerContext(
        node_def=node,
        resolved_inputs={"x": "test"}
    )
    result = GateRunner().run(ctx)
    
    assert result.status == NodeStatus.FAILED


def test_gate_field_access():
    """Test field access from resolved inputs works."""
    node = NodeDef(
        id="g1",
        name="Gate",
        type="gate",
        condition="user_count > threshold"
    )
    
    ctx = RunnerContext(
        node_def=node,
        resolved_inputs={"user_count": 100, "threshold": 50}
    )
    result = GateRunner().run(ctx)
    
    assert result.status == NodeStatus.COMPLETED
