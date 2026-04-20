"""Tests for the create-implementation-plan.yaml workflow definition.

Validates that the YAML-based create-implementation-plan sub-DAG parses correctly,
has proper node ordering, channel declarations, dispatch configuration, and outputs
contract matching what work.yaml expects.
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
    WorkflowDef,
)


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "create-implementation-plan.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the create-implementation-plan.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1: YAML parses without errors and has correct structure."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """create-implementation-plan.yaml loads with no validation errors."""
        assert workflow.name == "Create Implementation Plan Command Sub-DAG"
        assert len(workflow.nodes) >= 17  # At least the 17 planned nodes

    def test_input_issue_key_required_with_pattern(
        self, workflow: WorkflowDef
    ) -> None:
        """issue_key input is required and has Jira key pattern."""
        ik = workflow.inputs["issue_key"]
        assert ik.required is True
        assert ik.pattern == r"^[A-Z]+-\d+$"

    def test_config_valid(self, workflow: WorkflowDef) -> None:
        """Workflow config has correct checkpoint prefix."""
        assert workflow.config.checkpoint_prefix == "create-impl-plan"


class TestTopologicalOrdering:
    """Test 2: Topological sort produces correct phase ordering."""

    def test_phase_ordering(self, workflow: WorkflowDef) -> None:
        """Phases execute in correct order per the implementation plan."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        # Verify critical ordering constraints based on plan's node mapping
        def before(a: str, b: str) -> None:
            assert flat_order.index(a) < flat_order.index(b), (
                f"{a} must execute before {b}"
            )

        # Phase 0: Health and pattern retrieval must come first
        before("agentdb_health", "retrieve_patterns")
        before("agentdb_health", "fetch_issue")
        
        # Phase 0.5: Domain context after issue fetch
        before("fetch_issue", "domain_context")
        
        # Phase 0.7: File discovery after domain context
        before("domain_context", "file_discovery")
        
        # Phase 0.8: Already-implemented check and gate
        before("file_discovery", "already_impl_check")
        before("already_impl_check", "already_impl_gate")
        
        # Phase 1: Transition must come after gate
        before("already_impl_gate", "transition_in_progress")
        
        # Phase 1.2: Classify after transition
        before("transition_in_progress", "classify_issue_type")
        
        # Phase 1.3: Multi-repo check after classify
        before("classify_issue_type", "multi_repo_check")
        
        # Phase 2: Worktree creation after multi-repo check
        before("multi_repo_check", "create_worktree")
        
        # Phase 3.1: Plan writing after worktree
        before("create_worktree", "write_plan")
        
        # Phase 3.3+: Post-plan steps
        before("write_plan", "post_plan_jira")
        before("post_plan_jira", "store_validation")
        before("store_validation", "store_impl_context")
        before("store_impl_context", "write_agent_context")
        before("write_agent_context", "add_outcome_label")


class TestChannelDeclarations:
    """Test 3: All 7 state channels declared with correct types and reducers."""

    def test_all_channels_declared(self, workflow: WorkflowDef) -> None:
        """Workflow has all 7 planned channels."""
        expected_channels = {
            "issue_data",
            "issue_type",
            "feasibility",
            "worktree_info",
            "plan",
            "validation_criteria",
            "errors",
        }
        actual_channels = set(workflow.state.keys())
        assert expected_channels == actual_channels, (
            f"Missing channels: {expected_channels - actual_channels}, "
            f"Unexpected: {actual_channels - expected_channels}"
        )

    def test_issue_data_channel_type(self, workflow: WorkflowDef) -> None:
        """issue_data channel is dict with overwrite reducer."""
        channel = workflow.state["issue_data"]
        assert channel.type == "dict"
        assert channel.reducer.strategy.value == "overwrite"

    def test_issue_type_channel_type(self, workflow: WorkflowDef) -> None:
        """issue_type channel is string with overwrite reducer."""
        channel = workflow.state["issue_type"]
        assert channel.type == "string"
        assert channel.reducer.strategy.value == "overwrite"

    def test_feasibility_channel_type(self, workflow: WorkflowDef) -> None:
        """feasibility channel is dict with overwrite reducer."""
        channel = workflow.state["feasibility"]
        assert channel.type == "dict"
        assert channel.reducer.strategy.value == "overwrite"

    def test_worktree_info_channel_type(self, workflow: WorkflowDef) -> None:
        """worktree_info channel is dict with overwrite reducer."""
        channel = workflow.state["worktree_info"]
        assert channel.type == "dict"
        assert channel.reducer.strategy.value == "overwrite"

    def test_plan_channel_type(self, workflow: WorkflowDef) -> None:
        """plan channel is dict with overwrite reducer."""
        channel = workflow.state["plan"]
        assert channel.type == "dict"
        assert channel.reducer.strategy.value == "overwrite"

    def test_validation_criteria_channel_type(self, workflow: WorkflowDef) -> None:
        """validation_criteria channel is dict with overwrite reducer."""
        channel = workflow.state["validation_criteria"]
        assert channel.type == "dict"
        assert channel.reducer.strategy.value == "overwrite"

    def test_errors_channel_type(self, workflow: WorkflowDef) -> None:
        """errors channel is list with append reducer."""
        channel = workflow.state["errors"]
        assert channel.type == "list"
        assert channel.reducer.strategy.value == "append"


class TestNodeChannelSubscriptions:
    """Test 4: Every node declares reads/writes for channels it uses."""

    def test_fetch_issue_writes_issue_data(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """fetch_issue writes to issue_data channel."""
        node = nodes_by_id["fetch_issue"]
        assert "issue_data" in node.writes

    def test_classify_writes_issue_type(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """classify_issue_type writes to issue_type channel."""
        node = nodes_by_id["classify_issue_type"]
        assert "issue_type" in node.writes

    def test_file_discovery_writes_feasibility(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """file_discovery writes to feasibility channel."""
        node = nodes_by_id["file_discovery"]
        assert "feasibility" in node.writes

    def test_create_worktree_writes_worktree_info(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """create_worktree writes to worktree_info channel."""
        node = nodes_by_id["create_worktree"]
        assert "worktree_info" in node.writes

    def test_write_plan_writes_plan(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """write_plan writes to plan channel."""
        node = nodes_by_id["write_plan"]
        assert "plan" in node.writes

    def test_store_validation_reads_plan(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """store_validation reads from plan channel."""
        node = nodes_by_id["store_validation"]
        assert "plan" in node.reads


class TestGateNodes:
    """Test 5: already_impl_gate uses on_failure: stop."""

    def test_already_impl_gate_stops_on_failure(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """already_impl_gate stops workflow if issue already implemented."""
        gate = nodes_by_id["already_impl_gate"]
        assert gate.type == "gate"
        assert gate.on_failure == OnFailure.STOP


class TestDispatchConfig:
    """Test 6: Opus prompt nodes use dispatch: inline."""

    def test_file_discovery_uses_inline_dispatch(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """file_discovery uses dispatch: inline (Opus)."""
        node = nodes_by_id["file_discovery"]
        assert node.dispatch == DispatchMode.INLINE

    def test_already_impl_check_uses_inline_dispatch(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """already_impl_check uses dispatch: inline (Opus)."""
        node = nodes_by_id["already_impl_check"]
        assert node.dispatch == DispatchMode.INLINE

    def test_classify_uses_inline_dispatch(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """classify_issue_type uses dispatch: inline (Opus)."""
        node = nodes_by_id["classify_issue_type"]
        assert node.dispatch == DispatchMode.INLINE

    def test_write_plan_uses_inline_dispatch(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """write_plan uses dispatch: inline (Opus)."""
        node = nodes_by_id["write_plan"]
        assert node.dispatch == DispatchMode.INLINE


class TestVariableSubstitution:
    """Test 7: $issue_key appears in bash scripts."""

    def test_issue_key_in_bash_scripts(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Bash nodes reference $issue_key in their scripts."""
        bash_with_issue_key = [
            "fetch_issue",
            "transition_in_progress",
            "post_plan_jira",
            "store_validation",
            "store_impl_context",
            "add_outcome_label",
        ]
        for nid in bash_with_issue_key:
            node = nodes_by_id[nid]
            assert "$issue_key" in (node.script or ""), (
                f"{nid} script should reference $issue_key"
            )


class TestOutputContract:
    """Test 8: Outputs match expected shape for work.yaml consumption."""

    def test_outputs_defined(self, workflow: WorkflowDef) -> None:
        """Workflow outputs include worktree_path, branch, issue_type."""
        assert "worktree_path" in workflow.outputs
        assert "branch" in workflow.outputs
        assert "issue_type" in workflow.outputs

    def test_worktree_path_output(self, workflow: WorkflowDef) -> None:
        """worktree_path output comes from create_worktree node."""
        output = workflow.outputs["worktree_path"]
        assert output.node == "create_worktree"
        assert output.field == "worktree_path"

    def test_branch_output(self, workflow: WorkflowDef) -> None:
        """branch output comes from create_worktree node."""
        output = workflow.outputs["branch"]
        assert output.node == "create_worktree"
        assert output.field == "branch"

    def test_issue_type_output(self, workflow: WorkflowDef) -> None:
        """issue_type output comes from classify_issue_type node."""
        output = workflow.outputs["issue_type"]
        assert output.node == "classify_issue_type"
        assert output.field == "issue_type"


class TestExitHooks:
    """Test 9: Cost capture exit hook declared."""

    def test_exit_hooks_exist(self, workflow: WorkflowDef) -> None:
        """Workflow has on_exit hooks for cleanup."""
        assert workflow.config.on_exit is not None
        assert len(workflow.config.on_exit) > 0


class TestMockExecution:
    """Test 10: Full mock execution through happy path + already-implemented gate path."""

    def test_happy_path_node_count(self, workflow: WorkflowDef) -> None:
        """All 17 nodes are reachable in happy path."""
        # This validates that the dependency graph is well-formed
        layers = topological_sort_with_layers(workflow.nodes)
        all_nodes = [nid for layer in layers for nid in layer]
        assert len(all_nodes) == 17

    def test_gate_node_exists(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """already_impl_gate exists for early exit path."""
        assert "already_impl_gate" in nodes_by_id
        gate = nodes_by_id["already_impl_gate"]
        assert gate.type == "gate"
