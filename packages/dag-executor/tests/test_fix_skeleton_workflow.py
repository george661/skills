"""Tests for the fix-skeleton.yaml workflow definition."""
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
    Path(__file__).parent.parent / "workflows" / "fix-skeleton.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the fix-skeleton.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1: YAML parses without errors."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """fix-skeleton.yaml loads with 6 nodes."""
        assert workflow.name == "Fix Skeleton Command Sub-DAG"
        assert len(workflow.nodes) == 6

    def test_input_epic_key_required(self, workflow: WorkflowDef) -> None:
        """epic_key input is required."""
        ek = workflow.inputs["epic_key"]
        assert ek.required is True

    def test_config_checkpoint_prefix(self, workflow: WorkflowDef) -> None:
        """Workflow config has correct checkpoint prefix."""
        assert workflow.config.checkpoint_prefix == "fix-skeleton"

    def test_state_channels_declared(self, workflow: WorkflowDef) -> None:
        """State channels are properly declared."""
        assert "review_feedback" in workflow.state
        assert workflow.state["review_feedback"].type == "dict"

        assert "gaps" in workflow.state
        assert workflow.state["gaps"].type == "list"
        assert workflow.state["gaps"].reducer.strategy.value == "append"

        assert "fix_cycle" in workflow.state
        assert workflow.state["fix_cycle"].type == "dict"

        assert "fix_result" in workflow.state
        assert workflow.state["fix_result"].type == "dict"


class TestRetryMaxAttempts:
    """Test 2: fix_gaps node has retry.max_attempts = 2 (MANDATORY per AC)."""

    def test_retry_max_attempts_2(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """fix_gaps has retry.max_attempts = 2."""
        node = nodes_by_id["fix_gaps"]
        assert node.retry is not None
        assert node.retry.max_attempts == 2


class TestEscalationGate:
    """Test 3: Escalation gate stops on failure."""

    def test_escalation_gate_exists(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """escalation_gate is a gate that stops on failure."""
        gate = nodes_by_id["escalation_gate"]
        assert gate.type == "gate"
        assert gate.on_failure == OnFailure.STOP


class TestTopologicalOrdering:
    """Test 4: Topological ordering is correct."""

    def test_phase_ordering(self, workflow: WorkflowDef) -> None:
        """Nodes execute in correct order."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        def before(a: str, b: str) -> None:
            assert flat_order.index(a) < flat_order.index(b), (
                f"{a} must execute before {b}"
            )

        # load → gate → categorize → fix → update → summary
        before("load_review_feedback", "escalation_gate")
        before("escalation_gate", "categorize_gaps")
        before("categorize_gaps", "fix_gaps")
        before("fix_gaps", "update_skeleton_doc")
        before("update_skeleton_doc", "post_fix_summary")


class TestNodeChannelSubscriptions:
    """Test 5: Nodes read/write correct channels."""

    def test_load_writes_channels(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """load_review_feedback writes review_feedback and fix_cycle."""
        node = nodes_by_id["load_review_feedback"]
        assert "review_feedback" in node.writes
        assert "fix_cycle" in node.writes

    def test_fix_gaps_uses_channels(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """fix_gaps reads gaps and review_feedback, writes fix_result."""
        node = nodes_by_id["fix_gaps"]
        assert "gaps" in node.reads
        assert "review_feedback" in node.reads
        assert "fix_result" in node.writes
