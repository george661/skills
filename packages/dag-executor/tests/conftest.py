"""Shared pytest fixtures and test harness for DAG executor test suite.

Provides centralized fixtures for isolated workflow testing without real
side effects. Inspired by Prefect's test_harness and Temporal's activity
mocking patterns.

Usage:
    def test_my_workflow(test_harness, simple_workflow):
        harness = test_harness
        harness.mock_all_runners(NodeResult(status=NodeStatus.COMPLETED, output={"ok": True}))
        result = harness.execute(simple_workflow)
        harness.assert_workflow_completed()
        assert harness.get_node_output("step_1") == {"ok": True}
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Type
from unittest.mock import patch

import pytest

from dag_executor.checkpoint import CheckpointMetadata, CheckpointStore
from dag_executor.events import EventEmitter, EventType, WorkflowEvent
from dag_executor.executor import WorkflowExecutor, WorkflowResult
from dag_executor.runners.base import BaseRunner, RunnerContext, get_runner
from dag_executor.schema import (
    NodeDef,
    NodeResult,
    NodeStatus,
    WorkflowConfig,
    WorkflowDef,
    WorkflowStatus,
)


# ---------------------------------------------------------------------------
# MockRunnerFactory
# ---------------------------------------------------------------------------


class MockRunnerFactory:
    """Factory that creates mock runner classes returning specified NodeResults.

    Each ``create*`` method returns a **class** (not an instance) suitable for
    injection via ``get_runner`` patching or ``WorkflowTestHarness.mock_runner``.
    """

    @staticmethod
    def create(
        status: NodeStatus = NodeStatus.COMPLETED,
        output: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        delay: float = 0,
    ) -> Type[BaseRunner]:
        """Create a mock runner class that always returns the same result.

        Args:
            status: NodeStatus to return.
            output: Output dict to include in the result.
            error: Error message to include in the result.
            delay: Seconds to sleep before returning (simulates work).

        Returns:
            A BaseRunner subclass.
        """
        result = NodeResult(status=status, output=output, error=error)

        class _MockRunner(BaseRunner):
            def run(self, ctx: RunnerContext) -> NodeResult:
                if delay:
                    time.sleep(delay)
                return result

        _MockRunner.__qualname__ = f"MockRunner[{status.value}]"
        return _MockRunner

    @staticmethod
    def create_sequence(results: List[NodeResult]) -> Type[BaseRunner]:
        """Create a mock runner that returns results in order, cycling if exhausted.

        Each instantiation of the runner class shares the same call counter so
        sequential node executions get successive results.

        Args:
            results: Ordered list of NodeResult objects to return.

        Returns:
            A BaseRunner subclass.
        """
        call_index: List[int] = [0]  # mutable counter shared across instances

        class _SequenceRunner(BaseRunner):
            def run(self, ctx: RunnerContext) -> NodeResult:
                idx = call_index[0] % len(results)
                call_index[0] += 1
                return results[idx]

        _SequenceRunner.__qualname__ = f"SequenceRunner[{len(results)} results]"
        return _SequenceRunner

    @staticmethod
    def create_failing(error: str = "mock failure") -> Type[BaseRunner]:
        """Create a mock runner that always returns a FAILED result.

        Args:
            error: Error message to include.

        Returns:
            A BaseRunner subclass.
        """
        return MockRunnerFactory.create(
            status=NodeStatus.FAILED,
            error=error,
        )


# ---------------------------------------------------------------------------
# WorkflowTestHarness
# ---------------------------------------------------------------------------


class WorkflowTestHarness:
    """Context-free test harness for executing workflows in isolation.

    Patches ``dag_executor.executor.get_runner`` so that the executor uses
    mock runners instead of real ones.  All events are captured and the
    harness provides assertion helpers for common checks.

    Typical usage::

        harness = WorkflowTestHarness(tmp_path)
        harness.mock_runner("bash", factory.create(output={"v": 1}))
        harness.mock_runner("gate", factory.create())
        result = harness.execute(workflow_def, {"branch": "main"})
        harness.assert_workflow_completed()
        harness.assert_node_completed("build")
    """

    def __init__(self, tmp_dir: Any) -> None:
        """Initialize the harness with a temporary directory for checkpoints.

        Args:
            tmp_dir: A ``pathlib.Path`` (typically from pytest's ``tmp_path``
                     fixture) used as the checkpoint store root.
        """
        self.events: List[WorkflowEvent] = []
        self.event_emitter: EventEmitter = EventEmitter()
        self.event_emitter.add_listener(self._capture_event)
        self.checkpoint_store: CheckpointStore = CheckpointStore(
            checkpoint_prefix=str(tmp_dir / ".dag-checkpoints"),
        )
        self.executor: WorkflowExecutor = WorkflowExecutor()
        self._runner_overrides: Dict[str, Type[BaseRunner]] = {}
        self._default_runner: Optional[Type[BaseRunner]] = None
        self._last_result: Optional[WorkflowResult] = None

    # -- runner configuration ------------------------------------------------

    def mock_runner(self, node_type: str, runner_class: Type[BaseRunner]) -> None:
        """Register a mock runner for a specific node type.

        Args:
            node_type: The node type string (e.g. ``"bash"``, ``"gate"``).
            runner_class: A BaseRunner subclass to use for that type.
        """
        self._runner_overrides[node_type] = runner_class

    def mock_all_runners(self, default_result: NodeResult) -> None:
        """Set a default runner that handles any node type not explicitly mocked.

        Args:
            default_result: The NodeResult every unmocked node type will return.
        """

        class _DefaultRunner(BaseRunner):
            def run(self, ctx: RunnerContext) -> NodeResult:
                return default_result

        self._default_runner = _DefaultRunner

    # -- execution -----------------------------------------------------------

    def execute(
        self,
        workflow_def: WorkflowDef,
        inputs: Optional[Dict[str, Any]] = None,
        concurrency_limit: int = 10,
    ) -> WorkflowResult:
        """Execute a workflow using the configured mock runners.

        The ``get_runner`` function in the executor module is patched for the
        duration of execution so no real runners are invoked.

        Args:
            workflow_def: The workflow definition to execute.
            inputs: Workflow input values (default empty dict).
            concurrency_limit: Maximum concurrent node executions.

        Returns:
            The ``WorkflowResult`` produced by the executor.
        """

        def _patched_get_runner(node_type: str) -> Optional[Type[BaseRunner]]:
            if node_type in self._runner_overrides:
                return self._runner_overrides[node_type]
            if self._default_runner is not None:
                return self._default_runner
            # Fall back to real registry as last resort
            return get_runner(node_type)

        with patch(
            "dag_executor.executor.get_runner",
            side_effect=_patched_get_runner,
        ):
            self._last_result = asyncio.run(
                self.executor.execute(
                    workflow_def,
                    inputs or {},
                    concurrency_limit,
                    event_emitter=self.event_emitter,
                    checkpoint_store=self.checkpoint_store,
                )
            )
        return self._last_result

    # -- assertions ----------------------------------------------------------

    def _require_result(self) -> WorkflowResult:
        """Return the last result, raising if execute() hasn't been called."""
        if self._last_result is None:
            raise RuntimeError(
                "No workflow result available. Call execute() first."
            )
        return self._last_result

    def assert_node_completed(self, node_id: str) -> None:
        """Assert that a node finished with COMPLETED status."""
        result = self._require_result()
        assert node_id in result.node_results, (
            f"Node '{node_id}' not found in results. "
            f"Available: {list(result.node_results.keys())}"
        )
        actual = result.node_results[node_id].status
        assert actual == NodeStatus.COMPLETED, (
            f"Expected node '{node_id}' COMPLETED, got {actual.value}"
        )

    def assert_node_failed(self, node_id: str) -> None:
        """Assert that a node finished with FAILED status."""
        result = self._require_result()
        assert node_id in result.node_results, (
            f"Node '{node_id}' not found in results. "
            f"Available: {list(result.node_results.keys())}"
        )
        actual = result.node_results[node_id].status
        assert actual == NodeStatus.FAILED, (
            f"Expected node '{node_id}' FAILED, got {actual.value}"
        )

    def assert_node_skipped(self, node_id: str) -> None:
        """Assert that a node finished with SKIPPED status."""
        result = self._require_result()
        assert node_id in result.node_results, (
            f"Node '{node_id}' not found in results. "
            f"Available: {list(result.node_results.keys())}"
        )
        actual = result.node_results[node_id].status
        assert actual == NodeStatus.SKIPPED, (
            f"Expected node '{node_id}' SKIPPED, got {actual.value}"
        )

    def assert_workflow_completed(self) -> None:
        """Assert the overall workflow status is COMPLETED."""
        result = self._require_result()
        assert result.status == WorkflowStatus.COMPLETED, (
            f"Expected workflow COMPLETED, got {result.status.value}"
        )

    def get_node_output(self, node_id: str) -> Dict[str, Any]:
        """Return the output dict for a completed node.

        Args:
            node_id: The node whose output to retrieve.

        Returns:
            The output dictionary (empty dict if output was None).

        Raises:
            KeyError: If the node is not in the results.
        """
        result = self._require_result()
        if node_id not in result.node_results:
            raise KeyError(
                f"Node '{node_id}' not found in results. "
                f"Available: {list(result.node_results.keys())}"
            )
        return result.node_results[node_id].output or {}

    # -- event helpers -------------------------------------------------------

    def _capture_event(self, event: WorkflowEvent) -> None:
        self.events.append(event)

    def get_events_for_node(self, node_id: str) -> List[WorkflowEvent]:
        """Return all events emitted for a specific node."""
        return [e for e in self.events if e.node_id == node_id]

    def get_events_by_type(self, event_type: EventType) -> List[WorkflowEvent]:
        """Return all events matching a given EventType."""
        return [e for e in self.events if e.event_type == event_type]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_runner_factory() -> MockRunnerFactory:
    """Return a MockRunnerFactory instance for creating mock runners."""
    return MockRunnerFactory()


@pytest.fixture()
def test_harness(tmp_path: Any) -> WorkflowTestHarness:
    """Return a WorkflowTestHarness backed by a temporary directory."""
    return WorkflowTestHarness(tmp_path)


@pytest.fixture()
def simple_workflow() -> WorkflowDef:
    """A minimal 3-node linear workflow: bash -> gate -> bash.

    Graph::

        step_1 (bash)  -->  gate_1 (gate, condition=true)  -->  step_2 (bash)
    """
    return WorkflowDef(
        name="simple-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        nodes=[
            NodeDef(
                id="step_1",
                name="Step 1",
                type="bash",
                script="echo step1",
            ),
            NodeDef(
                id="gate_1",
                name="Gate 1",
                type="gate",
                condition="true",
                depends_on=["step_1"],
            ),
            NodeDef(
                id="step_2",
                name="Step 2",
                type="bash",
                script="echo step2",
                depends_on=["gate_1"],
            ),
        ],
    )


@pytest.fixture()
def diamond_workflow() -> WorkflowDef:
    """A 4-node diamond DAG.

    Graph::

           A (bash)
          / \\
         B   C  (bash, bash)
          \\ /
           D (bash)
    """
    return WorkflowDef(
        name="diamond-workflow",
        config=WorkflowConfig(checkpoint_prefix=".dag-checkpoints"),
        nodes=[
            NodeDef(id="A", name="Node A", type="bash", script="echo A"),
            NodeDef(
                id="B", name="Node B", type="bash", script="echo B",
                depends_on=["A"],
            ),
            NodeDef(
                id="C", name="Node C", type="bash", script="echo C",
                depends_on=["A"],
            ),
            NodeDef(
                id="D", name="Node D", type="bash", script="echo D",
                depends_on=["B", "C"],
            ),
        ],
    )


@pytest.fixture()
def sample_node_result() -> NodeResult:
    """A completed NodeResult with sample output."""
    return NodeResult(
        status=NodeStatus.COMPLETED,
        output={"value": "sample", "count": 42},
    )


@pytest.fixture()
def event_collector() -> tuple:
    """An EventEmitter paired with a list that captures all emitted events.

    Returns:
        Tuple of ``(emitter, captured_events)`` where *captured_events* is a
        list that grows as events are emitted.
    """
    captured_events: List[WorkflowEvent] = []
    emitter = EventEmitter()
    emitter.add_listener(lambda e: captured_events.append(e))
    return emitter, captured_events


# ---------------------------------------------------------------------------
# Checkpoint fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def checkpoint_store(tmp_path: Path) -> CheckpointStore:
    """A CheckpointStore backed by a temporary directory."""
    return CheckpointStore(str(tmp_path / ".dag-checkpoints"))


@pytest.fixture()
def sample_metadata() -> CheckpointMetadata:
    """A shared CheckpointMetadata fixture for checkpoint roundtrip tests.

    Uses status="running" as the general case (checkpoint created mid-execution).
    """
    return CheckpointMetadata(
        workflow_name="test-workflow",
        run_id="run-123",
        started_at=datetime.now(timezone.utc).isoformat(),
        inputs={"input1": "value1"},
        status="running",
    )


@pytest.fixture()
def sample_node_def() -> NodeDef:
    """A sample NodeDef for checkpoint and general testing."""
    return NodeDef(
        id="node1",
        name="Test Node",
        type="bash",
        script="echo 'test'",
    )


@pytest.fixture()
def checkpoint_node_result() -> NodeResult:
    """A NodeResult fixture tailored for checkpoint tests.

    Distinct from sample_node_result — includes timestamps and checkpoint-specific
    output shape.
    """
    return NodeResult(
        status=NodeStatus.COMPLETED,
        output={"result": "test-output"},
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )
