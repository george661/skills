"""Tests for the groom.yaml workflow definition.

Validates that the YAML-based groom workflow parses correctly, has proper
node ordering, skeleton invocation, review gates, and issues router usage.
"""
from pathlib import Path
from typing import Dict

import pytest

from dag_executor.graph import topological_sort_with_layers
from dag_executor.parser import load_workflow
from dag_executor.schema import (
    NodeDef,
    OnFailure,
    TriggerRule,
    WorkflowDef,
)


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "groom.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the groom.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1: YAML parses without errors and has correct structure."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """groom.yaml loads with no validation errors."""
        assert workflow.name == "Groom Command Workflow"
        assert len(workflow.nodes) >= 20  # At least 20 nodes for the phases

    def test_input_epic_key_required(
        self, workflow: WorkflowDef
    ) -> None:
        """epic_key input is required."""
        ek = workflow.inputs["epic_key"]
        assert ek.required is True

    def test_config_valid(self, workflow: WorkflowDef) -> None:
        """Workflow config has correct checkpoint prefix."""
        assert workflow.config.checkpoint_prefix == "groom"

    def test_labels_config(self, workflow: WorkflowDef) -> None:
        """Workflow has labels config for failure handling."""
        assert workflow.config.labels is not None
        assert "outcome:grooming-incomplete" in str(workflow.config.labels.on_failure)

    def test_no_hardcoded_tenant_paths(self, workflow: WorkflowDef) -> None:
        """groom.yaml should not contain hardcoded tenant paths."""
        with open(WORKFLOW_PATH, 'r') as f:
            content = f.read()
        assert 'gw-docs' not in content, \
            "Found hardcoded 'gw-docs' path"
        assert '"gw"' not in content.lower() or 'tenant_namespace' in content.lower(), \
            "Found hardcoded 'gw' namespace - should use $TENANT_NAMESPACE"


class TestTopologicalOrdering:
    """Test 2: Topological sort produces correct phase ordering."""

    def test_phase_ordering(self, workflow: WorkflowDef) -> None:
        """Phases execute in correct order matching /groom command."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        def before(a: str, b: str) -> None:
            assert flat_order.index(a) < flat_order.index(b), (
                f"{a} must execute before {b}"
            )

        # Phase 0: Init → design_discovery
        before("init_session", "design_discovery")
        
        # Phase 1: Fetch epic
        before("design_discovery", "fetch_epic")
        
        # Phase 2: Parse PRP
        before("fetch_epic", "parse_prp")
        
        # Phase 2.5: Domain derivation
        before("parse_prp", "domain_derivation")
        
        # Phase 3: Calculate tiers
        before("domain_derivation", "calculate_tiers")
        
        # Phase 3.5: Skeleton pipeline
        before("calculate_tiers", "create_skeleton")
        before("create_skeleton", "review_skeleton")
        before("review_skeleton", "skeleton_gate")

    def test_skeleton_gate_before_reviews(
        self, workflow: WorkflowDef
    ) -> None:
        """Skeleton pipeline completes before review layer."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        def before(a: str, b: str) -> None:
            assert flat_order.index(a) < flat_order.index(b)

        # Skeleton must complete (including fix if needed) before reviews
        before("skeleton_gate", "first_review")

    def test_reviews_sequential(self, workflow: WorkflowDef) -> None:
        """Reviews form a linear chain: first → arch → final."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        def before(a: str, b: str) -> None:
            assert flat_order.index(a) < flat_order.index(b)

        before("first_review", "arch_review")
        before("arch_review", "final_review")


class TestChannelsAndState:
    """Test 3: State channels are declared and used correctly."""

    def test_state_channels_declared(
        self, workflow: WorkflowDef
    ) -> None:
        """Required state channels are declared."""
        state = workflow.state
        assert "prp_state" in state
        assert "issue_list" in state
        assert "dependency_graph" in state
        assert "review_verdicts" in state
        assert "skeleton_output" in state

    def test_reducers_correct(self, workflow: WorkflowDef) -> None:
        """State channels have correct reducers."""
        state = workflow.state
        # Append reducers for list channels
        assert state["issue_list"].reducer.strategy.value == "append"
        assert state["review_verdicts"].reducer.strategy.value == "append"
        # Overwrite reducers for dict channels
        assert state["prp_state"].reducer.strategy.value == "overwrite"
        assert state["dependency_graph"].reducer.strategy.value == "overwrite"
        assert state["skeleton_output"].reducer.strategy.value == "overwrite"

    def test_review_verdicts_writers(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Review nodes write to review_verdicts channel."""
        review_nodes = ["first_review", "arch_review", "final_review"]
        for node_id in review_nodes:
            node = nodes_by_id[node_id]
            assert node.writes and "review_verdicts" in node.writes, \
                f"{node_id} should write to review_verdicts"


class TestSubDAGInvocation:
    """Test 4: Skeleton sub-DAG invocation pattern."""

    def test_skeleton_subdag_commands(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Skeleton nodes use type=command."""
        assert nodes_by_id["create_skeleton"].type == "command"
        assert nodes_by_id["review_skeleton"].type == "command"
        assert nodes_by_id["fix_skeleton"].type == "command"

    def test_fix_skeleton_retry(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """fix_skeleton has retry configuration."""
        node = nodes_by_id["fix_skeleton"]
        assert node.retry is not None
        assert node.retry.max_attempts >= 2

    def test_skeleton_gate_condition(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """skeleton_gate is a gate node with APPROVED condition."""
        gate = nodes_by_id["skeleton_gate"]
        assert gate.type == "gate"
        assert gate.condition is not None
        assert "APPROVED" in gate.condition or "verdict" in gate.condition


class TestExitHooksAndFailureHandling:
    """Test 5: Exit hooks and failure strategies."""

    def test_exit_hooks_present(self, workflow: WorkflowDef) -> None:
        """Cost capture exit hook exists."""
        assert workflow.config.on_exit is not None
        assert len(workflow.config.on_exit) > 0
        cost_hook = next(
            (h for h in workflow.config.on_exit if h.id == "cost_capture"),
            None
        )
        assert cost_hook is not None
        assert "completed" in cost_hook.run_on
        assert "failed" in cost_hook.run_on

    def test_on_failure_stop_on_reviews(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Review nodes use on_failure: stop."""
        # first_review and subsequent reviews should stop on failure
        node = nodes_by_id["first_review"]
        assert node.on_failure == OnFailure.STOP

    def test_on_failure_continue_on_skeleton_gate(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """skeleton_gate uses on_failure: continue to allow fix_skeleton."""
        gate = nodes_by_id["skeleton_gate"]
        assert gate.on_failure == OnFailure.CONTINUE


class TestIssuesRouterUsage:
    """Test 6: All Jira operations use issues/ router (GW-5045 requirement)."""

    def test_no_direct_jira_refs(self, workflow: WorkflowDef) -> None:
        """groom.yaml should have zero ~/.claude/skills/jira/ references."""
        with open(WORKFLOW_PATH, 'r') as f:
            content = f.read()
        
        # Should NOT have direct jira/ skill references
        assert '/.claude/skills/jira/' not in content, \
            "Found direct jira/ skill reference - must use issues/ router"
        
        # Should have issues/ router references
        assert '/.claude/skills/issues/' in content, \
            "No issues/ router references found - required for Jira ops"
