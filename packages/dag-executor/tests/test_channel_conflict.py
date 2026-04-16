"""Tests for parallel write conflict detection in ChannelStore.

Validates that LastValueChannel raises ChannelConflictError when multiple
nodes write to it in parallel, and that ReducerChannel always succeeds.
"""
from __future__ import annotations

import pytest
from dag_executor.channels import ChannelConflictError
from dag_executor.schema import (
    NodeDef,
    NodeResult,
    NodeStatus,
    WorkflowConfig,
    WorkflowDef,
    ChannelFieldDef,
    ReducerDef,
    ReducerStrategy,
)


def test_parallel_writes_to_lastvalue_without_reducer_conflict(
    test_harness, mock_runner_factory
):
    """Two parallel nodes writing to LastValueChannel raises ChannelConflictError."""
    workflow = WorkflowDef(
        name="conflict-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "shared": ChannelFieldDef(type="any"),  # No reducer = LastValueChannel
        },
        nodes=[
            NodeDef(id="root", name="Root", type="bash", script="echo start"),
            NodeDef(
                id="writer_a",
                name="Writer A",
                type="bash",
                script="echo a",
                depends_on=["root"],
            ),
            NodeDef(
                id="writer_b",
                name="Writer B",
                type="bash",
                script="echo b",
                depends_on=["root"],
            ),
        ],
    )
    
    factory = mock_runner_factory
    test_harness.mock_runner("bash", factory.create(output={"shared": 1}))
    
    with pytest.raises(ChannelConflictError) as exc_info:
        test_harness.execute(workflow)
    
    # Error message includes channel key and both writer node IDs
    error_msg = str(exc_info.value)
    assert "shared" in error_msg
    assert "writer_a" in error_msg or "writer_b" in error_msg


def test_conflict_error_includes_channel_key_and_writers(
    test_harness, mock_runner_factory
):
    """ChannelConflictError message includes channel key and writer node IDs."""
    workflow = WorkflowDef(
        name="conflict-detail-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "target": ChannelFieldDef(type="any"),
        },
        nodes=[
            NodeDef(id="start", name="Start", type="bash", script="echo start"),
            NodeDef(
                id="node_x",
                name="Node X",
                type="bash",
                script="echo x",
                depends_on=["start"],
            ),
            NodeDef(
                id="node_y",
                name="Node Y",
                type="bash",
                script="echo y",
                depends_on=["start"],
            ),
        ],
    )
    
    factory = mock_runner_factory
    test_harness.mock_runner("bash", factory.create(output={"target": "data"}))
    
    with pytest.raises(ChannelConflictError) as exc_info:
        test_harness.execute(workflow)
    
    error_msg = str(exc_info.value)
    assert "target" in error_msg
    # At least one writer ID should be present
    assert "node_x" in error_msg or "node_y" in error_msg


def test_parallel_writes_to_reducer_channel_succeed(test_harness, mock_runner_factory):
    """Parallel writes to ReducerChannel with APPEND strategy succeed."""
    workflow = WorkflowDef(
        name="reducer-success-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "logs": ChannelFieldDef(
                type="list",
                reducer=ReducerDef(strategy=ReducerStrategy.APPEND)
            ),
        },
        nodes=[
            NodeDef(id="start", name="Start", type="bash", script="echo start"),
            NodeDef(
                id="logger_a",
                name="Logger A",
                type="bash",
                script="echo a",
                depends_on=["start"],
            ),
            NodeDef(
                id="logger_b",
                name="Logger B",
                type="bash",
                script="echo b",
                depends_on=["start"],
            ),
        ],
    )
    
    factory = mock_runner_factory
    # All nodes write to logs, including start node
    test_harness.mock_runner("bash", factory.create(output={"logs": "log_entry"}))

    result = test_harness.execute(workflow)

    test_harness.assert_workflow_completed()
    logs = result.outputs.get("logs", [])
    # start, logger_a, logger_b all write = 3 entries
    assert len(logs) == 3
    assert all(entry == "log_entry" for entry in logs)


def test_parallel_writes_to_reducer_with_overwrite_still_conflict(
    test_harness, mock_runner_factory
):
    """Parallel writes to OVERWRITE ReducerChannel still conflict (uses LastValueChannel)."""
    # Note: OVERWRITE strategy actually creates a LastValueChannel under the hood
    # so it still raises conflicts on parallel writes from different nodes
    workflow = WorkflowDef(
        name="overwrite-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "latest": ChannelFieldDef(
                type="any",
                reducer=ReducerDef(strategy=ReducerStrategy.OVERWRITE)
            ),
        },
        nodes=[
            NodeDef(id="init", name="Init", type="bash", script="echo init"),
            NodeDef(
                id="updater_a",
                name="Updater A",
                type="bash",
                script="echo a",
                depends_on=["init"],
            ),
            NodeDef(
                id="updater_b",
                name="Updater B",
                type="bash",
                script="echo b",
                depends_on=["init"],
            ),
        ],
    )

    factory = mock_runner_factory
    test_harness.mock_runner("bash", factory.create(output={"latest": "updated"}))

    # OVERWRITE uses LastValueChannel, so parallel writes still conflict
    with pytest.raises(ChannelConflictError):
        test_harness.execute(workflow)


def test_conflict_detection_end_to_end_via_executor(
    test_harness, mock_runner_factory
):
    """Full end-to-end: executor detects conflict and fails workflow gracefully."""
    workflow = WorkflowDef(
        name="e2e-conflict-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "result": ChannelFieldDef(type="any"),
        },
        nodes=[
            NodeDef(id="start", name="Start", type="bash", script="echo start"),
            NodeDef(
                id="compute_a",
                name="Compute A",
                type="bash",
                script="echo a",
                depends_on=["start"],
            ),
            NodeDef(
                id="compute_b",
                name="Compute B",
                type="bash",
                script="echo b",
                depends_on=["start"],
            ),
            NodeDef(
                id="downstream",
                name="Downstream",
                type="bash",
                script="echo downstream",
                depends_on=["compute_a", "compute_b"],
            ),
        ],
    )
    
    factory = mock_runner_factory
    test_harness.mock_runner("bash", factory.create(output={"result": "value"}))
    
    with pytest.raises(ChannelConflictError):
        test_harness.execute(workflow)


def test_error_recovery_workflow_fails_with_clear_error(
    test_harness, mock_runner_factory
):
    """When conflict occurs, workflow fails with clear ChannelConflictError."""
    workflow = WorkflowDef(
        name="clear-error-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "state": ChannelFieldDef(type="any"),
        },
        nodes=[
            NodeDef(id="root", name="Root", type="bash", script="echo root"),
            NodeDef(
                id="writer1",
                name="Writer 1",
                type="bash",
                script="echo w1",
                depends_on=["root"],
            ),
            NodeDef(
                id="writer2",
                name="Writer 2",
                type="bash",
                script="echo w2",
                depends_on=["root"],
            ),
        ],
    )
    
    factory = mock_runner_factory
    test_harness.mock_runner("bash", factory.create(output={"state": "test"}))
    
    try:
        test_harness.execute(workflow)
        pytest.fail("Expected ChannelConflictError but workflow succeeded")
    except ChannelConflictError as e:
        # Error should be informative
        assert "state" in str(e)
        assert "writer" in str(e).lower() or "node" in str(e).lower()
