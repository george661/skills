"""Tests for the loop-issue.yaml workflow definition.

Validates that the YAML-based loop-issue workflow parses correctly, has proper
state channels, interrupt nodes, and dispatch routing.
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
    ReducerStrategy,
    TriggerRule,
    WorkflowDef,
)


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "loop-issue.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the loop-issue.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1: YAML parses without errors and has correct structure."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """loop-issue.yaml loads with no validation errors."""
        assert workflow.name == "Loop Issue Workflow"
        assert len(workflow.nodes) > 8  # At least core nodes

    def test_checkpoint_prefix(self, workflow: WorkflowDef) -> None:
        """Workflow config has correct checkpoint prefix."""
        assert workflow.config.checkpoint_prefix == "loop-issue"

    def test_issue_key_input_required(
        self, workflow: WorkflowDef
    ) -> None:
        """issue_key input is required."""
        ik = workflow.inputs["issue_key"]
        assert ik.required is True


class TestStateChannels:
    """Test 2: State channels declared with correct types/reducers."""

    def test_current_status_channel(self, workflow: WorkflowDef) -> None:
        """current_status channel is string with overwrite."""
        ch = workflow.state["current_status"]
        assert ch.type == "string"
        assert ch.reducer.strategy == ReducerStrategy.OVERWRITE

    def test_current_labels_channel(self, workflow: WorkflowDef) -> None:
        """current_labels channel is list with overwrite."""
        ch = workflow.state["current_labels"]
        assert ch.type == "list"
        assert ch.reducer.strategy == ReducerStrategy.OVERWRITE

    def test_action_channel(self, workflow: WorkflowDef) -> None:
        """action channel is string with overwrite."""
        ch = workflow.state["action"]
        assert ch.type == "string"
        assert ch.reducer.strategy == ReducerStrategy.OVERWRITE

    def test_pr_info_channel(self, workflow: WorkflowDef) -> None:
        """pr_info channel is dict with overwrite."""
        ch = workflow.state["pr_info"]
        assert ch.type == "dict"
        assert ch.reducer.strategy == ReducerStrategy.OVERWRITE

    def test_ci_status_channel(self, workflow: WorkflowDef) -> None:
        """ci_status channel is string with overwrite."""
        ch = workflow.state["ci_status"]
        assert ch.type == "string"
        assert ch.reducer.strategy == ReducerStrategy.OVERWRITE


class TestNodeChannelUsage:
    """Test 3: Nodes use correct reads/writes on channels."""

    def test_load_context_writes_status_and_labels(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """load_context writes current_status and current_labels."""
        node = nodes_by_id["load_context"]
        assert "current_status" in node.writes
        assert "current_labels" in node.writes

    def test_detect_pr_writes_pr_info(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """detect_pr writes pr_info."""
        node = nodes_by_id["detect_pr"]
        assert "pr_info" in node.writes

    def test_determine_action_writes_action(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """determine_action writes action."""
        node = nodes_by_id["determine_action"]
        assert "action" in node.writes


class TestDetermineActionEdges:
    """Test 4: determine_action has edges to all dispatch nodes."""

    def test_has_edges_to_dispatch_nodes(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """determine_action routes to work, validate, review, fix-pr, resolve-pr."""
        node = nodes_by_id["determine_action"]
        assert node.edges is not None
        edge_targets = [e.target for e in node.edges]
        assert "dispatch_work" in edge_targets
        assert "dispatch_validate" in edge_targets
        assert "dispatch_review" in edge_targets
        assert "dispatch_fix_pr" in edge_targets
        assert "dispatch_resolve_pr" in edge_targets

    def test_has_default_edge(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """determine_action has a default edge for action == 'done'."""
        node = nodes_by_id["determine_action"]
        assert node.edges is not None
        default_edges = [e for e in node.edges if e.default]
        assert len(default_edges) == 1


class TestInterruptNode:
    """Test 5: pipeline_interrupt is an interrupt node with correct config."""

    def test_pipeline_interrupt_exists(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """pipeline_interrupt is an interrupt node."""
        node = nodes_by_id["pipeline_interrupt"]
        assert node.type == "interrupt"

    def test_interrupt_has_resume_key(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """pipeline_interrupt has resume_key: pipeline_resume."""
        node = nodes_by_id["pipeline_interrupt"]
        assert node.resume_key == "pipeline_resume"

    def test_interrupt_channels(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """pipeline_interrupt has terminal channel."""
        node = nodes_by_id["pipeline_interrupt"]
        assert node.channels == ["terminal"]


class TestDispatchNodes:
    """Test 6: dispatch_work has correct dispatch config."""

    def test_dispatch_work_local(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """dispatch_work uses dispatch: local."""
        node = nodes_by_id["dispatch_work"]
        assert node.dispatch == DispatchMode.LOCAL

    def test_dispatch_work_command(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """dispatch_work uses command: work."""
        node = nodes_by_id["dispatch_work"]
        assert node.command == "work"


class TestCIWaitGate:
    """Test 7: ci_wait_gate uses on_failure: continue."""

    def test_ci_wait_gate_on_failure_continue(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """ci_wait_gate uses on_failure: continue to allow interrupt path."""
        node = nodes_by_id["ci_wait_gate"]
        assert node.on_failure == OnFailure.CONTINUE


class TestStoreEpisode:
    """Test 8: store_episode uses trigger_rule: all_done."""

    def test_store_episode_trigger_rule(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """store_episode uses trigger_rule: all_done."""
        node = nodes_by_id["store_episode"]
        assert node.trigger_rule == TriggerRule.ALL_DONE


class TestTopologicalOrdering:
    """Test 9: Topological sort produces correct phase ordering."""

    def test_phase_ordering(self, workflow: WorkflowDef) -> None:
        """Phases execute in correct order."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        def before(a: str, b: str) -> None:
            assert flat_order.index(a) < flat_order.index(b), (
                f"{a} must execute before {b}"
            )

        # Basic ordering
        before("load_context", "determine_action")
        before("detect_pr", "determine_action")
        before("determine_action", "dispatch_work")


class TestVariableSubstitution:
    """Test 10: Variable substitution in node scripts."""

    def test_issue_key_variable_present(self, workflow: WorkflowDef) -> None:
        """$issue_key appears in node scripts."""
        # Check load_context script for issue_key variable
        load_context = next(n for n in workflow.nodes if n.id == "load_context")
        assert "$issue_key" in load_context.script

    def test_no_braced_variable_syntax(self, workflow: WorkflowDef) -> None:
        """No node uses ${var} syntax — executor only resolves bare $var.

        The variable resolver regex in variables.py matches \\$name but not
        \\${name}, so ${var} references survive to simpleeval (SyntaxError on
        conditions) or the LLM (literal pass-through in prompts) or bash
        (empty string for unexported names). Catch this class of bug at
        parse time.
        """
        for node in workflow.nodes:
            for field_name in ("script", "prompt", "condition"):
                value = getattr(node, field_name, None)
                if value is None:
                    continue
                assert "${" not in value, (
                    f"Node {node.id!r} field {field_name!r} uses ${{var}} "
                    f"syntax, which the executor does not resolve. Use bare "
                    f"$var instead. Snippet: {value[:120]!r}"
                )
            if node.edges:
                for edge in node.edges:
                    if edge.condition:
                        assert "${" not in edge.condition, (
                            f"Edge from {node.id!r} uses ${{var}} in "
                            f"condition: {edge.condition!r}"
                        )
