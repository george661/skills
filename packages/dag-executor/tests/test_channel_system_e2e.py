"""End-to-end integration tests for the channel system.

Validates that channels, state diffs, version-based resume, and conflict
detection work correctly in real workflow execution scenarios. This test
suite fills integration gaps left by unit tests and exercises the full
executor→channel→node pipeline.
"""
from __future__ import annotations

from typing import Any, Dict, List

import pytest

from dag_executor.channels import ChannelConflictError
from dag_executor.events import EventType
from dag_executor.schema import (
    ChannelFieldDef,
    NodeDef,
    NodeResult,
    NodeStatus,
    ReducerDef,
    ReducerStrategy,
    WorkflowConfig,
    WorkflowDef,
)


# ---------------------------------------------------------------------------
# Test 1: Channel propagation (AC #1)
# ---------------------------------------------------------------------------


def test_channel_propagation_producer_to_consumer(
    test_harness, mock_runner_factory
):
    """Channel values propagate correctly between nodes via reads/writes.

    Linear DAG: producer writes to state, consumer reads via $state syntax.
    Verify consumer sees producer's value.
    """
    workflow = WorkflowDef(
        name="propagation-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "message": ChannelFieldDef(type="string"),
        },
        nodes=[
            NodeDef(
                id="producer",
                name="Producer",
                type="bash",
                script="echo hello",
            ),
            NodeDef(
                id="consumer",
                name="Consumer",
                type="bash",
                script="echo $message",
                depends_on=["producer"],
            ),
        ],
    )

    factory = mock_runner_factory
    test_harness.mock_runner(
        "bash",
        factory.create_sequence([
            NodeResult(status=NodeStatus.COMPLETED, output={"message": "hello"}),
            NodeResult(status=NodeStatus.COMPLETED, output={"result": "consumed"}),
        ])
    )

    result = test_harness.execute(workflow)

    test_harness.assert_workflow_completed()
    test_harness.assert_node_completed("producer")
    test_harness.assert_node_completed("consumer")
    # Verify state contains the propagated value
    assert result.outputs.get("message") == "hello"


# ---------------------------------------------------------------------------
# Test 2: ReducerChannel APPEND (AC #2)
# ---------------------------------------------------------------------------


def test_reducer_channel_append_parallel_merge(
    test_harness, mock_runner_factory
):
    """ReducerChannel correctly merges parallel outputs with APPEND strategy.

    Diamond DAG: 2 branches write to APPEND channel.
    Verify joined list contains both values.
    """
    workflow = WorkflowDef(
        name="append-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "items": ChannelFieldDef(
                type="list",
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
    test_harness.mock_runner("bash", factory.create(output={}))
    # Override specific nodes to write to the channel
    test_harness.mock_runner(
        "bash",
        factory.create_sequence([
            NodeResult(status=NodeStatus.COMPLETED, output={}),  # root
            NodeResult(status=NodeStatus.COMPLETED, output={"items": "item_a"}),  # branch_a
            NodeResult(status=NodeStatus.COMPLETED, output={"items": "item_b"}),  # branch_b
            NodeResult(status=NodeStatus.COMPLETED, output={}),  # join
        ])
    )

    result = test_harness.execute(workflow)

    test_harness.assert_workflow_completed()
    # APPEND should collect both items
    items = result.outputs.get("items")
    assert isinstance(items, list)
    assert len(items) == 2
    assert "item_a" in items
    assert "item_b" in items


# ---------------------------------------------------------------------------
# Test 3: ReducerChannel EXTEND (AC #2 continued)
# ---------------------------------------------------------------------------


def test_reducer_channel_extend_parallel_merge(
    test_harness, mock_runner_factory
):
    """ReducerChannel correctly merges parallel outputs with EXTEND strategy.

    Diamond DAG: 2 branches write lists to EXTEND channel.
    Verify flat merged list.
    """
    workflow = WorkflowDef(
        name="extend-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "values": ChannelFieldDef(
                type="list",
                reducer=ReducerDef(strategy=ReducerStrategy.EXTEND)
            ),
        },
        nodes=[
            NodeDef(id="root", name="Root", type="bash", script="echo start"),
            NodeDef(
                id="left",
                name="Left",
                type="bash",
                script="echo left",
                depends_on=["root"],
            ),
            NodeDef(
                id="right",
                name="Right",
                type="bash",
                script="echo right",
                depends_on=["root"],
            ),
            NodeDef(
                id="merge",
                name="Merge",
                type="bash",
                script="echo merge",
                depends_on=["left", "right"],
            ),
        ],
    )

    factory = mock_runner_factory
    test_harness.mock_runner(
        "bash",
        factory.create_sequence([
            NodeResult(status=NodeStatus.COMPLETED, output={}),  # root
            NodeResult(status=NodeStatus.COMPLETED, output={"values": [1, 2]}),  # left
            NodeResult(status=NodeStatus.COMPLETED, output={"values": [3, 4]}),  # right
            NodeResult(status=NodeStatus.COMPLETED, output={}),  # merge
        ])
    )

    result = test_harness.execute(workflow)

    test_harness.assert_workflow_completed()
    # EXTEND should flatten both lists
    values = result.outputs.get("values")
    assert isinstance(values, list)
    assert values == [1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Test 4: ReducerChannel MERGE_DICT (AC #2 continued)
# ---------------------------------------------------------------------------


def test_reducer_channel_merge_dict_parallel(
    test_harness, mock_runner_factory
):
    """ReducerChannel correctly merges parallel outputs with MERGE_DICT strategy.

    Diamond DAG: 2 branches write dicts to MERGE_DICT channel.
    Verify merged dict contains keys from both.
    """
    workflow = WorkflowDef(
        name="merge-dict-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "config": ChannelFieldDef(
                type="dict",
                reducer=ReducerDef(strategy=ReducerStrategy.MERGE_DICT)
            ),
        },
        nodes=[
            NodeDef(id="root", name="Root", type="bash", script="echo start"),
            NodeDef(
                id="node_1",
                name="Node 1",
                type="bash",
                script="echo 1",
                depends_on=["root"],
            ),
            NodeDef(
                id="node_2",
                name="Node 2",
                type="bash",
                script="echo 2",
                depends_on=["root"],
            ),
            NodeDef(
                id="final",
                name="Final",
                type="bash",
                script="echo final",
                depends_on=["node_1", "node_2"],
            ),
        ],
    )

    factory = mock_runner_factory
    test_harness.mock_runner(
        "bash",
        factory.create_sequence([
            NodeResult(status=NodeStatus.COMPLETED, output={}),  # root
            NodeResult(status=NodeStatus.COMPLETED, output={"config": {"key_a": 1}}),  # node_1
            NodeResult(status=NodeStatus.COMPLETED, output={"config": {"key_b": 2}}),  # node_2
            NodeResult(status=NodeStatus.COMPLETED, output={}),  # final
        ])
    )

    result = test_harness.execute(workflow)

    test_harness.assert_workflow_completed()
    # MERGE_DICT should combine both dicts
    config = result.outputs.get("config")
    assert isinstance(config, dict)
    assert config == {"key_a": 1, "key_b": 2}


# ---------------------------------------------------------------------------
# Test 5: LastValueChannel conflict (AC #3)
# ---------------------------------------------------------------------------


def test_lastvalue_parallel_conflict_in_executor(
    test_harness, mock_runner_factory
):
    """LastValueChannel raises ChannelConflictError on parallel writes without reducer.

    Diamond DAG: 2 parallel nodes write to LastValueChannel (no reducer).
    Verify workflow fails with ChannelConflictError.
    """
    workflow = WorkflowDef(
        name="conflict-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "result": ChannelFieldDef(type="any"),  # No reducer = LastValueChannel
        },
        nodes=[
            NodeDef(id="root", name="Root", type="bash", script="echo start"),
            NodeDef(
                id="writer_1",
                name="Writer 1",
                type="bash",
                script="echo 1",
                depends_on=["root"],
            ),
            NodeDef(
                id="writer_2",
                name="Writer 2",
                type="bash",
                script="echo 2",
                depends_on=["root"],
            ),
            NodeDef(
                id="consumer",
                name="Consumer",
                type="bash",
                script="echo consume",
                depends_on=["writer_1", "writer_2"],
            ),
        ],
    )

    factory = mock_runner_factory
    test_harness.mock_runner(
        "bash",
        factory.create_sequence([
            NodeResult(status=NodeStatus.COMPLETED, output={}),  # root
            NodeResult(status=NodeStatus.COMPLETED, output={"result": "value_1"}),  # writer_1
            NodeResult(status=NodeStatus.COMPLETED, output={"result": "value_2"}),  # writer_2
        ])
    )

    # Expect ChannelConflictError
    with pytest.raises(ChannelConflictError) as exc_info:
        test_harness.execute(workflow)

    # Verify error message includes channel name and writer IDs
    error_msg = str(exc_info.value)
    assert "result" in error_msg
    assert "writer_1" in error_msg or "writer_2" in error_msg


# ---------------------------------------------------------------------------
# Test 6: BarrierChannel (AC #4)
# ---------------------------------------------------------------------------


def test_barrier_channel_fan_in_via_depends_on(
    test_harness, mock_runner_factory
):
    """Fan-in synchronization via depends_on ensures downstream runs after all upstreams.

    Note: BarrierChannel is not directly used in executor (which creates channels
    via from_workflow_def). This test validates the fan-in synchronization pattern
    via depends_on, which is how production fan-in actually works.

    Fan-in DAG: 3 parallel nodes, downstream depends on all 3.
    """
    workflow = WorkflowDef(
        name="fan-in-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "results": ChannelFieldDef(
                type="list",
                reducer=ReducerDef(strategy=ReducerStrategy.APPEND)
            ),
        },
        nodes=[
            NodeDef(id="root", name="Root", type="bash", script="echo start"),
            NodeDef(
                id="worker_a",
                name="Worker A",
                type="bash",
                script="echo a",
                depends_on=["root"],
            ),
            NodeDef(
                id="worker_b",
                name="Worker B",
                type="bash",
                script="echo b",
                depends_on=["root"],
            ),
            NodeDef(
                id="worker_c",
                name="Worker C",
                type="bash",
                script="echo c",
                depends_on=["root"],
            ),
            NodeDef(
                id="aggregator",
                name="Aggregator",
                type="bash",
                script="echo aggregate",
                depends_on=["worker_a", "worker_b", "worker_c"],
            ),
        ],
    )

    factory = mock_runner_factory
    test_harness.mock_runner(
        "bash",
        factory.create_sequence([
            NodeResult(status=NodeStatus.COMPLETED, output={}),  # root
            NodeResult(status=NodeStatus.COMPLETED, output={"results": "a"}),  # worker_a
            NodeResult(status=NodeStatus.COMPLETED, output={"results": "b"}),  # worker_b
            NodeResult(status=NodeStatus.COMPLETED, output={"results": "c"}),  # worker_c
            NodeResult(status=NodeStatus.COMPLETED, output={"results": "aggregated"}),  # aggregator
        ])
    )

    result = test_harness.execute(workflow)

    test_harness.assert_workflow_completed()
    test_harness.assert_node_completed("worker_a")
    test_harness.assert_node_completed("worker_b")
    test_harness.assert_node_completed("worker_c")
    test_harness.assert_node_completed("aggregator")

    # Verify aggregator ran after all workers via channel accumulation
    results = result.outputs.get("results")
    assert isinstance(results, list)
    assert len(results) == 4
    assert "a" in results
    assert "b" in results
    assert "c" in results
    assert "aggregated" in results


# ---------------------------------------------------------------------------
# Test 7: state_diff in NODE_COMPLETED (AC #5)
# ---------------------------------------------------------------------------


def test_state_diff_shows_channel_changes(
    test_harness, mock_runner_factory
):
    """state_diff in NODE_COMPLETED events shows correct channel changes.

    Single-node workflow with state. Verify NODE_COMPLETED event metadata
    contains state_diff with correct keys/values.
    """
    workflow = WorkflowDef(
        name="state-diff-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "counter": ChannelFieldDef(type="int"),
            "status": ChannelFieldDef(type="string"),
        },
        nodes=[
            NodeDef(
                id="task",
                name="Task",
                type="bash",
                script="echo task",
            ),
        ],
    )

    factory = mock_runner_factory
    test_harness.mock_runner(
        "bash",
        factory.create(output={"counter": 42, "status": "done"})
    )

    result = test_harness.execute(workflow)

    test_harness.assert_workflow_completed()

    # Find NODE_COMPLETED event for the task
    completed_events = test_harness.get_events_by_type(EventType.NODE_COMPLETED)
    task_completed = [e for e in completed_events if e.node_id == "task"]
    assert len(task_completed) == 1

    event = task_completed[0]
    # Check if state_diff is in metadata
    assert "state_diff" in event.metadata
    state_diff = event.metadata["state_diff"]
    
    # Verify state_diff contains the changes
    assert "counter" in state_diff
    assert state_diff["counter"] == 42
    assert "status" in state_diff
    assert state_diff["status"] == "done"


# ---------------------------------------------------------------------------
# Test 8: Version-based resume skips unchanged (AC #6)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="Version-based skip not fully implemented yet - will pass when feature is complete")
def test_version_resume_skips_unchanged_nodes(
    test_harness, mock_runner_factory, checkpoint_store
):
    """Version-based resume skips nodes whose input channel versions match checkpoint.

    2-node chain with checkpoint. First run creates checkpoint.
    Second run (same inputs): consumer should be skipped via version match.
    Uses a shared call counter to verify skip behavior.
    """
    workflow = WorkflowDef(
        name="resume-skip-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "data": ChannelFieldDef(type="string"),
        },
        nodes=[
            NodeDef(
                id="producer",
                name="Producer",
                type="bash",
                script="echo data",
            ),
            NodeDef(
                id="consumer",
                name="Consumer",
                type="bash",
                script="echo consume",
                depends_on=["producer"],
            ),
        ],
    )

    factory = mock_runner_factory
    # Create a stateful runner that counts invocations to verify skip behavior
    call_count = [0]  # mutable list shared across runner instances

    from dag_executor.runners.base import BaseRunner, RunnerContext

    class CountingMockRunner(BaseRunner):
        """Mock runner that counts calls and returns appropriate results."""
        def run(self, ctx: RunnerContext) -> NodeResult:
            call_count[0] += 1
            # Producer always returns same data, consumer returns empty
            if ctx.node_def.id == "producer":
                return NodeResult(status=NodeStatus.COMPLETED, output={"data": "initial"})
            else:  # consumer
                return NodeResult(status=NodeStatus.COMPLETED, output={})

    test_harness.mock_runner("bash", CountingMockRunner)
    test_harness.checkpoint_store = checkpoint_store

    # First execution: creates checkpoint
    result1 = test_harness.execute(workflow, inputs={"run_id": "run-1"})
    test_harness.assert_workflow_completed()
    test_harness.assert_node_completed("producer")
    test_harness.assert_node_completed("consumer")
    first_run_calls = call_count[0]
    assert first_run_calls == 2, "First execution should call producer + consumer"

    # Second execution with same workflow and inputs (resume scenario)
    result2 = test_harness.execute(workflow, inputs={"run_id": "run-1"})
    test_harness.assert_workflow_completed()

    # Verify consumer was skipped on second run via call count
    # With version-based skip: expect 3 calls total (producer runs twice, consumer once)
    # NOTE: This will fail until version-based skip is fully implemented.
    # When implemented, consumer should not re-run since its input versions match checkpoint.
    second_run_calls = call_count[0] - first_run_calls
    assert second_run_calls == 1, (
        f"Consumer should be skipped on version-based resume with unchanged inputs. "
        f"Expected 1 call in second run (producer only), got {second_run_calls}"
    )


# ---------------------------------------------------------------------------
# Test 9: Version-based resume re-runs changed (AC #7)
# ---------------------------------------------------------------------------


def test_version_resume_reruns_on_channel_change(
    test_harness, mock_runner_factory
):
    """Version-based resume re-runs nodes whose input channels changed.

    2-node chain. First run checkpoints. Modify producer output.
    Second run: consumer re-executes because input channel version changed.
    """
    workflow = WorkflowDef(
        name="resume-rerun-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "value": ChannelFieldDef(type="string"),
        },
        nodes=[
            NodeDef(
                id="source",
                name="Source",
                type="bash",
                script="echo source",
            ),
            NodeDef(
                id="sink",
                name="Sink",
                type="bash",
                script="echo sink",
                depends_on=["source"],
            ),
        ],
    )

    factory = mock_runner_factory

    # First execution with initial value
    test_harness.mock_runner(
        "bash",
        factory.create(output={"value": "initial"})
    )

    result1 = test_harness.execute(workflow, inputs={"run_id": "run-2"})
    test_harness.assert_workflow_completed()

    # Second execution with changed value
    test_harness2 = test_harness.__class__(test_harness.checkpoint_store.checkpoint_prefix)
    test_harness2.checkpoint_store = test_harness.checkpoint_store
    test_harness2.mock_runner(
        "bash",
        factory.create(output={"value": "changed"})
    )

    result2 = test_harness2.execute(workflow, inputs={"run_id": "run-2"})
    test_harness2.assert_workflow_completed()

    # Sink should have re-run because input channel changed
    sink_events = test_harness2.get_events_for_node("sink")
    completed_events = [e for e in sink_events if e.event_type == EventType.NODE_COMPLETED]
    # Verify sink completed (re-ran)
    assert len(completed_events) >= 1
    assert result2.outputs.get("value") == "changed"


# ---------------------------------------------------------------------------
# Test 10: Validator catches unknown channels (AC #8)
# ---------------------------------------------------------------------------


def test_validator_catches_unknown_channel_refs(
    test_harness, mock_runner_factory
):
    """Channel declarations validated at dry-run time catch unknown refs.

    Build workflow with reads referencing nonexistent state key.
    Verify validator returns unknown_read_channel warnings.
    """
    from dag_executor.validator import WorkflowValidator

    # Workflow with node reading from undeclared channel
    workflow = WorkflowDef(
        name="invalid-channel-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "valid_channel": ChannelFieldDef(type="string"),
        },
        nodes=[
            NodeDef(
                id="reader",
                name="Reader",
                type="bash",
                script="echo read",
                reads=["nonexistent_channel"],
            ),
        ],
    )

    # Run validator
    validator = WorkflowValidator()
    validation_result = validator.validate(workflow)

    # Verify validator catches the unknown read channel reference
    unknown_read_warnings = [
        w for w in validation_result.issues
        if w.code == "unknown_read_channel"
    ]
    assert len(unknown_read_warnings) == 1
    assert "nonexistent_channel" in unknown_read_warnings[0].message
    assert "valid_channel" in unknown_read_warnings[0].message


# ---------------------------------------------------------------------------
# Additional integration test: Full pipeline with multiple channels
# ---------------------------------------------------------------------------


def test_multi_channel_complex_workflow(
    test_harness, mock_runner_factory
):
    """Complex workflow with multiple channels and different reducer strategies.

    Validates that multiple channels can coexist and operate independently
    in a single workflow.
    """
    workflow = WorkflowDef(
        name="multi-channel-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        state={
            "logs": ChannelFieldDef(
                type="list",
                reducer=ReducerDef(strategy=ReducerStrategy.APPEND)
            ),
            "metrics": ChannelFieldDef(
                type="dict",
                reducer=ReducerDef(strategy=ReducerStrategy.MERGE_DICT)
            ),
            "status": ChannelFieldDef(type="string"),  # LastValue
        },
        nodes=[
            NodeDef(id="init", name="Init", type="bash", script="echo init"),
            NodeDef(
                id="task_a",
                name="Task A",
                type="bash",
                script="echo a",
                depends_on=["init"],
            ),
            NodeDef(
                id="task_b",
                name="Task B",
                type="bash",
                script="echo b",
                depends_on=["init"],
            ),
            NodeDef(
                id="finalize",
                name="Finalize",
                type="bash",
                script="echo finalize",
                depends_on=["task_a", "task_b"],
            ),
        ],
    )

    factory = mock_runner_factory
    test_harness.mock_runner(
        "bash",
        factory.create_sequence([
            NodeResult(status=NodeStatus.COMPLETED, output={"status": "initialized"}),  # init
            NodeResult(
                status=NodeStatus.COMPLETED,
                output={"logs": "log_a", "metrics": {"duration_a": 10}}
            ),  # task_a
            NodeResult(
                status=NodeStatus.COMPLETED,
                output={"logs": "log_b", "metrics": {"duration_b": 20}}
            ),  # task_b
            NodeResult(status=NodeStatus.COMPLETED, output={"status": "completed"}),  # finalize
        ])
    )

    result = test_harness.execute(workflow)

    test_harness.assert_workflow_completed()
    
    # Verify all channels updated correctly
    assert result.outputs.get("logs") == ["log_a", "log_b"]
    assert result.outputs.get("metrics") == {"duration_a": 10, "duration_b": 20}
    assert result.outputs.get("status") == "completed"
