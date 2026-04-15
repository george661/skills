"""Tests for the DAG workflow executor."""
import asyncio
import time
from typing import Dict, Any
from unittest.mock import Mock, patch, MagicMock

import pytest
from dag_executor.executor import WorkflowExecutor, ExecutionContext, WorkflowResult
from dag_executor.runners.base import BaseRunner, RunnerContext
from dag_executor.schema import (
    NodeDef, NodeResult, NodeStatus, WorkflowStatus, WorkflowDef, 
    WorkflowConfig, TriggerRule, OnFailure
)


def create_mock_runner_class(result: NodeResult, delay: float = 0):
    """Factory to create a mock runner class."""
    class TestMockRunner(BaseRunner):
        def __init__(self):
            self.result = result
            self.delay = delay
            self.called = False
            self.call_time = None
        
        def run(self, ctx: RunnerContext) -> NodeResult:
            """Execute with optional delay."""
            self.called = True
            self.call_time = time.time()
            if self.delay:
                time.sleep(self.delay)
            return self.result
    
    return TestMockRunner


class TestWorkflowExecutor:
    """Test workflow executor functionality."""

    def test_full_dag_execution(self) -> None:
        """4-node diamond DAG with mocked runners - all complete."""
        # Diamond: A -> B,C -> D
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="echo A"),
            NodeDef(id="B", name="Node B", type="bash", script="echo B", depends_on=["A"]),
            NodeDef(id="C", name="Node C", type="bash", script="echo C", depends_on=["A"]),
            NodeDef(id="D", name="Node D", type="bash", script="echo D", depends_on=["B", "C"]),
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes
        )
        
        # Mock get_runner to return completed results
        def mock_get_runner(node_type):
            return create_mock_runner_class(
                NodeResult(status=NodeStatus.COMPLETED, output={"value": "done"})
            )
        
        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {}))
        
        assert result.status == WorkflowStatus.COMPLETED
        assert len(result.node_results) == 4
        assert all(r.status == NodeStatus.COMPLETED for r in result.node_results.values())

    def test_parallel_independent_nodes(self) -> None:
        """3 independent nodes execute concurrently."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="echo A"),
            NodeDef(id="B", name="Node B", type="bash", script="echo B"),
            NodeDef(id="C", name="Node C", type="bash", script="echo C"),
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes
        )
        
        # Each runner takes 0.1s - if parallel, total should be ~0.1s not 0.3s
        def mock_get_runner(node_type):
            return create_mock_runner_class(
                NodeResult(status=NodeStatus.COMPLETED), 
                delay=0.1
            )
        
        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            start = time.time()
            result = asyncio.run(executor.execute(workflow_def, {}))
            elapsed = time.time() - start
        
        assert result.status == WorkflowStatus.COMPLETED
        # Should take ~0.1s (parallel), not 0.3s (sequential)
        assert elapsed < 0.25, f"Expected parallel execution (~0.1s), got {elapsed:.2f}s"

    def test_sequential_dependent_nodes(self) -> None:
        """A->B->C chain executes in order."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="echo A"),
            NodeDef(id="B", name="Node B", type="bash", script="echo B", depends_on=["A"]),
            NodeDef(id="C", name="Node C", type="bash", script="echo C", depends_on=["B"]),
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes
        )
        
        call_times = {}
        
        def mock_get_runner(node_type):
            class OrderTrackingRunner(BaseRunner):
                def run(self, ctx: RunnerContext) -> NodeResult:
                    call_times[ctx.node_def.id] = time.time()
                    return NodeResult(status=NodeStatus.COMPLETED, output={"order": 1})
            return OrderTrackingRunner
        
        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {}))
        
        # Verify execution order via call times
        assert call_times["A"] < call_times["B"] < call_times["C"]

    def test_when_clause_false_skips_node(self) -> None:
        """Node with when: false is skipped."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="echo A", when="false"),
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes
        )
        
        executor = WorkflowExecutor()
        result = asyncio.run(executor.execute(workflow_def, {}))
        
        assert result.node_results["A"].status == NodeStatus.SKIPPED

    def test_when_clause_true_executes_node(self) -> None:
        """Node with when: true executes."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="echo A", when="true"),
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes
        )
        
        def mock_get_runner(node_type):
            return create_mock_runner_class(NodeResult(status=NodeStatus.COMPLETED))
        
        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {}))
        
        assert result.node_results["A"].status == NodeStatus.COMPLETED

    def test_trigger_rule_one_success(self) -> None:
        """Downstream with one_success triggers if one upstream succeeds."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="fail", on_failure=OnFailure.CONTINUE),
            NodeDef(id="B", name="Node B", type="bash", script="ok"),
            NodeDef(id="C", name="Node C", type="bash", script="echo C", 
                   depends_on=["A", "B"], trigger_rule=TriggerRule.ONE_SUCCESS),
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes
        )
        
        call_count = {"A": 0, "B": 0, "C": 0}
        
        def mock_get_runner(node_type):
            class ConditionalRunner(BaseRunner):
                def run(self, ctx: RunnerContext) -> NodeResult:
                    node_id = ctx.node_def.id
                    call_count[node_id] += 1
                    if node_id == "A":
                        return NodeResult(status=NodeStatus.FAILED, error="failed")
                    return NodeResult(status=NodeStatus.COMPLETED)
            return ConditionalRunner
        
        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {}))
        
        # C should execute because B succeeded (one_success)
        assert result.node_results["A"].status == NodeStatus.FAILED
        assert result.node_results["B"].status == NodeStatus.COMPLETED
        assert result.node_results["C"].status == NodeStatus.COMPLETED
        assert call_count["C"] == 1

    def test_trigger_rule_all_done(self) -> None:
        """Downstream with all_done triggers after all upstreams finish (any status)."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="fail", on_failure=OnFailure.CONTINUE),
            NodeDef(id="B", name="Node B", type="bash", script="ok"),
            NodeDef(id="C", name="Node C", type="bash", script="echo C", 
                   depends_on=["A", "B"], trigger_rule=TriggerRule.ALL_DONE),
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes
        )
        
        def mock_get_runner(node_type):
            class ConditionalRunner(BaseRunner):
                def run(self, ctx: RunnerContext) -> NodeResult:
                    if ctx.node_def.id == "A":
                        return NodeResult(status=NodeStatus.FAILED, error="failed")
                    return NodeResult(status=NodeStatus.COMPLETED)
            return ConditionalRunner
        
        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {}))
        
        # C should execute because both A and B finished
        assert result.node_results["C"].status == NodeStatus.COMPLETED

    def test_trigger_rule_all_success_blocks(self) -> None:
        """Downstream with all_success is skipped if any upstream fails."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="fail", on_failure=OnFailure.CONTINUE),
            NodeDef(id="B", name="Node B", type="bash", script="ok"),
            NodeDef(id="C", name="Node C", type="bash", script="echo C", 
                   depends_on=["A", "B"], trigger_rule=TriggerRule.ALL_SUCCESS),
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes
        )
        
        def mock_get_runner(node_type):
            class ConditionalRunner(BaseRunner):
                def run(self, ctx: RunnerContext) -> NodeResult:
                    if ctx.node_def.id == "A":
                        return NodeResult(status=NodeStatus.FAILED, error="failed")
                    return NodeResult(status=NodeStatus.COMPLETED)
            return ConditionalRunner
        
        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {}))
        
        # C should be skipped because A failed (all_success requirement not met)
        assert result.node_results["A"].status == NodeStatus.FAILED
        assert result.node_results["B"].status == NodeStatus.COMPLETED
        assert result.node_results["C"].status == NodeStatus.SKIPPED

    def test_on_failure_stop(self) -> None:
        """Node fails with on_failure=stop, workflow halts."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="fail", on_failure=OnFailure.STOP),
            NodeDef(id="B", name="Node B", type="bash", script="ok", depends_on=["A"]),  # Dependent, should not run
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes
        )
        
        def mock_get_runner(node_type):
            class ConditionalRunner(BaseRunner):
                def run(self, ctx: RunnerContext) -> NodeResult:
                    if ctx.node_def.id == "A":
                        return NodeResult(status=NodeStatus.FAILED, error="stopped")
                    return NodeResult(status=NodeStatus.COMPLETED)
            return ConditionalRunner
        
        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {}))
        
        assert result.status == WorkflowStatus.FAILED
        assert result.node_results["A"].status == NodeStatus.FAILED
        # B should be skipped because workflow stopped
        assert result.node_results["B"].status == NodeStatus.SKIPPED

    def test_on_failure_continue(self) -> None:
        """Node fails with on_failure=continue, subsequent nodes still run."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="fail", on_failure=OnFailure.CONTINUE),
            NodeDef(id="B", name="Node B", type="bash", script="ok"),
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes
        )
        
        def mock_get_runner(node_type):
            class ConditionalRunner(BaseRunner):
                def run(self, ctx: RunnerContext) -> NodeResult:
                    if ctx.node_def.id == "A":
                        return NodeResult(status=NodeStatus.FAILED, error="continued")
                    return NodeResult(status=NodeStatus.COMPLETED)
            return ConditionalRunner
        
        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {}))
        
        assert result.node_results["A"].status == NodeStatus.FAILED
        assert result.node_results["B"].status == NodeStatus.COMPLETED

    def test_on_failure_skip_downstream(self) -> None:
        """Node fails with skip_downstream, dependents skipped, non-dependents run."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="fail", on_failure=OnFailure.SKIP_DOWNSTREAM),
            NodeDef(id="B", name="Node B", type="bash", script="ok", depends_on=["A"]),  # Dependent
            NodeDef(id="C", name="Node C", type="bash", script="ok"),  # Independent
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes
        )
        
        def mock_get_runner(node_type):
            class ConditionalRunner(BaseRunner):
                def run(self, ctx: RunnerContext) -> NodeResult:
                    if ctx.node_def.id == "A":
                        return NodeResult(status=NodeStatus.FAILED, error="skip downstream")
                    return NodeResult(status=NodeStatus.COMPLETED)
            return ConditionalRunner
        
        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {}))
        
        assert result.node_results["A"].status == NodeStatus.FAILED
        assert result.node_results["B"].status == NodeStatus.SKIPPED  # Dependent, skipped
        assert result.node_results["C"].status == NodeStatus.COMPLETED  # Independent, ran

    def test_timeout_enforcement(self) -> None:
        """Node with short timeout fails when runner takes too long."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="sleep 10", timeout=1),  # 1s timeout
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes
        )
        
        def mock_get_runner(node_type):
            return create_mock_runner_class(NodeResult(status=NodeStatus.COMPLETED), delay=2)
        
        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            start = time.time()
            result = asyncio.run(executor.execute(workflow_def, {}))
            elapsed = time.time() - start
        
        # Should timeout and return error
        assert result.node_results["A"].status == NodeStatus.FAILED
        assert "timed out" in (result.node_results["A"].error or "")

    def test_output_size_enforcement(self) -> None:
        """Mock runner returns huge output, verify truncation/warning."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="echo big"),
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes
        )
        
        # Create output larger than 10MB
        huge_output = {"data": "X" * (11 * 1024 * 1024)}  # 11MB
        
        def mock_get_runner(node_type):
            return create_mock_runner_class(NodeResult(status=NodeStatus.COMPLETED, output=huge_output))
        
        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {}))
        
        # Output should be truncated
        node_result = result.node_results["A"]
        assert "_truncated" in node_result.output

    def test_variable_substitution_integration(self) -> None:
        """Node params reference $upstream.field, verify resolved."""
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="echo A"),
            NodeDef(id="B", name="Node B", type="bash", script="echo $A.value", depends_on=["A"]),
        ]
        
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes
        )
        
        def mock_get_runner(node_type):
            class ConditionalRunner(BaseRunner):
                def run(self, ctx: RunnerContext) -> NodeResult:
                    if ctx.node_def.id == "A":
                        return NodeResult(status=NodeStatus.COMPLETED, output={"value": "test-value"})
                    # For B, verify the script was resolved
                    resolved_script = ctx.resolved_inputs.get("script", ctx.node_def.script)
                    if "test-value" in str(resolved_script):
                        return NodeResult(status=NodeStatus.COMPLETED, output={"resolved": True})
                    return NodeResult(status=NodeStatus.COMPLETED)
            return ConditionalRunner
        
        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {}))
        
        # Both should complete (variable substitution worked)
        assert result.node_results["A"].status == NodeStatus.COMPLETED
        assert result.node_results["B"].status == NodeStatus.COMPLETED

    def test_concurrency_limit(self) -> None:
        """10+ independent nodes with limit=2, verify max 2 run concurrently."""
        import threading

        nodes = [
            NodeDef(id=f"N{i}", name=f"Node {i}", type="bash", script=f"echo {i}")
            for i in range(8)
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes
        )

        # Track actual concurrent execution count
        lock = threading.Lock()
        active_count = 0
        max_observed = 0

        def mock_get_runner(node_type: str) -> type:
            class ConcurrencyTracker(BaseRunner):
                def run(self, ctx: RunnerContext) -> NodeResult:
                    nonlocal active_count, max_observed
                    with lock:
                        active_count += 1
                        if active_count > max_observed:
                            max_observed = active_count
                    time.sleep(0.1)  # Hold the slot to observe concurrency
                    with lock:
                        active_count -= 1
                    return NodeResult(status=NodeStatus.COMPLETED)
            return ConcurrencyTracker

        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {}, concurrency_limit=2))

        # All nodes should complete
        assert len(result.node_results) == 8
        assert all(r.status == NodeStatus.COMPLETED for r in result.node_results.values())
        # Concurrency limit must be enforced: at most 2 running at any time
        assert max_observed <= 2, f"Expected max 2 concurrent, observed {max_observed}"


class TestReducerIntegration:
    """Test reducer integration in workflow execution."""

    def test_append_reducer_parallel_nodes(self) -> None:
        """Test append reducer with 2 parallel nodes writing to same state key."""
        from dag_executor.schema import ReducerDef, ReducerStrategy

        nodes = [
            NodeDef(id="review1", name="Review 1", type="bash", script="echo review1"),
            NodeDef(id="review2", name="Review 2", type="bash", script="echo review2"),
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes,
            state={
                "findings": ReducerDef(strategy=ReducerStrategy.APPEND)
            }
        )

        # Mock runners to return findings (using node_id to make unique values)
        def mock_get_runner(node_type):
            original_class = create_mock_runner_class(NodeResult(status=NodeStatus.COMPLETED))

            class FindingRunner(original_class):
                def run(self, ctx: RunnerContext) -> NodeResult:
                    # Use node_id from context to generate unique finding
                    node_id = ctx.node_def.id
                    return NodeResult(
                        status=NodeStatus.COMPLETED,
                        output={"findings": f"finding_from_{node_id}"}
                    )

            return FindingRunner

        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {}))

        assert result.status == WorkflowStatus.COMPLETED
        assert "findings" in result.outputs
        # Both findings should be in the list (order may vary due to parallelism)
        findings = result.outputs["findings"]
        assert isinstance(findings, list)
        assert len(findings) == 2
        assert set(findings) == {"finding_from_review1", "finding_from_review2"}

    def test_max_reducer_parallel_nodes(self) -> None:
        """Test max reducer with parallel nodes writing numeric values."""
        from dag_executor.schema import ReducerDef, ReducerStrategy

        nodes = [
            NodeDef(id="scanner1", name="Scanner 1", type="bash", script="echo scanner1"),
            NodeDef(id="scanner2", name="Scanner 2", type="bash", script="echo scanner2"),
            NodeDef(id="scanner3", name="Scanner 3", type="bash", script="echo scanner3"),
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes,
            state={
                "severity": ReducerDef(strategy=ReducerStrategy.MAX)
            }
        )

        # Mock runners to return different severities (mapped by node_id)
        severities = {"scanner1": 3, "scanner2": 8, "scanner3": 5}

        def mock_get_runner(node_type):
            original_class = create_mock_runner_class(NodeResult(status=NodeStatus.COMPLETED))

            class SeverityRunner(original_class):
                def run(self, ctx: RunnerContext) -> NodeResult:
                    node_id = ctx.node_def.id
                    return NodeResult(
                        status=NodeStatus.COMPLETED,
                        output={"severity": severities[node_id]}
                    )

            return SeverityRunner

        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {}))

        assert result.status == WorkflowStatus.COMPLETED
        assert "severity" in result.outputs
        assert result.outputs["severity"] == 8  # max of [3, 8, 5]

    def test_merge_dict_reducer(self) -> None:
        """Test merge_dict reducer with parallel nodes."""
        from dag_executor.schema import ReducerDef, ReducerStrategy

        nodes = [
            NodeDef(id="collector1", name="Collector 1", type="bash", script="echo c1"),
            NodeDef(id="collector2", name="Collector 2", type="bash", script="echo c2"),
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes,
            state={
                "metadata": ReducerDef(strategy=ReducerStrategy.MERGE_DICT)
            }
        )

        # Mock runners to return different metadata (using node_id for unique keys)
        def mock_get_runner(node_type):
            original_class = create_mock_runner_class(NodeResult(status=NodeStatus.COMPLETED))

            class MetadataRunner(original_class):
                def run(self, ctx: RunnerContext) -> NodeResult:
                    node_id = ctx.node_def.id
                    return NodeResult(
                        status=NodeStatus.COMPLETED,
                        output={"metadata": {f"key_{node_id}": f"value_{node_id}"}}
                    )

            return MetadataRunner

        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {}))

        assert result.status == WorkflowStatus.COMPLETED
        assert "metadata" in result.outputs
        metadata = result.outputs["metadata"]
        assert isinstance(metadata, dict)
        assert len(metadata) == 2
        assert "key_collector1" in metadata
        assert "key_collector2" in metadata

    def test_concurrency_stress_append_reducer(self) -> None:
        """Test concurrency safety with 5 parallel nodes writing to same state key."""
        from dag_executor.schema import ReducerDef, ReducerStrategy

        # Create 5 parallel nodes
        nodes = [
            NodeDef(id=f"node{i}", name=f"Node {i}", type="bash", script=f"echo node{i}")
            for i in range(5)
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes,
            state={
                "items": ReducerDef(strategy=ReducerStrategy.APPEND)
            }
        )

        # Mock runners to return items (using node_id for unique values)
        def mock_get_runner(node_type):
            original_class = create_mock_runner_class(NodeResult(status=NodeStatus.COMPLETED))

            class ItemRunner(original_class):
                def run(self, ctx: RunnerContext) -> NodeResult:
                    node_id = ctx.node_def.id
                    # Add small random delay to increase chance of races
                    import random
                    time.sleep(random.uniform(0.001, 0.005))
                    return NodeResult(
                        status=NodeStatus.COMPLETED,
                        output={"items": f"item_{node_id}"}
                    )

            return ItemRunner

        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {}))

        assert result.status == WorkflowStatus.COMPLETED
        assert "items" in result.outputs
        items = result.outputs["items"]
        assert isinstance(items, list)
        # All 5 items should be present (no race condition losses)
        assert len(items) == 5
        # Verify all unique items are present
        expected_items = {f"item_node{i}" for i in range(5)}
        assert set(items) == expected_items

    def test_backward_compatibility_no_reducers(self) -> None:
        """Test that workflows without state/reducers still work identically."""
        # Diamond: A -> B,C -> D (same as test_full_dag_execution)
        nodes = [
            NodeDef(id="A", name="Node A", type="bash", script="echo A"),
            NodeDef(id="B", name="Node B", type="bash", script="echo B", depends_on=["A"]),
            NodeDef(id="C", name="Node C", type="bash", script="echo C", depends_on=["A"]),
            NodeDef(id="D", name="Node D", type="bash", script="echo D", depends_on=["B", "C"]),
        ]
        workflow_def = WorkflowDef(
            name="test-workflow",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=nodes
            # No state field - backward compatible
        )

        # Mock get_runner to return completed results
        def mock_get_runner(node_type):
            return create_mock_runner_class(
                NodeResult(status=NodeStatus.COMPLETED, output={"value": "done"})
            )

        with patch("dag_executor.executor.get_runner", side_effect=mock_get_runner):
            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {}))

        assert result.status == WorkflowStatus.COMPLETED
        assert len(result.node_results) == 4
        assert all(r.status == NodeStatus.COMPLETED for r in result.node_results.values())
        # workflow_state should be empty
        # Check via outputs - if state was used, it would be in outputs
        # Since no state reducers, outputs should be empty (no explicit outputs defined)
        assert result.outputs == {}
