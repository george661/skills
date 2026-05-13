"""Tests for the validate-deploy-status.yaml workflow definition.

GW-5491: this workflow was rewritten from a 3-node bash pipeline into a
single contract-tier prompt node. The tests below validate the new shape:
* One prompt node referencing commands/validate-deploy-status.md as
  `prompt_file`
* `issue_key` input wired into `prompt_inputs.issue`
* All 7 declared output fields wired into workflow outputs

The runtime stub-LLM integration test lives at
tests/integration/test_validate_deploy_status_workflow.py.
"""
from pathlib import Path
from typing import Dict

import pytest

from dag_executor.parser import load_workflow
from dag_executor.schema import NodeDef, WorkflowDef


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
    """YAML parses without errors and has the expected single-node shape."""

    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        assert workflow.name == "Validate Deploy Status Sub-DAG"
        # GW-5491: one prompt node replaces the prior 3-bash-node pipeline.
        assert len(workflow.nodes) == 1

    def test_input_issue_key_required_with_pattern(
        self, workflow: WorkflowDef
    ) -> None:
        """issue_key input is required and has the Jira key pattern."""
        ik = workflow.inputs["issue_key"]
        assert ik.required is True
        assert ik.pattern == r"^[A-Z]+-\d+$"

    def test_config_valid(self, workflow: WorkflowDef) -> None:
        assert workflow.config.checkpoint_prefix == "validate-deploy-status"
        assert workflow.config.worktree is False


class TestPromptNodeWiring:
    """The single node is a prompt node wired to the contract command."""

    def test_node_is_prompt_type(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        node = nodes_by_id["check_deploy_status"]
        assert node.type == "prompt", (
            f"Expected prompt node, got {node.type}. The whole point of "
            f"GW-5491 was to replace the bash pipeline with a contract-tier "
            f"prompt node."
        )

    def test_prompt_file_points_at_contract_command(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        node = nodes_by_id["check_deploy_status"]
        assert node.prompt_file is not None
        assert "commands/validate-deploy-status.md" in node.prompt_file

    def test_prompt_inputs_wires_issue_key(
        self, nodes_by_id: Dict[str, NodeDef]
    ) -> None:
        """The workflow's issue_key input flows into prompt_inputs.issue,
        which promptc.render binds to {% $inputs.issue %} in the .md."""
        node = nodes_by_id["check_deploy_status"]
        assert node.prompt_inputs == {"issue": "${issue_key}"}


class TestOutputContract:
    """All 7 declared output fields surface as workflow outputs."""

    def test_declares_all_seven_output_fields(
        self, workflow: WorkflowDef
    ) -> None:
        for expected in (
            "deploy_status",
            "repo",
            "pipeline",
            "build_id",
            "build_status",
            "env_url",
            "deploy_gap_reason",
        ):
            assert expected in workflow.outputs, (
                f"Missing output {expected!r} on workflow"
            )

    def test_outputs_map_to_check_deploy_status_node(
        self, workflow: WorkflowDef
    ) -> None:
        for name, decl in workflow.outputs.items():
            assert decl.node == "check_deploy_status", (
                f"Output {name} sourced from {decl.node!r}, "
                f"expected check_deploy_status"
            )


class TestStateChannels:
    """State channels are declared for each output field with overwrite reducer."""

    def test_declares_per_output_state_channels(
        self, workflow: WorkflowDef
    ) -> None:
        for channel in (
            "deploy_status",
            "repo",
            "pipeline",
            "build_id",
            "build_status",
            "env_url",
            "deploy_gap_reason",
        ):
            assert channel in workflow.state, f"Missing state channel {channel!r}"


class TestNoLegacyBashPipeline:
    """Regression guard: the legacy bash pipeline must not creep back in."""

    def test_no_jira_skill_references(self) -> None:
        """The contract command itself fetches Jira context through its
        own {% run skill=... %} blocks at render time. The workflow YAML
        must NOT shell out to jira/concourse skills directly — that's
        what we deleted in GW-5491."""
        with open(WORKFLOW_PATH, "r") as f:
            content = f.read()
        assert "skills/jira/" not in content, (
            "Legacy bash pipeline reference detected — Jira fetching now "
            "happens inside commands/validate-deploy-status.md"
        )
        assert "skills/concourse/" not in content, (
            "Legacy bash pipeline reference detected — CI fetching now "
            "happens inside commands/validate-deploy-status.md"
        )
