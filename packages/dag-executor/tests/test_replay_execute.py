"""Unit tests for execute_replay() function."""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest

from dag_executor.checkpoint import CheckpointMetadata, CheckpointStore, NodeCheckpoint
from dag_executor.replay import execute_replay
from dag_executor.schema import NodeDef, NodeStatus, WorkflowDef, WorkflowConfig


@pytest.fixture
def sample_workflow() -> WorkflowDef:
    """Create a simple linear workflow for testing."""
    return WorkflowDef(
        name="test_workflow",
        nodes=[
            NodeDef(id="step1", name="step1", type="python", params={"code": "print('1')"}),
            NodeDef(id="step2", name="step2", type="python", params={"code": "print('2')"}, depends_on=["step1"]),
            NodeDef(id="step3", name="step3", type="python", params={"code": "print('3')"}, depends_on=["step2"]),
        ],
        config=WorkflowConfig(checkpoint_prefix="/tmp/test_checkpoints"),
    )


@pytest.fixture
def checkpoint_store_with_run(tmp_path: Path) -> tuple[CheckpointStore, str, WorkflowDef]:
    """Create a checkpoint store with a completed run."""
    store = CheckpointStore(str(tmp_path))
    workflow_name = "test_workflow"
    run_id = "20260420-120000"
    
    # Save metadata
    meta = CheckpointMetadata(
        workflow_name=workflow_name,
        run_id=run_id,
        started_at=datetime.now(timezone.utc).isoformat(),
        inputs={"input_key": "input_value"},
        status="completed",
    )
    store.save_metadata(workflow_name, run_id, meta)
    
    # Save node checkpoints for all three steps
    from dag_executor.schema import NodeResult
    for node_id in ["step1", "step2", "step3"]:
        result = NodeResult(
            node_id=node_id,
            status=NodeStatus.COMPLETED,
            output={f"{node_id}_output": f"{node_id}_value"},
            error=None,
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        store.save_node(workflow_name, run_id, node_id, result, f"hash_{node_id}", input_versions={})
    
    workflow = WorkflowDef(
        name=workflow_name,
        nodes=[
            NodeDef(id="step1", name="step1", type="python", params={"code": "print('1')"}),
            NodeDef(id="step2", name="step2", type="python", params={"code": "print('2')"}, depends_on=["step1"]),
            NodeDef(id="step3", name="step3", type="python", params={"code": "print('3')"}, depends_on=["step2"]),
        ],
        config=WorkflowConfig(checkpoint_prefix=str(tmp_path)),
    )
    
    return store, run_id, workflow


def test_execute_replay_happy_path(checkpoint_store_with_run: tuple[CheckpointStore, str, WorkflowDef]) -> None:
    """Test basic replay from a node."""
    store, run_id, workflow = checkpoint_store_with_run
    
    result = execute_replay(
        workflow_def=workflow,
        store=store,
        run_id=run_id,
        from_node="step2",
        overrides={},
    )
    
    assert "new_run_id" in result
    assert result["parent_run_id"] == run_id
    assert result["replayed_from"] == "step2"
    assert result["nodes_cleared"] == ["step3"]
    
    # Verify the new run exists
    new_run_id = result["new_run_id"]
    new_meta = store.load_metadata(workflow.name, new_run_id)
    assert new_meta is not None
    assert new_meta.workflow_name == workflow.name
    assert new_meta.run_id == new_run_id
    
    # Verify step1 still has checkpoint (before from_node)
    step1_checkpoint = store.load_node(workflow.name, new_run_id, "step1")
    assert step1_checkpoint is not None
    
    # Verify step2 still has checkpoint (from_node is kept)
    step2_checkpoint = store.load_node(workflow.name, new_run_id, "step2")
    assert step2_checkpoint is not None
    
    # Verify step3 checkpoint was cleared (after from_node)
    step3_checkpoint = store.load_node(workflow.name, new_run_id, "step3")
    assert step3_checkpoint is None


def test_execute_replay_with_overrides(checkpoint_store_with_run: tuple[CheckpointStore, str, WorkflowDef]) -> None:
    """Test replay with input overrides."""
    store, run_id, workflow = checkpoint_store_with_run
    
    overrides = {"new_key": "new_value", "input_key": "overridden_value"}
    
    result = execute_replay(
        workflow_def=workflow,
        store=store,
        run_id=run_id,
        from_node="step1",
        overrides=overrides,
    )
    
    # Verify overrides are applied to metadata
    new_run_id = result["new_run_id"]
    new_meta = store.load_metadata(workflow.name, new_run_id)
    assert new_meta is not None
    assert new_meta.inputs["new_key"] == "new_value"
    assert new_meta.inputs["input_key"] == "overridden_value"


def test_execute_replay_missing_run_id(checkpoint_store_with_run: tuple[CheckpointStore, str, WorkflowDef]) -> None:
    """Test that replay fails clearly when run_id doesn't exist."""
    store, _, workflow = checkpoint_store_with_run
    
    with pytest.raises(ValueError, match="No metadata found for run 'nonexistent'"):
        execute_replay(
            workflow_def=workflow,
            store=store,
            run_id="nonexistent",
            from_node="step1",
            overrides={},
        )


def test_execute_replay_invalid_from_node(checkpoint_store_with_run: tuple[CheckpointStore, str, WorkflowDef]) -> None:
    """Test that replay fails clearly when from_node is not in workflow."""
    store, run_id, workflow = checkpoint_store_with_run
    
    with pytest.raises(ValueError, match="Node 'invalid_node' not found in workflow"):
        execute_replay(
            workflow_def=workflow,
            store=store,
            run_id=run_id,
            from_node="invalid_node",
            overrides={},
        )


def test_execute_replay_preserves_original_run(checkpoint_store_with_run: tuple[CheckpointStore, str, WorkflowDef]) -> None:
    """Test that the original run directory is not modified."""
    store, run_id, workflow = checkpoint_store_with_run
    
    # Load original metadata before replay
    original_meta = store.load_metadata(workflow.name, run_id)
    assert original_meta is not None
    original_inputs = original_meta.inputs.copy()
    
    # Perform replay
    execute_replay(
        workflow_def=workflow,
        store=store,
        run_id=run_id,
        from_node="step2",
        overrides={"new_key": "new_value"},
    )
    
    # Verify original is unchanged
    original_meta_after = store.load_metadata(workflow.name, run_id)
    assert original_meta_after is not None
    assert original_meta_after.inputs == original_inputs
    
    # Original step3 checkpoint should still exist
    original_step3 = store.load_node(workflow.name, run_id, "step3")
    assert original_step3 is not None
