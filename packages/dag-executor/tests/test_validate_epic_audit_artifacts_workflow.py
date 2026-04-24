"""Tests for the validate-epic-audit-artifacts.yaml workflow definition.

Validates parsing, required gate nodes, inputs/outputs, and repo resolver usage.
"""
from pathlib import Path
from typing import Dict

import pytest

from dag_executor.parser import load_workflow
from dag_executor.schema import NodeDef, WorkflowDef


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "validate-epic-audit-artifacts.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load validate-epic-audit-artifacts workflow for testing."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Map of node ID to NodeDef."""
    return {node.id: node for node in workflow.nodes}


class TestValidateEpicAuditArtifactsParsing:
    """Test 1: YAML parses and has correct structure."""

    def test_workflow_yaml_parses(self, workflow: WorkflowDef) -> None:
        """validate-epic-audit-artifacts.yaml loads with no validation errors (AC-26)."""
        assert workflow.name is not None
        assert len(workflow.nodes) >= 7  # At least 7 required nodes

    def test_workflow_has_required_gate_nodes(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """Workflow has all required gate nodes."""
        required_nodes = [
            "resolve_paths",
            "deploy_gate",
            "test_artifacts",
            "smoke_baseline",
            "migration_check",
            "route_check",
            "aggregate_result",
        ]
        for node_id in required_nodes:
            assert node_id in nodes_by_id, f"Missing required node: {node_id}"

    def test_workflow_inputs_and_outputs(self, workflow: WorkflowDef) -> None:
        """Workflow has required inputs and outputs."""
        # Required inputs
        assert "epic" in workflow.inputs
        assert workflow.inputs["epic"].required is True
        
        assert "repos" in workflow.inputs
        assert workflow.inputs["repos"].required is True
        assert workflow.inputs["repos"].pattern is not None
        # Pattern should match space-separated repo list
        assert "a-zA-Z0-9_-" in workflow.inputs["repos"].pattern

        # Required outputs
        required_outputs = [
            "hard_gate_failures",
            "deploy_gates",
            "test_artifact_gates",
            "smoke_gate",
            "migration_gate",
            "route_gate",
        ]
        for output_name in required_outputs:
            assert output_name in workflow.outputs, f"Missing required output: {output_name}"
            # Verify output node exists
            output_def = workflow.outputs[output_name]
            assert output_def.node in [n.id for n in workflow.nodes]

    def test_repo_path_resolution_referenced(self, workflow: WorkflowDef) -> None:
        """Workflow uses resolve_repo_path for out-of-tree repo resolution."""
        # Convert workflow to string representation to grep
        workflow_yaml_path = Path(WORKFLOW_PATH)
        workflow_content = workflow_yaml_path.read_text()
        
        # Should contain resolve_repo_path call (runtime mechanism for Task 11)
        assert "resolve_repo_path" in workflow_content, \
            "Workflow must use resolve_repo_path() for out-of-tree repo resolution"
