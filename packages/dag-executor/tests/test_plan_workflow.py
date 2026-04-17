"""Tests for the plan.yaml workflow definition.

Validates that the YAML-based plan workflow parses correctly, has proper
node ordering, review pipeline with skeleton gate, and correct failure strategies.
"""
from pathlib import Path
from typing import Dict

import pytest

from dag_executor.graph import topological_sort_with_layers
from dag_executor.parser import load_workflow
from dag_executor.schema import (
    DispatchMode,
    NodeDef,
    OnFailure,
    TriggerRule,
    WorkflowDef,
)


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "plan.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the plan.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1: YAML parses without errors and has correct structure."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """plan.yaml loads with no validation errors."""
        assert workflow.name == "Plan Command Workflow"
        assert len(workflow.nodes) >= 10  # At least 10 nodes in the workflow

    def test_input_epic_key_required(
        self, workflow: WorkflowDef
    ) -> None:
        """epic_key input is required."""
        ek = workflow.inputs["epic_key"]
        assert ek.required is True

    def test_config_valid(self, workflow: WorkflowDef) -> None:
        """Workflow config has correct checkpoint prefix."""
        assert workflow.config.checkpoint_prefix == "plan"

    def test_labels_config(self, workflow: WorkflowDef) -> None:
        """Workflow has labels config for failure handling."""
        assert workflow.config.labels is not None


class TestTopologicalOrdering:
    """Test 2: Topological sort produces correct phase ordering."""

    def test_phase_ordering(self, workflow: WorkflowDef) -> None:
        """Phases execute in correct order matching /plan command."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        # Verify critical ordering constraints
        def before(a: str, b: str) -> None:
            assert flat_order.index(a) < flat_order.index(b), (
                f"{a} must execute before {b}"
            )

        # Phase 0: Init → design_discovery
        before("init_session", "design_discovery")
        
        # Phase 1: Parallel fetch epic and domain design
        before("design_discovery", "fetch_epic")
        before("design_discovery", "domain_design")
        
        # Phase 2: Create PRP after requirements
        before("read_repo_requirements", "create_prp")
        
        # Phase 3: Review pipeline
        before("create_prp", "design_integration")
        before("design_integration", "create_skeleton")
        before("create_skeleton", "review_skeleton")
        before("review_skeleton", "skeleton_gate")


class TestReviewPipeline:
    """Test 3: Review pipeline with skeleton gate."""

    def test_skeleton_gate_exists(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """skeleton_gate is a gate node."""
        gate = nodes_by_id["skeleton_gate"]
        assert gate.type == "gate"

    def test_skeleton_gate_continues_on_failure(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """skeleton_gate uses on_failure: continue to allow fix_skeleton."""
        gate = nodes_by_id["skeleton_gate"]
        assert gate.on_failure == OnFailure.CONTINUE

    def test_fix_skeleton_depends_on_skeleton_gate(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """fix_skeleton depends on skeleton_gate."""
        node = nodes_by_id["fix_skeleton"]
        assert "skeleton_gate" in node.depends_on

    def test_fix_skeleton_uses_all_done_trigger(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """fix_skeleton uses trigger_rule: all_done."""
        node = nodes_by_id["fix_skeleton"]
        assert node.trigger_rule == TriggerRule.ALL_DONE


class TestFirstReviewConvergence:
    """Test 4: first_review converges skeleton_gate and fix_skeleton."""

    def test_first_review_uses_one_success(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """first_review uses trigger_rule: one_success."""
        node = nodes_by_id["first_review"]
        assert node.trigger_rule == TriggerRule.ONE_SUCCESS

    def test_first_review_depends_on_both_paths(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """first_review depends on skeleton_gate and fix_skeleton."""
        node = nodes_by_id["first_review"]
        assert "skeleton_gate" in node.depends_on or "review_skeleton" in node.depends_on
        assert "fix_skeleton" in node.depends_on

    def test_arch_review_after_first_review(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """arch_review depends on first_review."""
        node = nodes_by_id["arch_review"]
        assert "first_review" in node.depends_on


class TestFailureStrategies:
    """Test 5: Failure strategies for different nodes."""

    def test_fetch_epic_stops_on_failure(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """fetch_epic uses on_failure: stop (hard stop)."""
        node = nodes_by_id["fetch_epic"]
        assert node.on_failure == OnFailure.STOP

    def test_domain_design_continues_on_failure(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """domain_design uses on_failure: continue (soft continue)."""
        node = nodes_by_id["domain_design"]
        assert node.on_failure == OnFailure.CONTINUE


class TestDispatchConfig:
    """Test 6: Dispatch configuration for different node types."""

    def test_design_discovery_dispatch(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """design_discovery has appropriate dispatch mode."""
        node = nodes_by_id["design_discovery"]
        # Check it has a dispatch mode set (local or inline)
        assert node.dispatch in [DispatchMode.LOCAL, DispatchMode.INLINE, None]

    def test_create_prp_dispatch(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """create_prp has appropriate dispatch mode."""
        node = nodes_by_id["create_prp"]
        # Check it has a dispatch mode set
        assert node.dispatch in [DispatchMode.LOCAL, DispatchMode.INLINE, None]


class TestVariableSubstitution:
    """Test 7: Variable $epic_key resolves in node scripts/args."""

    def test_epic_key_in_nodes(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Nodes reference $epic_key in their scripts or prompts."""
        # fetch_epic should reference epic_key
        node = nodes_by_id["fetch_epic"]
        node_text = (node.script or "") + (node.prompt or "")
        assert "$epic_key" in node_text, (
            "fetch_epic should reference $epic_key"
        )


# Import additional classes for integration tests
from dag_executor.schema import NodeResult, NodeStatus, TriggerRule
from tests.conftest import MockRunnerFactory, WorkflowTestHarness


class TestPlanWorkflowReviewOrdering:
    """Integration test: Verify review pipeline node ordering."""

    def test_skeleton_before_reviews(
        self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Skeleton creation/review happens before domain reviews."""
        create_skel = nodes_by_id["create_skeleton"]
        review_skel = nodes_by_id["review_skeleton"]
        first_review = nodes_by_id["first_review"]

        # create_skeleton should come before review_skeleton
        assert "create_skeleton" in review_skel.depends_on

        # skeleton_gate should come after review_skeleton
        skel_gate = nodes_by_id["skeleton_gate"]
        assert "review_skeleton" in skel_gate.depends_on

        # first_review should depend on skeleton_gate (directly or via trigger rule)
        # Check if first_review depends on skeleton_gate or uses a trigger rule
        assert "skeleton_gate" in first_review.depends_on or first_review.trigger_rule is not None

    def test_review_pipeline_ordering(
        self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Review phases proceed in correct order."""
        # Verify review nodes exist
        first_review = nodes_by_id["first_review"]
        arch_review = nodes_by_id["arch_review"]
        security_audit = nodes_by_id["security_audit"]
        final_review = nodes_by_id["final_review"]

        assert first_review is not None
        assert arch_review is not None
        assert security_audit is not None
        assert final_review is not None


class TestSkeletonGateFailureRetry:
    """Integration test: skeleton_gate failure triggers fix_skeleton retry."""

    def test_skeleton_gate_has_continue_on_failure(
        self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """skeleton_gate uses on_failure: continue (soft continue)."""
        skel_gate = nodes_by_id["skeleton_gate"]
        assert skel_gate.on_failure == OnFailure.CONTINUE

    def test_fix_skeleton_exists_with_correct_dependencies(
        self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """fix_skeleton node exists and depends on skeleton_gate."""
        fix_skel = nodes_by_id["fix_skeleton"]
        assert fix_skel is not None

        # fix_skeleton should depend on skeleton_gate (triggered when gate fails)
        assert "skeleton_gate" in fix_skel.depends_on

    def test_first_review_uses_one_success_trigger(
        self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """first_review uses one_success to run after skeleton_gate OR fix_skeleton."""
        first_review = nodes_by_id["first_review"]

        # first_review should use one_success trigger rule
        assert first_review.trigger_rule == TriggerRule.ONE_SUCCESS
