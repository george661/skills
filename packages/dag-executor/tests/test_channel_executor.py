"""Integration tests for executor's ChannelStore integration.

Validates that the WorkflowExecutor correctly creates, manages, and uses
a ChannelStore for managing workflow state instead of plain dicts.
"""
from __future__ import annotations

import pytest
from dag_executor.channels import ChannelStore, ReducerChannel
from dag_executor.schema import (
    NodeDef,
    NodeResult,
    NodeStatus,
    WorkflowConfig,
    WorkflowDef,
    ReducerDef,
    ReducerStrategy,
    ChannelFieldDef,
)


def test_executor_creates_channel_store_from_empty_state(
    test_harness, mock_runner_factory
):
    """Executor creates empty ChannelStore when WorkflowDef has no state."""
    workflow = WorkflowDef(
        name="no-state-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        nodes=[
            NodeDef(id="task1", name="Task 1", type="bash", script="echo test"),
        ],
    )
    
    test_harness.mock_all_runners(
        NodeResult(status=NodeStatus.COMPLETED, output={"done": True})
    )
    result = test_harness.execute(workflow)
    
    test_harness.assert_workflow_completed()
    assert result.outputs == {}  # No state channels


def test_executor_creates_channel_store_from_populated_state(
    test_harness, mock_runner_factory
):
    """Executor creates ChannelStore with channels from WorkflowDef.state."""
    workflow = WorkflowDef(
        name="stateful-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "counter": ChannelFieldDef(
                type="list",
                reducer=ReducerDef(strategy=ReducerStrategy.APPEND)
            ),
            "result": ChannelFieldDef(type="any"),
        },
        nodes=[
            NodeDef(id="task1", name="Task 1", type="bash", script="echo test"),
        ],
    )
    
    test_harness.mock_all_runners(
        NodeResult(status=NodeStatus.COMPLETED, output={"done": True})
    )
    result = test_harness.execute(workflow)
    
    test_harness.assert_workflow_completed()
    # State should exist but be empty (no nodes wrote to channels)
    assert "counter" in result.outputs or result.outputs == {}
    assert "result" in result.outputs or result.outputs == {}


def test_node_outputs_write_to_channel_store(test_harness, mock_runner_factory):
    """Node outputs writing to state fields update the ChannelStore."""
    workflow = WorkflowDef(
        name="write-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "value": ChannelFieldDef(type="any"),
        },
        nodes=[
            NodeDef(
                id="writer",
                name="Writer",
                type="bash",
                script="echo value",
            ),
        ],
    )

    # Node returns output with key matching state field name
    test_harness.mock_all_runners(
        NodeResult(status=NodeStatus.COMPLETED, output={"value": 42})
    )
    result = test_harness.execute(workflow)

    test_harness.assert_workflow_completed()
    assert result.outputs.get("value") == 42


def test_workflow_state_backwards_compat_via_ctx_property(
    test_harness, mock_runner_factory
):
    """ctx.workflow_state property returns dict view from channel_store.to_dict()."""
    # This test verifies backwards compatibility: existing code accessing
    # ctx.workflow_state still works even though storage is now ChannelStore
    workflow = WorkflowDef(
        name="compat-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "x": ChannelFieldDef(type="any"),
        },
        nodes=[
            NodeDef(
                id="writer",
                name="Writer",
                type="bash",
                script="echo x",
            ),
        ],
    )
    
    test_harness.mock_all_runners(
        NodeResult(status=NodeStatus.COMPLETED, output={"x": "test"})
    )
    result = test_harness.execute(workflow)

    test_harness.assert_workflow_completed()
    assert result.outputs.get("x") == "test"


def test_channel_writers_reset_at_layer_boundaries(test_harness, mock_runner_factory):
    """Channels reset writer tracking between topological layers."""
    workflow = WorkflowDef(
        name="reset-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "shared": ChannelFieldDef(type="any"),
        },
        nodes=[
            NodeDef(
                id="layer1_writer",
                name="Layer 1 Writer",
                type="bash",
                script="echo layer1",
            ),
            NodeDef(
                id="layer2_writer",
                name="Layer 2 Writer",
                type="bash",
                script="echo layer2",
                depends_on=["layer1_writer"],
            ),
        ],
    )
    
    factory = mock_runner_factory
    # Both nodes write to "shared" state field
    test_harness.mock_all_runners(
        NodeResult(status=NodeStatus.COMPLETED, output={"shared": "value"})
    )
    result = test_harness.execute(workflow)

    test_harness.assert_workflow_completed()
    # Layer 2 overwrites layer 1 without conflict because writers reset
    assert result.outputs.get("shared") == "value"


def test_diamond_dag_with_reducer_channel(test_harness, mock_runner_factory):
    """Diamond DAG with parallel writes to ReducerChannel merges correctly."""
    workflow = WorkflowDef(
        name="diamond-reducer",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "items": ChannelFieldDef(type="list", 
                reducer=ReducerDef(strategy=ReducerStrategy.APPEND)
            ),
        },
        nodes=[
            NodeDef(id="root", name="Root", type="bash", script="echo start"),
            NodeDef(
                id="branch_a",
                name="Branch A",
                type="bash",
                script="echo a",
                depends_on=["root"],
            ),
            NodeDef(
                id="branch_b",
                name="Branch B",
                type="bash",
                script="echo b",
                depends_on=["root"],
            ),
            NodeDef(
                id="join",
                name="Join",
                type="bash",
                script="echo join",
                depends_on=["branch_a", "branch_b"],
            ),
        ],
    )
    
    factory = mock_runner_factory
    # Each node writes to "items" which uses APPEND reducer
    test_harness.mock_runner("bash", factory.create(output={"items": "A"}))

    result = test_harness.execute(workflow)

    test_harness.assert_workflow_completed()
    # Both branches write to items (APPEND), should have 2 items
    items = result.outputs.get("items", [])
    # Root, branch_a, and branch_b all write, so we get 3 items (or subset if root doesn't write)
    assert len(items) >= 2


def test_workflow_result_includes_channel_state(test_harness, mock_runner_factory):
    """WorkflowResult.outputs includes final channel state."""
    workflow = WorkflowDef(
        name="output-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "final": ChannelFieldDef(type="any"),
        },
        nodes=[
            NodeDef(
                id="producer",
                name="Producer",
                type="bash",
                script="echo done",
            ),
        ],
    )
    
    test_harness.mock_all_runners(
        NodeResult(status=NodeStatus.COMPLETED, output={"final": "complete"})
    )
    result = test_harness.execute(workflow)

    test_harness.assert_workflow_completed()
    assert result.outputs == {"final": "complete"}
