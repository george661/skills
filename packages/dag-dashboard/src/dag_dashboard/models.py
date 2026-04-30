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
    RESUMING = "resuming"


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
    trigger_source: Optional[str] = None

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
    tokens_input: Optional[int] = None
    tokens_output: Optional[int] = None
    tokens_cache: Optional[int] = None
    cache_hit: Optional[int] = 0


class WorkflowTotalsResponse(BaseModel):
    """Response model for workflow totals (cost, tokens, status counts)."""
    model_config = {"extra": "forbid"}

    cost: float
    tokens_input: int
    tokens_output: int
    tokens_cache: int
    total_tokens: int
    failed_nodes: int
    skipped_nodes: int


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
        """Validate content is non-empty.

        Chat messages are persisted verbatim to SQLite (parametrized) and
        echoed back via SSE (HTML-sanitized client-side by DOMPurify in
        chat-panel.js). They are NEVER fed to a shell. An earlier version
        of this validator rejected shell metacharacters (`$`, `(`, `:` in
        some builds, `\n`, etc.), which caused the "Talk to orchestrator"
        chat to HTTP 422 on realistic prompts like
        "variable reference $foo: how should I proceed?". The concern is
        misplaced here — we only guard structural invariants now.
        """
        stripped = v.strip()
        if not stripped:
            raise ValueError("content must contain at least 1 character after stripping whitespace")
        # Reject raw NULs (SQLite truncates, clients misrender).
        if "\x00" in v:
            raise ValueError("content must not contain NUL characters")
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


class InterruptResumeRequest(BaseModel):
    """Request model for interrupt resume with value injection."""
    model_config = {"extra": "forbid"}

    resume_value: Any
    decided_by: Optional[str] = None
    comment: Optional[str] = Field(default=None, max_length=1000)


class ChangeType(str, Enum):
    """Whitelisted change type values for state diff changes."""
    ADDED = "added"
    CHANGED = "changed"
    REMOVED = "removed"


class StateDiffChange(BaseModel):
    """Model for a single state diff change."""
    model_config = {"extra": "forbid"}

    key: str
    change_type: ChangeType
    before: Optional[Any] = None
    after: Optional[Any] = None


class NodeStateDiff(BaseModel):
    """Model for node state diff timeline entry."""
    model_config = {"extra": "forbid"}

    node_name: str
    node_id: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    changes: List[StateDiffChange]


# Checkpoint models for replay/inspect UI
class CheckpointRunSummary(BaseModel):
    """Summary of a workflow run from checkpoint metadata."""
    model_config = {"extra": "forbid"}

    run_id: str
    workflow_name: str
    started_at: str
    status: str
    node_count: int
    inputs: Dict[str, Any]


class CheckpointNodeSummary(BaseModel):
    """Summary of a node checkpoint (without full output)."""
    model_config = {"extra": "forbid"}

    node_id: str
    status: str
    started_at: str
    completed_at: str
    content_hash: str
    has_error: bool


class CheckpointRunDetail(BaseModel):
    """Full run details including node summaries."""
    model_config = {"extra": "forbid"}

    metadata: CheckpointRunSummary
    nodes: List[CheckpointNodeSummary]


class RerunRequest(BaseModel):
    """Request body for rerun endpoint."""
    model_config = {"extra": "forbid"}

    inputs: Optional[Dict[str, Any]] = None


class ReplayRequest(BaseModel):
    """Request body for replay endpoint."""
    model_config = {"extra": "forbid"}

    from_node: str = Field(min_length=1)
    overrides: Dict[str, Any] = Field(default_factory=dict)
    workflow_path: str = Field(min_length=1)


class ReplaySummary(BaseModel):
    """Response from replay execution."""
    model_config = {"extra": "forbid"}

    new_run_id: str
    parent_run_id: str
    replayed_from: str
    nodes_cleared: List[str]


# Draft models for workflow editing
class DraftListItem(BaseModel):
    """Single draft in list response."""
    model_config = {"extra": "forbid"}

    timestamp: str = Field(pattern=r"^[0-9]{8}T[0-9]{6}_[0-9]{6}Z$")
    size_bytes: int = Field(ge=0)
    publisher: Optional[str] = None


class DraftCreateRequest(BaseModel):
    """Request body for creating a draft."""
    model_config = {"extra": "forbid"}

    content: str = Field(min_length=1, max_length=2_097_152)


class DraftUpdateRequest(BaseModel):
    """Request body for updating a draft."""
    model_config = {"extra": "forbid"}

    content: str = Field(min_length=1, max_length=2_097_152)


class DraftCreateResponse(BaseModel):
    """Response from creating a draft."""
    model_config = {"extra": "forbid"}

    timestamp: str = Field(pattern=r"^[0-9]{8}T[0-9]{6}_[0-9]{6}Z$")


class DraftPublishResponse(BaseModel):
    """Response from publishing a draft."""
    model_config = {"extra": "forbid"}

    published_path: str
    source_timestamp: str


class DraftDiffRequest(BaseModel):
    """Request body for getting diff between draft and content."""
    model_config = {"extra": "forbid"}

    from_ts: str = Field(pattern=r"^[0-9]{8}T[0-9]{6}_[0-9]{6}Z$")
    to_content: str


class DraftDiffResponse(BaseModel):
    """Response from draft diff endpoint."""
    model_config = {"extra": "forbid"}

    unified_diff: str
    first_change_line: str


class CurrentDraftResponse(BaseModel):
    """Response from getting the current draft pointer."""
    model_config = {"extra": "forbid"}

    timestamp: str = Field(pattern=r"^[0-9]{8}T[0-9]{6}_[0-9]{6}Z$")


class CurrentDraftUpdateRequest(BaseModel):
    """Request body for updating the current draft pointer."""
    model_config = {"extra": "forbid"}

    timestamp: str = Field(pattern=r"^[0-9]{8}T[0-9]{6}_[0-9]{6}Z$")


class ValidationIssueOut(BaseModel):
    """Validation issue (error or warning) for a workflow node or workflow-level."""
    model_config = {"extra": "forbid"}

    severity: str = Field(..., description="Issue severity: 'error' or 'warning'")
    node_id: Optional[str] = Field(None, description="Node ID causing the issue (null for workflow-level issues)")
    code: str = Field(..., description="Machine-readable error code (e.g., 'required_field', 'cycle_detected')")
    message: str = Field(..., description="Human-readable error message")


class ValidateRequest(BaseModel):
    """Request body for POST /api/workflows/validate."""
    model_config = {"extra": "forbid"}

    yaml: str = Field(..., description="Workflow definition YAML string to validate")


class ValidateResponse(BaseModel):
    """Response body for POST /api/workflows/validate."""
    model_config = {"extra": "forbid"}

    errors: List[ValidationIssueOut] = Field(default_factory=list, description="Validation errors")
    warnings: List[ValidationIssueOut] = Field(default_factory=list, description="Validation warnings")
