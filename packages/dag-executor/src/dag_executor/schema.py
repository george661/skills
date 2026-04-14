"""Pydantic v2 models for DAG executor workflow definitions."""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class NodeStatus(str, Enum):
    """Execution status of a workflow node."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowStatus(str, Enum):
    """Overall execution status of a workflow."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


class NodeResult(BaseModel):
    """Result of a node execution."""
    status: NodeStatus
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class Node(BaseModel):
    """A single node in a workflow DAG."""
    id: str = Field(..., description="Unique node identifier")
    name: str = Field(..., description="Human-readable node name")
    runner: str = Field(..., description="Runner type (e.g., 'bash', 'python', 'http')")
    inputs: Dict[str, Any] = Field(default_factory=dict, description="Node input parameters")
    depends_on: List[str] = Field(default_factory=list, description="List of node IDs this node depends on")
    status: NodeStatus = Field(default=NodeStatus.PENDING, description="Current execution status")
    result: Optional[NodeResult] = Field(default=None, description="Execution result when completed")


class Workflow(BaseModel):
    """A complete workflow definition with nodes and execution state."""
    id: str = Field(..., description="Unique workflow identifier")
    name: str = Field(..., description="Human-readable workflow name")
    nodes: List[Node] = Field(..., description="List of nodes in the workflow")
    status: WorkflowStatus = Field(default=WorkflowStatus.PENDING, description="Overall workflow status")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional workflow metadata")
