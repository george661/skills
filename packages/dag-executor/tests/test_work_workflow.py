"""Tests for the work.yaml workflow definition.

Validates that the YAML-based /work workflow parses correctly, has proper
node ordering, dispatch configuration, gate conditions, and variable
references matching the original /work markdown command behavior.
"""
from pathlib import Path
from typing import Dict, Set

import pytest

from dag_executor.graph import topological_sort_with_layers
from dag_executor.parser import load_workflow
from dag_executor.schema import (
    DispatchMode,
    NodeDef,
    OnFailure,
    ReducerStrategy,
    WorkflowDef,
)


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "work.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the work.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1: YAML parses without errors via load_workflow()."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """work.yaml loads with no validation errors."""
        assert workflow.name == "Work Command Workflow"
        assert len(workflow.nodes) == 21

    def test_input_issue_key_required_with_pattern(
        self, workflow: WorkflowDef
    ) -> None:
        """issue_key input is required and has Jira key pattern."""
        ik = workflow.inputs["issue_key"]
        assert ik.required is True
        assert ik.pattern == r"^[A-Z]+-\d+$"

    def test_config_valid(self, workflow: WorkflowDef) -> None:
        """Workflow config has correct checkpoint prefix and worktree flag."""
        assert workflow.config.checkpoint_prefix == "work"
        assert workflow.config.worktree is True

    def test_outputs_defined(self, workflow: WorkflowDef) -> None:
        """Workflow outputs reference correct nodes and fields."""
        assert workflow.outputs["repo"].node == "implement"
        assert workflow.outputs["repo"].field == "repo"
        assert workflow.outputs["pr_number"].node == "implement"
        assert workflow.outputs["pr_number"].field == "pr_number"
        assert workflow.outputs["merge_status"].node == "merge"
        assert workflow.outputs["merge_status"].field == "status"


class TestTopologicalOrdering:
    """Test 2: Topological sort produces correct phase ordering."""

    def test_phase_ordering(self, workflow: WorkflowDef) -> None:
        """Phases execute in correct order matching /work command."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        # Verify critical ordering constraints
        def before(a: str, b: str) -> None:
            assert flat_order.index(a) < flat_order.index(b), (
                f"{a} must execute before {b}"
            )

        before("resume_check", "git_sync")
        before("git_sync", "repo_context")
        before("repo_context", "prior_work_assessment")
        before("prior_work_assessment", "bug_test_gate")
        before("bug_test_gate", "bug_test_verify")
        before("planning", "plan_review")
        before("plan_review", "plan_approval")
        before("plan_approval", "implement")
        before("implement", "code_review")
        before("code_review", "review_verdict")
        before("review_verdict", "fix_pr")
        before("fix_pr", "re_review")
        before("gate_check", "merge")
        before("merge", "verify_jira")
        before("merge", "verify_pr")
        before("summary", "cleanup")


class TestGateNodes:
    """Test 3: Gate nodes block on failure condition."""

    def test_ci_success_gate_stops_on_failure(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """gate_check with on_failure: stop blocks merge when CI fails."""
        gate = nodes_by_id["gate_check"]
        assert gate.type == "gate"
        assert gate.on_failure == OnFailure.STOP
        assert "$ci_success" in (gate.condition or "")

    def test_bug_test_gate_continues_on_failure(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """bug_test_gate uses on_failure: continue so planning still runs."""
        gate = nodes_by_id["bug_test_gate"]
        assert gate.type == "gate"
        assert gate.on_failure == OnFailure.CONTINUE


class TestDispatchConfig:
    """Test 4 & 5: Command nodes have correct dispatch modes."""

    INLINE_COMMANDS: Set[str] = {
        "planning",
        "plan_review",
        "code_review",
        "re_review",
        "merge",
    }
    LOCAL_COMMANDS: Set[str] = {"implement", "fix_pr"}

    def test_inline_dispatch_commands(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Inline commands match dispatch-routing config."""
        for nid in self.INLINE_COMMANDS:
            node = nodes_by_id[nid]
            assert node.dispatch == DispatchMode.INLINE, (
                f"{nid} should be dispatch: inline"
            )

    def test_local_dispatch_commands(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Dispatched commands use dispatch: local."""
        for nid in self.LOCAL_COMMANDS:
            node = nodes_by_id[nid]
            assert node.dispatch == DispatchMode.LOCAL, (
                f"{nid} should be dispatch: local"
            )


class TestVariableSubstitution:
    """Test 6: Variable $issue_key resolves in node scripts/args."""

    def test_issue_key_in_bash_scripts(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Bash nodes reference $issue_key in their scripts."""
        bash_with_issue_key = [
            "resume_check", "review_verdict", "verify_jira",
        ]
        for nid in bash_with_issue_key:
            node = nodes_by_id[nid]
            assert "$issue_key" in (node.script or ""), (
                f"{nid} script should reference $issue_key"
            )

    def test_issue_key_in_command_args(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Command nodes pass $issue_key as argument."""
        cmd_with_issue_key = [
            "planning", "plan_review", "implement",
            "fix_pr", "merge",
        ]
        for nid in cmd_with_issue_key:
            node = nodes_by_id[nid]
            assert "$issue_key" in (node.args or []), (
                f"{nid} args should include $issue_key"
            )

    def test_code_review_uses_channels(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """code_review references $repo and $pr_number from channels."""
        code_review = nodes_by_id["code_review"]
        assert "$repo" in (code_review.args or [])
        assert "$pr_number" in (code_review.args or [])


class TestConditionalNodes:
    """Test 7: Conditional when/gate expressions are syntactically valid."""

    def test_gate_conditions_have_variable_refs(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Gate conditions use channel variable references."""
        gates = {
            "bug_test_gate": "$issue_type",
            "gate_check": "$ci_success",
        }
        for nid, expected_var in gates.items():
            node = nodes_by_id[nid]
            assert expected_var in (node.condition or ""), (
                f"{nid} condition should reference {expected_var}"
            )

    def test_review_verdict_is_bash(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """review_verdict reads from Jira (bash), not from node output (gate)."""
        rv = nodes_by_id["review_verdict"]
        assert rv.type == "bash"


class TestParallelExecution:
    """Test 8: verify_jira and verify_pr are in the same topological layer."""

    def test_verify_nodes_parallel(self, workflow: WorkflowDef) -> None:
        """verify_jira and verify_pr execute in parallel."""
        layers = topological_sort_with_layers(workflow.nodes)
        for layer in layers:
            if "verify_jira" in layer:
                assert "verify_pr" in layer, (
                    "verify_jira and verify_pr must be in the same layer"
                )
                return
        pytest.fail("verify_jira not found in any layer")


class TestStateChannels:
    """Test 9: State channels are declared with correct types and reducers."""

    def test_state_channels_declared(self, workflow: WorkflowDef) -> None:
        """State block declares all 7 required channels."""
        assert workflow.state is not None, "state block must be declared"
        required_channels = {
            "issue_type", "repo", "pr_number", "verdict",
            "ci_success", "branch", "plan_approved"
        }
        declared_channels = set(workflow.state.keys())
        assert required_channels.issubset(declared_channels), (
            f"Missing channels: {required_channels - declared_channels}"
        )

    def test_channel_types(self, workflow: WorkflowDef) -> None:
        """Channels have correct types."""
        assert workflow.state["issue_type"].type == "string"
        assert workflow.state["repo"].type == "string"
        assert workflow.state["pr_number"].type == "integer"
        assert workflow.state["verdict"].type == "string"
        assert workflow.state["ci_success"].type == "boolean"
        assert workflow.state["branch"].type == "string"
        assert workflow.state["plan_approved"].type == "boolean"

    def test_all_reducers_overwrite(self, workflow: WorkflowDef) -> None:
        """All channels use overwrite reducer."""
        for channel_name, channel_def in workflow.state.items():
            assert channel_def.reducer.strategy == ReducerStrategy.OVERWRITE, (
                f"{channel_name} should use overwrite reducer"
            )


class TestReadsWrites:
    """Test 10: Nodes declare reads/writes for channel data."""

    def test_prior_work_assessment_writes_issue_type(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """prior_work_assessment writes to issue_type channel."""
        node = nodes_by_id["prior_work_assessment"]
        assert "issue_type" in (node.writes or [])

    def test_implement_writes_channels(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """implement writes to repo, pr_number, and branch channels."""
        node = nodes_by_id["implement"]
        assert "repo" in (node.writes or [])
        assert "pr_number" in (node.writes or [])
        assert "branch" in (node.writes or [])

    def test_review_verdict_writes_verdict(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """review_verdict writes to verdict channel."""
        node = nodes_by_id["review_verdict"]
        assert "verdict" in (node.writes or [])

    def test_ci_gate_reads_writes(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """ci_gate reads repo and writes ci_success."""
        node = nodes_by_id["ci_gate"]
        assert "repo" in (node.reads or [])
        assert "ci_success" in (node.writes or [])

    def test_gate_check_reads_ci_success(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """gate_check reads ci_success channel."""
        node = nodes_by_id["gate_check"]
        assert "ci_success" in (node.reads or [])


class TestExitHooks:
    """Test 11: Exit hooks for worktree cleanup and cost capture."""

    def test_exit_hooks_declared(self, workflow: WorkflowDef) -> None:
        """Config has two exit hooks."""
        assert workflow.config.on_exit is not None
        assert len(workflow.config.on_exit) == 2

    def test_worktree_cleanup_hook(self, workflow: WorkflowDef) -> None:
        """worktree_cleanup hook exists and runs on completed/failed."""
        hooks = {h.id: h for h in workflow.config.on_exit}
        assert "worktree_cleanup" in hooks
        hook = hooks["worktree_cleanup"]
        assert hook.type == "bash"
        assert set(hook.run_on) == {"completed", "failed"}

    def test_cost_capture_hook(self, workflow: WorkflowDef) -> None:
        """cost_capture hook exists and runs on completed/failed."""
        hooks = {h.id: h for h in workflow.config.on_exit}
        assert "cost_capture" in hooks
        hook = hooks["cost_capture"]
        assert hook.type == "bash"
        assert "capture_session_cost.py" in hook.script
        assert set(hook.run_on) == {"completed", "failed"}


class TestConditionalEdges:
    """Test 12: Conditional edges replace rework_gate."""

    def test_rework_gate_removed(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """rework_gate node no longer exists."""
        assert "rework_gate" not in nodes_by_id

    def test_review_verdict_has_edges(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """review_verdict has 2 edges: conditional to fix_pr, default to ci_gate."""
        node = nodes_by_id["review_verdict"]
        assert node.edges is not None
        assert len(node.edges) == 2

    def test_review_verdict_conditional_edge(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """First edge routes REQUIRES_REWORK to fix_pr."""
        node = nodes_by_id["review_verdict"]
        edge1 = node.edges[0]
        assert edge1.target == "fix_pr"
        assert "$verdict == 'REQUIRES_REWORK'" in (edge1.condition or "")

    def test_review_verdict_default_edge(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Second edge is default route to ci_gate."""
        node = nodes_by_id["review_verdict"]
        edge2 = node.edges[1]
        assert edge2.target == "ci_gate"
        assert edge2.default is True

    def test_fix_pr_depends_on_review_verdict(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """fix_pr depends directly on review_verdict (no gate in between)."""
        node = nodes_by_id["fix_pr"]
        assert "review_verdict" in node.depends_on


class TestInterruptNode:
    """Test 13: Interrupt node pauses before implementation."""

    def test_plan_approval_exists(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """plan_approval interrupt node exists."""
        assert "plan_approval" in nodes_by_id

    def test_plan_approval_is_interrupt(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """plan_approval is an interrupt node."""
        node = nodes_by_id["plan_approval"]
        assert node.type == "interrupt"

    def test_plan_approval_no_condition(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """plan_approval has no condition (always interrupts)."""
        node = nodes_by_id["plan_approval"]
        assert node.condition is None

    def test_plan_approval_between_review_and_implement(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """plan_approval depends on plan_review, implement depends on plan_approval."""
        approval = nodes_by_id["plan_approval"]
        implement = nodes_by_id["implement"]
        assert "plan_review" in approval.depends_on
        assert "plan_approval" in implement.depends_on

    def test_plan_approval_writes_channel(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """plan_approval writes to plan_approved channel."""
        node = nodes_by_id["plan_approval"]
        assert "plan_approved" in (node.writes or [])


class TestRetryWithChannels:
    """Test 14: Verify retry config coexists with reads/writes."""

    def test_fix_pr_retry_with_channels(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """fix_pr has retry.max_attempts == 3 AND reads/writes declarations."""
        node = nodes_by_id["fix_pr"]
        assert node.retry is not None
        assert node.retry.max_attempts == 3
        assert "repo" in (node.reads or [])
        assert "pr_number" in (node.reads or [])
