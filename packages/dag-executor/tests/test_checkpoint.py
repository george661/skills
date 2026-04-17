"""Tests for checkpoint store functionality."""
import json
import os
from pathlib import Path


from dag_executor.checkpoint import CheckpointMetadata, CheckpointStore
from dag_executor.schema import NodeDef, NodeResult, NodeStatus


def test_save_creates_directory_structure(
    checkpoint_store: CheckpointStore,
    checkpoint_node_result: NodeResult,
    tmp_path: Path
):
    """Test that save creates the correct directory structure."""
    checkpoint_store.save_node(
        "test-workflow",
        "run-123",
        "node1",
        checkpoint_node_result,
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
    checkpoint_node_result: NodeResult,
    tmp_path: Path
):
    """Test that saved JSON contains all NodeCheckpoint fields."""
    checkpoint_store.save_node(
        "test-workflow",
        "run-123",
        "node1",
        checkpoint_node_result,
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
    checkpoint_node_result: NodeResult
):
    """Test that load returns dict of all completed node outputs for a run."""
    # Save multiple node checkpoints
    checkpoint_store.save_node("workflow1", "run1", "node1", checkpoint_node_result, "hash1")
    checkpoint_store.save_node("workflow1", "run1", "node2", checkpoint_node_result, "hash2")
    
    # Load all nodes
    checkpoints = checkpoint_store.load_all_nodes("workflow1", "run1")
    
    assert len(checkpoints) == 2
    assert "node1" in checkpoints
    assert "node2" in checkpoints
    assert checkpoints["node1"].output == {"result": "test-output"}
    assert checkpoints["node2"].output == {"result": "test-output"}


def test_resume_skips_completed_nodes(checkpoint_store: CheckpointStore, tmp_path: Path):
    """Test that resume detects checkpoints and skips completed nodes."""
    from unittest.mock import patch
    from dag_executor import execute_workflow, resume_workflow, WorkflowDef, WorkflowConfig
    from dag_executor.runners.base import BaseRunner, RunnerContext

    # Create a multi-node workflow: node1 -> node2
    node1 = NodeDef(id="node1", name="Node 1", type="bash", script="echo step1")
    node2 = NodeDef(id="node2", name="Node 2", type="bash", script="echo step2", depends_on=["node1"])
    workflow_def = WorkflowDef(
        name="test-resume",
        config=WorkflowConfig(checkpoint_prefix="test"),
        nodes=[node1, node2]
    )

    # Mock runner that tracks execution calls
    execution_log = []

    class TrackingRunner(BaseRunner):
        def run(self, ctx: RunnerContext) -> NodeResult:
            execution_log.append(ctx.node_def.id)
            return NodeResult(status=NodeStatus.COMPLETED, output={"result": f"output-{ctx.node_def.id}"})

    # 1. Execute full workflow with checkpointing
    import uuid
    run_id = str(uuid.uuid4())
    with patch("dag_executor.executor.get_runner", return_value=TrackingRunner):
        result1 = execute_workflow(workflow_def, {}, checkpoint_store=checkpoint_store, run_id=run_id)

    assert result1.status.value == "completed"
    assert execution_log == ["node1", "node2"]
    execution_log.clear()

    # 2. Resume with same run_id - both nodes should be skipped (cache hit)
    with patch("dag_executor.executor.get_runner", return_value=TrackingRunner):
        result2 = resume_workflow("test-resume", run_id, checkpoint_store, workflow_def)

    assert result2.status.value == "completed"
    # Verify nodes were NOT re-executed (cache hit)
    assert len(execution_log) == 0, f"Expected no re-execution, but got: {execution_log}"


def test_resume_restores_outputs_for_downstream(checkpoint_store: CheckpointStore, tmp_path: Path):
    """Test that restored outputs are available for downstream variable substitution."""
    from unittest.mock import patch
    from dag_executor import execute_workflow, resume_workflow, WorkflowDef, WorkflowConfig
    from dag_executor.runners.base import BaseRunner, RunnerContext

    # Create workflow with variable substitution: node1 -> node2 (uses $node1.result)
    node1 = NodeDef(id="node1", name="Node 1", type="bash", script="echo upstream")
    node2 = NodeDef(id="node2", name="Node 2", type="bash", script="echo $node1.result", depends_on=["node1"])
    workflow_def = WorkflowDef(
        name="test-restore-outputs",
        config=WorkflowConfig(checkpoint_prefix="test"),
        nodes=[node1, node2]
    )

    # Mock runner that returns structured output
    class OutputRunner(BaseRunner):
        def run(self, ctx: RunnerContext) -> NodeResult:
            if ctx.node_def.id == "node1":
                return NodeResult(status=NodeStatus.COMPLETED, output={"result": "upstream-value"})
            # node2 should receive resolved variables from node1's cached output
            return NodeResult(status=NodeStatus.COMPLETED, output={"script": ctx.node_def.script})

    # 1. Execute full workflow
    import uuid
    run_id = str(uuid.uuid4())
    with patch("dag_executor.executor.get_runner", return_value=OutputRunner):
        result1 = execute_workflow(workflow_def, {}, checkpoint_store=checkpoint_store, run_id=run_id)

    assert result1.status.value == "completed"
    assert result1.node_results["node1"].output["result"] == "upstream-value"

    # 2. Resume workflow - node2 should access node1's restored output
    with patch("dag_executor.executor.get_runner", return_value=OutputRunner):
        result2 = resume_workflow("test-restore-outputs", run_id, checkpoint_store, workflow_def)

    assert result2.status.value == "completed"
    # Verify node1's output was restored and available
    assert result2.node_results["node1"].output["result"] == "upstream-value"


def test_content_cache_hit_skips_execution(
    checkpoint_store: CheckpointStore,
    sample_node_def: NodeDef,
    checkpoint_node_result: NodeResult
):
    """Test that when content hash matches, cache returns the checkpoint."""
    # Compute content hash
    content_hash = checkpoint_store.compute_content_hash(sample_node_def, {})
    
    # Save checkpoint with this hash
    checkpoint_store.save_node("workflow1", "run1", "node1", checkpoint_node_result, content_hash)
    
    # Check cache with same hash - should hit
    cached = checkpoint_store.check_cache("workflow1", "run1", "node1", content_hash)
    
    assert cached is not None
    assert cached.node_id == "node1"
    assert cached.content_hash == content_hash
    assert cached.output == {"result": "test-output"}


def test_content_cache_miss_triggers_execution(
    checkpoint_store: CheckpointStore,
    sample_node_def: NodeDef,
    checkpoint_node_result: NodeResult
):
    """Test that when content hash differs, cache returns None."""
    # Save checkpoint with one hash
    checkpoint_store.save_node("workflow1", "run1", "node1", checkpoint_node_result, "hash1")
    
    # Check cache with different hash - should miss
    cached = checkpoint_store.check_cache("workflow1", "run1", "node1", "hash2")
    
    assert cached is None


def test_file_permissions_0600(
    checkpoint_store: CheckpointStore,
    checkpoint_node_result: NodeResult,
    sample_metadata: CheckpointMetadata,
    tmp_path: Path
):
    """Test that all checkpoint files are created with 0o600 permissions."""
    # Save node checkpoint
    checkpoint_store.save_node("workflow1", "run1", "node1", checkpoint_node_result, "hash1")
    
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


# ---------------------------------------------------------------------------
# Version-based checkpoint tests (GW-5025)
# ---------------------------------------------------------------------------


def test_node_checkpoint_has_input_versions_field(
    checkpoint_store: CheckpointStore,
    checkpoint_node_result: NodeResult,
    tmp_path: Path
):
    """Test that NodeCheckpoint includes input_versions field with correct default."""
    # Save with input_versions
    input_versions = {"channel_a": 1, "channel_b": 2}
    checkpoint_store.save_node(
        "workflow1",
        "run1",
        "node1",
        checkpoint_node_result,
        "hash123",
        input_versions=input_versions
    )

    # Load and verify field is persisted
    checkpoint = checkpoint_store.load_node("workflow1", "run1", "node1")
    assert checkpoint is not None
    assert hasattr(checkpoint, "input_versions")
    assert checkpoint.input_versions == input_versions

    # Verify JSON structure
    node_file = tmp_path / ".dag-checkpoints" / "workflow1-run1" / "nodes" / "node1.json"
    data = json.loads(node_file.read_text())
    assert "input_versions" in data
    assert data["input_versions"] == input_versions


def test_save_node_with_input_versions_roundtrip(
    checkpoint_store: CheckpointStore,
    checkpoint_node_result: NodeResult
):
    """Test that save_node with input_versions parameter roundtrips correctly."""
    input_versions = {"state.user": 3, "state.config": 1}

    checkpoint_store.save_node(
        "workflow1",
        "run1",
        "node1",
        checkpoint_node_result,
        "hash123",
        input_versions=input_versions
    )

    loaded = checkpoint_store.load_node("workflow1", "run1", "node1")
    assert loaded is not None
    assert loaded.input_versions == input_versions


def test_check_versions_hit_when_all_versions_match(
    checkpoint_store: CheckpointStore,
    checkpoint_node_result: NodeResult
):
    """Test that check_versions returns cached result when all input versions match."""
    input_versions = {"channel_a": 5, "channel_b": 3}

    # Save checkpoint with specific versions
    checkpoint_store.save_node(
        "workflow1",
        "run1",
        "node1",
        checkpoint_node_result,
        "hash123",
        input_versions=input_versions
    )

    # Check with same versions - should hit
    cached = checkpoint_store.check_versions(
        "workflow1",
        "run1",
        "node1",
        current_versions={"channel_a": 5, "channel_b": 3}
    )

    assert cached is not None
    assert cached.node_id == "node1"
    assert cached.output == {"result": "test-output"}


def test_check_versions_miss_when_versions_differ(
    checkpoint_store: CheckpointStore,
    checkpoint_node_result: NodeResult
):
    """Test that check_versions returns None when versions mismatch."""
    input_versions = {"channel_a": 5, "channel_b": 3}

    # Save checkpoint with specific versions
    checkpoint_store.save_node(
        "workflow1",
        "run1",
        "node1",
        checkpoint_node_result,
        "hash123",
        input_versions=input_versions
    )

    # Check with different versions - should miss
    cached = checkpoint_store.check_versions(
        "workflow1",
        "run1",
        "node1",
        current_versions={"channel_a": 6, "channel_b": 3}  # channel_a version changed
    )

    assert cached is None


def test_check_versions_returns_none_for_empty_input_versions(
    checkpoint_store: CheckpointStore,
    checkpoint_node_result: NodeResult
):
    """Test that old checkpoints (empty input_versions) fall back to None."""
    # Save checkpoint without input_versions (simulates old checkpoint)
    checkpoint_store.save_node(
        "workflow1",
        "run1",
        "node1",
        checkpoint_node_result,
        "hash123"
        # no input_versions parameter
    )

    # Check with any versions - should return None (forces fallback to hash check)
    cached = checkpoint_store.check_versions(
        "workflow1",
        "run1",
        "node1",
        current_versions={"channel_a": 1}
    )

    assert cached is None


def test_old_checkpoint_without_input_versions_loads(
    checkpoint_store: CheckpointStore,
    tmp_path: Path
):
    """Test backwards compatibility: old checkpoints without input_versions still load."""
    # Manually create an old-style checkpoint JSON without input_versions field
    nodes_dir = tmp_path / ".dag-checkpoints" / "workflow1-run1" / "nodes"
    nodes_dir.mkdir(parents=True)
    node_file = nodes_dir / "node1.json"

    old_checkpoint_data = {
        "node_id": "node1",
        "status": "completed",
        "output": {"result": "old-output"},
        "error": None,
        "started_at": "2024-01-01T00:00:00Z",
        "completed_at": "2024-01-01T00:01:00Z",
        "content_hash": "oldhash123"
        # NOTE: no input_versions field
    }
    node_file.write_text(json.dumps(old_checkpoint_data, indent=2))

    # Load should succeed with default empty dict
    checkpoint = checkpoint_store.load_node("workflow1", "run1", "node1")
    assert checkpoint is not None
    assert checkpoint.node_id == "node1"
    assert checkpoint.output == {"result": "old-output"}
    assert checkpoint.input_versions == {}  # default value
