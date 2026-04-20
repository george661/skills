"""Tests for Pydantic models and validation."""
import pytest
from pydantic import ValidationError

from dag_dashboard.models import (
    SortBy,
    RunStatus,
    WorkflowRunResponse,
    NodeExecutionResponse,
    PaginatedResponse,
    ListParams,
    GateDecision,
    GateDecisionRequest,
)


def test_sort_by_enum_values():
    """Test SortBy enum has whitelisted values."""
    assert SortBy.STARTED_AT == "started_at"
    assert SortBy.FINISHED_AT == "finished_at"
    # Note: total_cost removed from whitelist as column doesn't exist in schema


def test_run_status_enum_values():
    """Test RunStatus enum has whitelisted values."""
    assert RunStatus.RUNNING == "running"
    assert RunStatus.COMPLETED == "completed"
    assert RunStatus.FAILED == "failed"
    assert RunStatus.CANCELLED == "cancelled"


def test_workflow_run_response_valid():
    """Test WorkflowRunResponse accepts valid data."""
    data = {
        "id": "run-123",
        "workflow_name": "my-workflow",
        "status": "running",
        "started_at": "2026-04-17T12:00:00Z",
        "finished_at": None,
        "inputs": {"key": "value"},
        "outputs": None,
        "error": None,
    }
    run = WorkflowRunResponse(**data)
    assert run.id == "run-123"
    assert run.workflow_name == "my-workflow"
    assert run.status == "running"


def test_workflow_name_alphanumeric_hyphens_valid():
    """Test workflow_name accepts alphanumeric + hyphens."""
    data = {
        "id": "run-123",
        "workflow_name": "Valid-Workflow-123",
        "status": "running",
        "started_at": "2026-04-17T12:00:00Z",
    }
    run = WorkflowRunResponse(**data)
    assert run.workflow_name == "Valid-Workflow-123"


def test_workflow_name_rejects_special_chars():
    """Test workflow_name rejects non-alphanumeric characters."""
    data = {
        "id": "run-123",
        "workflow_name": "bad; DROP TABLE workflow_runs;",
        "status": "running",
        "started_at": "2026-04-17T12:00:00Z",
    }
    with pytest.raises(ValidationError) as exc_info:
        WorkflowRunResponse(**data)
    assert "workflow_name" in str(exc_info.value)


def test_node_execution_response_valid():
    """Test NodeExecutionResponse accepts valid data."""
    data = {
        "id": "node-123",
        "run_id": "run-123",
        "node_name": "step-1",
        "status": "completed",
        "started_at": "2026-04-17T12:00:00Z",
        "finished_at": "2026-04-17T12:05:00Z",
        "inputs": {"input": "data"},
        "outputs": {"output": "result"},
        "error": None,
    }
    node = NodeExecutionResponse(**data)
    assert node.id == "node-123"
    assert node.status == "completed"


def test_paginated_response_structure():
    """Test PaginatedResponse generic structure."""
    data = {
        "items": [{"id": "1"}, {"id": "2"}],
        "total": 10,
        "limit": 2,
        "offset": 0,
    }
    response = PaginatedResponse[dict](**data)
    assert len(response.items) == 2
    assert response.total == 10
    assert response.limit == 2
    assert response.offset == 0


def test_list_params_defaults():
    """Test ListParams has sensible defaults."""
    params = ListParams()
    assert params.limit == 50
    assert params.offset == 0
    assert params.status is None
    assert params.sort_by == SortBy.STARTED_AT


def test_list_params_limit_max():
    """Test ListParams enforces max limit of 100."""
    with pytest.raises(ValidationError) as exc_info:
        ListParams(limit=200)
    assert "limit" in str(exc_info.value)


def test_list_params_limit_min():
    """Test ListParams enforces min limit of 1."""
    with pytest.raises(ValidationError) as exc_info:
        ListParams(limit=0)
    assert "limit" in str(exc_info.value)


def test_list_params_offset_non_negative():
    """Test ListParams enforces non-negative offset."""
    with pytest.raises(ValidationError) as exc_info:
        ListParams(offset=-1)
    assert "offset" in str(exc_info.value)


def test_list_params_valid_sort_by():
    """Test ListParams accepts valid sortBy values."""
    params = ListParams(sort_by=SortBy.FINISHED_AT)
    assert params.sort_by == SortBy.FINISHED_AT


def test_list_params_valid_status():
    """Test ListParams accepts valid status values."""
    params = ListParams(status=RunStatus.COMPLETED)
    assert params.status == RunStatus.COMPLETED


def test_gate_decision_enum_values():
    """Test GateDecision enum has approved and rejected values."""
    assert GateDecision.APPROVED == "approved"
    assert GateDecision.REJECTED == "rejected"


def test_gate_decision_request_valid():
    """Test GateDecisionRequest accepts valid data."""
    data = {
        "decided_by": "alice",
        "comment": "Looks good to proceed",
    }
    request = GateDecisionRequest(**data)
    assert request.decided_by == "alice"
    assert request.comment == "Looks good to proceed"


def test_gate_decision_request_optional_fields():
    """Test GateDecisionRequest allows optional fields."""
    request = GateDecisionRequest()
    assert request.decided_by is None
    assert request.comment is None


def test_gate_decision_request_rejects_long_comment():
    """Test GateDecisionRequest rejects comment > 1000 chars."""
    data = {
        "decided_by": "alice",
        "comment": "x" * 1001,
    }
    with pytest.raises(ValidationError) as exc_info:
        GateDecisionRequest(**data)
    assert "comment" in str(exc_info.value)
