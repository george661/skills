"""Tests for the validate-deploy-status.yaml workflow definition.

Validates that the YAML-based deploy status sub-DAG parses correctly, declares
required channels, uses unified routers, and has proper dispatch configuration.
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
    Path(__file__).parent.parent / "workflows" / "validate-deploy-status.yaml"
)


@pytest.fixture
def workflow() -> WorkflowDef:
    """Load and return the validate-deploy-status.yaml workflow definition."""
    return load_workflow(WORKFLOW_PATH)


@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    """Return workflow nodes indexed by ID."""
    return {n.id: n for n in workflow.nodes}


class TestWorkflowParsing:
    """Test 1: YAML parses without errors and has correct structure."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        """validate-deploy-status.yaml loads with no validation errors."""
        assert workflow.name == "Validate Deploy Status Sub-DAG"
        assert len(workflow.nodes) >= 3

    def test_input_issue_key_required_with_pattern(
        self, workflow: WorkflowDef
    ) -> None:
        """issue_key input is required and has Jira key pattern."""
        ik = workflow.inputs["issue_key"]
        assert ik.required is True
        assert ik.pattern == r"^[A-Z]+-\d+$"

    def test_config_valid(self, workflow: WorkflowDef) -> None:
        """Workflow config has correct checkpoint prefix."""
        assert workflow.config.checkpoint_prefix == "validate-deploy-status"
        assert workflow.config.worktree is False


class TestStateChannels:
    """Test 2: State channels declared with correct reducers."""

    def test_declares_required_channels(self, workflow: WorkflowDef) -> None:
        """Sub-DAG declares issue_data, ci_status, deploy_status channels."""
        assert "issue_data" in workflow.state
        assert "ci_status" in workflow.state
        assert "deploy_status" in workflow.state


class TestOutputContract:
    """Test 3: Outputs contract matches parent workflow expectations."""

    def test_declares_output_contract(self, workflow: WorkflowDef) -> None:
        """Sub-DAG declares structured outputs for parent workflow."""
        assert "deploy_status" in workflow.outputs
        assert "repo" in workflow.outputs
        assert "pipeline" in workflow.outputs


class TestDispatchMode:
    """Test 4: Dispatch configuration matches local execution requirement."""

    def test_dispatch_local(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        """All nodes in deploy-status use local dispatch (no remote Opus)."""
        for node_id, node in nodes_by_id.items():
            if node.type == "bash":
                # Bash nodes are implicitly local
                assert node.dispatch is None or node.dispatch == DispatchMode.LOCAL
            elif node.type == "prompt":
                # No prompts should be in this local-dispatch sub-DAG
                pytest.fail(f"Node {node_id} is a prompt but should be bash for local dispatch")


class TestSkillPaths:
    """Test 5: Skill invocations reference real skill directories.

    GW-5356: the prior TestUnifiedRouterUsage enshrined aspirational
    `issues/`, `ci/`, and `vcs/` router aliases that were never implemented.
    The live skills live at `jira/`, `concourse/`, and `bitbucket/` directly.
    """

    def test_uses_real_skill_paths(self, workflow: WorkflowDef) -> None:
        with open(WORKFLOW_PATH, 'r') as f:
            content = f.read()
        assert "~/.claude/skills/jira/" in content
        # This workflow uses Concourse directly for CI status.
        assert "~/.claude/skills/concourse/" in content
        # Aspirational alias dirs never shipped; make sure nothing references them.
        assert "skills/issues/" not in content
        assert "skills/ci/" not in content
