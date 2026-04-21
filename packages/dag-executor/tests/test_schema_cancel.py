"""Tests for cancel-related schema additions."""
import pytest
from dag_executor.schema import WorkflowStatus


def test_schema_cancelled_status():
    """Verify WorkflowStatus.CANCELLED exists and has correct value."""
    assert hasattr(WorkflowStatus, 'CANCELLED')
    assert WorkflowStatus.CANCELLED == "cancelled"
