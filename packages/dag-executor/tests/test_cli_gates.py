"""Tests for gates CLI subcommand."""
import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from dag_executor.gates import build_approval_resolved_event


def test_event_shape_matches_cli() -> None:
    """Verify canonical approval_resolved event shape."""
    # Canonical shape fixture
    expected_shape = {
        "event_type": "approval_resolved",
        "payload": {
            "run_id": str,
            "node_id": str,
            "resume_key": (str, type(None)),
            "decision": str,
            "resume_value": (bool, type(None)),
            "decided_by": str,
            "decided_at": str,
            "comment": (str, type(None)),
            "source": str
        },
        "created_at": str
    }
    
    # Build an event
    event = build_approval_resolved_event(
        run_id="test-run-id",
        node_id="test-node",
        resume_key="test-key",
        decision="approved",
        resume_value=True,
        decided_by="cli-user",
        comment="test comment",
        source="cli"
    )
    
    # Verify shape
    assert event["event_type"] == "approval_resolved"
    assert isinstance(event["payload"]["run_id"], str)
    assert isinstance(event["payload"]["node_id"], str)
    assert event["payload"]["resume_key"] in [None] or isinstance(event["payload"]["resume_key"], str)
    assert event["payload"]["decision"] in ["approved", "rejected"]
    assert event["payload"]["resume_value"] in [None, True, False]
    assert isinstance(event["payload"]["decided_by"], str)
    assert isinstance(event["payload"]["decided_at"], str)
    assert event["payload"]["comment"] in [None] or isinstance(event["payload"]["comment"], str)
    assert event["payload"]["source"] in ["cli", "api", "slack"]
    assert isinstance(event["created_at"], str)


def test_gates_approve_local_writes_both_events() -> None:
    """CLI approve in local mode should write both gate.decided and approval_resolved."""
    import tempfile
    from pathlib import Path
    from dag_executor.cli_gates import run_gates
    import sys
    from io import StringIO
    
    with tempfile.TemporaryDirectory() as tmpdir:
        events_dir = Path(tmpdir)
        run_id = "test-run"
        event_file = events_dir / f"{run_id}.ndjson"
        
        # Create empty event file
        event_file.touch()
        
        # Capture stdout to suppress output
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        
        try:
            run_gates([
                "approve",
                run_id,
                "test-node",
                "--events-dir", str(events_dir),
                "--comment", "LGTM"
            ])
        finally:
            sys.stdout = old_stdout
        
        # Read events
        with open(event_file) as f:
            events = [json.loads(line) for line in f]
        
        # Should have both events
        assert len(events) == 2
        assert events[0]["event_type"] == "gate.decided"
        assert events[1]["event_type"] == "approval_resolved"
        assert events[1]["payload"]["decision"] == "approved"
        assert events[1]["payload"]["source"] == "cli"


def test_gates_list_local_mode_requires_events_dir() -> None:
    """CLI list without events_dir or remote should error."""
    from dag_executor.cli_gates import run_gates
    import sys
    from io import StringIO
    
    # Capture stderr
    old_stderr = sys.stderr
    sys.stderr = StringIO()
    
    try:
        run_gates(["list", "test-run"])
        # Should exit with error
        assert False, "Should have exited"
    except SystemExit as e:
        assert e.code == 1
    finally:
        sys.stderr = old_stderr
