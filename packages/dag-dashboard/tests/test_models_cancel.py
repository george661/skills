"""Tests for cancel-related model enums."""
import pytest
from dag_dashboard.models import RunStatus


def test_models_run_status_cancelled_exists():
    """Verify RunStatus.CANCELLED already exists (not adding, just verifying)."""
    assert hasattr(RunStatus, 'CANCELLED')
    assert RunStatus.CANCELLED == "cancelled"
