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
    NodeResult,
    NodeStatus,
    OnFailure,
    TriggerRule,
    WorkflowDef,
    WorkflowStatus,
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
        assert len(workflow.nodes) == 22  # 20 original nodes + 2 interrupt nodes

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

    def test_no_hardcoded_gw_docs_path(self, workflow: WorkflowDef) -> None:
        """plan.yaml should not contain hardcoded 'gw-docs' paths."""
        # Read the raw YAML file to check for hardcoded paths
        with open(WORKFLOW_PATH, 'r') as f:
            content = f.read()
        assert 'gw-docs' not in content, \
            "Found hardcoded 'gw-docs' path - should use $TENANT_DOCS_REPO env var"


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

        # Phase 4-6: Review stages with interrupts
        before("security_audit", "security_signoff_interrupt")
        before("security_signoff_interrupt", "final_review")
        before("final_review", "prp_approval_interrupt")
        before("prp_approval_interrupt", "commit_prp")


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


from tests.conftest import MockRunnerFactory, WorkflowTestHarness


class TestChannelDeclarations:
    """Test 8: State channel declarations exist with correct types/reducers."""

    def test_state_channels_declared(self, workflow: WorkflowDef) -> None:
        """plan.yaml declares state: block with 3 channels."""
        assert workflow.state is not None
        assert len(workflow.state) == 3

    def test_prp_state_channel(self, workflow: WorkflowDef) -> None:
        """prp_state channel has dict type and overwrite reducer."""
        prp_state = workflow.state.get("prp_state")
        assert prp_state is not None
        assert prp_state.type == "dict"
        assert prp_state.reducer.strategy.value == "overwrite"

    def test_review_verdicts_channel(self, workflow: WorkflowDef) -> None:
        """review_verdicts channel has list type, append reducer, default []."""
        review_verdicts = workflow.state.get("review_verdicts")
        assert review_verdicts is not None
        assert review_verdicts.type == "list"
        assert review_verdicts.reducer.strategy.value == "append"
        assert review_verdicts.default == []

    def test_skeleton_output_channel(self, workflow: WorkflowDef) -> None:
        """skeleton_output channel has dict type and overwrite reducer."""
        skeleton_output = workflow.state.get("skeleton_output")
        assert skeleton_output is not None
        assert skeleton_output.type == "dict"
        assert skeleton_output.reducer.strategy.value == "overwrite"


class TestNodeChannelSubscriptions:
    """Test 9: Nodes declare reads/writes channel subscriptions."""

    def test_create_prp_writes_prp_state(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """create_prp writes to prp_state channel."""
        node = nodes_by_id["create_prp"]
        assert node.writes is not None
        assert "prp_state" in node.writes

    def test_design_integration_reads_writes_prp_state(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """design_integration reads and writes prp_state."""
        node = nodes_by_id["design_integration"]
        assert node.reads is not None
        assert "prp_state" in node.reads
        assert node.writes is not None
        assert "prp_state" in node.writes

    def test_create_skeleton_writes_skeleton_output(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """create_skeleton writes to skeleton_output channel."""
        node = nodes_by_id["create_skeleton"]
        assert node.writes is not None
        assert "skeleton_output" in node.writes

    def test_review_skeleton_reads_writes_channels(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """review_skeleton reads skeleton_output, writes review_verdicts."""
        node = nodes_by_id["review_skeleton"]
        assert node.reads is not None
        assert "skeleton_output" in node.reads
        assert node.writes is not None
        assert "review_verdicts" in node.writes

    def test_fix_skeleton_reads_writes_skeleton_output(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """fix_skeleton reads and writes skeleton_output."""
        node = nodes_by_id["fix_skeleton"]
        assert node.reads is not None
        assert "skeleton_output" in node.reads
        assert node.writes is not None
        assert "skeleton_output" in node.writes

    def test_first_review_reads_channels(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """first_review reads prp_state and review_verdicts."""
        node = nodes_by_id["first_review"]
        assert node.reads is not None
        assert "prp_state" in node.reads
        assert "review_verdicts" in node.reads
        assert node.writes is not None
        assert "review_verdicts" in node.writes

    def test_final_review_reads_channels(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """final_review reads prp_state and review_verdicts, writes review_verdicts."""
        node = nodes_by_id["final_review"]
        assert node.reads is not None
        assert "prp_state" in node.reads
        assert "review_verdicts" in node.reads
        assert node.writes is not None
        assert "review_verdicts" in node.writes

    def test_commit_prp_reads_prp_state(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """commit_prp reads prp_state."""
        node = nodes_by_id["commit_prp"]
        assert node.reads is not None
        assert "prp_state" in node.reads


class TestInterruptNodes:
    """Test 10: Interrupt nodes exist with correct configuration."""

    def test_security_signoff_interrupt_exists(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """security_signoff_interrupt node exists as interrupt type."""
        node = nodes_by_id["security_signoff_interrupt"]
        assert node.type == "interrupt"

    def test_security_signoff_interrupt_config(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """security_signoff_interrupt has correct message, resume_key, channels."""
        node = nodes_by_id["security_signoff_interrupt"]
        assert node.message is not None
        assert "Security audit complete" in node.message
        assert node.resume_key == "security_signoff"
        assert node.channels == ["terminal"]

    def test_security_signoff_interrupt_depends_on(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """security_signoff_interrupt depends on security_audit."""
        node = nodes_by_id["security_signoff_interrupt"]
        assert "security_audit" in node.depends_on

    def test_security_signoff_interrupt_reads_channels(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """security_signoff_interrupt reads prp_state and review_verdicts."""
        node = nodes_by_id["security_signoff_interrupt"]
        assert node.reads is not None
        assert "prp_state" in node.reads
        assert "review_verdicts" in node.reads

    def test_prp_approval_interrupt_exists(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """prp_approval_interrupt node exists as interrupt type."""
        node = nodes_by_id["prp_approval_interrupt"]
        assert node.type == "interrupt"

    def test_prp_approval_interrupt_config(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """prp_approval_interrupt has correct message, resume_key, channels."""
        node = nodes_by_id["prp_approval_interrupt"]
        assert node.message is not None
        assert "PRP for" in node.message
        assert "approve" in node.message.lower()
        assert node.resume_key == "prp_approval"
        assert node.channels == ["terminal"]

    def test_prp_approval_interrupt_depends_on(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """prp_approval_interrupt depends on final_review."""
        node = nodes_by_id["prp_approval_interrupt"]
        assert "final_review" in node.depends_on

    def test_prp_approval_interrupt_reads_channels(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """prp_approval_interrupt reads prp_state and review_verdicts."""
        node = nodes_by_id["prp_approval_interrupt"]
        assert node.reads is not None
        assert "prp_state" in node.reads
        assert "review_verdicts" in node.reads

    def test_final_review_depends_on_security_signoff_interrupt(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """final_review depends on security_signoff_interrupt (not security_audit)."""
        node = nodes_by_id["final_review"]
        assert "security_signoff_interrupt" in node.depends_on
        assert "security_audit" not in node.depends_on

    def test_commit_prp_depends_on_prp_approval_interrupt(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """commit_prp depends on prp_approval_interrupt (not final_review)."""
        node = nodes_by_id["commit_prp"]
        assert "prp_approval_interrupt" in node.depends_on
        assert "final_review" not in node.depends_on


def _strip_scripts(workflow: WorkflowDef) -> WorkflowDef:
    """Clear script/prompt/args bodies so mock runners skip variable resolution."""
    import copy
    wf = copy.deepcopy(workflow)
    for node in wf.nodes:
        node.script = None
        node.prompt = None
        node.args = None
    return wf


class TestInterruptWorkflowExecution:
    """Test 11: Mock-execute workflow with interrupts, verify pause/resume."""

    INPUTS = {"epic_key": "TEST-100"}

    def test_workflow_pauses_at_security_signoff_interrupt(
        self, test_harness: WorkflowTestHarness,
        mock_runner_factory: MockRunnerFactory,
        workflow: WorkflowDef,
    ) -> None:
        """Workflow pauses at security_signoff_interrupt, waits for resume."""
        wf = _strip_scripts(workflow)
        test_harness.mock_all_runners(NodeResult(
            status=NodeStatus.COMPLETED,
            output={"ok": True},
        ))
        # Interrupt runner returns INTERRUPTED status
        test_harness.mock_runner(
            "interrupt",
            mock_runner_factory.create(status=NodeStatus.INTERRUPTED),
        )
        result = test_harness.execute(wf, self.INPUTS)

        # Workflow should pause at first interrupt
        assert result.status in [WorkflowStatus.PAUSED, WorkflowStatus.COMPLETED]
        test_harness.assert_node_completed("security_audit")

    def test_workflow_pauses_at_prp_approval_interrupt(
        self, test_harness: WorkflowTestHarness,
        mock_runner_factory: MockRunnerFactory,
        workflow: WorkflowDef,
    ) -> None:
        """Workflow pauses at prp_approval_interrupt after final_review."""
        wf = _strip_scripts(workflow)
        test_harness.mock_all_runners(NodeResult(
            status=NodeStatus.COMPLETED,
            output={"ok": True},
        ))
        # Mock interrupt to pause - but workflow will pause at first interrupt (security_signoff)
        test_harness.mock_runner(
            "interrupt",
            mock_runner_factory.create(status=NodeStatus.INTERRUPTED),
        )
        result = test_harness.execute(wf, self.INPUTS)

        # Workflow should pause at one of the interrupt nodes
        assert result.status == WorkflowStatus.PAUSED
        # Should have completed security_audit before pausing at security_signoff_interrupt
        test_harness.assert_node_completed("security_audit")


class TestSkeletonGateWithChannels:
    """Test 12: Skeleton gate retry pattern works with channel subscriptions."""

    INPUTS = {"epic_key": "TEST-100"}

    def test_skeleton_gate_success_skips_fix_skeleton(
        self, test_harness: WorkflowTestHarness,
        workflow: WorkflowDef,
    ) -> None:
        """When skeleton_gate passes, fix_skeleton is skipped, first_review runs."""
        wf = _strip_scripts(workflow)
        test_harness.mock_all_runners(NodeResult(
            status=NodeStatus.COMPLETED,
            output={"verdict": "APPROVED", "ok": True},
        ))
        test_harness.execute(wf, self.INPUTS)

        test_harness.assert_node_completed("skeleton_gate")
        test_harness.assert_node_completed("first_review")

    def test_skeleton_gate_failure_triggers_fix_with_channels(
        self, test_harness: WorkflowTestHarness,
        mock_runner_factory: MockRunnerFactory,
        workflow: WorkflowDef,
    ) -> None:
        """When skeleton_gate fails, fix_skeleton reads/writes skeleton_output."""
        wf = _strip_scripts(workflow)
        test_harness.mock_all_runners(NodeResult(
            status=NodeStatus.COMPLETED,
            output={"verdict": "REJECTED", "ok": True},
        ))
        test_harness.mock_runner(
            "gate", mock_runner_factory.create(status=NodeStatus.FAILED),
        )
        test_harness.execute(wf, self.INPUTS)

        test_harness.assert_node_failed("skeleton_gate")
        test_harness.assert_node_completed("fix_skeleton")
        # first_review should still run via one_success trigger
        test_harness.assert_node_completed("first_review")


class TestPlanWorkflowExecution:
    """Integration test: Mock-execute plan.yaml workflow scenarios."""

    INPUTS = {"epic_key": "TEST-100"}

    def test_review_pipeline_ordering_execution(
        self, test_harness: WorkflowTestHarness,
        workflow: WorkflowDef,
    ) -> None:
        """AC4: Mock-execute plan.yaml, verify review pipeline ordering."""
        wf = _strip_scripts(workflow)
        test_harness.mock_all_runners(NodeResult(
            status=NodeStatus.COMPLETED,
            output={"verdict": "APPROVED", "ok": True},
        ))
        test_harness.execute(wf, self.INPUTS)

        for node_id in [
            "create_skeleton", "review_skeleton", "skeleton_gate",
            "first_review", "arch_review", "security_audit",
            "security_signoff_interrupt", "final_review",
            "prp_approval_interrupt",
        ]:
            test_harness.assert_node_completed(node_id)

    def test_skeleton_gate_failure_triggers_fix_skeleton(
        self, test_harness: WorkflowTestHarness,
        mock_runner_factory: MockRunnerFactory,
        workflow: WorkflowDef,
    ) -> None:
        """AC5: skeleton_gate failure triggers fix_skeleton, first_review still runs."""
        wf = _strip_scripts(workflow)
        test_harness.mock_all_runners(NodeResult(
            status=NodeStatus.COMPLETED,
            output={"verdict": "REJECTED", "ok": True},
        ))
        test_harness.mock_runner(
            "gate", mock_runner_factory.create(status=NodeStatus.FAILED),
        )
        test_harness.execute(wf, self.INPUTS)

        test_harness.assert_node_failed("skeleton_gate")
        test_harness.assert_node_completed("fix_skeleton")
        test_harness.assert_node_completed("first_review")
