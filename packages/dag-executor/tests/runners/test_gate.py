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


# GW-6041: condition strings with $-prefixed variable references must resolve
# string values via SimpleEval name-binding (not via pre-interpolation that
# turns string values into bare identifiers).
def test_gate_dollar_ref_string_value_passes():
    """`$issue_type == "Bug"` with issue_type="Bug" -> COMPLETED."""
    node = NodeDef(
        id="g1",
        name="Gate",
        type="gate",
        condition='$issue_type == "Bug"',
    )
    ctx = RunnerContext(
        node_def=node,
        resolved_inputs={"issue_type": "Bug"},
    )
    result = GateRunner().run(ctx)
    assert result.status == NodeStatus.COMPLETED, result.error


def test_gate_dollar_ref_string_value_fails_when_not_matching():
    """`$issue_type == "Bug"` with issue_type="Task" -> FAILED, no NameNotDefined."""
    node = NodeDef(
        id="g1",
        name="Gate",
        type="gate",
        condition='$issue_type == "Bug"',
    )
    ctx = RunnerContext(
        node_def=node,
        resolved_inputs={"issue_type": "Task"},
    )
    result = GateRunner().run(ctx)
    # Pre-fix this raised NameNotDefined: "'Task' is not defined" because the
    # executor pre-interpolated the value into the string, turning it into the
    # SimpleEval expression `Task == "Bug"` (Task as bare identifier).
    assert result.status == NodeStatus.FAILED
    assert "evaluated to false" in (result.error or "").lower(), result.error
    assert "not defined" not in (result.error or "").lower(), result.error


def test_gate_dollar_ref_dict_value_does_not_crash():
    """Dict-typed channel value under $ref must not surface as 'Dict not available'.

    Pre-fix: when the upstream prompt node failed and `issue_type` was a dict
    (or absent), the executor's string interpolation produced `{...} == "Bug"`,
    which SimpleEval rejected with "Sorry, Dict is not available in this
    evaluator". The fix: bind dict values as SimpleEval names so the equality
    check evaluates as Python (dict != string -> False) without surfacing a
    type-error from the evaluator.
    """
    node = NodeDef(
        id="g1",
        name="Gate",
        type="gate",
        condition='$issue_type == "Bug"',
    )
    ctx = RunnerContext(
        node_def=node,
        resolved_inputs={"issue_type": {"name": "Task"}},
    )
    result = GateRunner().run(ctx)
    assert result.status == NodeStatus.FAILED
    assert "dict is not available" not in (result.error or "").lower(), result.error


def test_gate_dollar_ref_with_braces():
    """`${issue_type} == "Bug"` (braced form) resolves identically to `$issue_type`."""
    node = NodeDef(
        id="g1",
        name="Gate",
        type="gate",
        condition='${issue_type} == "Bug"',
    )
    ctx = RunnerContext(
        node_def=node,
        resolved_inputs={"issue_type": "Bug"},
    )
    result = GateRunner().run(ctx)
    assert result.status == NodeStatus.COMPLETED, result.error


def test_gate_dollar_ref_undefined_surfaces_clean_error():
    """A `$ref` to an unbound name surfaces as 'Undefined variable in condition'.

    Distinct from `NameNotDefined` on a value-shaped identifier: this happens
    when the workflow author references a channel that doesn't exist in scope.
    """
    node = NodeDef(
        id="g1",
        name="Gate",
        type="gate",
        condition='$mystery_channel == "Bug"',
    )
    ctx = RunnerContext(node_def=node, resolved_inputs={})
    result = GateRunner().run(ctx)
    assert result.status == NodeStatus.FAILED
    assert "undefined" in (result.error or "").lower(), result.error


# GW-6062: dotted node-output references (`$node_id.field`) resolve via
# SimpleEval's dict-attribute access. The gate runner now binds each
# upstream node's output dict under both its node-id and its flat keys.
def test_gate_dollar_ref_dotted_node_output():
    """`$node.field == false` resolves via the node's output dict."""
    node = NodeDef(
        id="g1",
        name="Gate",
        type="gate",
        condition='$already_impl_check.already_implemented == false',
    )
    ctx = RunnerContext(
        node_def=node,
        node_outputs={
            "already_impl_check": {"already_implemented": False, "evidence": "not yet"}
        },
    )
    result = GateRunner().run(ctx)
    assert result.status == NodeStatus.COMPLETED, result.error


def test_gate_dollar_ref_dotted_node_output_truthy_path():
    """Same shape, but the field is True so the gate condition fails-clean."""
    node = NodeDef(
        id="g1",
        name="Gate",
        type="gate",
        condition='$already_impl_check.already_implemented == false',
    )
    ctx = RunnerContext(
        node_def=node,
        node_outputs={
            "already_impl_check": {"already_implemented": True, "evidence": "found at lib.py:42"}
        },
    )
    result = GateRunner().run(ctx)
    assert result.status == NodeStatus.FAILED
    assert "evaluated to false" in (result.error or "").lower(), result.error


def test_gate_dollar_ref_dotted_keeps_flat_binding_compat():
    """Flat top-level field bindings still work alongside nested-dict bindings.

    Backward compat: existing workflows that wrote `condition: "$some_field == X"`
    expecting flat-key access still resolve, even when the same field
    appears inside an upstream node's output dict.
    """
    node = NodeDef(
        id="g1",
        name="Gate",
        type="gate",
        condition='$flat_field == "ok"',
    )
    ctx = RunnerContext(
        node_def=node,
        node_outputs={
            "upstream": {"flat_field": "ok"}
        },
    )
    result = GateRunner().run(ctx)
    assert result.status == NodeStatus.COMPLETED, result.error
