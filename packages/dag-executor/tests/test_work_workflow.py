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
        before("plan_review", "implement")
        before("implement", "code_review")
        before("code_review", "review_verdict")
        before("review_verdict", "rework_gate")
        before("rework_gate", "fix_pr")
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
        assert "$ci_gate.ci_success" in (gate.condition or "")

    def test_bug_test_gate_continues_on_failure(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """bug_test_gate uses on_failure: continue so planning still runs."""
        gate = nodes_by_id["bug_test_gate"]
        assert gate.type == "gate"
        assert gate.on_failure == OnFailure.CONTINUE

    def test_rework_gate_skips_downstream(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """rework_gate skips fix_pr and re_review when review is approved."""
        gate = nodes_by_id["rework_gate"]
        assert gate.type == "gate"
        assert gate.on_failure == OnFailure.SKIP_DOWNSTREAM


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

    def test_implement_outputs_used_downstream(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Downstream nodes reference $implement.repo and $implement.pr_number."""
        code_review = nodes_by_id["code_review"]
        assert "$implement.repo" in (code_review.args or [])
        assert "$implement.pr_number" in (code_review.args or [])


class TestConditionalNodes:
    """Test 7: Conditional when/gate expressions are syntactically valid."""

    def test_gate_conditions_have_variable_refs(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Gate conditions use $node.field variable references."""
        gates = {
            "bug_test_gate": "$prior_work_assessment.issue_type",
            "rework_gate": "$review_verdict.verdict",
            "gate_check": "$ci_gate.ci_success",
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
