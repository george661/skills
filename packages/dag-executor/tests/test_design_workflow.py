"""Tests for the design.yaml workflow definition.

Validates that the YAML-based design workflow parses correctly, has proper
node ordering, interrupt handling, gate-based phase selection, and correct
channel/checkpoint configuration.

These integration tests follow test_plan_workflow.py's pattern — command-node
runtime dispatch is stubbed in the executor, so the harness mocks the command
runner rather than exercising real phase execution.
"""
from pathlib import Path
from typing import Dict

import pytest

from dag_executor.graph import topological_sort_with_layers
from dag_executor.parser import load_workflow
from dag_executor.schema import (
    NodeDef,
    OnFailure,
    ReducerStrategy,
    TriggerRule,
    WorkflowDef,
)


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "design.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the design.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1: YAML parses without errors and has correct structure."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """design.yaml loads with no validation errors."""
        assert workflow.name == "Design Command Workflow"
        assert len(workflow.nodes) == 14  # 1 init + 1 interrupt + 1 determine + 5 gates + 5 run_* + 1 commit

    def test_checkpoint_prefix(self, workflow: WorkflowDef) -> None:
        """Workflow config has checkpoint prefix 'design'."""
        assert workflow.config.checkpoint_prefix == "design"

    def test_labels_on_failure(self, workflow: WorkflowDef) -> None:
        """Workflow has labels config for failure handling."""
        assert workflow.config.labels is not None
        assert workflow.config.labels.on_failure == "outcome:design-failed"


class TestInputs:
    """Test 2: Input parameter validation."""

    def test_prompt_required(self, workflow: WorkflowDef) -> None:
        """prompt input is required."""
        prompt_input = workflow.inputs["prompt"]
        assert prompt_input.required is True
        assert prompt_input.type == "string"

    def test_session_id_optional(self, workflow: WorkflowDef) -> None:
        """session_id input is optional with default."""
        session_input = workflow.inputs["session_id"]
        assert session_input.required is False
        assert session_input.default == ""


class TestStateChannels:
    """Test 3: State channel declarations."""

    def test_session_state_channel(self, workflow: WorkflowDef) -> None:
        """session_state channel exists with correct config."""
        channel = workflow.state["session_state"]
        assert channel.type == "dict"
        assert channel.reducer.strategy == ReducerStrategy.OVERWRITE

    def test_active_phases_channel(self, workflow: WorkflowDef) -> None:
        """active_phases channel exists with list type."""
        channel = workflow.state["active_phases"]
        assert channel.type == "list"
        assert channel.reducer.strategy == ReducerStrategy.OVERWRITE
        assert channel.default == []

    def test_phase_outputs_channel(self, workflow: WorkflowDef) -> None:
        """phase_outputs channel uses merge_dict reducer."""
        channel = workflow.state["phase_outputs"]
        assert channel.type == "dict"
        assert channel.reducer.strategy == ReducerStrategy.MERGE_DICT
        assert channel.default == {}

    def test_confidence_scores_channel(self, workflow: WorkflowDef) -> None:
        """confidence_scores channel uses merge_dict reducer."""
        channel = workflow.state["confidence_scores"]
        assert channel.type == "dict"
        assert channel.reducer.strategy == ReducerStrategy.MERGE_DICT
        assert channel.default == {}


class TestTopologicalOrdering:
    """Test 4: Topological sort produces correct phase ordering."""

    def test_phase_ordering(self, workflow: WorkflowDef) -> None:
        """Phases execute in correct order."""
        layers = topological_sort_with_layers(workflow.nodes)
        flat_order = [nid for layer in layers for nid in layer]

        def before(a: str, b: str) -> None:
            assert flat_order.index(a) < flat_order.index(b), (
                f"{a} must execute before {b}"
            )

        # Init → interrupt → determine → gates → commit
        before("init_session", "master_interview")
        before("master_interview", "determine_phases")
        before("determine_phases", "domain_model_gate")
        before("determine_phases", "diagram_gate")
        before("determine_phases", "wireframe_gate")
        before("determine_phases", "mockup_gate")
        before("determine_phases", "contract_gate")

        # Each gate → its run_* phase
        before("domain_model_gate", "run_domain_model")
        before("diagram_gate", "run_diagram")
        before("wireframe_gate", "run_wireframe")
        before("mockup_gate", "run_mockup")
        before("contract_gate", "run_contract")

        # All phases → commit
        before("run_domain_model", "commit_artifacts")
        before("run_diagram", "commit_artifacts")
        before("run_wireframe", "commit_artifacts")
        before("run_mockup", "commit_artifacts")
        before("run_contract", "commit_artifacts")


class TestInterruptNode:
    """Test 5: Master interview interrupt node."""

    def test_interrupt_type(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """master_interview is an interrupt node."""
        node = nodes_by_id["master_interview"]
        assert node.type == "interrupt"

    def test_interrupt_resume_key(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """master_interview uses resume_key 'design_selections'."""
        node = nodes_by_id["master_interview"]
        assert node.resume_key == "design_selections"

    def test_interrupt_channels(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """master_interview uses terminal channel."""
        node = nodes_by_id["master_interview"]
        assert node.channels == ["terminal"]

    def test_interrupt_reads_state(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """master_interview reads session_state."""
        node = nodes_by_id["master_interview"]
        assert "session_state" in node.reads


class TestPhaseGates:
    """Test 6: Gate nodes for conditional phase execution."""

    @pytest.mark.parametrize(
        "gate_id",
        [
            "domain_model_gate",
            "diagram_gate",
            "wireframe_gate",
            "mockup_gate",
            "contract_gate",
        ],
    )
    def test_gate_type(
        self, nodes_by_id: Dict[str, NodeDef], gate_id: str
    ) -> None:
        """Each phase gate is type 'gate'."""
        node = nodes_by_id[gate_id]
        assert node.type == "gate"

    @pytest.mark.parametrize(
        "gate_id",
        [
            "domain_model_gate",
            "diagram_gate",
            "wireframe_gate",
            "mockup_gate",
            "contract_gate",
        ],
    )
    def test_gate_on_failure_continue(
        self, nodes_by_id: Dict[str, NodeDef], gate_id: str
    ) -> None:
        """Each gate uses on_failure: continue to skip unselected phases."""
        node = nodes_by_id[gate_id]
        assert node.on_failure == OnFailure.CONTINUE

    @pytest.mark.parametrize(
        "gate_id",
        [
            "domain_model_gate",
            "diagram_gate",
            "wireframe_gate",
            "mockup_gate",
            "contract_gate",
        ],
    )
    def test_gate_condition_references_active_phases(
        self, nodes_by_id: Dict[str, NodeDef], gate_id: str
    ) -> None:
        """Each gate condition checks active_phases."""
        node = nodes_by_id[gate_id]
        assert node.condition is not None
        assert "active_phases" in node.condition


class TestTriggerRules:
    """Test 7: Trigger rules for handling skipped phases."""

    @pytest.mark.parametrize(
        "node_id",
        [
            "diagram_gate",
            "wireframe_gate",
            "mockup_gate",
            "contract_gate",
            "commit_artifacts",
        ],
    )
    def test_all_done_trigger(
        self, nodes_by_id: Dict[str, NodeDef], node_id: str
    ) -> None:
        """Gates after first phase and commit use trigger_rule: all_done."""
        node = nodes_by_id[node_id]
        assert node.trigger_rule == TriggerRule.ALL_DONE


class TestCommandNodes:
    """Test 8: Command nodes invoke markdown phase commands."""

    @pytest.mark.parametrize(
        "node_id,command",
        [
            ("run_domain_model", "design:domain-model"),
            ("run_diagram", "design:diagram"),
            ("run_wireframe", "design:wireframe"),
            ("run_mockup", "design:mockup"),
            ("run_contract", "design:contract"),
        ],
    )
    def test_command_node_type(
        self,
        nodes_by_id: Dict[str, NodeDef],
        node_id: str,
        command: str,
    ) -> None:
        """Each run_* node is type 'command'."""
        node = nodes_by_id[node_id]
        assert node.type == "command"
        assert node.command == command


class TestChannelSubscriptions:
    """Test 9: Channel reads/writes across phases."""

    @pytest.mark.parametrize(
        "node_id",
        [
            "run_domain_model",
            "run_diagram",
            "run_wireframe",
            "run_mockup",
            "run_contract",
        ],
    )
    def test_phase_writes_outputs(
        self, nodes_by_id: Dict[str, NodeDef], node_id: str
    ) -> None:
        """Each run_* node writes phase_outputs and confidence_scores."""
        node = nodes_by_id[node_id]
        assert "phase_outputs" in node.writes
        assert "confidence_scores" in node.writes

    def test_commit_reads_outputs(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """commit_artifacts reads phase_outputs and confidence_scores."""
        node = nodes_by_id["commit_artifacts"]
        assert "phase_outputs" in node.reads
        assert "confidence_scores" in node.reads


class TestCheckpoints:
    """Test 10: Checkpoint configuration for resume."""

    @pytest.mark.parametrize(
        "node_id",
        [
            "master_interview",
            "run_domain_model",
            "run_diagram",
            "run_wireframe",
            "run_mockup",
            "run_contract",
            "commit_artifacts",
        ],
    )
    def test_checkpoint_enabled(
        self, nodes_by_id: Dict[str, NodeDef], node_id: str
    ) -> None:
        """Key nodes have checkpoint: true for session resume."""
        node = nodes_by_id[node_id]
        assert node.checkpoint is True


# Integration tests would go here if we had WorkflowTestHarness
# For now, these structural tests verify the YAML definition is correct
