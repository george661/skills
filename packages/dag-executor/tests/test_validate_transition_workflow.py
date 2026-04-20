"""Tests for the validate-transition.yaml workflow definition."""
from pathlib import Path
from typing import Dict
import pytest
from dag_executor.parser import load_workflow
from dag_executor.schema import WorkflowDef, NodeDef

WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "validate-transition.yaml"
)

@pytest.fixture
def workflow() -> WorkflowDef:
    return load_workflow(WORKFLOW_PATH)

@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    return {n.id: n for n in workflow.nodes}

class TestWorkflowParsing:
    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        assert workflow.name == "Validate Transition Sub-DAG"
        assert len(workflow.nodes) >= 2

    def test_input_issue_key_required(self, workflow: WorkflowDef) -> None:
        assert workflow.inputs["issue_key"].required is True
        assert workflow.inputs["verdict"].required is True

class TestStateChannels:
    def test_declares_required_channels(self, workflow: WorkflowDef) -> None:
        assert "transition_result" in workflow.state

class TestOutputContract:
    def test_declares_output_contract(self, workflow: WorkflowDef) -> None:
        assert "transitioned" in workflow.outputs
        assert "new_status" in workflow.outputs

class TestDispatchMode:
    def test_uses_inline_opus(self, nodes_by_id: Dict[str, NodeDef]) -> None:
        prompt_nodes = [n for n in nodes_by_id.values() if n.type == "prompt"]
        assert len(prompt_nodes) > 0
        opus_nodes = [n for n in prompt_nodes if n.model == "opus"]
        assert len(opus_nodes) > 0
