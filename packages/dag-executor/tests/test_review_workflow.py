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
    ChannelFieldDef,
    DispatchMode,
    NodeDef,
    OnFailure,
    ReducerStrategy,
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
    """Test 5: Verdict flow through conditional edges."""

    def test_code_quality_has_conditional_edges(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """code_quality has conditional edges for verdict routing."""
        cq = nodes_by_id["code_quality"]
        assert cq.edges is not None
        assert len(cq.edges) == 3

    def test_approved_edge_routes_to_pass_through(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """APPROVED verdict routes to pass-through node."""
        cq = nodes_by_id["code_quality"]
        assert cq.edges is not None
        approved = cq.edges[0]
        assert approved.condition == 'code_quality.verdict == "APPROVED"'
        assert approved.target == "verdict_approved_pass"

    def test_rework_edge_fans_out_to_analysis(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """REQUIRES_REWORK verdict fans out to analysis nodes."""
        cq = nodes_by_id["code_quality"]
        assert cq.edges is not None
        rework = cq.edges[1]
        assert rework.condition == 'code_quality.verdict == "REQUIRES_REWORK"'
        assert set(rework.targets or []) == {
            "requirements_coverage", "test_adequacy",
        }

    def test_exactly_one_default_edge(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Exactly one edge has default=True (escalate path)."""
        cq = nodes_by_id["code_quality"]
        assert cq.edges is not None
        defaults = [e for e in cq.edges if e.default]
        assert len(defaults) == 1
        assert set(defaults[0].targets or []) == {
            "requirements_coverage", "test_adequacy",
        }

    def test_analysis_nodes_depend_on_code_quality(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Analysis nodes MUST depend_on code_quality so the edge-based skip
        marker arrives before they start executing.

        Previous design wanted these to run in parallel with code_quality via
        conditional edges alone, but the executor resolves layers sequentially
        — a node in layer N runs before any layer N+1 node completes. That
        made the skip mark arrive after the fact, which meant
        requirements_coverage and test_adequacy executed on the APPROVED
        branch too (the exact race that GW-5056's workflow-invariants check
        catches).
        """
        assert "code_quality" in nodes_by_id["requirements_coverage"].depends_on
        assert "code_quality" in nodes_by_id["test_adequacy"].depends_on

    def test_requirements_coverage_keeps_jira_dependency(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """requirements_coverage still depends on find_jira_issue."""
        assert "find_jira_issue" in nodes_by_id["requirements_coverage"].depends_on

    def test_post_inline_comments_converges_with_all_done(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """post_inline_comments waits for all analysis via all_done trigger."""
        pic = nodes_by_id["post_inline_comments"]
        assert "code_quality" in pic.depends_on
        assert "requirements_coverage" in pic.depends_on
        assert "test_adequacy" in pic.depends_on
        assert pic.trigger_rule == TriggerRule.ALL_DONE

    def test_post_pr_summary_depends_on_inline_comments(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """post_pr_summary depends on post_inline_comments."""
        assert "post_inline_comments" in nodes_by_id["post_pr_summary"].depends_on


class TestStateChannels:
    """Test: State channel declarations with reducers."""

    def test_state_declarations_present(
        self, workflow: WorkflowDef
    ) -> None:
        """Workflow declares verdict, findings, and review_metadata channels."""
        assert "verdict" in workflow.state
        assert "findings" in workflow.state
        assert "review_metadata" in workflow.state

    def test_verdict_reducer_is_max(self, workflow: WorkflowDef) -> None:
        """verdict channel uses max reducer for escalation (R > A)."""
        ch = workflow.state["verdict"]
        assert isinstance(ch, ChannelFieldDef)
        assert ch.reducer is not None
        assert ch.reducer.strategy == ReducerStrategy.MAX

    def test_findings_reducer_is_append(self, workflow: WorkflowDef) -> None:
        """findings channel uses append reducer to accumulate."""
        ch = workflow.state["findings"]
        assert isinstance(ch, ChannelFieldDef)
        assert ch.reducer is not None
        assert ch.reducer.strategy == ReducerStrategy.APPEND
        assert ch.default == []

    def test_review_metadata_reducer_is_merge_dict(
        self, workflow: WorkflowDef
    ) -> None:
        """review_metadata uses merge_dict to combine from multiple nodes."""
        ch = workflow.state["review_metadata"]
        assert isinstance(ch, ChannelFieldDef)
        assert ch.reducer is not None
        assert ch.reducer.strategy == ReducerStrategy.MERGE_DICT


class TestReadsWrites:
    """Test: All nodes declare reads or writes subscriptions."""

    def test_code_quality_writes_verdict_and_findings(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """code_quality writes to verdict and findings channels."""
        cq = nodes_by_id["code_quality"]
        assert cq.writes is not None
        assert "verdict" in cq.writes
        assert "findings" in cq.writes

    def test_post_pr_summary_reads_verdict(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """post_pr_summary reads verdict for final determination."""
        pps = nodes_by_id["post_pr_summary"]
        assert pps.reads is not None
        assert "verdict" in pps.reads

    def test_analysis_nodes_read_and_write_verdict(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """requirements_coverage and test_adequacy both read+write verdict."""
        for nid in ("requirements_coverage", "test_adequacy"):
            node = nodes_by_id[nid]
            assert node.reads is not None
            assert "verdict" in node.reads
            assert node.writes is not None
            assert "verdict" in node.writes

    def test_all_nodes_have_reads_or_writes(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Every node except verdict_approved_pass has reads or writes."""
        for nid, node in nodes_by_id.items():
            if nid == "verdict_approved_pass":
                continue
            has_reads = node.reads is not None and len(node.reads) > 0
            has_writes = node.writes is not None and len(node.writes) > 0
            assert has_reads or has_writes, (
                f"Node {nid} has neither reads nor writes"
            )


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


from dag_executor.schema import NodeResult, NodeStatus
from tests.conftest import MockRunnerFactory, WorkflowTestHarness


def _strip_scripts(workflow: WorkflowDef) -> WorkflowDef:
    """Clear script/prompt/args bodies so mock runners skip variable resolution."""
    import copy
    wf = copy.deepcopy(workflow)
    for node in wf.nodes:
        node.script = None
        node.prompt = None
        node.args = None
    return wf


class TestReviewWorkflowExecution:
    """Integration test: Mock-execute review.yaml workflow scenarios."""

    INPUTS = {"repo": "test-repo", "pr_number": "42", "PROJECT_ROOT": "/tmp/test"}

    def test_full_review_pipeline_execution(
        self, test_harness: WorkflowTestHarness,
        mock_runner_factory: MockRunnerFactory,
        workflow: WorkflowDef,
    ) -> None:
        """AC6: Mock-execute review.yaml, verify node ordering end-to-end."""
        wf = _strip_scripts(workflow)
        test_harness.mock_all_runners(NodeResult(
            status=NodeStatus.COMPLETED,
            output={"ok": True},
        ))

        test_harness.execute(wf, self.INPUTS)

        for node_id in [
            "branch_sync", "parse_input", "fetch_pr",
            "find_jira_issue", "local_validation",
            "code_quality", "requirements_coverage", "test_adequacy",
            "post_inline_comments", "post_pr_summary", "post_jira_summary",
        ]:
            test_harness.assert_node_completed(node_id)

    def test_jira_lookup_failure_continue_path(
        self, test_harness: WorkflowTestHarness,
        mock_runner_factory: MockRunnerFactory,
        workflow: WorkflowDef,
    ) -> None:
        """AC7: find_jira_issue failure does not block review pipeline."""
        wf = _strip_scripts(workflow)
        ok = NodeResult(status=NodeStatus.COMPLETED, output={"ok": True})
        fail = NodeResult(status=NodeStatus.FAILED, error="Jira unavailable")
        bash_seq = mock_runner_factory.create_sequence([
            ok,    # branch_sync
            ok,    # parse_input
            ok,    # fetch_pr
            fail,  # find_jira_issue
            ok, ok, ok, ok, ok, ok, ok, ok,
        ])
        test_harness.mock_runner("bash", bash_seq)
        test_harness.mock_runner("prompt", mock_runner_factory.create(
            output={"ok": True}
        ))

        test_harness.execute(wf, self.INPUTS)

        test_harness.assert_node_failed("find_jira_issue")
        test_harness.assert_node_completed("code_quality")
        test_harness.assert_node_completed("post_pr_summary")
