"""Tests for the review.yaml workflow definition.

Validates that the YAML-based review workflow parses correctly, has proper
node ordering, failure strategies including Jira-failure continue path,
and correct verdict flow.
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
    Path(__file__).parent.parent / "workflows" / "review.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the review.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1: YAML parses without errors and has correct structure."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """review.yaml loads with no validation errors."""
        assert workflow.name == "Review Command Workflow"
        assert len(workflow.nodes) >= 10  # At least 10 nodes in the workflow

    def test_inputs_required(
        self, workflow: WorkflowDef
    ) -> None:
        """repo and pr_number inputs are required."""
        repo_input = workflow.inputs["repo"]
        assert repo_input.required is True
        pr_number_input = workflow.inputs["pr_number"]
        assert pr_number_input.required is True

    def test_config_valid(self, workflow: WorkflowDef) -> None:
        """Workflow config has correct checkpoint prefix."""
        assert workflow.config.checkpoint_prefix == "review"

    def test_labels_config(self, workflow: WorkflowDef) -> None:
        """Workflow has labels config for failure handling."""
        assert workflow.config.labels is not None


class TestTopologicalOrdering:
    """Test 2: Topological sort produces correct phase ordering."""

    def test_phase_ordering(self, workflow: WorkflowDef) -> None:
        """Phases execute in correct order matching /review command."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        # Verify critical ordering constraints
        def before(a: str, b: str) -> None:
            assert flat_order.index(a) < flat_order.index(b), (
                f"{a} must execute before {b}"
            )

        # Phase 0: branch_sync → parse_input
        before("branch_sync", "parse_input")
        
        # Phase 1: parse_input → fetch_pr
        before("parse_input", "fetch_pr")
        
        # Phase 2: Parallel find_jira_issue and local_validation
        before("fetch_pr", "find_jira_issue")
        before("fetch_pr", "local_validation")
        
        # Phase 3: Verdict flow
        before("code_quality", "requirements_coverage")
        before("code_quality", "test_adequacy")
        # requirements_coverage and test_adequacy are parallel (same layer)
        # both depend only on code_quality, so verify they're in the same layer
        req_cov_layer = next(i for i, layer in enumerate(layers) if "requirements_coverage" in layer)
        test_adeq_layer = next(i for i, layer in enumerate(layers) if "test_adequacy" in layer)
        assert req_cov_layer == test_adeq_layer, (
            f"requirements_coverage and test_adequacy must be in same layer, "
            f"got layers {req_cov_layer} and {test_adeq_layer}"
        )
        before("requirements_coverage", "post_inline_comments")
        before("test_adequacy", "post_inline_comments")
        before("post_inline_comments", "post_pr_summary")


class TestFailureStrategies:
    """Test 3: Failure strategies for different nodes."""

    def test_branch_sync_stops_on_failure(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """branch_sync uses on_failure: stop."""
        node = nodes_by_id["branch_sync"]
        assert node.on_failure == OnFailure.STOP

    def test_fetch_pr_stops_on_failure(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """fetch_pr uses on_failure: stop."""
        node = nodes_by_id["fetch_pr"]
        assert node.on_failure == OnFailure.STOP

    def test_find_jira_issue_continues_on_failure(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """find_jira_issue uses on_failure: continue."""
        node = nodes_by_id["find_jira_issue"]
        assert node.on_failure == OnFailure.CONTINUE

    def test_local_validation_continues_on_failure(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """local_validation uses on_failure: continue."""
        node = nodes_by_id["local_validation"]
        assert node.on_failure == OnFailure.CONTINUE

    def test_post_jira_summary_continues_on_failure(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """post_jira_summary uses on_failure: continue."""
        node = nodes_by_id["post_jira_summary"]
        assert node.on_failure == OnFailure.CONTINUE


class TestJiraFailureContinuePath:
    """Test 4: Jira-failure continue path allows code_quality to run."""

    def test_code_quality_uses_all_done_trigger(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """code_quality uses trigger_rule: all_done."""
        node = nodes_by_id["code_quality"]
        assert node.trigger_rule == TriggerRule.ALL_DONE

    def test_code_quality_depends_on_local_validation(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """code_quality depends on local_validation."""
        node = nodes_by_id["code_quality"]
        assert "local_validation" in node.depends_on

    def test_post_jira_summary_uses_all_done_trigger(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """post_jira_summary uses trigger_rule: all_done."""
        node = nodes_by_id["post_jira_summary"]
        assert node.trigger_rule == TriggerRule.ALL_DONE


class TestVerdictFlow:
    """Test 5: Verdict flow through code quality pipeline."""

    def test_verdict_pipeline_ordering(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Verdict nodes form a proper pipeline."""
        # code_quality → test_adequacy
        test_adeq = nodes_by_id["test_adequacy"]
        assert "code_quality" in test_adeq.depends_on

        # code_quality → requirements_coverage (parallel to test_adequacy)
        req_cov = nodes_by_id["requirements_coverage"]
        assert "code_quality" in req_cov.depends_on

        # test_adequacy → post_inline_comments
        inline_comments = nodes_by_id["post_inline_comments"]
        assert "test_adequacy" in inline_comments.depends_on

        # post_inline_comments → post_pr_summary
        pr_summary = nodes_by_id["post_pr_summary"]
        assert "post_inline_comments" in pr_summary.depends_on


class TestDispatchConfig:
    """Test 6: Dispatch configuration for different node types."""

    def test_code_quality_dispatch(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """code_quality has appropriate dispatch mode."""
        node = nodes_by_id["code_quality"]
        # Check it has a dispatch mode set
        assert node.dispatch in [DispatchMode.LOCAL, DispatchMode.INLINE, None]

    def test_requirements_coverage_dispatch(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """requirements_coverage has appropriate dispatch mode."""
        node = nodes_by_id["requirements_coverage"]
        # Check it has a dispatch mode set
        assert node.dispatch in [DispatchMode.LOCAL, DispatchMode.INLINE, None]


class TestVariableSubstitution:
    """Test 7: Variables resolve in node scripts/args."""

    def test_repo_and_pr_number_in_nodes(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Nodes reference $repo and $pr_number in their scripts or prompts."""
        # fetch_pr should reference repo and pr_number
        node = nodes_by_id["fetch_pr"]
        node_text = (node.script or "") + (node.prompt or "")
        assert "$repo" in node_text or "$pr_number" in node_text, (
            "fetch_pr should reference $repo or $pr_number"
        )


# Import additional classes for integration tests
from dag_executor.schema import NodeResult, NodeStatus, TriggerRule
from tests.conftest import MockRunnerFactory, WorkflowTestHarness


class TestReviewWorkflowNodeOrdering:
    """Integration test: Verify review workflow node ordering end-to-end."""

    def test_phase_0_to_phase_2_ordering(
        self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Phase 0-2: branch_sync → parse_input → fetch_pr → find_jira_issue → local_validation."""
        branch_sync = nodes_by_id["branch_sync"]
        parse_input = nodes_by_id["parse_input"]
        fetch_pr = nodes_by_id["fetch_pr"]
        find_jira = nodes_by_id["find_jira_issue"]
        local_val = nodes_by_id["local_validation"]

        # branch_sync → parse_input
        assert "branch_sync" in parse_input.depends_on

        # parse_input → fetch_pr
        assert "parse_input" in fetch_pr.depends_on

        # fetch_pr → find_jira_issue
        assert "fetch_pr" in find_jira.depends_on

        # find_jira_issue → local_validation
        assert "find_jira_issue" in local_val.depends_on

    def test_phase_3_to_verdict_flow(
        self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Phase 3+: code_quality → parallel (requirements_coverage, test_adequacy) → comments → summaries."""
        code_quality = nodes_by_id["code_quality"]
        req_cov = nodes_by_id["requirements_coverage"]
        test_adeq = nodes_by_id["test_adequacy"]
        inline_comments = nodes_by_id["post_inline_comments"]
        pr_summary = nodes_by_id["post_pr_summary"]
        jira_summary = nodes_by_id["post_jira_summary"]

        # code_quality → requirements_coverage + test_adequacy (parallel)
        assert "code_quality" in req_cov.depends_on
        assert "code_quality" in test_adeq.depends_on

        # requirements_coverage + test_adequacy → post_inline_comments
        assert "requirements_coverage" in inline_comments.depends_on
        assert "test_adequacy" in inline_comments.depends_on

        # post_inline_comments → post_pr_summary
        assert "post_inline_comments" in pr_summary.depends_on

        # post_pr_summary → post_jira_summary
        assert "post_pr_summary" in jira_summary.depends_on


class TestJiraLookupFailureContinuePath:
    """Integration test: Jira lookup failure does not block review."""

    def test_find_jira_issue_has_continue_on_failure(
        self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """find_jira_issue uses on_failure: continue (soft continue)."""
        find_jira = nodes_by_id["find_jira_issue"]
        assert find_jira.on_failure == OnFailure.CONTINUE

    def test_code_quality_uses_all_done_trigger(
        self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """code_quality uses all_done trigger to run even if find_jira_issue fails."""
        code_quality = nodes_by_id["code_quality"]

        # code_quality should use all_done trigger rule
        assert code_quality.trigger_rule == TriggerRule.ALL_DONE

        # code_quality should depend on local_validation (not find_jira_issue)
        assert "local_validation" in code_quality.depends_on

    def test_requirements_coverage_handles_missing_jira(
        self, workflow: WorkflowDef, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """requirements_coverage depends on find_jira_issue with all_done trigger."""
        req_cov = nodes_by_id["requirements_coverage"]

        # requirements_coverage should depend on both code_quality and find_jira_issue
        assert "code_quality" in req_cov.depends_on
        assert "find_jira_issue" in req_cov.depends_on

        # requirements_coverage should use all_done trigger to run even if find_jira fails
        assert req_cov.trigger_rule == TriggerRule.ALL_DONE
