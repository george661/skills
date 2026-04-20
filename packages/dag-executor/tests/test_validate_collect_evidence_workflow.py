"""Tests for the validate-collect-evidence.yaml workflow definition."""
from pathlib import Path
from typing import Dict
import pytest
from dag_executor.parser import load_workflow
from dag_executor.schema import WorkflowDef, NodeDef

WORKFLOW_PATH = str(
    Path(__file__).parent.parent / "workflows" / "validate-collect-evidence.yaml"
)

@pytest.fixture
def workflow() -> WorkflowDef:
    return load_workflow(WORKFLOW_PATH)

@pytest.fixture
def nodes_by_id(workflow: WorkflowDef) -> Dict[str, NodeDef]:
    return {n.id: n for n in workflow.nodes}

class TestWorkflowParsing:
    def test_parses_successfully(self, workflow: WorkflowDef) -> None:
        assert workflow.name == "Validate Collect Evidence Sub-DAG"
        assert len(workflow.nodes) >= 2

    def test_input_issue_key_required(self, workflow: WorkflowDef) -> None:
        assert workflow.inputs["issue_key"].required is True

class TestStateChannels:
    def test_declares_required_channels(self, workflow: WorkflowDef) -> None:
        assert "evidence" in workflow.state

class TestOutputContract:
    def test_declares_output_contract(self, workflow: WorkflowDef) -> None:
        assert "artifact_count" in workflow.outputs
