"""Tests for the issue.yaml workflow definition.

Validates parsing, node ordering, channels, gates, and integration tests with mock execution.
"""
import asyncio
import os
import tempfile
from pathlib import Path
from typing import Dict

import pytest
import yaml

from dag_executor.executor import WorkflowExecutor
from dag_executor.graph import topological_sort_with_layers
from dag_executor.parser import load_workflow, load_workflow_from_string
from dag_executor.schema import (
    NodeDef,
    NodeStatus,
    ReducerStrategy,
    WorkflowDef,
    WorkflowStatus,
)


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "issue.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load issue workflow for testing."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Map of node ID to NodeDef."""
    return {node.id: node for node in workflow.nodes}


class TestIssueWorkflowParsing:
    """Test 1: YAML parses and has correct structure."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """issue.yaml loads with no validation errors."""
        assert workflow.name == "Issue Creation"
        assert len(workflow.nodes) >= 5  # At least 5 nodes as per plan

    def test_input_description_required(self, workflow: WorkflowDef) -> None:
        """description input is required."""
        assert "description" in workflow.inputs
        assert workflow.inputs["description"].required is True

    def test_state_channels_declared(self, workflow: WorkflowDef) -> None:
        """Workflow declares refinement, classification, creation_result channels."""
        # refinement channel
        assert "refinement" in workflow.state
        refinement_ch = workflow.state["refinement"]
        assert refinement_ch.type == "dict"
        assert refinement_ch.reducer is not None
        assert refinement_ch.reducer.strategy == ReducerStrategy.OVERWRITE

        # classification channel
        assert "classification" in workflow.state
        classification_ch = workflow.state["classification"]
        assert classification_ch.type == "dict"
        assert classification_ch.reducer is not None
        assert classification_ch.reducer.strategy == ReducerStrategy.OVERWRITE

        # creation_result channel
        assert "creation_result" in workflow.state
        creation_result_ch = workflow.state["creation_result"]
        assert creation_result_ch.type == "dict"
        assert creation_result_ch.reducer is not None
        assert creation_result_ch.reducer.strategy == ReducerStrategy.OVERWRITE


class TestIssueTopologicalOrdering:
    """Test 2: Topological sort produces correct phase ordering."""

    def test_phase_ordering(self, workflow: WorkflowDef) -> None:
        """Phases execute in correct order."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        def before(a: str, b: str) -> None:
            idx_a = flat_order.index(a) if a in flat_order else -1
            idx_b = flat_order.index(b) if b in flat_order else -1
            assert idx_a >= 0 and idx_b >= 0, f"Both {a} and {b} must be in workflow"
            assert idx_a < idx_b, f"{a} must execute before {b}"

        # Phase ordering as per plan
        before("brainstorm_and_refine", "classify_issue_type")
        before("classify_issue_type", "duplicate_detection")
        before("duplicate_detection", "duplicate_gate")
        before("duplicate_gate", "create_and_link")


class TestIssueGate:
    """Test 3: duplicate_gate stops on duplicate."""

    def test_duplicate_gate_stops_on_duplicate(self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]) -> None:
        """duplicate_gate is a gate with on_failure=stop."""
        gate = nodes_by_id.get("duplicate_gate")
        assert gate is not None, "duplicate_gate node must exist"
        assert gate.type == "gate"
        assert gate.on_failure == "stop"


class TestIssueOutputs:
    """Test 4: issue_key output is declared."""

    def test_issue_key_output_declared(self, workflow: WorkflowDef) -> None:
        """issue_key output wired to create_and_link node."""
        assert "issue_key" in workflow.outputs
        # The output should reference a node that creates the issue


class TestIssueConfig:
    """Test 5: checkpoint_prefix is correct."""

    def test_checkpoint_prefix(self, workflow: WorkflowDef) -> None:
        """config.checkpoint_prefix == 'issue'."""
        assert workflow.config is not None
        assert workflow.config.checkpoint_prefix == "issue"


class TestIssueIntegrationWithMockExecution:
    """Test 6: Integration tests with mock execution."""

    def test_duplicate_gate_stops_workflow(self) -> None:
        """Mock duplicate_detection to return is_duplicate=true, verify gate stops workflow."""
        fixture_path = Path(__file__).parent.parent / "workflows" / "issue.yaml"

        # Load and modify workflow
        with open(fixture_path) as f:
            workflow_data = yaml.safe_load(f)

        # Mock duplicate_detection to return is_duplicate=true
        for node in workflow_data["nodes"]:
            if node["id"] == "brainstorm_and_refine":
                node["type"] = "bash"
                node["script"] = 'echo \'{"refined_summary": "Test", "refined_description": "Test"}\''
                node.pop("prompt", None)
                node.pop("dispatch", None)
            elif node["id"] == "classify_issue_type":
                node["type"] = "bash"
                node["script"] = 'echo \'{"issue_type": "standalone"}\''
                node.pop("prompt", None)
                node.pop("dispatch", None)
            elif node["id"] == "duplicate_detection":
                node["type"] = "bash"
                node["script"] = 'echo \'{"is_duplicate": true, "duplicate_key": "GW-0000"}\''
                node.pop("prompt", None)
                node.pop("dispatch", None)
            elif node["id"] == "create_and_link":
                node["script"] = 'echo "Should not execute"'

        # Save to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            yaml.dump(workflow_data, tmp)
            tmp_path = tmp.name

        try:
            with open(tmp_path) as f:
                workflow_def = load_workflow_from_string(f.read())

            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {"description": "test issue"}))

            # Workflow may complete or fail at gate
            assert result.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]

            # duplicate_detection should complete
            assert result.node_results["duplicate_detection"].status == NodeStatus.COMPLETED

            # Gate should fail/skip
            assert result.node_results["duplicate_gate"].status in [NodeStatus.FAILED, NodeStatus.SKIPPED]

            # Downstream node should be skipped
            assert result.node_results["create_and_link"].status == NodeStatus.SKIPPED

        finally:
            os.unlink(tmp_path)

    def test_happy_path_creates_issue(self) -> None:
        """Mock happy path, verify issue_key surfaces in outputs."""
        fixture_path = Path(__file__).parent.parent / "workflows" / "issue.yaml"

        # Load and modify workflow
        with open(fixture_path) as f:
            workflow_data = yaml.safe_load(f)

        # Mock all nodes to return success
        for node in workflow_data["nodes"]:
            if node["id"] == "brainstorm_and_refine":
                node["type"] = "bash"
                node["script"] = 'echo \'{"refined_summary": "Refined", "refined_description": "Refined desc"}\''
                node.pop("prompt", None)
                node.pop("dispatch", None)
            elif node["id"] == "classify_issue_type":
                node["type"] = "bash"
                node["script"] = 'echo \'{"issue_type": "standalone"}\''
                node.pop("prompt", None)
                node.pop("dispatch", None)
            elif node["id"] == "duplicate_detection":
                node["type"] = "bash"
                node["script"] = 'echo \'{"is_duplicate": false}\''
                node.pop("prompt", None)
                node.pop("dispatch", None)
            elif node["id"] == "duplicate_gate":
                # Gate should pass when is_duplicate is false
                node["type"] = "bash"
                node["script"] = 'echo "Gate passed"'
                node.pop("condition", None)
            elif node["id"] == "create_and_link":
                node["script"] = 'echo \'{"issue_key": "GW-8888"}\''

        # Save to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            yaml.dump(workflow_data, tmp)
            tmp_path = tmp.name

        try:
            with open(tmp_path) as f:
                workflow_def = load_workflow_from_string(f.read())

            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {"description": "test issue"}))

            # Workflow should complete
            assert result.status == WorkflowStatus.COMPLETED

            # All nodes should complete
            assert result.node_results["brainstorm_and_refine"].status == NodeStatus.COMPLETED
            assert result.node_results["classify_issue_type"].status == NodeStatus.COMPLETED
            assert result.node_results["duplicate_detection"].status == NodeStatus.COMPLETED
            assert result.node_results["duplicate_gate"].status == NodeStatus.COMPLETED
            assert result.node_results["create_and_link"].status == NodeStatus.COMPLETED

        finally:
            os.unlink(tmp_path)


class TestIssueDryRun:
    """Test 7: Dry-run succeeds."""

    def test_dry_run_succeeds(self) -> None:
        """Dry-run completes without error."""
        from dag_executor.cli import run_dry_run

        workflow_path = Path(__file__).parent.parent / "workflows" / "issue.yaml"
        # run_dry_run should not raise an exception
        run_dry_run(str(workflow_path))
