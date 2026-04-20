"""Tests for the review-skeleton.yaml workflow definition."""
from pathlib import Path
from typing import Dict

import pytest

from dag_executor.graph import topological_sort_with_layers
from dag_executor.parser import load_workflow
from dag_executor.schema import (
    NodeDef,
    OnFailure,
    WorkflowDef,
)


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "review-skeleton.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the review-skeleton.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1: YAML parses without errors."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """review-skeleton.yaml loads with no validation errors."""
        assert workflow.name == "Review Skeleton Command Sub-DAG"
        assert len(workflow.nodes) >= 8

    def test_input_epic_key_required(self, workflow: WorkflowDef) -> None:
        """epic_key input is required."""
        ek = workflow.inputs["epic_key"]
        assert ek.required is True

    def test_config_checkpoint_prefix(self, workflow: WorkflowDef) -> None:
        """Workflow config has correct checkpoint prefix."""
        assert workflow.config.checkpoint_prefix == "review-skeleton"

    def test_state_channels_declared(self, workflow: WorkflowDef) -> None:
        """State channels are properly declared."""
        assert "skeleton_data" in workflow.state
        assert workflow.state["skeleton_data"].type == "dict"

        assert "checks" in workflow.state
        assert workflow.state["checks"].type == "list"
        assert workflow.state["checks"].reducer.strategy.value == "append"

        assert "verdict" in workflow.state
        assert workflow.state["verdict"].type == "string"


class TestTopologicalOrdering:
    """Test 2: Topological sort produces correct ordering."""

    def test_phase_ordering(self, workflow: WorkflowDef) -> None:
        """Nodes execute in correct order."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        def before(a: str, b: str) -> None:
            assert flat_order.index(a) < flat_order.index(b), (
                f"{a} must execute before {b}"
            )

        # Load → gate → checks → verdict → post
        before("load_skeleton", "validate_skeleton_exists")
        before("validate_skeleton_exists", "check_full_stack_span")
        before("check_full_stack_span", "produce_verdict")
        before("produce_verdict", "post_jira_verdict")


class TestGateStopsOnNoSkeleton:
    """Test 3: Gate stops workflow if no skeleton found."""

    def test_gate_stops_on_failure(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """validate_skeleton_exists gate stops on failure."""
        gate = nodes_by_id["validate_skeleton_exists"]
        assert gate.type == "gate"
        assert gate.on_failure == OnFailure.STOP


class TestVerdictOutputDeclared:
    """Test 4: Verdict output is declared."""

    def test_verdict_output_declared(self, workflow: WorkflowDef) -> None:
        """verdict output is declared."""
        assert "verdict" in workflow.outputs
        assert workflow.outputs["verdict"].node == "produce_verdict"
