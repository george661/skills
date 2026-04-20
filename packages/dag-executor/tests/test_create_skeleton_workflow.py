"""Tests for the create-skeleton.yaml workflow definition.

Validates that the YAML-based create-skeleton workflow parses correctly,
has proper node ordering, state channels, and correct structure.
"""
from pathlib import Path
from typing import Dict

import pytest

from dag_executor.graph import topological_sort_with_layers
from dag_executor.parser import load_workflow
from dag_executor.schema import (
    NodeDef,
    WorkflowDef,
)


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "create-skeleton.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the create-skeleton.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1: YAML parses without errors and has correct structure."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """create-skeleton.yaml loads with no validation errors."""
        assert workflow.name == "Create Skeleton Command Sub-DAG"
        assert len(workflow.nodes) >= 8

    def test_input_epic_key_required(self, workflow: WorkflowDef) -> None:
        """epic_key input is required with Jira pattern."""
        ek = workflow.inputs["epic_key"]
        assert ek.required is True
        assert ek.pattern is not None

    def test_config_checkpoint_prefix(self, workflow: WorkflowDef) -> None:
        """Workflow config has correct checkpoint prefix."""
        assert workflow.config.checkpoint_prefix == "create-skeleton"

    def test_state_channels_declared(self, workflow: WorkflowDef) -> None:
        """State channels are properly declared."""
        assert "epic_context" in workflow.state
        assert workflow.state["epic_context"].type == "dict"
        assert workflow.state["epic_context"].reducer.strategy.value == "overwrite"

        assert "affected_repos" in workflow.state
        assert workflow.state["affected_repos"].type == "list"
        assert workflow.state["affected_repos"].reducer.strategy.value == "append"
        assert workflow.state["affected_repos"].default == []

        assert "skeleton_path" in workflow.state
        assert workflow.state["skeleton_path"].type == "dict"

        assert "skeleton_issues" in workflow.state
        assert workflow.state["skeleton_issues"].type == "list"
        assert workflow.state["skeleton_issues"].reducer.strategy.value == "append"


class TestTopologicalOrdering:
    """Test 2: Topological sort produces correct phase ordering."""

    def test_phase_ordering(self, workflow: WorkflowDef) -> None:
        """Phases execute in correct order."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        def before(a: str, b: str) -> None:
            assert flat_order.index(a) < flat_order.index(b), (
                f"{a} must execute before {b}"
            )

        # Load → identify → define → create → store
        before("load_epic_context", "identify_repos")
        before("identify_repos", "define_skeleton_path")
        before("define_skeleton_path", "create_skeleton_issues")
        before("create_skeleton_issues", "store_definition")


class TestNodeChannelSubscriptions:
    """Test 3: Nodes read/write correct channels."""

    def test_load_epic_context_writes_channel(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """load_epic_context writes epic_context."""
        node = nodes_by_id["load_epic_context"]
        assert "epic_context" in node.writes

    def test_identify_repos_uses_channels(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """identify_repos reads epic_context, writes affected_repos."""
        node = nodes_by_id["identify_repos"]
        assert "epic_context" in node.reads
        assert "affected_repos" in node.writes

    def test_create_skeleton_issues_writes_channel(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """create_skeleton_issues writes skeleton_issues."""
        node = nodes_by_id["create_skeleton_issues"]
        assert "skeleton_issues" in node.writes


class TestOutputsContract:
    """Test 4: Outputs are properly declared."""

    def test_outputs_declared(self, workflow: WorkflowDef) -> None:
        """skeleton_issues and affected_repos outputs are declared."""
        assert "skeleton_issues" in workflow.outputs
        assert workflow.outputs["skeleton_issues"].node == "create_skeleton_issues"

        assert "affected_repos" in workflow.outputs
        assert workflow.outputs["affected_repos"].node == "identify_repos"
