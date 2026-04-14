"""Checkpoint store for workflow state persistence and resume."""
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

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
    """
    node_id: str
    status: NodeStatus
    output: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    started_at: str
    completed_at: str
    content_hash: str


class CheckpointMetadata(BaseModel):
    """Metadata for a workflow run checkpoint.
    
    Attributes:
        workflow_name: Name of the workflow
        run_id: Unique run identifier
        started_at: ISO timestamp when workflow started
        inputs: Workflow input values
        status: Current workflow status
    """
    workflow_name: str
    run_id: str
    started_at: str
    inputs: Dict[str, Any] = Field(default_factory=dict)
    status: str


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
    
    def _get_run_dir(self, workflow_name: str, run_id: str) -> Path:
        """Get checkpoint directory for a specific workflow run."""
        return self.checkpoint_prefix / f"{workflow_name}-{run_id}"
    
    def _get_nodes_dir(self, workflow_name: str, run_id: str) -> Path:
        """Get nodes directory for a specific workflow run."""
        return self._get_run_dir(workflow_name, run_id) / "nodes"
    
    def save_metadata(
        self,
        workflow_name: str,
        run_id: str,
        metadata: CheckpointMetadata
    ) -> None:
        """Save workflow run metadata.
        
        Args:
            workflow_name: Name of the workflow
            run_id: Unique run identifier
            metadata: Metadata to save
        """
        run_dir = self._get_run_dir(workflow_name, run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        
        meta_path = run_dir / "meta.json"
        meta_path.write_text(metadata.model_dump_json(indent=2))
        meta_path.chmod(0o600)
    
    def load_metadata(
        self,
        workflow_name: str,
        run_id: str
    ) -> Optional[CheckpointMetadata]:
        """Load workflow run metadata.
        
        Args:
            workflow_name: Name of the workflow
            run_id: Unique run identifier
        
        Returns:
            CheckpointMetadata if found, None if missing or corrupted
        """
        meta_path = self._get_run_dir(workflow_name, run_id) / "meta.json"
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
        content_hash: str
    ) -> None:
        """Save node execution checkpoint.
        
        Args:
            workflow_name: Name of the workflow
            run_id: Unique run identifier
            node_id: Node identifier
            result: Node execution result
            content_hash: Content-addressed hash for caching
        """
        nodes_dir = self._get_nodes_dir(workflow_name, run_id)
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
            content_hash=content_hash
        )
        
        node_path = nodes_dir / f"{node_id}.json"
        node_path.write_text(checkpoint.model_dump_json(indent=2))
        node_path.chmod(0o600)
    
    def load_node(
        self,
        workflow_name: str,
        run_id: str,
        node_id: str
    ) -> Optional[NodeCheckpoint]:
        """Load node execution checkpoint.
        
        Args:
            workflow_name: Name of the workflow
            run_id: Unique run identifier
            node_id: Node identifier
        
        Returns:
            NodeCheckpoint if found, None if missing or corrupted
        """
        node_path = self._get_nodes_dir(workflow_name, run_id) / f"{node_id}.json"
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
