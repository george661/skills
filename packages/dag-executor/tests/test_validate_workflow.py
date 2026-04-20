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
        assert len(workflow.nodes) >= 14  # 16 nodes after removing 2 gates

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

    def test_no_hardcoded_smoke_test_path(self, workflow: WorkflowDef) -> None:
        """validate.yaml should not contain hardcoded smoke test paths."""
        # Read the raw YAML file to check for hardcoded paths
        with open(WORKFLOW_PATH, 'r') as f:
            content = f.read()
        assert 'lambda-functions/tests/smoke' not in content, \
            "Found hardcoded smoke test path - should use $TENANT_SMOKE_TEST_PATH env var"

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

        # Phase 1: classify_type routes via edges (no gates)
        before("classify_type", "file_verification")
        before("classify_type", "pipeline_verification")
        before("classify_type", "deploy_check")

        # Phase 2: deploy_check → run_tests
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
    """Test 3: Three mutually exclusive routing paths via edges."""

    def test_classify_type_has_edges(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """classify_type has edges for 3-way routing."""
        node = nodes_by_id["classify_type"]
        assert node.edges is not None, "classify_type should have edges"
        assert len(node.edges) == 3, "classify_type should have 3 edges"

    def test_classify_type_edges_structure(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """classify_type edges have correct targets and conditions."""
        node = nodes_by_id["classify_type"]
        targets = {edge.target for edge in node.edges}
        assert targets == {
            "file_verification",
            "pipeline_verification",
            "deploy_check",
        }, "classify_type edges should route to 3 targets"

    def test_classify_type_has_default_edge(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """classify_type has exactly one default edge."""
        node = nodes_by_id["classify_type"]
        default_edges = [e for e in node.edges if e.default]
        assert len(default_edges) == 1, "Should have exactly one default edge"
        assert default_edges[0].target == "deploy_check", (
            "Default edge should route to deploy_check (full path)"
        )

    def test_fast_path_gate_removed(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """fast_path_gate node removed (replaced by edges)."""
        assert "fast_path_gate" not in nodes_by_id

    def test_pipeline_path_gate_removed(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """pipeline_path_gate node removed (replaced by edges)."""
        assert "pipeline_path_gate" not in nodes_by_id

    def test_file_verification_no_explicit_depends_on(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """file_verification depends on classify_type via edge (not explicit)."""
        node = nodes_by_id["file_verification"]
        # Edge-implied dependency, so depends_on should be empty or only list classify_type
        assert (
            not node.depends_on or "classify_type" in node.depends_on
        ), "file_verification should not have gate in depends_on"

    def test_pipeline_verification_no_explicit_depends_on(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """pipeline_verification depends on classify_type via edge (not explicit)."""
        node = nodes_by_id["pipeline_verification"]
        assert (
            not node.depends_on or "classify_type" in node.depends_on
        ), "pipeline_verification should not have gate in depends_on"


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


class TestStateChannels:
    """Test 5: State channel declarations exist."""

    def test_state_channels_declared(self, workflow: WorkflowDef) -> None:
        """Workflow has state channel declarations."""
        assert workflow.state is not None, "Workflow should have state channels"
        assert len(workflow.state) >= 6, "Should have at least 6 state channels"

    def test_state_channel_names(self, workflow: WorkflowDef) -> None:
        """Required state channels are declared."""
        channel_names = set(workflow.state.keys())
        required_channels = {
            "classification",
            "visual_impact",
            "test_results",
            "evidence",
            "verdict",
            "transition_result",
        }
        assert required_channels.issubset(channel_names), (
            f"Missing channels: {required_channels - channel_names}"
        )


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
        """Nodes reference $issue_key in their scripts or prompts or args."""
        nodes_with_issue_key = [
            "resume_check",
            "transition_jira",
            "store_episode",
        ]
        for nid in nodes_with_issue_key:
            node = nodes_by_id[nid]
            node_text = (node.script or "") + (node.prompt or "")
            # Command nodes pass $issue_key via args
            if node.type == "command" and node.args:
                node_text += " ".join(str(arg) for arg in node.args)
            assert "$issue_key" in node_text, (
                f"{nid} should reference $issue_key"
            )


def _strip_scripts(workflow: WorkflowDef) -> WorkflowDef:
    """Return a copy of *workflow* with script/prompt/args bodies cleared.

    The executor resolves ``$var`` references in script, prompt, and args
    before calling the runner.  Production workflows use shell variables
    and output references that are only valid at runtime.  Clearing them
    lets mock runners execute without variable-resolution errors while
    preserving the full DAG structure (deps, trigger rules, on_failure).
    """
    import copy
    wf = copy.deepcopy(workflow)
    for node in wf.nodes:
        node.script = None
        node.prompt = None
        node.args = None
    return wf


class TestRoutingPathExecution:
    """Integration test: Mock-execute validate.yaml through the executor.

    Strips script/prompt bodies so the variable resolver doesn't trip on
    undeclared shell variables.  Gate conditions are preserved so the real
    GateRunner evaluates routing.
    """

    INPUTS = {"issue_key": "TEST-1", "PROJECT_ROOT": "/tmp/test"}

    def test_workflow_structure_valid(
        self, workflow: WorkflowDef,
    ) -> None:
        """AC1: Workflow structure validates correctly."""
        # Verify all required nodes exist
        node_ids = {n.id for n in workflow.nodes}
        required_nodes = {
            "resume_check", "code_review_blocker", "classify_type",
            "visual_impact", "file_verification", "pipeline_verification",
            "deploy_check", "run_tests", "evaluate_results",
            "transition_jira", "store_episode", "print_summary",
        }
        assert required_nodes.issubset(node_ids), (
            f"Missing nodes: {required_nodes - node_ids}"
        )

        # Verify gate nodes removed
        assert "fast_path_gate" not in node_ids
        assert "pipeline_path_gate" not in node_ids

    def test_edge_routing_skips_non_matching_paths(
        self, test_harness: WorkflowTestHarness,
        workflow: WorkflowDef,
    ) -> None:
        """AC2: Edge-based routing skips non-matching paths."""
        wf = _strip_scripts(workflow)
        # Return "full" validation type to route to deploy_check (default edge)
        test_harness.mock_all_runners(NodeResult(
            status=NodeStatus.COMPLETED,
            output={"validation_type": "full", "ok": True},
        ))
        test_harness.execute(wf, self.INPUTS)

        # Fast and pipeline paths should be skipped (edges don't match)
        test_harness.assert_node_skipped("file_verification")
        test_harness.assert_node_skipped("pipeline_verification")
        test_harness.assert_node_completed("deploy_check")

    def test_convergence_with_one_path(
        self, test_harness: WorkflowTestHarness,
        workflow: WorkflowDef,
    ) -> None:
        """AC3: evaluate_results runs via one_success when full path completes."""
        wf = _strip_scripts(workflow)
        test_harness.mock_all_runners(NodeResult(
            status=NodeStatus.COMPLETED,
            output={"validation_type": "full", "ok": True},
        ))
        test_harness.execute(wf, self.INPUTS)

        test_harness.assert_node_completed("evaluate_results")
        test_harness.assert_node_completed("transition_jira")
        test_harness.assert_node_completed("print_summary")


    def test_full_path_routing(
        self, test_harness: WorkflowTestHarness,
        workflow: WorkflowDef,
    ) -> None:
        """AC7: Full path routes to deploy_check as default."""
        wf = _strip_scripts(workflow)
        test_harness.mock_all_runners(NodeResult(
            status=NodeStatus.COMPLETED,
            output={"validation_type": "full", "ok": True},
        ))
        test_harness.execute(wf, self.INPUTS)

        test_harness.assert_node_skipped("file_verification")
        test_harness.assert_node_skipped("pipeline_verification")
        test_harness.assert_node_completed("deploy_check")


class TestSubDAGIntegration:
    """Test: evaluate_results and transition_jira converted to command nodes."""

    def test_evaluate_results_is_command_node(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """evaluate_results is now a command node invoking validate-evaluate sub-DAG."""
        node = nodes_by_id["evaluate_results"]
        assert node.type == "command", (
            "evaluate_results should be type: command (was prompt, now sub-DAG)"
        )
        assert node.command == "validate-evaluate", (
            "evaluate_results should invoke validate-evaluate sub-DAG"
        )

    def test_transition_jira_is_command_node(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """transition_jira is now a command node invoking validate-transition sub-DAG."""
        node = nodes_by_id["transition_jira"]
        assert node.type == "command", (
            "transition_jira should be type: command (was prompt, now sub-DAG)"
        )
        assert node.command == "validate-transition", (
            "transition_jira should invoke validate-transition sub-DAG"
        )

    def test_sub_dag_files_exist(self) -> None:
        """Verify all sub-DAG YAML files exist."""
        from pathlib import Path
        workflows_dir = Path(__file__).parent.parent / "workflows"
        
        sub_dags = [
            "validate-deploy-status.yaml",
            "validate-run-tests.yaml",
            "validate-collect-evidence.yaml",
            "validate-evaluate.yaml",
            "validate-transition.yaml",
        ]
        
        for sub_dag in sub_dags:
            path = workflows_dir / sub_dag
            assert path.exists(), f"Sub-DAG {sub_dag} should exist"
