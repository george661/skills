"""Tests for the next.yaml workflow definition.

Validates that the YAML-based next workflow parses correctly, has proper
validation drain gate, and selection interrupt.
"""
from pathlib import Path
from typing import Dict

import pytest

from dag_executor.graph import topological_sort_with_layers
from dag_executor.parser import load_workflow
from dag_executor.schema import (
    NodeDef,
    OnFailure,
    ReducerStrategy,
    WorkflowDef,
)


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "next.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the next.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1: YAML parses without errors and has correct structure."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """next.yaml loads with no validation errors."""
        assert workflow.name == "Next Issue Workflow"
        assert len(workflow.nodes) >= 10  # At least core nodes

    def test_checkpoint_prefix(self, workflow: WorkflowDef) -> None:
        """Workflow config has correct checkpoint prefix."""
        assert workflow.config.checkpoint_prefix == "next"


class TestValidationDrainGate:
    """Test 2: validation_drain_gate uses on_failure: stop (BLOCKING)."""

    def test_validation_drain_gate_exists(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """validation_drain_gate is a gate node."""
        node = nodes_by_id["validation_drain_gate"]
        assert node.type == "gate"

    def test_validation_drain_gate_on_failure_stop(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """validation_drain_gate uses on_failure: stop."""
        node = nodes_by_id["validation_drain_gate"]
        assert node.on_failure == OnFailure.STOP


class TestQueryNodes:
    """Test 3: All four query nodes exist."""

    def test_query_needs_attention_exists(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """query_needs_attention exists."""
        node = nodes_by_id["query_needs_attention"]
        assert node is not None
        assert "needs_attention" in node.writes

    def test_query_validation_queue_exists(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """query_validation_queue exists."""
        node = nodes_by_id["query_validation_queue"]
        assert node is not None
        assert "validation_queue" in node.writes

    def test_query_bugs_exists(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """query_bugs exists."""
        node = nodes_by_id["query_bugs"]
        assert node is not None
        assert "bugs_todo" in node.writes

    def test_query_tasks_exists(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """query_tasks exists."""
        node = nodes_by_id["query_tasks"]
        assert node is not None
        assert "tasks_todo" in node.writes


class TestSelectionInterrupt:
    """Test 4: selection_interrupt has resume_key user_selection, channel terminal."""

    def test_selection_interrupt_exists(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """selection_interrupt is an interrupt node."""
        node = nodes_by_id["selection_interrupt"]
        assert node.type == "interrupt"

    def test_selection_interrupt_resume_key(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """selection_interrupt has resume_key: user_selection."""
        node = nodes_by_id["selection_interrupt"]
        assert node.resume_key == "user_selection"

    def test_selection_interrupt_channels(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """selection_interrupt has terminal channel."""
        node = nodes_by_id["selection_interrupt"]
        assert node.channels == ["terminal"]


class TestSmokeCheckFailureMode:
    """Test 5: Smoke check on_failure: continue (non-blocking)."""

    def test_smoke_check_on_failure_continue(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """smoke_check uses on_failure: continue."""
        node = nodes_by_id["smoke_check"]
        assert node.on_failure == OnFailure.CONTINUE


class TestPresentResultsDependencies:
    """Test 6: present_results depends on all four query nodes + manifest + skeleton check."""

    def test_present_results_depends_on_queries(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """present_results depends on all four query nodes."""
        node = nodes_by_id["present_results"]
        assert "query_needs_attention" in node.depends_on
        assert "query_validation_queue" in node.depends_on
        assert "query_bugs" in node.depends_on
        assert "query_tasks" in node.depends_on

    def test_present_results_depends_on_manifest(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """present_results depends on load_sequence_manifest."""
        node = nodes_by_id["present_results"]
        assert "load_sequence_manifest" in node.depends_on

    def test_present_results_depends_on_skeleton_check(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """present_results depends on skeleton_dependency_check."""
        node = nodes_by_id["present_results"]
        assert "skeleton_dependency_check" in node.depends_on


class TestStateChannels:
    """Test 7: State channels declared correctly."""

    def test_validation_drain_channel(self, workflow: WorkflowDef) -> None:
        """validation_drain channel is dict with overwrite."""
        ch = workflow.state["validation_drain"]
        assert ch.type == "dict"
        assert ch.reducer.strategy == ReducerStrategy.OVERWRITE

    def test_selected_issue_channel(self, workflow: WorkflowDef) -> None:
        """selected_issue channel is string with overwrite."""
        ch = workflow.state["selected_issue"]
        assert ch.type == "string"
        assert ch.reducer.strategy == ReducerStrategy.OVERWRITE


class TestTopologicalOrdering:
    """Test 8: Topological sort produces correct ordering."""

    def test_drain_before_queries(self, workflow: WorkflowDef) -> None:
        """validation_drain_check before queries."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        def before(a: str, b: str) -> None:
            assert flat_order.index(a) < flat_order.index(b), (
                f"{a} must execute before {b}"
            )

        before("validation_drain_check", "validation_drain_gate")
        before("validation_drain_gate", "query_needs_attention")
        before("query_needs_attention", "present_results")
