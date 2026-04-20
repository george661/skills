"""Pydantic models for API responses and validation."""
import re
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel, Field, field_validator


class SortBy(str, Enum):
    """Whitelisted sortBy values for list queries."""
    STARTED_AT = "started_at"
    FINISHED_AT = "finished_at"
    DURATION = "duration"
    # Note: total_cost removed - column doesn't exist in schema
    # Note: Using finished_at to match actual schema column name


class RunStatus(str, Enum):
    """Whitelisted status values for workflow runs."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PENDING = "pending"


class WorkflowRunResponse(BaseModel):
    """Response model for workflow run data."""
    model_config = {"extra": "forbid"}

    id: str
    workflow_name: str
    status: str
    started_at: str
    finished_at: Optional[str] = None
    inputs: Optional[Dict[str, Any]] = None
    outputs: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    workflow_definition: Optional[str] = None

    @field_validator("workflow_name")
    @classmethod
    def validate_workflow_name(cls, v: str) -> str:
        """Validate workflow_name is alphanumeric + hyphens only."""
        if not re.match(r"^[a-zA-Z0-9-]+$", v):
            raise ValueError("workflow_name must contain only alphanumeric characters and hyphens")
        return v


class NodeExecutionResponse(BaseModel):
    """Response model for node execution data."""
    model_config = {"extra": "forbid"}

    id: str
    run_id: str
    node_name: str
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    inputs: Optional[Dict[str, Any]] = None
    outputs: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    depends_on: Optional[List[str]] = None
    model: Optional[str] = None
    tokens: Optional[int] = None
    cost: Optional[float] = None


T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""
    model_config = {"extra": "forbid"}

    items: List[T]
    total: int
    limit: int
    offset: int


class ListParams(BaseModel):
    """Query parameters for list operations."""
    model_config = {"extra": "forbid"}

    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    status: Optional[RunStatus] = None
    sort_by: SortBy = Field(default=SortBy.STARTED_AT)
    name: Optional[str] = None
    started_after: Optional[str] = None
    started_before: Optional[str] = None


class StatusSummary(BaseModel):
    """Status summary counts for dashboard."""
    model_config = {"extra": "forbid"}

    running: int
    completed: int
    failed: int
    pending: int
    cancelled: int


class ChatRole(str, Enum):
    """Whitelisted role values for chat messages."""
    OPERATOR = "operator"
    AGENT = "agent"
    SYSTEM = "system"


class ChatMessageRequest(BaseModel):
    """Request model for posting chat messages."""
    model_config = {"extra": "forbid"}

    content: str = Field(min_length=1, max_length=10000)
    operator_username: str

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        """Validate content doesn't contain shell metacharacters and isn't empty after stripping."""
        # Strip and check for empty
        stripped = v.strip()
        if not stripped:
            raise ValueError("content must contain at least 1 character after stripping whitespace")

        # Check for shell metacharacters
        dangerous_chars = [";", "&", "|", "`", "$", "(", ")", "<", ">", "\n", "\\"]
        for char in dangerous_chars:
            if char in v:
                raise ValueError(f"content must not contain shell metacharacters: {char}")

        return v


class GateDecision(str, Enum):
    """Whitelisted decision values for gate approvals."""
    APPROVED = "approved"
    REJECTED = "rejected"


class GateDecisionRequest(BaseModel):
    """Request model for gate approval/rejection."""
    model_config = {"extra": "forbid"}

    decided_by: Optional[str] = None
    comment: Optional[str] = Field(default=None, max_length=1000)
