"""Tests for the validate-epic.yaml workflow and stub child workflows.

Validates that the YAML-based validate-epic orchestrator parses correctly,
has proper node ordering, context:shared configuration, conditional routing
with NO $ prefix in edge conditions, and that stub child workflows have
correct input/output contracts.
"""
from pathlib import Path
from typing import Dict

import pytest

from dag_executor.graph import topological_sort_with_layers
from dag_executor.parser import load_workflow
from dag_executor.schema import (
    DispatchMode,
    NodeDef,
    TriggerRule,
    WorkflowDef,
)


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "validate-epic.yaml"
)
CHILDREN_STUB_PATH = str(
    Path(__file__).parent.parent / "workflows" / "validate-epic-audit-children.yaml"
)
ARTIFACTS_STUB_PATH = str(
    Path(__file__).parent.parent / "workflows" / "validate-epic-audit-artifacts.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the validate-epic.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def children_stub() -> WorkflowDef:
    """Load and return the validate-epic-audit-children.yaml stub."""
    return load_workflow(CHILDREN_STUB_PATH)


@pytest.fixture
def artifacts_stub() -> WorkflowDef:
    """Load and return the validate-epic-audit-artifacts.yaml stub."""
    return load_workflow(ARTIFACTS_STUB_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1: All 3 YAMLs parse without errors and have correct structure."""

    def test_orchestrator_parses_successfully(self, workflow: WorkflowDef) -> None:
        """validate-epic.yaml loads with no validation errors."""
        assert workflow.name == "Validate Epic Workflow"
        assert len(workflow.nodes) >= 9  # 9 phase nodes minimum

    def test_input_epic_required_with_pattern(self, workflow: WorkflowDef) -> None:
        """epic input is required and has Jira key pattern."""
        epic_input = workflow.inputs["epic"]
        assert epic_input.required is True
        assert epic_input.pattern == r"^[A-Z]+-\d+$"

    def test_input_audit_only_has_default(self, workflow: WorkflowDef) -> None:
        """audit_only input has default: false."""
        audit_only = workflow.inputs["audit_only"]
        assert audit_only.required is False
        assert audit_only.default is False

    def test_config_checkpoint_prefix(self, workflow: WorkflowDef) -> None:
        """Workflow config has checkpoint_prefix: vale."""
        assert workflow.config.checkpoint_prefix == "vale"
        assert workflow.config.worktree is False

    def test_labels_config(self, workflow: WorkflowDef) -> None:
        """Workflow has labels config for failure handling."""
        assert workflow.config.labels is not None
        assert workflow.config.labels.on_failure == "outcome:epic-incomplete"

    def test_children_stub_parses(self, children_stub: WorkflowDef) -> None:
        """validate-epic-audit-children.yaml loads successfully."""
        assert children_stub.name is not None
        assert len(children_stub.nodes) >= 1

    def test_artifacts_stub_parses(self, artifacts_stub: WorkflowDef) -> None:
        """validate-epic-audit-artifacts.yaml loads successfully."""
        assert artifacts_stub.name is not None
        assert len(artifacts_stub.nodes) >= 1


class TestPhaseNodes:
    """Test 2: All expected node ids present with correct types, models, dispatch."""

    def test_all_phase_nodes_present(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """All 9 phase nodes exist."""
        expected_nodes = [
            "resume_check",
            "load_spec",
            "audit_children",
            "audit_artifacts",
            "ac_reconciliation",
            "integration_check",
            "invariants_audit",
            "produce_verdict",
            "transition_epic",
            "store_episode",
            "print_summary",
        ]
        for node_id in expected_nodes:
            assert node_id in nodes_by_id, f"Expected node {node_id} not found"

    def test_load_spec_is_prompt_opus_inline(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Phase 0.5 load_spec is prompt node with model:opus, dispatch:inline."""
        node = nodes_by_id["load_spec"]
        assert node.type == "prompt"
        assert node.model == "opus"
        assert node.dispatch == DispatchMode.INLINE

    def test_semantic_nodes_have_context_shared(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """Phase 3-7 semantic nodes have context:shared."""
        semantic_nodes = [
            "load_spec",
            "ac_reconciliation",
            "integration_check",
            "invariants_audit",
            "produce_verdict",
            "transition_epic",
        ]
        for node_id in semantic_nodes:
            node = nodes_by_id[node_id]
            # context:shared is the default, so either explicit or omitted is fine
            # but if it's explicit, check it's "shared"
            if hasattr(node, 'context') and node.context is not None:
                assert node.context == "shared", f"{node_id} should have context:shared"

    def test_audit_children_is_command_node(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """audit_children is type:command with correct command and dispatch."""
        node = nodes_by_id["audit_children"]
        assert node.type == "command"
        assert node.command == "validate-epic-audit-children"
        assert node.dispatch == DispatchMode.LOCAL

    def test_audit_artifacts_is_command_node(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """audit_artifacts is type:command with correct command and dispatch."""
        node = nodes_by_id["audit_artifacts"]
        assert node.type == "command"
        assert node.command == "validate-epic-audit-artifacts"
        assert node.dispatch == DispatchMode.LOCAL

    def test_produce_verdict_has_trigger_rule(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """produce_verdict uses trigger_rule: one_success."""
        node = nodes_by_id["produce_verdict"]
        assert node.trigger_rule == TriggerRule.ONE_SUCCESS


class TestEdgesAndRouting:
    """Test 3: Topological sort succeeds, edges have NO $ prefix, conditions correct."""

    def test_topological_sort_succeeds(self, workflow: WorkflowDef) -> None:
        """Topological sort produces valid ordering (no cycles)."""
        layers = topological_sort_with_layers(workflow.nodes)
        assert len(layers) > 0

    def test_audit_children_has_three_edges(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """audit_children has 3 edges (2 conditional + 1 default)."""
        node = nodes_by_id["audit_children"]
        assert node.edges is not None
        assert len(node.edges) == 3

    def test_no_dollar_prefix_in_edge_conditions(
        self, workflow: WorkflowDef
    ) -> None:
        """NO edge condition contains literal $ character (v3 critical fix)."""
        for node in workflow.nodes:
            if node.edges:
                for edge in node.edges:
                    if edge.condition:
                        assert "$" not in edge.condition, (
                            f"Edge condition '{edge.condition}' on node {node.id} "
                            f"contains $ prefix (causes simpleeval syntax error)"
                        )

    def test_integration_check_has_conditional_routing(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """integration_check has conditional edge to invariants_audit."""
        node = nodes_by_id["integration_check"]
        assert node.edges is not None
        targets = {edge.target for edge in node.edges}
        assert "invariants_audit" in targets
        assert "produce_verdict" in targets

    def test_edges_use_python_boolean_operators(
        self, workflow: WorkflowDef
    ) -> None:
        """Edge conditions use Python 'and', 'or', 'not', not C-style &&, ||, !."""
        for node in workflow.nodes:
            if node.edges:
                for edge in node.edges:
                    if edge.condition:
                        # Should NOT contain C-style operators
                        assert "&&" not in edge.condition, (
                            f"Edge condition on {node.id} uses && (should be 'and')"
                        )
                        assert "||" not in edge.condition, (
                            f"Edge condition on {node.id} uses || (should be 'or')"
                        )
                        # Check for likely use of ! (not always wrong, but suspicious)
                        if "!" in edge.condition and "!=" not in edge.condition:
                            # ! used for negation (not part of !=)
                            assert False, (
                                f"Edge condition on {node.id} uses ! (should be 'not')"
                            )


class TestOutputs:
    """Test 4: Outputs reference produce_verdict and do NOT include conversation_id."""

    def test_verdict_output_exists(self, workflow: WorkflowDef) -> None:
        """outputs.verdict references produce_verdict."""
        assert "verdict" in workflow.outputs
        verdict_output = workflow.outputs["verdict"]
        assert verdict_output.node == "produce_verdict"

    def test_report_path_output_exists(self, workflow: WorkflowDef) -> None:
        """outputs.report_path references produce_verdict."""
        assert "report_path" in workflow.outputs
        report_path_output = workflow.outputs["report_path"]
        assert report_path_output.node == "produce_verdict"

    def test_conversation_id_not_in_outputs(self, workflow: WorkflowDef) -> None:
        """outputs.conversation_id does NOT exist (v2 fix)."""
        assert "conversation_id" not in workflow.outputs


class TestStubChildContracts:
    """Test 5: Verify stub child workflows have correct input/output schemas."""

    def test_children_stub_has_epic_input(
        self, children_stub: WorkflowDef
    ) -> None:
        """validate-epic-audit-children.yaml has epic input with pattern."""
        assert "epic" in children_stub.inputs
        epic = children_stub.inputs["epic"]
        assert epic.required is True
        assert epic.pattern == r"^[A-Z]+-\d+$"

    def test_children_stub_outputs(
        self, children_stub: WorkflowDef
    ) -> None:
        """Children stub has correct output fields."""
        expected_outputs = [
            "hard_gate_failures",
            "children_total",
            "children_done",
        ]
        for output_name in expected_outputs:
            assert output_name in children_stub.outputs, (
                f"Expected output {output_name} not found in children stub"
            )

    def test_artifacts_stub_has_required_inputs(
        self, artifacts_stub: WorkflowDef
    ) -> None:
        """Artifacts stub has epic and affected_repos inputs."""
        assert "epic" in artifacts_stub.inputs
        assert artifacts_stub.inputs["epic"].required is True
        assert "affected_repos" in artifacts_stub.inputs
        assert artifacts_stub.inputs["affected_repos"].required is True

    def test_artifacts_stub_outputs(
        self, artifacts_stub: WorkflowDef
    ) -> None:
        """Artifacts stub has correct output fields."""
        expected_outputs = [
            "hard_gate_failures",
            "deploy_gates",
            "test_artifact_gates",
            "smoke_gate",
            "json_path",
        ]
        for output_name in expected_outputs:
            assert output_name in artifacts_stub.outputs, (
                f"Expected output {output_name} not found in artifacts stub"
            )


class TestBehavioralRouting:
    """Test 6: Verify trigger_rule:one_success and conditional routing structure."""

    def test_produce_verdict_accepts_multiple_dependencies(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """produce_verdict has multiple depends_on entries and trigger_rule:one_success."""
        node = nodes_by_id["produce_verdict"]
        assert node.depends_on is not None
        assert len(node.depends_on) >= 2
        assert "audit_children" in node.depends_on
        assert "invariants_audit" in node.depends_on
        assert node.trigger_rule == TriggerRule.ONE_SUCCESS

    def test_design_session_conditional_routes_to_invariants(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """integration_check has edge to invariants_audit with design_session condition."""
        node = nodes_by_id["integration_check"]
        assert node.edges is not None
        
        # Find edge to invariants_audit
        invariants_edge = None
        for edge in node.edges:
            if edge.target == "invariants_audit":
                invariants_edge = edge
                break
        
        assert invariants_edge is not None
        assert invariants_edge.condition is not None
        assert "load_spec.design_session" in invariants_edge.condition
        assert "!=" in invariants_edge.condition or "not" in invariants_edge.condition

    def test_audit_children_has_audit_only_branching(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """audit_children has edges for audit_only branching logic."""
        node = nodes_by_id["audit_children"]
        assert node.edges is not None
        assert len(node.edges) == 3
        
        # Should have edges to both produce_verdict and audit_artifacts
        targets = {edge.target for edge in node.edges}
        assert "produce_verdict" in targets
        assert "audit_artifacts" in targets
        
        # Check that at least one edge uses audit_only in condition
        has_audit_only_condition = any(
            edge.condition and "audit_only" in edge.condition
            for edge in node.edges
        )
        assert has_audit_only_condition

    def test_routing_uses_bare_variable_names(
        self, workflow: WorkflowDef
    ) -> None:
        """Edge conditions use bare names like 'audit_children.field', not '$audit_children.field'."""
        for node in workflow.nodes:
            if node.edges:
                for edge in node.edges:
                    if edge.condition and "." in edge.condition:
                        # Check for node references in conditions
                        if "audit_children" in edge.condition:
                            # Should be bare name, not $audit_children
                            assert "$audit_children" not in edge.condition
                        if "load_spec" in edge.condition:
                            assert "$load_spec" not in edge.condition
