"""Tests for cancel-related event types."""
import pytest
from dag_executor.events import EventType


def test_events_workflow_cancelled_type():
    """Verify EventType.WORKFLOW_CANCELLED exists and has correct value."""
    assert hasattr(EventType, 'WORKFLOW_CANCELLED')
    assert EventType.WORKFLOW_CANCELLED == "workflow_cancelled"
