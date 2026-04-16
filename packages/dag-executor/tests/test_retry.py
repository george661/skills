"""Test retry_on filter and partial output clearing enhancements to retry logic."""
from __future__ import annotations

import asyncio
import concurrent.futures
from unittest.mock import patch

import pytest

from dag_executor.executor import WorkflowExecutor, ExecutionContext
from dag_executor.runners.base import BaseRunner, RunnerContext
from dag_executor.schema import (
    NodeDef,
    NodeResult,
    NodeStatus,
    RetryConfig,
)


class FlakeyRunner(BaseRunner):
    """Runner that fails N times with specific error, then succeeds."""

    def __init__(self, fail_count: int = 1, error_message: str = "Transient timeout error"):
        self.fail_count = fail_count
        self.error_message = error_message
        self.call_count = 0

    def run(self, ctx: RunnerContext) -> NodeResult:
        self.call_count += 1
        if self.call_count <= self.fail_count:
            return NodeResult(
                status=NodeStatus.FAILED,
                error=f"{self.error_message} (attempt {self.call_count})"
            )
        return NodeResult(status=NodeStatus.COMPLETED, output={"success": True})


@pytest.mark.asyncio
class TestRetryOnFilter:
    """Test retry_on filter that selectively retries based on error patterns."""

    async def test_retry_on_filter_matches_allows_retry(self) -> None:
        """Test retry_on=['timeout'], error contains 'timeout' -> retries."""
        node_def = NodeDef(
            id="node1",
            name="Flakey Node",
            type="bash",
            script="echo test",
            retry=RetryConfig(max_attempts=3, delay_ms=100, retry_on=["timeout"])
        )

        runner = FlakeyRunner(fail_count=1, error_message="Connection timeout")
        runner_ctx = RunnerContext(
            node_def=node_def,
            workflow_id="test",
        )

        ctx = ExecutionContext(
            workflow_state={},
            node_outputs={},
            
            semaphore=asyncio.Semaphore(1),
            pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
        )

        with patch("asyncio.sleep", return_value=None):
            executor = WorkflowExecutor()
            result = await executor._execute_with_retry(
                node_def, runner, runner_ctx, timeout=30, ctx=ctx
            )

            # Should retry and succeed on 2nd attempt
            assert result.status == NodeStatus.COMPLETED
            assert runner.call_count == 2

    async def test_retry_on_filter_no_match_skips_retry(self) -> None:
        """Test retry_on=['timeout'], error is 'validation error' -> no retry."""
        node_def = NodeDef(
            id="node1",
            name="Always Fails Node",
            type="bash",
            script="echo test",
            retry=RetryConfig(max_attempts=3, delay_ms=100, retry_on=["timeout"])
        )

        runner = FlakeyRunner(fail_count=5, error_message="Permanent validation error")
        runner_ctx = RunnerContext(
            node_def=node_def,
            workflow_id="test",
        )

        ctx = ExecutionContext(
            workflow_state={},
            node_outputs={},
            
            semaphore=asyncio.Semaphore(1),
            pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
        )

        executor = WorkflowExecutor()
        result = await executor._execute_with_retry(
            node_def, runner, runner_ctx, timeout=30, ctx=ctx
        )

        # Should NOT retry since error doesn't match filter
        assert result.status == NodeStatus.FAILED
        assert runner.call_count == 1
        assert "validation error" in result.error

    async def test_retry_on_filter_case_insensitive(self) -> None:
        """Test retry_on filter is case-insensitive."""
        node_def = NodeDef(
            id="node1",
            name="Flakey Node",
            type="bash",
            script="echo test",
            retry=RetryConfig(max_attempts=3, delay_ms=100, retry_on=["TIMEOUT"])
        )

        runner = FlakeyRunner(fail_count=1, error_message="connection timeout error")
        runner_ctx = RunnerContext(
            node_def=node_def,
            workflow_id="test",
        )

        ctx = ExecutionContext(
            workflow_state={},
            node_outputs={},
            
            semaphore=asyncio.Semaphore(1),
            pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
        )

        with patch("asyncio.sleep", return_value=None):
            executor = WorkflowExecutor()
            result = await executor._execute_with_retry(
                node_def, runner, runner_ctx, timeout=30, ctx=ctx
            )

            # Should match despite case difference
            assert result.status == NodeStatus.COMPLETED
            assert runner.call_count == 2

    async def test_retry_on_filter_multiple_patterns(self) -> None:
        """Test retry_on with multiple patterns matches any."""
        node_def = NodeDef(
            id="node1",
            name="Flakey Node",
            type="bash",
            script="echo test",
            retry=RetryConfig(max_attempts=3, delay_ms=100, retry_on=["timeout", "network", "connection"])
        )

        runner = FlakeyRunner(fail_count=1, error_message="Network error occurred")
        runner_ctx = RunnerContext(
            node_def=node_def,
            workflow_id="test",
        )

        ctx = ExecutionContext(
            workflow_state={},
            node_outputs={},
            
            semaphore=asyncio.Semaphore(1),
            pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
        )

        with patch("asyncio.sleep", return_value=None):
            executor = WorkflowExecutor()
            result = await executor._execute_with_retry(
                node_def, runner, runner_ctx, timeout=30, ctx=ctx
            )

            # Should match "network" pattern
            assert result.status == NodeStatus.COMPLETED
            assert runner.call_count == 2


@pytest.mark.asyncio
class TestPartialOutputClearing:
    """Test that partial outputs are cleared before retry loop starts."""

    async def test_partial_outputs_cleared_before_retry(self) -> None:
        """Test ctx.node_outputs[node_id] cleared at start of _execute_with_retry."""
        node_def = NodeDef(
            id="node1",
            name="Flakey Node",
            type="bash",
            script="echo test",
            retry=RetryConfig(max_attempts=3, delay_ms=100)
        )

        runner = FlakeyRunner(fail_count=1)
        runner_ctx = RunnerContext(
            node_def=node_def,
            workflow_id="test",
        )

        # Pre-populate node_outputs with stale data
        ctx = ExecutionContext(
            workflow_state={},
            node_outputs={"node1": {"stale": "data"}},
            
            semaphore=asyncio.Semaphore(1),
            pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
        )

        with patch("asyncio.sleep", return_value=None):
            executor = WorkflowExecutor()
            result = await executor._execute_with_retry(
                node_def, runner, runner_ctx, timeout=30, ctx=ctx
            )

            assert result.status == NodeStatus.COMPLETED
            # After _execute_with_retry, node_outputs should not contain the stale data
            # (it was cleared at the start of the method)
            # Note: _execute_node populates node_outputs AFTER _execute_with_retry returns
            # So at this point, node_outputs should still be empty for node1
            assert "node1" not in ctx.node_outputs or ctx.node_outputs["node1"] != {"stale": "data"}

    async def test_no_clearing_when_no_retry_config(self) -> None:
        """Test that clearing still happens even with default retry (1 attempt)."""
        node_def = NodeDef(
            id="node1",
            name="Node",
            type="bash",
            script="echo test",
            # No retry config = max_attempts defaults to 1
        )

        runner = FlakeyRunner(fail_count=0)  # Succeeds immediately
        runner_ctx = RunnerContext(
            node_def=node_def,
            workflow_id="test",
        )

        # Pre-populate node_outputs
        ctx = ExecutionContext(
            workflow_state={},
            node_outputs={"node1": {"old": "output"}},
            
            semaphore=asyncio.Semaphore(1),
            pool=concurrent.futures.ThreadPoolExecutor(max_workers=1)
        )

        executor = WorkflowExecutor()
        result = await executor._execute_with_retry(
            node_def, runner, runner_ctx, timeout=30, ctx=ctx
        )

        assert result.status == NodeStatus.COMPLETED
        # Old output should have been cleared
        assert "node1" not in ctx.node_outputs or ctx.node_outputs["node1"] != {"old": "output"}
