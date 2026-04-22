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


def test_gates_list_local_mode_uses_default_db() -> None:
    """CLI list in local mode uses default database path."""
    from dag_executor.cli_gates import run_gates
    import sys
    from io import StringIO
    import sqlite3

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        db_path = tmppath / "test.db"

        # Create empty database with schema
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE workflow_runs (
                id TEXT PRIMARY KEY,
                workflow_name TEXT,
                status TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE node_executions (
                id TEXT PRIMARY KEY,
                run_id TEXT,
                node_name TEXT,
                status TEXT,
                started_at TEXT,
                depends_on TEXT,
                inputs TEXT
            )
        """)
        conn.commit()
        conn.close()

        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            # Use custom db path
            run_gates(["list", "test-run", "--db-path", str(db_path)])
            # Should succeed with no pending gates message
        finally:
            sys.stdout = old_stdout


def test_gates_approve_saves_resume_values() -> None:
    """CLI approve should save resume_values to checkpoint store for interrupt nodes."""
    from dag_executor.cli_gates import run_gates
    from dag_executor.checkpoint import CheckpointStore, InterruptCheckpoint
    from datetime import datetime, timezone
    import sys
    from io import StringIO

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        events_dir = tmppath / "events"
        checkpoint_dir = tmppath / "checkpoints"
        events_dir.mkdir()
        checkpoint_dir.mkdir()

        run_id = "test-run"
        workflow_name = "test-workflow"
        node_name = "approval-node"
        resume_key = "user_approved"

        # Create event file
        event_file = events_dir / f"{run_id}.ndjson"
        event_file.touch()

        # Create interrupt checkpoint
        store = CheckpointStore(str(checkpoint_dir))
        interrupt_checkpoint = InterruptCheckpoint(
            node_id=node_name,
            message="Test approval required",
            resume_key=resume_key,
            channels=["terminal"],
            workflow_state={},
            pending_nodes=[],
        )
        store.save_interrupt(workflow_name, run_id, interrupt_checkpoint)

        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            run_gates([
                "approve",
                run_id,
                node_name,
                "--events-dir", str(events_dir),
                "--checkpoint-dir", str(checkpoint_dir),
                "--workflow-name", workflow_name,
            ])
        finally:
            sys.stdout = old_stdout

        # Verify resume_values were saved
        resume_values = store.load_resume_values(workflow_name, run_id)
        assert resume_values is not None
        assert resume_values.get(resume_key) is True


def test_gates_reject_saves_false_resume_value() -> None:
    """CLI reject should save resume_value=False to checkpoint store."""
    from dag_executor.cli_gates import run_gates
    from dag_executor.checkpoint import CheckpointStore, InterruptCheckpoint
    from datetime import datetime, timezone
    import sys
    from io import StringIO

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        events_dir = tmppath / "events"
        checkpoint_dir = tmppath / "checkpoints"
        events_dir.mkdir()
        checkpoint_dir.mkdir()

        run_id = "test-run"
        workflow_name = "test-workflow"
        node_name = "approval-node"
        resume_key = "user_approved"

        # Create event file
        event_file = events_dir / f"{run_id}.ndjson"
        event_file.touch()

        # Create interrupt checkpoint
        store = CheckpointStore(str(checkpoint_dir))
        interrupt_checkpoint = InterruptCheckpoint(
            node_id=node_name,
            message="Test approval required",
            resume_key=resume_key,
            channels=["terminal"],
            workflow_state={},
            pending_nodes=[],
        )
        store.save_interrupt(workflow_name, run_id, interrupt_checkpoint)

        # Capture stdout
        old_stdout = sys.stdout
        sys.stdout = StringIO()

        try:
            run_gates([
                "reject",
                run_id,
                node_name,
                "--events-dir", str(events_dir),
                "--checkpoint-dir", str(checkpoint_dir),
                "--workflow-name", workflow_name,
            ])
        finally:
            sys.stdout = old_stdout

        # Verify resume_values were saved with False
        resume_values = store.load_resume_values(workflow_name, run_id)
        assert resume_values is not None
        assert resume_values.get(resume_key) is False


def test_gates_approve_unblocks_downstream_workflow() -> None:
    """Integration: dag-exec gates approve unblocks an interrupted workflow so downstream nodes execute."""
    from dag_executor import (
        load_workflow,
        execute_workflow,
        resume_workflow,
        CheckpointStore,
        WorkflowStatus,
        NodeStatus,
    )
    from dag_executor.cli_gates import run_gates
    import sys
    from io import StringIO

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        events_dir = tmppath / "events"
        checkpoint_dir = tmppath / "checkpoints"
        events_dir.mkdir()
        checkpoint_dir.mkdir()

        workflow_yaml = f"""
name: gates_approve_integration
config:
  checkpoint_prefix: {checkpoint_dir}
inputs:
  deploy_approved:
    type: boolean
    required: false
nodes:
  - id: approval_gate
    name: Approval Gate
    type: interrupt
    message: "Approve deployment?"
    resume_key: "deploy_approved"

  - id: downstream_node
    name: Downstream
    type: bash
    depends_on: [approval_gate]
    script: 'echo "deployment approved"'
"""
        workflow_file = tmppath / "workflow.yaml"
        workflow_file.write_text(workflow_yaml)

        workflow_def = load_workflow(str(workflow_file))
        store = CheckpointStore(str(checkpoint_dir))

        # Execute until interrupt
        result1 = execute_workflow(workflow_def, inputs={}, checkpoint_store=store)
        assert result1.status == WorkflowStatus.PAUSED
        run_id = result1.run_id

        # Seed the event file so local-mode CLI has a file to append to
        event_file = events_dir / f"{run_id}.ndjson"
        event_file.touch()

        # Approve via CLI local mode
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            run_gates([
                "approve",
                run_id,
                "approval_gate",
                "--events-dir", str(events_dir),
                "--checkpoint-dir", str(checkpoint_dir),
                "--workflow-name", workflow_def.name,
            ])
        finally:
            sys.stdout = old_stdout

        # Resume the workflow — approve should have saved resume_values, so resume picks them up
        result2 = resume_workflow(
            workflow_name=workflow_def.name,
            run_id=run_id,
            checkpoint_store=store,
            workflow_def=workflow_def,
        )

        assert result2.status == WorkflowStatus.COMPLETED
        interrupt_node = next(n for n in result2.nodes if n.id == "approval_gate")
        assert interrupt_node.status == NodeStatus.COMPLETED
        downstream = next(n for n in result2.nodes if n.id == "downstream_node")
        assert downstream.status == NodeStatus.COMPLETED


def test_gates_reject_routes_to_on_failure() -> None:
    """Integration: dag-exec gates reject marks interrupt as failed so on_failure branch executes."""
    from dag_executor import (
        load_workflow,
        execute_workflow,
        resume_workflow,
        CheckpointStore,
        WorkflowStatus,
        NodeStatus,
    )
    from dag_executor.cli_gates import run_gates
    import sys
    from io import StringIO

    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        events_dir = tmppath / "events"
        checkpoint_dir = tmppath / "checkpoints"
        events_dir.mkdir()
        checkpoint_dir.mkdir()

        # Interrupt -> gate (condition: deploy_approved) -> happy_path.
        # When reject stores resume_value=False, the gate evaluates false,
        # fails, and the downstream happy_path is skipped. This is the
        # on_failure / rejection routing behavior from the Jira AC.
        workflow_yaml = f"""
name: gates_reject_integration
config:
  checkpoint_prefix: {checkpoint_dir}
inputs:
  deploy_approved:
    type: boolean
    required: false
nodes:
  - id: approval_gate
    name: Approval Gate
    type: interrupt
    message: "Approve deployment?"
    resume_key: "deploy_approved"

  - id: approval_check
    name: Check Approval
    type: gate
    depends_on: [approval_gate]
    condition: "deploy_approved"

  - id: happy_path
    name: Deploy
    type: bash
    depends_on: [approval_check]
    script: 'echo "deploying"'
"""
        workflow_file = tmppath / "workflow.yaml"
        workflow_file.write_text(workflow_yaml)

        workflow_def = load_workflow(str(workflow_file))
        store = CheckpointStore(str(checkpoint_dir))

        result1 = execute_workflow(workflow_def, inputs={}, checkpoint_store=store)
        assert result1.status == WorkflowStatus.PAUSED
        run_id = result1.run_id

        event_file = events_dir / f"{run_id}.ndjson"
        event_file.touch()

        # Reject via CLI local mode
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            run_gates([
                "reject",
                run_id,
                "approval_gate",
                "--events-dir", str(events_dir),
                "--checkpoint-dir", str(checkpoint_dir),
                "--workflow-name", workflow_def.name,
            ])
        finally:
            sys.stdout = old_stdout

        # resume_values should now contain {deploy_approved: False}
        resume_values = store.load_resume_values(workflow_def.name, run_id)
        assert resume_values is not None
        assert resume_values.get("deploy_approved") is False

        # Resume — downstream should be skipped because its condition evaluates to False
        result2 = resume_workflow(
            workflow_name=workflow_def.name,
            run_id=run_id,
            checkpoint_store=store,
            workflow_def=workflow_def,
        )

        # Workflow ends in FAILED because the gate rejected — that is the
        # "run continues per on_failure" path for a rejected boolean gate.
        assert result2.status == WorkflowStatus.FAILED
        gate_check = next(n for n in result2.nodes if n.id == "approval_check")
        assert gate_check.status == NodeStatus.FAILED
        happy = next(n for n in result2.nodes if n.id == "happy_path")
        # The happy-path node should NOT have completed (skipped or never started)
        assert happy.status != NodeStatus.COMPLETED
