"""Tests for the validate-epic-audit-children.yaml workflow definition.

Validates that the YAML-based epic children audit sub-DAG parses correctly,
declares required channels, uses unified routers, and has proper dispatch configuration.
"""
from pathlib import Path
from typing import Dict

import pytest

from dag_executor.parser import load_workflow
from dag_executor.schema import (
    DispatchMode,
    NodeDef,
    WorkflowDef,
)


WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "validate-epic-audit-children.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the validate-epic-audit-children.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1: YAML parses without errors and has correct structure."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """validate-epic-audit-children.yaml loads with no validation errors."""
        assert workflow.name == "Validate Epic Audit Children Sub-DAG"
        assert len(workflow.nodes) >= 3

    def test_input_epic_required_with_pattern(
        self, workflow: WorkflowDef
    ) -> None:
        """epic input is required and has Jira key pattern."""
        epic_input = workflow.inputs["epic"]
        assert epic_input.required is True
        assert epic_input.pattern == r"^[A-Z]+-\d+$"

    def test_config_valid(self, workflow: WorkflowDef) -> None:
        """Workflow config has correct checkpoint prefix and worktree setting."""
        assert workflow.config.checkpoint_prefix == "validate-epic-audit-children"
        assert workflow.config.worktree is False


class TestStateChannels:
    """Test 2: State channels declared with correct reducers."""

    def test_declares_required_channels(self, workflow: WorkflowDef) -> None:
        """Sub-DAG declares children_list, audit_results, aggregate_summary channels."""
        assert "children_list" in workflow.state
        assert "audit_results" in workflow.state
        assert "aggregate_summary" in workflow.state


class TestOutputContract:
    """Test 3: Outputs contract matches parent workflow expectations."""

    def test_declares_output_contract(self, workflow: WorkflowDef) -> None:
        """Sub-DAG declares structured outputs for parent workflow."""
        assert "children_total" in workflow.outputs
        assert "children_done" in workflow.outputs
        assert "hard_gate_failures" in workflow.outputs
        assert "children" in workflow.outputs

    def test_output_sources_from_aggregate_node(
        self, workflow: WorkflowDef
    ) -> None:
        """All outputs come from the aggregate node."""
        assert workflow.outputs["children_total"].node == "aggregate"
        assert workflow.outputs["children_done"].node == "aggregate"
        assert workflow.outputs["hard_gate_failures"].node == "aggregate"
        assert workflow.outputs["children"].node == "aggregate"


class TestDispatchMode:
    """Test 4: Dispatch configuration matches local execution requirement."""

    def test_all_bash_local_dispatch(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """All nodes use bash with local dispatch (no remote Opus)."""
        for node_id, node in nodes_by_id.items():
            if node.type == "bash":
                # Bash nodes are implicitly local
                assert node.dispatch is None or node.dispatch == DispatchMode.LOCAL
            elif node.type == "prompt":
                # No prompts should be in this deterministic sub-DAG
                pytest.fail(
                    f"Node {node_id} is a prompt but should be bash for deterministic audit"
                )


class TestSkillPaths:
    """Test 5: Skill invocations reference real skill directories.

    GW-5356: the prior TestUnifiedRouterUsage enshrined an aspirational
    `skills/issues/` alias that was never implemented. The live skills live at
    `skills/jira/` and `skills/vcs/` directly. Tests now assert the real paths.
    """

    def test_uses_real_skill_paths(self, workflow: WorkflowDef) -> None:
        with open(WORKFLOW_PATH, 'r') as f:
            content = f.read()
        assert "~/.claude/skills/jira/" in content
        assert "~/.claude/skills/vcs/" in content
        # The aspirational unified-router alias was never implemented
        assert "skills/issues/" not in content
