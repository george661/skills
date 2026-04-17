"""Tests for the implement.yaml workflow definition.

Validates that the YAML-based implement sub-DAG parses correctly, has proper
node ordering, dispatch configuration, gate conditions, and outputs contract
matching what work.yaml consumes downstream.
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
    Path(__file__).parent.parent / "workflows" / "implement.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the implement.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1: YAML parses without errors and has correct structure."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """implement.yaml loads with no validation errors."""
        assert workflow.name == "Implement Command Sub-DAG"
        assert len(workflow.nodes) >= 10  # At least the 10 planned nodes

    def test_input_issue_key_required_with_pattern(
        self, workflow: WorkflowDef
    ) -> None:
        """issue_key input is required and has Jira key pattern."""
        ik = workflow.inputs["issue_key"]
        assert ik.required is True
        assert ik.pattern == r"^[A-Z]+-\d+$"

    def test_config_valid(self, workflow: WorkflowDef) -> None:
        """Workflow config has correct checkpoint prefix and worktree flag."""
        assert workflow.config.checkpoint_prefix == "implement"
        assert workflow.config.worktree is True

    def test_outputs_defined(self, workflow: WorkflowDef) -> None:
        """Workflow outputs reference correct nodes and fields matching work.yaml contract."""
        # Critical: work.yaml uses $implement.repo, $implement.pr_number (no .output.)
        # Outputs use flat field names; the node outputs both channel key and flat keys
        assert workflow.outputs["repo"].node == "push_and_create_pr"
        assert workflow.outputs["repo"].field == "repo"
        assert workflow.outputs["pr_number"].node == "push_and_create_pr"
        assert workflow.outputs["pr_number"].field == "pr_number"
        assert workflow.outputs["branch"].node == "push_and_create_pr"
        assert workflow.outputs["branch"].field == "branch"

    def test_labels_config(self, workflow: WorkflowDef) -> None:
        """Workflow has labels config for failure handling."""
        assert workflow.config.labels is not None
        assert workflow.config.labels.on_failure == "outcome:implement-failed"


class TestTopologicalOrdering:
    """Test 2: Topological sort produces correct phase ordering."""

    def test_phase_ordering(self, workflow: WorkflowDef) -> None:
        """Phases execute in correct order matching /implement command."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        # Verify critical ordering constraints
        def before(a: str, b: str) -> None:
            assert flat_order.index(a) < flat_order.index(b), (
                f"{a} must execute before {b}"
            )

        before("load_plan", "plan_freshness")
        before("plan_freshness", "e2e_red_gate")
        before("plan_freshness", "step_label_implementing")
        before("e2e_red_gate", "tdd_implement")
        before("step_label_implementing", "tdd_implement")
        before("tdd_implement", "run_validation")
        before("run_validation", "file_location_guard")
        before("file_location_guard", "push_and_create_pr")
        before("push_and_create_pr", "step_label_awaiting_ci")


class TestGateNodes:
    """Test 3: Gate nodes use on_failure: continue for E2E checks."""

    def test_e2e_red_gate_continues_on_failure(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """e2e_red_gate uses on_failure: continue so TDD runs even without E2E."""
        gate = nodes_by_id["e2e_red_gate"]
        assert gate.type == "gate"
        assert gate.on_failure == OnFailure.CONTINUE


class TestDispatchConfig:
    """Test 4: tdd_implement uses dispatch: local."""

    def test_tdd_implement_uses_local_dispatch(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """tdd_implement uses dispatch: local (heavy work on local model)."""
        node = nodes_by_id["tdd_implement"]
        assert node.dispatch == DispatchMode.LOCAL, (
            "tdd_implement should use dispatch: local"
        )


class TestVariableSubstitution:
    """Test 5: Variable $issue_key resolves in node scripts/args."""

    def test_issue_key_in_bash_scripts(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Bash nodes reference $issue_key in their scripts."""
        bash_with_issue_key = [
            "load_plan",
            "plan_freshness",
            "step_label_implementing",
            "step_label_awaiting_ci",
        ]
        for nid in bash_with_issue_key:
            node = nodes_by_id[nid]
            assert "$issue_key" in (node.script or ""), (
                f"{nid} script should reference $issue_key"
            )


class TestOutputContract:
    """Test 6: Outputs match expected shape for work.yaml consumption."""

    def test_output_types(self, workflow: WorkflowDef) -> None:
        """Outputs have correct data types."""
        # repo and branch are strings, pr_number is number
        # Outputs use flat field names; the node outputs both channel key and flat keys
        assert workflow.outputs["repo"].field == "repo"
        assert workflow.outputs["pr_number"].field == "pr_number"
        assert workflow.outputs["branch"].field == "branch"

    def test_all_outputs_from_same_node(self, workflow: WorkflowDef) -> None:
        """All outputs come from push_and_create_pr node."""
        assert workflow.outputs["repo"].node == "push_and_create_pr"
        assert workflow.outputs["pr_number"].node == "push_and_create_pr"
        assert workflow.outputs["branch"].node == "push_and_create_pr"


class TestSubDagOutputBubbling:
    """Test 7: Parent DAG can reference $implement.pr_number pattern."""

    def test_output_names_match_work_yaml_usage(
        self, workflow: WorkflowDef
    ) -> None:
        """Output names match what work.yaml references: repo, pr_number, branch."""
        expected_outputs = {"repo", "pr_number", "branch"}
        actual_outputs = set(workflow.outputs.keys())
        assert expected_outputs == actual_outputs, (
            f"Outputs mismatch: expected {expected_outputs}, got {actual_outputs}"
        )


class TestChannelDeclarations:
    """Test 8: State channels are declared with correct types and reducers."""

    def test_state_block_exists(self, workflow: WorkflowDef) -> None:
        """Workflow declares state channels."""
        assert workflow.state is not None, "State block must be declared"
        assert len(workflow.state) > 0, "State block must contain channels"

    def test_channel_types_and_reducers(self, workflow: WorkflowDef) -> None:
        """All channels have correct types and reducer strategies."""
        expected_channels = {
            "plan": ("dict", "overwrite"),
            "plan_status": ("string", "overwrite"),
            "impl_result": ("dict", "overwrite"),
            "validation_result": ("dict", "overwrite"),
            "pr_info": ("dict", "overwrite"),
            "errors": ("list", "append"),
        }

        for channel_name, (expected_type, expected_reducer) in expected_channels.items():
            assert channel_name in workflow.state, (
                f"Channel '{channel_name}' must be declared in state"
            )
            channel = workflow.state[channel_name]
            assert channel.type == expected_type, (
                f"Channel '{channel_name}' type should be {expected_type}, got {channel.type}"
            )
            # Check reducer strategy (can be string or ReducerDef)
            if hasattr(channel.reducer, 'strategy'):
                assert channel.reducer.strategy == expected_reducer, (
                    f"Channel '{channel_name}' reducer should be {expected_reducer}, got {channel.reducer.strategy}"
                )
            else:
                assert channel.reducer == expected_reducer, (
                    f"Channel '{channel_name}' reducer should be {expected_reducer}, got {channel.reducer}"
                )


class TestNodeChannelSubscriptions:
    """Test 9: All nodes declare reads/writes subscriptions."""

    def test_all_nodes_declare_reads_or_writes(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Every node that produces or consumes channel data declares reads/writes."""
        # Nodes that should declare writes
        nodes_with_writes = {
            "load_plan": ["plan"],
            "plan_freshness": ["plan_status"],
            "tdd_implement": ["impl_result"],
            "run_validation": ["validation_result", "errors"],
            "file_location_guard": ["errors"],
            "push_and_create_pr": ["pr_info"],
        }

        for node_id, expected_writes in nodes_with_writes.items():
            node = nodes_by_id[node_id]
            assert node.writes is not None, (
                f"Node '{node_id}' must declare writes"
            )
            for channel in expected_writes:
                assert channel in node.writes, (
                    f"Node '{node_id}' must write to channel '{channel}'"
                )

    def test_node_reads_declarations(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Nodes that consume channel data declare reads."""
        nodes_with_reads = {
            "plan_freshness": ["plan"],
            "tdd_implement": ["plan", "plan_status"],
            "run_validation": ["impl_result"],
            "file_location_guard": ["validation_result"],
            "push_and_create_pr": ["errors"],
            "step_label_awaiting_ci": ["pr_info"],
        }

        for node_id, expected_reads in nodes_with_reads.items():
            node = nodes_by_id[node_id]
            assert node.reads is not None, (
                f"Node '{node_id}' must declare reads"
            )
            for channel in expected_reads:
                assert channel in node.reads, (
                    f"Node '{node_id}' must read from channel '{channel}'"
                )


class TestExitHooks:
    """Test 10: Exit hooks are declared for worktree cleanup."""

    def test_exit_hook_declared(self, workflow: WorkflowDef) -> None:
        """Workflow config declares exit hooks."""
        assert workflow.config.on_exit is not None, (
            "Config must declare on_exit hooks"
        )
        assert len(workflow.config.on_exit) > 0, (
            "At least one exit hook must be declared"
        )

    def test_worktree_cleanup_hook(self, workflow: WorkflowDef) -> None:
        """Worktree cleanup exit hook runs on completed and failed."""
        cleanup_hook = None
        for hook in workflow.config.on_exit:
            if "cleanup" in hook.id.lower() or "worktree" in hook.id.lower():
                cleanup_hook = hook
                break

        assert cleanup_hook is not None, (
            "Exit hook for worktree cleanup must be declared"
        )
        assert cleanup_hook.type == "bash", (
            "Cleanup hook should be bash type"
        )
        assert "completed" in cleanup_hook.run_on, (
            "Cleanup hook must run on completed"
        )
        assert "failed" in cleanup_hook.run_on, (
            "Cleanup hook must run on failed"
        )
