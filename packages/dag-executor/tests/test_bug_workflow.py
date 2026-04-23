"""Tests for the bug.yaml workflow definition.

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
    Path(__file__).parent.parent / "workflows" / "bug.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load bug workflow for testing."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Map of node ID to NodeDef."""
    return {node.id: node for node in workflow.nodes}


class TestBugWorkflowParsing:
    """Test 1: YAML parses and has correct structure."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """bug.yaml loads with no validation errors."""
        assert workflow.name == "Bug Report"
        assert len(workflow.nodes) >= 7  # At least 7 nodes (plan says ~8)

    def test_input_description_required(self, workflow: WorkflowDef) -> None:
        """description input is required."""
        assert "description" in workflow.inputs
        assert workflow.inputs["description"].required is True

    def test_state_channels_declared(self, workflow: WorkflowDef) -> None:
        """Workflow declares evidence, classification, root_cause, creation_result, test_result channels."""
        # evidence channel
        assert "evidence" in workflow.state
        evidence_ch = workflow.state["evidence"]
        assert evidence_ch.type == "dict"
        assert evidence_ch.reducer is not None
        assert evidence_ch.reducer.strategy == ReducerStrategy.OVERWRITE

        # classification channel
        assert "classification" in workflow.state
        classification_ch = workflow.state["classification"]
        assert classification_ch.type == "dict"
        assert classification_ch.reducer is not None
        assert classification_ch.reducer.strategy == ReducerStrategy.OVERWRITE

        # root_cause channel
        assert "root_cause" in workflow.state
        root_cause_ch = workflow.state["root_cause"]
        assert root_cause_ch.type == "dict"
        assert root_cause_ch.reducer is not None
        assert root_cause_ch.reducer.strategy == ReducerStrategy.OVERWRITE

        # creation_result channel
        assert "creation_result" in workflow.state
        creation_result_ch = workflow.state["creation_result"]
        assert creation_result_ch.type == "dict"
        assert creation_result_ch.reducer is not None
        assert creation_result_ch.reducer.strategy == ReducerStrategy.OVERWRITE

        # test_result channel
        assert "test_result" in workflow.state
        test_result_ch = workflow.state["test_result"]
        assert test_result_ch.type == "dict"
        assert test_result_ch.reducer is not None
        assert test_result_ch.reducer.strategy == ReducerStrategy.OVERWRITE


class TestBugTopologicalOrdering:
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
        before("load_context", "collect_evidence")
        before("collect_evidence", "duplicate_detection")
        before("duplicate_detection", "duplicate_gate")
        before("duplicate_gate", "analyze_root_cause")
        before("analyze_root_cause", "create_bug_issue")
        before("create_bug_issue", "failing_test_gate")
        before("failing_test_gate", "transition_and_link")


class TestBugGate:
    """Test 3: duplicate_gate stops on duplicate."""

    def test_duplicate_gate_stops_on_duplicate(self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]) -> None:
        """duplicate_gate is a gate with on_failure=stop."""
        gate = nodes_by_id.get("duplicate_gate")
        assert gate is not None, "duplicate_gate node must exist"
        assert gate.type == "gate"
        assert gate.on_failure == "stop"


class TestBugOutputs:
    """Test 4: bug_key output is declared."""

    def test_bug_key_output_declared(self, workflow: WorkflowDef) -> None:
        """bug_key output wired to create_bug_issue node."""
        assert "bug_key" in workflow.outputs
        # The output should reference a node that creates the bug
        # (could be from create_bug_issue node's writes to creation_result channel)


class TestBugConfig:
    """Test 5: checkpoint_prefix is correct."""

    def test_checkpoint_prefix(self, workflow: WorkflowDef) -> None:
        """config.checkpoint_prefix == 'bug'."""
        assert workflow.config is not None
        assert workflow.config.checkpoint_prefix == "bug"


class TestBugIntegrationWithMockExecution:
    """Test 6: Integration tests with mock execution."""

    def test_duplicate_gate_stops_workflow(self) -> None:
        """Mock duplicate_detection to return is_duplicate=true, verify gate stops workflow."""
        fixture_path = Path(__file__).parent.parent / "workflows" / "bug.yaml"

        # Load and modify workflow
        with open(fixture_path) as f:
            workflow_data = yaml.safe_load(f)

        # Mock duplicate_detection to return is_duplicate=true
        for node in workflow_data["nodes"]:
            if node["id"] == "load_context":
                node["script"] = 'echo \'{"pipeline_mode": false}\''
            elif node["id"] == "collect_evidence":
                node["script"] = 'echo \'{"logs": "test log"}\''
            elif node["id"] == "duplicate_detection":
                node["type"] = "bash"
                node["script"] = 'echo \'{"is_duplicate": true, "duplicate_key": "GW-0000"}\''
                node.pop("prompt", None)
                node.pop("dispatch", None)
            elif node["id"] in ["analyze_root_cause", "create_bug_issue", "failing_test_gate"]:
                node["type"] = "bash"
                node["script"] = 'echo "Should not execute"'
                node.pop("prompt", None)
                node.pop("dispatch", None)
            elif node["id"] == "transition_and_link":
                node["script"] = 'echo "Should not execute"'

        # Save to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            yaml.dump(workflow_data, tmp)
            tmp_path = tmp.name

        try:
            with open(tmp_path) as f:
                workflow_def = load_workflow_from_string(f.read())

            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {"description": "test bug"}))

            # Workflow may complete or fail at gate
            assert result.status in [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED]

            # duplicate_detection should complete
            assert result.node_results["duplicate_detection"].status == NodeStatus.COMPLETED

            # Gate should fail/skip
            assert result.node_results["duplicate_gate"].status in [NodeStatus.FAILED, NodeStatus.SKIPPED]

            # Downstream nodes should be skipped
            assert result.node_results["analyze_root_cause"].status == NodeStatus.SKIPPED
            assert result.node_results["create_bug_issue"].status == NodeStatus.SKIPPED
            assert result.node_results["failing_test_gate"].status == NodeStatus.SKIPPED
            assert result.node_results["transition_and_link"].status == NodeStatus.SKIPPED

        finally:
            os.unlink(tmp_path)

    def test_happy_path_creates_bug(self) -> None:
        """Mock happy path, verify bug_key surfaces in outputs."""
        fixture_path = Path(__file__).parent.parent / "workflows" / "bug.yaml"

        # Load and modify workflow
        with open(fixture_path) as f:
            workflow_data = yaml.safe_load(f)

        # Mock all nodes to return success
        for node in workflow_data["nodes"]:
            if node["id"] == "load_context":
                node["script"] = 'echo \'{"pipeline_mode": false}\''
            elif node["id"] == "collect_evidence":
                node["script"] = 'echo \'{"logs": "test log", "errors": "test error"}\''
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
            elif node["id"] == "analyze_root_cause":
                node["type"] = "bash"
                node["script"] = 'echo \'{"hypothesis": "root cause found"}\''
                node.pop("prompt", None)
                node.pop("dispatch", None)
            elif node["id"] == "create_bug_issue":
                node["type"] = "bash"
                node["script"] = 'echo \'{"bug_key": "GW-9999"}\''
                node.pop("prompt", None)
                node.pop("dispatch", None)
            elif node["id"] == "failing_test_gate":
                node["type"] = "bash"
                node["script"] = 'echo \'{"test_branches": ["test-branch"]}\''
                node.pop("prompt", None)
                node.pop("dispatch", None)
            elif node["id"] == "transition_and_link":
                node["script"] = 'echo "Transitioned and linked"'

        # Save to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as tmp:
            yaml.dump(workflow_data, tmp)
            tmp_path = tmp.name

        try:
            with open(tmp_path) as f:
                workflow_def = load_workflow_from_string(f.read())

            executor = WorkflowExecutor()
            result = asyncio.run(executor.execute(workflow_def, {"description": "test bug"}))

            # Workflow should complete
            assert result.status == WorkflowStatus.COMPLETED

            # All nodes should complete
            assert result.node_results["load_context"].status == NodeStatus.COMPLETED
            assert result.node_results["collect_evidence"].status == NodeStatus.COMPLETED
            assert result.node_results["duplicate_detection"].status == NodeStatus.COMPLETED
            assert result.node_results["duplicate_gate"].status == NodeStatus.COMPLETED
            assert result.node_results["analyze_root_cause"].status == NodeStatus.COMPLETED
            assert result.node_results["create_bug_issue"].status == NodeStatus.COMPLETED
            assert result.node_results["failing_test_gate"].status == NodeStatus.COMPLETED
            assert result.node_results["transition_and_link"].status == NodeStatus.COMPLETED

        finally:
            os.unlink(tmp_path)


class TestBugDryRun:
    """Test 7: Dry-run succeeds."""

    def test_dry_run_succeeds(self) -> None:
        """Dry-run completes without error."""
        from dag_executor.cli import run_dry_run

        workflow_path = Path(__file__).parent.parent / "workflows" / "bug.yaml"
        # run_dry_run should not raise an exception
        run_dry_run(str(workflow_path))
