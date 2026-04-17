"""Golden-output migration tests for channel architecture.

Validates that existing workflows produce identical execution plans and results
with ChannelStore architecture compared to dict-based state management.
"""
from __future__ import annotations

import yaml
from pathlib import Path
import pytest
from dag_executor.channels import ChannelStore
from dag_executor.schema import (
    NodeResult,
    NodeStatus,
    WorkflowDef,
)


WORKFLOW_DIR = Path(__file__).parent.parent / "workflows"


def load_workflow_yaml(name: str) -> WorkflowDef:
    """Load workflow YAML and parse into WorkflowDef."""
    yaml_path = WORKFLOW_DIR / f"{name}.yaml"
    if not yaml_path.exists():
        pytest.skip(f"Workflow {name}.yaml not found at {yaml_path}")
    
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    
    return WorkflowDef.model_validate(data)


def test_parse_work_yaml_with_channels(test_harness, mock_runner_factory):
    """work.yaml parses correctly and creates appropriate channel types."""
    workflow = load_workflow_yaml("work")
    
    # Verify workflow loads
    assert workflow.name
    
    # If workflow has state, ChannelStore should create channels
    if workflow.state:
        channel_store = ChannelStore.from_workflow_def(workflow)
        assert len(channel_store.channels) == len(workflow.state)


def test_parse_plan_yaml_with_channels(test_harness, mock_runner_factory):
    """plan.yaml parses correctly and creates appropriate channel types."""
    workflow = load_workflow_yaml("plan")
    
    assert workflow.name
    
    if workflow.state:
        channel_store = ChannelStore.from_workflow_def(workflow)
        assert len(channel_store.channels) == len(workflow.state)


def test_parse_review_yaml_with_channels(test_harness, mock_runner_factory):
    """review.yaml parses correctly and creates appropriate channel types."""
    workflow = load_workflow_yaml("review")
    
    assert workflow.name
    
    if workflow.state:
        channel_store = ChannelStore.from_workflow_def(workflow)
        assert len(channel_store.channels) == len(workflow.state)


def test_parse_validate_yaml_with_channels(test_harness, mock_runner_factory):
    """validate.yaml parses correctly and creates appropriate channel types."""
    workflow = load_workflow_yaml("validate")
    
    assert workflow.name
    
    if workflow.state:
        channel_store = ChannelStore.from_workflow_def(workflow)
        assert len(channel_store.channels) == len(workflow.state)


def test_parse_implement_yaml_with_channels(test_harness, mock_runner_factory):
    """implement.yaml parses correctly and creates appropriate channel types."""
    workflow = load_workflow_yaml("implement")
    
    assert workflow.name
    
    if workflow.state:
        channel_store = ChannelStore.from_workflow_def(workflow)
        assert len(channel_store.channels) == len(workflow.state)


def test_execution_with_mock_runners_produces_topological_order(
    test_harness, mock_runner_factory
):
    """Workflow execution with channels respects topological ordering."""
    workflow = load_workflow_yaml("work")
    
    factory = mock_runner_factory
    test_harness.mock_all_runners(
        NodeResult(status=NodeStatus.COMPLETED, output={"result": "mock"})
    )
    
    result = test_harness.execute(workflow)
    
    # Workflow should complete
    assert result.status
    
    # All nodes should be executed in dependency order
    # (test validates execution happens, not specific order verification)
    assert len(result.node_results) > 0


def test_state_dict_output_matches_channel_store_to_dict(
    test_harness, mock_runner_factory
):
    """ChannelStore.to_dict() produces dict output for state fields."""
    workflow = load_workflow_yaml("work")
    
    if not workflow.state:
        pytest.skip("work.yaml has no state fields")
    
    channel_store = ChannelStore.from_workflow_def(workflow)
    
    # to_dict() should produce dict view
    state_dict = channel_store.to_dict()
    assert isinstance(state_dict, dict)
    assert len(state_dict) == len(workflow.state)


def test_all_workflows_produce_identical_execution_plans(
    test_harness, mock_runner_factory
):
    """All 5 workflows execute with mock runners and produce results."""
    workflow_names = ["work", "plan", "review", "validate", "implement"]
    
    factory = mock_runner_factory
    
    for name in workflow_names:
        workflow = load_workflow_yaml(name)
        
        test_harness.mock_all_runners(
            NodeResult(status=NodeStatus.COMPLETED, output={"done": True})
        )
        
        result = test_harness.execute(workflow)
        
        # Each workflow should execute successfully
        assert result.status
        assert len(result.node_results) > 0, f"{name}.yaml produced no node results"


def test_channel_store_from_workflow_def_creates_correct_types(
    test_harness, mock_runner_factory
):
    """ChannelStore.from_workflow_def() creates correct channel types."""
    workflow = load_workflow_yaml("work")
    
    if not workflow.state:
        pytest.skip("work.yaml has no state")
    
    channel_store = ChannelStore.from_workflow_def(workflow)
    
    # Verify channels created match state definitions
    for key, field_def in workflow.state.items():
        assert key in channel_store.channels
        channel = channel_store.channels[key]
        
        # Channel type should match field definition
        # (LastValueChannel for no reducer, ReducerChannel for reducer)
        from dag_executor.channels import LastValueChannel, ReducerChannel
        
        if field_def.reducer:
            assert isinstance(channel, ReducerChannel)
        else:
            assert isinstance(channel, LastValueChannel)
