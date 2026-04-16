"""Tests for checkpoint namespacing for sub-DAGs."""
import pytest
from pathlib import Path
from dag_executor.checkpoint import CheckpointStore, CheckpointMetadata, NodeCheckpoint


class TestCheckpointNamespacing:
    """Test checkpoint namespacing for sub-DAG hierarchy."""

    def test_flat_checkpoints_unchanged(self, tmp_path: Path) -> None:
        """Flat checkpoints (no parent_ns) work unchanged (backwards compat)."""
        store = CheckpointStore(str(tmp_path))
        
        # Save without parent_ns
        metadata = CheckpointMetadata(
            workflow_name="test-workflow",
            run_id="run-123",
            started_at="2024-01-01T00:00:00Z",
            inputs={},
            status="running"
        )
        store.save_metadata("test-workflow", "run-123", metadata)
        
        # Load without parent_ns
        loaded = store.load_metadata("test-workflow", "run-123")
        assert loaded is not None
        assert loaded.workflow_name == "test-workflow"
        assert loaded.run_id == "run-123"
        
        # Verify flat directory structure
        checkpoint_dir = tmp_path / "test-workflow-run-123"
        assert checkpoint_dir.exists()
        assert (checkpoint_dir / "meta.json").exists()

    def test_nested_checkpoint_with_parent_ns(self, tmp_path: Path) -> None:
        """Sub-DAG checkpoints nested under parent."""
        store = CheckpointStore(str(tmp_path))
        
        # Save parent checkpoint
        parent_metadata = CheckpointMetadata(
            workflow_name="work",
            run_id="parent-abc",
            started_at="2024-01-01T00:00:00Z",
            inputs={},
            status="running"
        )
        store.save_metadata("work", "parent-abc", parent_metadata)
        
        # Save child checkpoint with parent_ns
        child_metadata = CheckpointMetadata(
            workflow_name="implement",
            run_id="child-def",
            started_at="2024-01-01T00:01:00Z",
            inputs={},
            status="running"
        )
        store.save_metadata("implement", "child-def", child_metadata, parent_ns="work-parent-abc")
        
        # Verify nested directory structure
        parent_dir = tmp_path / "work-parent-abc"
        child_dir = parent_dir / "sub" / "implement-child-def"
        assert child_dir.exists()
        assert (child_dir / "meta.json").exists()
        
        # Load child checkpoint with parent_ns
        loaded_child = store.load_metadata("implement", "child-def", parent_ns="work-parent-abc")
        assert loaded_child is not None
        assert loaded_child.workflow_name == "implement"

    def test_parent_resume_discovers_children(self, tmp_path: Path) -> None:
        """Parent resume discovers and restores child checkpoint hierarchy."""
        store = CheckpointStore(str(tmp_path))
        
        # Create parent checkpoint
        parent_ns = "work-parent-xyz"
        parent_dir = tmp_path / parent_ns
        parent_dir.mkdir()
        
        # Create multiple child checkpoints
        child_names = ["implement-child-1", "validate-child-2", "review-child-3"]
        sub_dir = parent_dir / "sub"
        sub_dir.mkdir()
        
        for child_name in child_names:
            child_dir = sub_dir / child_name
            child_dir.mkdir()
            # Create a checkpoint file to mark it as valid
            (child_dir / "meta.json").write_text('{"workflow_name": "test"}')
        
        # List children
        children = store.list_children(parent_ns)
        assert len(children) == 3
        assert "implement-child-1" in children
        assert "validate-child-2" in children
        assert "review-child-3" in children
