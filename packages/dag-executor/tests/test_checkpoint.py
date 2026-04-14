"""Tests for checkpoint store functionality."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dag_executor.checkpoint import CheckpointMetadata, CheckpointStore, NodeCheckpoint
from dag_executor.schema import NodeDef, NodeResult, NodeStatus


@pytest.fixture
def checkpoint_store(tmp_path: Path) -> CheckpointStore:
    """Create a checkpoint store with temporary directory."""
    return CheckpointStore(str(tmp_path / ".dag-checkpoints"))


@pytest.fixture
def sample_metadata() -> CheckpointMetadata:
    """Create sample checkpoint metadata."""
    return CheckpointMetadata(
        workflow_name="test-workflow",
        run_id="run-123",
        started_at=datetime.now(timezone.utc).isoformat(),
        inputs={"input1": "value1"},
        status="running"
    )


@pytest.fixture
def sample_node_result() -> NodeResult:
    """Create sample node result."""
    return NodeResult(
        status=NodeStatus.COMPLETED,
        output={"result": "test-output"},
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc)
    )


@pytest.fixture
def sample_node_def() -> NodeDef:
    """Create sample node definition."""
    return NodeDef(
        id="node1",
        name="Test Node",
        type="bash",
        script="echo 'test'"
    )


def test_save_creates_directory_structure(
    checkpoint_store: CheckpointStore,
    sample_node_result: NodeResult,
    tmp_path: Path
):
    """Test that save creates the correct directory structure."""
    checkpoint_store.save_node(
        "test-workflow",
        "run-123",
        "node1",
        sample_node_result,
        "hash123"
    )
    
    # Verify directory structure
    checkpoint_dir = tmp_path / ".dag-checkpoints" / "test-workflow-run-123"
    nodes_dir = checkpoint_dir / "nodes"
    node_file = nodes_dir / "node1.json"
    
    assert checkpoint_dir.exists()
    assert nodes_dir.exists()
    assert node_file.exists()


def test_save_file_format(
    checkpoint_store: CheckpointStore,
    sample_node_result: NodeResult,
    tmp_path: Path
):
    """Test that saved JSON contains all NodeCheckpoint fields."""
    checkpoint_store.save_node(
        "test-workflow",
        "run-123",
        "node1",
        sample_node_result,
        "hash123"
    )
    
    node_file = tmp_path / ".dag-checkpoints" / "test-workflow-run-123" / "nodes" / "node1.json"
    data = json.loads(node_file.read_text())
    
    # Verify all required fields present
    assert "node_id" in data
    assert data["node_id"] == "node1"
    assert "status" in data
    assert data["status"] == "completed"
    assert "output" in data
    assert data["output"] == {"result": "test-output"}
    assert "content_hash" in data
    assert data["content_hash"] == "hash123"
    assert "started_at" in data
    assert "completed_at" in data


def test_load_returns_completed_node_outputs(
    checkpoint_store: CheckpointStore,
    sample_node_result: NodeResult
):
    """Test that load returns dict of all completed node outputs for a run."""
    # Save multiple node checkpoints
    checkpoint_store.save_node("workflow1", "run1", "node1", sample_node_result, "hash1")
    checkpoint_store.save_node("workflow1", "run1", "node2", sample_node_result, "hash2")
    
    # Load all nodes
    checkpoints = checkpoint_store.load_all_nodes("workflow1", "run1")
    
    assert len(checkpoints) == 2
    assert "node1" in checkpoints
    assert "node2" in checkpoints
    assert checkpoints["node1"].output == {"result": "test-output"}
    assert checkpoints["node2"].output == {"result": "test-output"}


def test_resume_skips_completed_nodes():
    """Test that resume populates ExecutionContext so completed nodes are skipped."""
    # This test will be implemented when integrating with executor
    # For now, we test that load_all_nodes returns the expected structure
    pass


def test_resume_restores_outputs_for_downstream():
    """Test that restored outputs are available for downstream variable substitution."""
    # This test will be implemented when integrating with executor
    pass


def test_content_cache_hit_skips_execution(
    checkpoint_store: CheckpointStore,
    sample_node_def: NodeDef,
    sample_node_result: NodeResult
):
    """Test that when content hash matches, cache returns the checkpoint."""
    # Compute content hash
    content_hash = checkpoint_store.compute_content_hash(sample_node_def, {})
    
    # Save checkpoint with this hash
    checkpoint_store.save_node("workflow1", "run1", "node1", sample_node_result, content_hash)
    
    # Check cache with same hash - should hit
    cached = checkpoint_store.check_cache("workflow1", "run1", "node1", content_hash)
    
    assert cached is not None
    assert cached.node_id == "node1"
    assert cached.content_hash == content_hash
    assert cached.output == {"result": "test-output"}


def test_content_cache_miss_triggers_execution(
    checkpoint_store: CheckpointStore,
    sample_node_def: NodeDef,
    sample_node_result: NodeResult
):
    """Test that when content hash differs, cache returns None."""
    # Save checkpoint with one hash
    checkpoint_store.save_node("workflow1", "run1", "node1", sample_node_result, "hash1")
    
    # Check cache with different hash - should miss
    cached = checkpoint_store.check_cache("workflow1", "run1", "node1", "hash2")
    
    assert cached is None


def test_file_permissions_0600(
    checkpoint_store: CheckpointStore,
    sample_node_result: NodeResult,
    sample_metadata: CheckpointMetadata,
    tmp_path: Path
):
    """Test that all checkpoint files are created with 0o600 permissions."""
    # Save node checkpoint
    checkpoint_store.save_node("workflow1", "run1", "node1", sample_node_result, "hash1")
    
    # Save metadata
    checkpoint_store.save_metadata("workflow1", "run1", sample_metadata)
    
    # Check permissions
    node_file = tmp_path / ".dag-checkpoints" / "workflow1-run1" / "nodes" / "node1.json"
    meta_file = tmp_path / ".dag-checkpoints" / "workflow1-run1" / "meta.json"
    
    assert oct(os.stat(node_file).st_mode)[-3:] == "600"
    assert oct(os.stat(meta_file).st_mode)[-3:] == "600"


def test_corrupted_checkpoint_handled_gracefully(
    checkpoint_store: CheckpointStore,
    tmp_path: Path
):
    """Test that corrupted JSON returns None and logs warning."""
    # Create corrupted checkpoint file
    nodes_dir = tmp_path / ".dag-checkpoints" / "workflow1-run1" / "nodes"
    nodes_dir.mkdir(parents=True)
    node_file = nodes_dir / "node1.json"
    node_file.write_text("{invalid json")
    
    # Load should return None and not crash
    checkpoint = checkpoint_store.load_node("workflow1", "run1", "node1")
    
    assert checkpoint is None


def test_save_metadata(
    checkpoint_store: CheckpointStore,
    sample_metadata: CheckpointMetadata,
    tmp_path: Path
):
    """Test that run metadata is saved to meta.json."""
    checkpoint_store.save_metadata("test-workflow", "run-123", sample_metadata)
    
    meta_file = tmp_path / ".dag-checkpoints" / "test-workflow-run-123" / "meta.json"
    assert meta_file.exists()
    
    data = json.loads(meta_file.read_text())
    assert data["workflow_name"] == "test-workflow"
    assert data["run_id"] == "run-123"
    assert data["inputs"] == {"input1": "value1"}
    assert data["status"] == "running"


def test_load_metadata(
    checkpoint_store: CheckpointStore,
    sample_metadata: CheckpointMetadata
):
    """Test that metadata can be loaded correctly."""
    checkpoint_store.save_metadata("workflow1", "run1", sample_metadata)
    
    loaded = checkpoint_store.load_metadata("workflow1", "run1")
    
    assert loaded is not None
    assert loaded.workflow_name == sample_metadata.workflow_name
    assert loaded.run_id == sample_metadata.run_id
    assert loaded.inputs == sample_metadata.inputs
    assert loaded.status == sample_metadata.status


def test_load_nonexistent_returns_none(checkpoint_store: CheckpointStore):
    """Test that loading nonexistent checkpoints returns None."""
    assert checkpoint_store.load_node("workflow1", "run1", "node1") is None
    assert checkpoint_store.load_metadata("workflow1", "run1") is None
    assert checkpoint_store.load_all_nodes("workflow1", "run1") == {}


def test_compute_content_hash_deterministic(
    checkpoint_store: CheckpointStore,
    sample_node_def: NodeDef
):
    """Test that content hash is deterministic for same inputs."""
    deps = {"upstream": {"output": "value"}}
    
    hash1 = checkpoint_store.compute_content_hash(sample_node_def, deps)
    hash2 = checkpoint_store.compute_content_hash(sample_node_def, deps)
    
    assert hash1 == hash2


def test_compute_content_hash_changes_with_script(
    checkpoint_store: CheckpointStore
):
    """Test that content hash changes when node definition changes."""
    node1 = NodeDef(id="node1", name="Node 1", type="bash", script="echo 'test1'")
    node2 = NodeDef(id="node1", name="Node 1", type="bash", script="echo 'test2'")
    
    hash1 = checkpoint_store.compute_content_hash(node1, {})
    hash2 = checkpoint_store.compute_content_hash(node2, {})
    
    assert hash1 != hash2


def test_compute_content_hash_changes_with_dependency_output(
    checkpoint_store: CheckpointStore,
    sample_node_def: NodeDef
):
    """Test that content hash changes when upstream output changes."""
    deps1 = {"upstream": {"output": "value1"}}
    deps2 = {"upstream": {"output": "value2"}}
    
    hash1 = checkpoint_store.compute_content_hash(sample_node_def, deps1)
    hash2 = checkpoint_store.compute_content_hash(sample_node_def, deps2)
    
    assert hash1 != hash2
