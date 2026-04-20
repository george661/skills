"""Checkpoint store for workflow state persistence and resume."""
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from dag_executor.schema import NodeDef, NodeResult, NodeStatus


logger = logging.getLogger(__name__)


class NodeCheckpoint(BaseModel):
    """Checkpoint data for a single node execution.

    Attributes:
        node_id: Unique node identifier
        status: Final execution status
        output: Node output dictionary (empty if failed)
        error: Error message if execution failed
        started_at: ISO timestamp when node started
        completed_at: ISO timestamp when node completed
        content_hash: SHA256 hash of node definition + dependency outputs
        input_versions: Channel version snapshot at execution time (for precise resume)
    """
    model_config = {"extra": "forbid"}

    node_id: str
    status: NodeStatus
    output: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    started_at: str
    completed_at: str
    content_hash: str
    input_versions: Dict[str, int] = Field(default_factory=dict)


class CheckpointMetadata(BaseModel):
    """Metadata for a workflow run checkpoint.

    Attributes:
        workflow_name: Name of the workflow
        run_id: Unique run identifier
        started_at: ISO timestamp when workflow started
        inputs: Workflow input values
        status: Current workflow status
    """
    model_config = {"extra": "forbid"}

    workflow_name: str
    run_id: str
    started_at: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    status: str


class InterruptCheckpoint(BaseModel):
    """Checkpoint data for an interrupt (human-in-the-loop pause).

    Attributes:
        node_id: ID of the interrupt node
        message: Message to display to the user
        resume_key: Key to inject resume value into workflow inputs
        channels: Channels to surface interrupt on
        timeout: Optional timeout in seconds
        workflow_state: Snapshot of workflow state at interrupt
        pending_nodes: List of node IDs that haven't executed yet
    """
    model_config = {"extra": "forbid"}

    node_id: str
    message: str
    resume_key: str
    channels: List[str] = Field(default_factory=lambda: ["terminal"])
    timeout: Optional[int] = None
    workflow_state: Dict[str, Any] = Field(default_factory=dict)
    pending_nodes: List[str] = Field(default_factory=list)


class CheckpointStore:
    """File-based checkpoint store for workflow state persistence.
    
    Directory structure:
        {checkpoint_prefix}/{workflow_name}-{run_id}/
            meta.json          # CheckpointMetadata
            nodes/
                {node_id}.json # NodeCheckpoint
    
    All files are created with 0o600 permissions (owner read/write only).
    """
    
    def __init__(self, checkpoint_prefix: str):
        """Initialize checkpoint store.
        
        Args:
            checkpoint_prefix: Base directory name for checkpoints
                             (from WorkflowConfig.checkpoint_prefix)
        """
        self.checkpoint_prefix = Path(checkpoint_prefix)
    
    def _get_run_dir(
        self, workflow_name: str, run_id: str, parent_ns: Optional[str] = None
    ) -> Path:
        """Get checkpoint directory for a specific workflow run.

        Args:
            workflow_name: Name of the workflow
            run_id: Unique run identifier
            parent_ns: Optional parent namespace for sub-DAG checkpoints

        Returns:
            Path to checkpoint directory
        """
        if parent_ns:
            # Nested structure for sub-DAGs: {prefix}/{parent_ns}/sub/{workflow_name}-{run_id}/
            return self.checkpoint_prefix / parent_ns / "sub" / f"{workflow_name}-{run_id}"
        else:
            # Flat structure for top-level workflows: {prefix}/{workflow_name}-{run_id}/
            return self.checkpoint_prefix / f"{workflow_name}-{run_id}"
    
    def _get_nodes_dir(
        self, workflow_name: str, run_id: str, parent_ns: Optional[str] = None
    ) -> Path:
        """Get nodes directory for a specific workflow run."""
        return self._get_run_dir(workflow_name, run_id, parent_ns) / "nodes"
    
    def save_metadata(
        self,
        workflow_name: str,
        run_id: str,
        metadata: CheckpointMetadata,
        parent_ns: Optional[str] = None
    ) -> None:
        """Save workflow run metadata.

        Args:
            workflow_name: Name of the workflow
            run_id: Unique run identifier
            metadata: Metadata to save
            parent_ns: Optional parent namespace for sub-DAG checkpoints
        """
        run_dir = self._get_run_dir(workflow_name, run_id, parent_ns)
        run_dir.mkdir(parents=True, exist_ok=True)

        meta_path = run_dir / "meta.json"
        meta_path.write_text(metadata.model_dump_json(indent=2))
        meta_path.chmod(0o600)
    
    def load_metadata(
        self,
        workflow_name: str,
        run_id: str,
        parent_ns: Optional[str] = None
    ) -> Optional[CheckpointMetadata]:
        """Load workflow run metadata.

        Args:
            workflow_name: Name of the workflow
            run_id: Unique run identifier
            parent_ns: Optional parent namespace for sub-DAG checkpoints

        Returns:
            CheckpointMetadata if found, None if missing or corrupted
        """
        meta_path = self._get_run_dir(workflow_name, run_id, parent_ns) / "meta.json"
        if not meta_path.exists():
            return None

        try:
            data = json.loads(meta_path.read_text())
            return CheckpointMetadata.model_validate(data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Corrupted checkpoint metadata at {meta_path}: {e}")
            return None
    
    def save_node(
        self,
        workflow_name: str,
        run_id: str,
        node_id: str,
        result: NodeResult,
        content_hash: str,
        parent_ns: Optional[str] = None,
        input_versions: Optional[Dict[str, int]] = None
    ) -> None:
        """Save node execution checkpoint.

        Args:
            workflow_name: Name of the workflow
            run_id: Unique run identifier
            node_id: Node identifier
            result: Node execution result
            content_hash: Content-addressed hash for caching
            parent_ns: Optional parent namespace for sub-DAG checkpoints
            input_versions: Channel version snapshot at execution time
        """
        nodes_dir = self._get_nodes_dir(workflow_name, run_id, parent_ns)
        nodes_dir.mkdir(parents=True, exist_ok=True)

        # Convert datetime objects to ISO format strings
        started_at_str = (
            result.started_at.isoformat() if result.started_at
            else datetime.now(timezone.utc).isoformat()
        )
        completed_at_str = (
            result.completed_at.isoformat() if result.completed_at
            else datetime.now(timezone.utc).isoformat()
        )

        checkpoint = NodeCheckpoint(
            node_id=node_id,
            status=result.status,
            output=result.output or {},
            error=result.error,
            started_at=started_at_str,
            completed_at=completed_at_str,
            content_hash=content_hash,
            input_versions=input_versions or {}
        )

        node_path = nodes_dir / f"{node_id}.json"
        node_path.write_text(checkpoint.model_dump_json(indent=2))
        node_path.chmod(0o600)
    
    def load_node(
        self,
        workflow_name: str,
        run_id: str,
        node_id: str,
        parent_ns: Optional[str] = None
    ) -> Optional[NodeCheckpoint]:
        """Load node execution checkpoint.

        Args:
            workflow_name: Name of the workflow
            run_id: Unique run identifier
            node_id: Node identifier
            parent_ns: Optional parent namespace for sub-DAG checkpoints

        Returns:
            NodeCheckpoint if found, None if missing or corrupted
        """
        node_path = self._get_nodes_dir(workflow_name, run_id, parent_ns) / f"{node_id}.json"
        if not node_path.exists():
            return None
        
        try:
            data = json.loads(node_path.read_text())
            return NodeCheckpoint.model_validate(data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Corrupted checkpoint at {node_path}: {e}")
            return None
    
    def load_all_nodes(
        self,
        workflow_name: str,
        run_id: str
    ) -> Dict[str, NodeCheckpoint]:
        """Load all node checkpoints for a workflow run.
        
        Args:
            workflow_name: Name of the workflow
            run_id: Unique run identifier
        
        Returns:
            Dict mapping node_id to NodeCheckpoint
        """
        nodes_dir = self._get_nodes_dir(workflow_name, run_id)
        if not nodes_dir.exists():
            return {}
        
        checkpoints = {}
        for node_file in nodes_dir.glob("*.json"):
            node_id = node_file.stem
            checkpoint = self.load_node(workflow_name, run_id, node_id)
            if checkpoint:
                checkpoints[node_id] = checkpoint
        
        return checkpoints
    
    def compute_content_hash(
        self,
        node_def: NodeDef,
        dependency_outputs: Dict[str, Any]
    ) -> str:
        """Compute content-addressed hash for cache invalidation.
        
        The hash includes:
        - Node definition fields (id, type, script/command/prompt/skill/condition, params, args)
        - Resolved dependency outputs (sorted by node ID)
        
        Args:
            node_def: Node definition
            dependency_outputs: Map of dependency node_id -> output dict
        
        Returns:
            SHA256 hash as hex string
        """
        # Extract relevant node definition fields
        node_data = {
            "id": node_def.id,
            "type": node_def.type,
            "script": node_def.script,
            "command": node_def.command,
            "prompt": node_def.prompt,
            "skill": node_def.skill,
            "condition": node_def.condition,
            "params": node_def.params,
            "args": node_def.args,
        }
        
        # Sort dependency outputs by key for deterministic hashing
        sorted_deps = {k: dependency_outputs[k] for k in sorted(dependency_outputs.keys())}
        
        # Combine into single dict
        hash_input = {
            "node": node_data,
            "dependencies": sorted_deps
        }
        
        # Compute SHA256 hash
        json_str = json.dumps(hash_input, sort_keys=True)
        return hashlib.sha256(json_str.encode()).hexdigest()
    
    def check_cache(
        self,
        workflow_name: str,
        run_id: str,
        node_id: str,
        content_hash: str
    ) -> Optional[NodeCheckpoint]:
        """Check if a cached result exists for the given content hash.

        Args:
            workflow_name: Name of the workflow
            run_id: Unique run identifier
            node_id: Node identifier
            content_hash: Content-addressed hash to check

        Returns:
            NodeCheckpoint if cache hit, None if cache miss
        """
        checkpoint = self.load_node(workflow_name, run_id, node_id)
        if checkpoint and checkpoint.content_hash == content_hash:
            return checkpoint
        return None

    def check_versions(
        self,
        workflow_name: str,
        run_id: str,
        node_id: str,
        current_versions: Dict[str, int]
    ) -> Optional[NodeCheckpoint]:
        """Check if a cached result exists with matching input channel versions.

        This is faster than check_cache (O(1) dict compare vs O(N) SHA256 hash).
        Returns None for old checkpoints without input_versions (forces fallback
        to content_hash check).

        Args:
            workflow_name: Name of the workflow
            run_id: Unique run identifier
            node_id: Node identifier
            current_versions: Current channel version snapshot

        Returns:
            NodeCheckpoint if all input versions match, None otherwise
        """
        checkpoint = self.load_node(workflow_name, run_id, node_id)
        if not checkpoint:
            return None

        # Old checkpoints without input_versions fall back to hash check
        if not checkpoint.input_versions:
            return None

        # Compare versions - all must match for cache hit
        if checkpoint.input_versions == current_versions:
            return checkpoint

        return None

    def list_runs(self, workflow_name: str) -> List[str]:
        """Scan checkpoint prefix for directories matching a workflow name.

        Looks for directories named ``{workflow_name}-*`` under
        ``checkpoint_prefix`` and extracts the run IDs.

        Args:
            workflow_name: Name of the workflow to list runs for

        Returns:
            Sorted list of run ID strings
        """
        if not self.checkpoint_prefix.exists():
            return []

        prefix = f"{workflow_name}-"
        run_ids: List[str] = []
        for entry in self.checkpoint_prefix.iterdir():
            if entry.is_dir() and entry.name.startswith(prefix):
                run_id = entry.name[len(prefix):]
                if run_id:
                    run_ids.append(run_id)
        return sorted(run_ids)

    def clear_nodes_after(
        self,
        workflow_name: str,
        run_id: str,
        after_node_id: str,
        node_order: List[str],
    ) -> List[str]:
        """Delete node checkpoint files after a given position in execution order.

        Args:
            workflow_name: Name of the workflow
            run_id: Run identifier
            after_node_id: Node ID to start clearing *after*
            node_order: Ordered list of node IDs representing execution order

        Returns:
            List of node IDs whose checkpoint files were deleted
        """
        try:
            pos = node_order.index(after_node_id)
        except ValueError:
            logger.warning(
                "Node '%s' not found in node_order; nothing cleared", after_node_id
            )
            return []

        nodes_to_clear = node_order[pos + 1:]
        nodes_dir = self._get_nodes_dir(workflow_name, run_id)
        cleared: List[str] = []
        for node_id in nodes_to_clear:
            node_path = nodes_dir / f"{node_id}.json"
            if node_path.exists():
                node_path.unlink()
                cleared.append(node_id)
        return cleared

    def save_interrupt(
        self,
        workflow_name: str,
        run_id: str,
        interrupt: InterruptCheckpoint
    ) -> None:
        """Save interrupt checkpoint.

        Args:
            workflow_name: Name of the workflow
            run_id: Unique run identifier
            interrupt: Interrupt checkpoint to save
        """
        run_dir = self._get_run_dir(workflow_name, run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        interrupt_path = run_dir / "interrupt.json"
        interrupt_path.write_text(interrupt.model_dump_json(indent=2))
        interrupt_path.chmod(0o600)

    def load_interrupt(
        self,
        workflow_name: str,
        run_id: str
    ) -> Optional[InterruptCheckpoint]:
        """Load interrupt checkpoint.

        Args:
            workflow_name: Name of the workflow
            run_id: Unique run identifier

        Returns:
            InterruptCheckpoint if found, None if missing or corrupted
        """
        interrupt_path = self._get_run_dir(workflow_name, run_id) / "interrupt.json"
        if not interrupt_path.exists():
            return None

        try:
            data = json.loads(interrupt_path.read_text())
            return InterruptCheckpoint.model_validate(data)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Corrupted interrupt checkpoint at {interrupt_path}: {e}")
            return None

    def save_resume_values(
        self,
        workflow_name: str,
        run_id: str,
        values: Dict[str, Any]
    ) -> None:
        """Save resume values for workflow resume.

        Args:
            workflow_name: Name of the workflow
            run_id: Unique run identifier
            values: Resume values to inject on workflow resume
        """
        run_dir = self._get_run_dir(workflow_name, run_id)
        run_dir.mkdir(parents=True, exist_ok=True)

        resume_path = run_dir / "resume_values.json"
        resume_path.write_text(json.dumps(values, indent=2))
        resume_path.chmod(0o600)

    def load_resume_values(
        self,
        workflow_name: str,
        run_id: str
    ) -> Dict[str, Any]:
        """Load resume values for workflow resume.

        Args:
            workflow_name: Name of the workflow
            run_id: Unique run identifier

        Returns:
            Resume values dict if found, empty dict if missing or corrupted
        """
        resume_path = self._get_run_dir(workflow_name, run_id) / "resume_values.json"
        if not resume_path.exists():
            return {}

        try:
            data = json.loads(resume_path.read_text())
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"Corrupted resume values at {resume_path}: {e}")
            return {}

    def list_children(self, parent_ns: str) -> List[str]:
        """List child checkpoint directories for a parent workflow.

        Args:
            parent_ns: Parent namespace (e.g., "work-run-abc")

        Returns:
            List of child checkpoint directory names (e.g., ["implement-run-def", "validate-run-ghi"])
        """
        parent_dir = self.checkpoint_prefix / parent_ns / "sub"
        if not parent_dir.exists():
            return []

        children = []
        for child_dir in parent_dir.iterdir():
            if child_dir.is_dir() and (child_dir / "meta.json").exists():
                children.append(child_dir.name)

        return children
