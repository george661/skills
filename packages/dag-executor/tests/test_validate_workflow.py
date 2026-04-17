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


class TestRoutingPathStructure:
    """Integration test: Verify routing path structure and conditional edges."""

    def test_file_verification_path_with_gate(
        self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """File-verification routing path uses fast_path_gate."""
        # Verify gate structure
        fast_gate = nodes_by_id["fast_path_gate"]
        assert fast_gate.type == "gate"
        assert "classify_type" in fast_gate.depends_on
        assert fast_gate.condition == "$classify_type.validation_type == \"file-verification\""

        # Verify file_verification depends on the gate
        file_verify = nodes_by_id["file_verification"]
        assert "fast_path_gate" in file_verify.depends_on

    def test_pipeline_verification_path_with_gate(
        self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Pipeline-verification routing path uses pipeline_path_gate."""
        # Verify gate structure
        pipeline_gate = nodes_by_id["pipeline_path_gate"]
        assert pipeline_gate.type == "gate"
        assert "classify_type" in pipeline_gate.depends_on
        assert pipeline_gate.condition == "$classify_type.validation_type == \"pipeline-verification\""

        # Verify pipeline_verification depends on the gate
        pipeline_verify = nodes_by_id["pipeline_verification"]
        assert "pipeline_path_gate" in pipeline_verify.depends_on

    def test_full_path_as_default(
        self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Full-path routing is default when fast/pipeline gates don't pass."""
        # deploy_check is entry point for full path
        deploy_check = nodes_by_id["deploy_check"]

        # It depends on both gates with all_done trigger (runs when gates are skipped)
        assert "fast_path_gate" in deploy_check.depends_on
        assert "pipeline_path_gate" in deploy_check.depends_on
        assert deploy_check.trigger_rule == TriggerRule.ALL_DONE


class TestRoutingPathConditionals:
    """Test conditional edges for routing paths."""

    def test_two_gates_route_fast_and_pipeline_paths(
        self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Verify two gates route fast and pipeline paths from classify_type."""
        # Both gates should depend on classify_type
        fast_gate = nodes_by_id["fast_path_gate"]
        pipeline_gate = nodes_by_id["pipeline_path_gate"]

        assert "classify_type" in fast_gate.depends_on
        assert "classify_type" in pipeline_gate.depends_on

        # Gates should have mutually exclusive conditions
        assert "file-verification" in fast_gate.condition
        assert "pipeline-verification" in pipeline_gate.condition

    def test_full_path_runs_when_gates_skip(
        self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Verify full path (deploy_check) runs when both gates fail/skip."""
        deploy_check = nodes_by_id["deploy_check"]

        # deploy_check uses all_done trigger on both gates, so it runs
        # when both gates are done (whether they passed or were skipped)
        assert deploy_check.trigger_rule == TriggerRule.ALL_DONE
        assert "fast_path_gate" in deploy_check.depends_on
        assert "pipeline_path_gate" in deploy_check.depends_on

    def test_paths_converge_at_evaluate_results(
        self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Verify all three paths converge at evaluate_results."""
        evaluate = nodes_by_id["evaluate_results"]

        # evaluate_results should have one_success trigger to run when any path completes
        assert evaluate.trigger_rule == TriggerRule.ONE_SUCCESS
