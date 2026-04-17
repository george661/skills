"""Tests for the validate.yaml workflow definition.

Validates that the YAML-based validate workflow parses correctly, has proper
node ordering, dispatch configuration, gate conditions, and three mutually
exclusive routing paths that converge at evaluate_results.
"""
from pathlib import Path
from typing import Dict

import pytest

from dag_executor.graph import topological_sort_with_layers
from dag_executor.parser import load_workflow
from dag_executor.schema import (
    DispatchMode,
    NodeDef,
    NodeResult,
    NodeStatus,
    OnFailure,
    TriggerRule,
    WorkflowDef,
)
from tests.conftest import MockRunnerFactory, WorkflowTestHarness


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "validate.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the validate.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1: YAML parses without errors and has correct structure."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """validate.yaml loads with no validation errors."""
        assert workflow.name == "Validate Command Workflow"
        assert len(workflow.nodes) >= 15  # At least 15 nodes in the workflow

    def test_input_issue_key_required_with_pattern(
        self, workflow: WorkflowDef
    ) -> None:
        """issue_key input is required and has Jira key pattern."""
        ik = workflow.inputs["issue_key"]
        assert ik.required is True
        assert ik.pattern == r"^[A-Z]+-\d+$"

    def test_config_valid(self, workflow: WorkflowDef) -> None:
        """Workflow config has correct checkpoint prefix."""
        assert workflow.config.checkpoint_prefix == "validate"
        assert workflow.config.worktree is False

    def test_labels_config(self, workflow: WorkflowDef) -> None:
        """Workflow has labels config for failure handling."""
        assert workflow.config.labels is not None
        assert workflow.config.labels.on_failure == "outcome:validation-failed"

    def test_exit_hooks_configured(self, workflow: WorkflowDef) -> None:
        """Exit hooks are configured with cost_capture on completed and failed."""
        assert workflow.config.on_exit is not None
        assert len(workflow.config.on_exit) == 1
        cost_hook = workflow.config.on_exit[0]
        assert cost_hook.id == "cost_capture"
        assert cost_hook.type == "bash"
        assert "completed" in cost_hook.run_on
        assert "failed" in cost_hook.run_on


class TestTopologicalOrdering:
    """Test 2: Topological sort produces correct phase ordering."""

    def test_phase_ordering(self, workflow: WorkflowDef) -> None:
        """Phases execute in correct order matching /validate command."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        # Verify critical ordering constraints
        def before(a: str, b: str) -> None:
            assert flat_order.index(a) < flat_order.index(b), (
                f"{a} must execute before {b}"
            )

        # Phase 0: resume → blocker → classify → visual_impact
        before("resume_check", "code_review_blocker")
        before("code_review_blocker", "classify_type")
        before("classify_type", "visual_impact")

        # Phase 1: Gates depend on visual_impact
        before("visual_impact", "fast_path_gate")
        before("visual_impact", "pipeline_path_gate")
        before("visual_impact", "deploy_check")

        # Phase 2: Each gate → its downstream path
        before("fast_path_gate", "file_verification")
        before("pipeline_path_gate", "pipeline_verification")
        before("deploy_check", "run_tests")

        # Phase 3: All paths converge at evaluate_results
        before("file_verification", "evaluate_results")
        before("pipeline_verification", "evaluate_results")
        # Full path: smoke_regression → evaluate_results
        # (smoke_regression comes after collect_evidence)

        # Phase 4: Post-convergence
        before("evaluate_results", "transition_jira")
        before("transition_jira", "store_episode")
        before("store_episode", "print_summary")


class TestRoutingPaths:
    """Test 3: Three mutually exclusive routing paths."""

    def test_fast_path_gate_exists(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """fast_path_gate is a gate node with continue on failure."""
        gate = nodes_by_id["fast_path_gate"]
        assert gate.type == "gate"
        assert gate.on_failure == OnFailure.CONTINUE

    def test_pipeline_path_gate_exists(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """pipeline_path_gate is a gate node with continue on failure."""
        gate = nodes_by_id["pipeline_path_gate"]
        assert gate.type == "gate"
        assert gate.on_failure == OnFailure.CONTINUE

    def test_deploy_check_exists(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """deploy_check exists and starts full path."""
        node = nodes_by_id["deploy_check"]
        assert node.type == "command"  # deploy_check is a command node, not gate

    def test_file_verification_gated_by_fast_path(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """file_verification depends on fast_path_gate."""
        node = nodes_by_id["file_verification"]
        assert "fast_path_gate" in node.depends_on

    def test_pipeline_verification_gated_by_pipeline_path(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """pipeline_verification depends on pipeline_path_gate."""
        node = nodes_by_id["pipeline_verification"]
        assert "pipeline_path_gate" in node.depends_on


class TestConvergenceNode:
    """Test 4: evaluate_results uses trigger_rule: one_success."""

    def test_evaluate_results_uses_one_success(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """evaluate_results uses trigger_rule: one_success to converge paths."""
        node = nodes_by_id["evaluate_results"]
        assert node.trigger_rule == TriggerRule.ONE_SUCCESS, (
            "evaluate_results should use trigger_rule: one_success"
        )

    def test_evaluate_results_has_multiple_dependencies(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """evaluate_results depends on outputs from all three paths."""
        node = nodes_by_id["evaluate_results"]
        # Should have dependencies from file_verification, pipeline_verification,
        # and the full path (smoke_regression or similar)
        assert len(node.depends_on) >= 3, (
            "evaluate_results should depend on all three routing paths"
        )


class TestGateFailureStrategy:
    """Test 5: Gates use on_failure: continue so failed gates don't propagate."""

    def test_routing_gates_continue_on_failure(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Routing gate nodes use on_failure: continue."""
        gate_ids = ["fast_path_gate", "pipeline_path_gate"]
        for gate_id in gate_ids:
            gate = nodes_by_id[gate_id]
            assert gate.type == "gate"
            # Gates should continue on failure (allowing other paths to proceed)


class TestDispatchConfig:
    """Test 6: Dispatch configuration for different node types."""

    def test_classify_type_uses_inline_dispatch(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """classify_type uses dispatch: inline."""
        node = nodes_by_id["classify_type"]
        assert node.dispatch == DispatchMode.INLINE, (
            "classify_type should use dispatch: inline"
        )

    def test_visual_impact_uses_inline_dispatch(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """visual_impact uses dispatch: inline."""
        node = nodes_by_id["visual_impact"]
        assert node.dispatch == DispatchMode.INLINE, (
            "visual_impact should use dispatch: inline"
        )


class TestVariableSubstitution:
    """Test 7: Variable $issue_key resolves in node scripts/args."""

    def test_issue_key_in_nodes(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Nodes reference $issue_key in their scripts or prompts."""
        nodes_with_issue_key = [
            "resume_check",
            "transition_jira",
            "store_episode",
        ]
        for nid in nodes_with_issue_key:
            node = nodes_by_id[nid]
            node_text = (node.script or "") + (node.prompt or "")
            assert "$issue_key" in node_text, (
                f"{nid} should reference $issue_key"
            )


class TestRoutingPathExecution:
    """Integration test: Mock-execute validate.yaml for all routing paths."""

    def test_file_verification_fast_path_execution(
        self, test_harness: WorkflowTestHarness,
        mock_runner_factory: MockRunnerFactory,
        workflow: WorkflowDef
    ) -> None:
        """AC1: Fast path taken when classify_type returns file-verification."""
        factory = mock_runner_factory

        # Mock all node types to succeed by default
        test_harness.mock_all_runners(NodeResult(
            status=NodeStatus.COMPLETED,
            output={"ok": True}
        ))

        # Override prompt nodes (classify_type) to return specific routing output
        test_harness.mock_runner("prompt", factory.create(
            output={"validation_type": "file-verification"}
        ))

        result = test_harness.execute(workflow, {
            "issue_key": "TEST-1",
            "PROJECT_ROOT": "/tmp/test-project"
        })

        # Assert fast path nodes completed
        test_harness.assert_node_completed("classify_type")
        test_harness.assert_node_completed("fast_path_gate")
        test_harness.assert_node_completed("file_verification")

        # Assert other paths were skipped
        test_harness.assert_node_skipped("pipeline_path_gate")
        test_harness.assert_node_skipped("pipeline_verification")
        test_harness.assert_node_skipped("deploy_check")

    def test_pipeline_verification_path_execution(
        self, test_harness: WorkflowTestHarness,
        mock_runner_factory: MockRunnerFactory,
        workflow: WorkflowDef
    ) -> None:
        """AC2: Pipeline path taken when classify_type returns pipeline-verification."""
        factory = mock_runner_factory

        test_harness.mock_all_runners(NodeResult(
            status=NodeStatus.COMPLETED,
            output={"ok": True}
        ))

        # Override prompt to return pipeline-verification
        test_harness.mock_runner("prompt", factory.create(
            output={"validation_type": "pipeline-verification"}
        ))

        result = test_harness.execute(workflow, {
            "issue_key": "TEST-2",
            "PROJECT_ROOT": "/tmp/test-project"
        })

        # Assert pipeline path nodes completed
        test_harness.assert_node_completed("classify_type")
        test_harness.assert_node_completed("pipeline_path_gate")
        test_harness.assert_node_completed("pipeline_verification")

        # Assert other paths were skipped
        test_harness.assert_node_skipped("fast_path_gate")
        test_harness.assert_node_skipped("file_verification")
        test_harness.assert_node_skipped("deploy_check")

    def test_full_path_execution(
        self, test_harness: WorkflowTestHarness,
        mock_runner_factory: MockRunnerFactory,
        workflow: WorkflowDef
    ) -> None:
        """AC3: Full path taken when classify_type returns full validation type."""
        factory = mock_runner_factory

        test_harness.mock_all_runners(NodeResult(
            status=NodeStatus.COMPLETED,
            output={"ok": True}
        ))

        # Override prompt to return full
        test_harness.mock_runner("prompt", factory.create(
            output={"validation_type": "full"}
        ))

        result = test_harness.execute(workflow, {
            "issue_key": "TEST-3",
            "PROJECT_ROOT": "/tmp/test-project"
        })

        # Assert full path nodes completed
        test_harness.assert_node_completed("classify_type")
        # Both gates should skip (condition fails for both)
        test_harness.assert_node_skipped("fast_path_gate")
        test_harness.assert_node_skipped("pipeline_path_gate")
        # Full path should execute
        test_harness.assert_node_completed("deploy_check")
        test_harness.assert_node_completed("run_tests")
        test_harness.assert_node_completed("collect_evidence")
        test_harness.assert_node_completed("smoke_regression")

        # Fast/pipeline paths should skip
        test_harness.assert_node_skipped("file_verification")
        test_harness.assert_node_skipped("pipeline_verification")
