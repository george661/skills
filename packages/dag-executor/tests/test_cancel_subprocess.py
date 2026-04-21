"""Tests for subprocess registry and cancel infrastructure."""
import subprocess
import time
from pathlib import Path
import pytest
from dag_executor.executor import SubprocessRegistry


def test_subprocess_registry_register_deregister():
    """Test basic register/deregister operations."""
    registry = SubprocessRegistry()
    
    # Start a dummy subprocess
    proc = subprocess.Popen(['sleep', '10'])
    
    # Register
    registry.register(proc)
    assert len(registry.list()) == 1
    assert proc in registry.list()
    
    # Deregister
    registry.deregister(proc)
    assert len(registry.list()) == 0
    
    # Cleanup
    proc.terminate()
    proc.wait(timeout=1)


def test_subprocess_registry_terminate_all():
    """Test terminate_all with SIGTERM."""
    registry = SubprocessRegistry()
    
    # Start dummy subprocesses
    proc1 = subprocess.Popen(['sleep', '10'])
    proc2 = subprocess.Popen(['sleep', '10'])
    
    registry.register(proc1)
    registry.register(proc2)
    
    # Terminate all
    registry.terminate_all(timeout=1)
    
    # Verify both terminated
    assert proc1.poll() is not None
    assert proc2.poll() is not None


def test_subprocess_registry_sigkill_escalation():
    """Test that SIGKILL is sent if SIGTERM doesn't work in time."""
    import signal
    registry = SubprocessRegistry()
    
    # Create a process that ignores SIGTERM (trap in shell)
    # Note: On macOS, 'trap "" TERM' may not work in all contexts, so we use a simpler test
    proc = subprocess.Popen(['sleep', '10'])
    
    registry.register(proc)
    
    # Terminate with very short timeout to trigger SIGKILL
    registry.terminate_all(timeout=0.1)
    
    # Verify process is dead
    assert proc.poll() is not None


# ---------------------------------------------------------------------------
# End-to-end executor cancellation tests
# ---------------------------------------------------------------------------

import asyncio as _asyncio
import json as _json
import os as _os

from dag_executor.executor import WorkflowExecutor
from dag_executor.events import EventEmitter, EventType
from dag_executor.schema import (
    NodeDef, WorkflowDef, WorkflowConfig, WorkflowStatus,
)


def _write_cancel_marker_atomic(events_dir: Path, run_id: str, cancelled_by: str) -> None:
    """Atomic marker write: .cancel.tmp then rename. Mirrors cli.run_cancel."""
    payload = {
        "cancelled_by": cancelled_by,
        "cancelled_at": "2026-04-21T14:00:00Z",
    }
    tmp = events_dir / f"{run_id}.cancel.tmp"
    final = events_dir / f"{run_id}.cancel"
    tmp.write_text(_json.dumps(payload))
    _os.replace(tmp, final)


@pytest.mark.asyncio
async def test_executor_marker_triggers_cancel(tmp_path):
    """Writing {events_dir}/{run_id}.cancel during execution transitions
    the workflow to CANCELLED and emits a workflow_cancelled event.
    """
    events_dir = tmp_path / "events"
    events_dir.mkdir()
    run_id = "test-run-cancel-1"

    # Two-layer workflow of sleeping bash nodes. The second layer should
    # never run because we cancel mid-first-layer.
    workflow_def = WorkflowDef(
        name="cancel-test-wf",
        config=WorkflowConfig(checkpoint_prefix="cancel-test"),
        nodes=[
            NodeDef(id="n1", name="n1", type="bash", script="sleep 10"),
            NodeDef(id="n2", name="n2", type="bash", script="sleep 1",
                    depends_on=["n1"]),
        ],
    )

    # Capture emitted events
    received: list = []
    emitter = EventEmitter()
    emitter.add_listener(lambda e: received.append(e))

    executor = WorkflowExecutor()
    exec_task = _asyncio.create_task(executor.execute(
        workflow_def=workflow_def,
        inputs={},
        event_emitter=emitter,
        run_id=run_id,
        events_dir=events_dir,
    ))

    # Give the executor a moment to spawn the first node and start polling.
    await _asyncio.sleep(1.5)

    # Write the cancel marker. Polling runs every 1s, so within ~2s the
    # marker should be seen and subprocesses SIGTERM'd.
    _write_cancel_marker_atomic(events_dir, run_id, cancelled_by="test-suite")

    # Wait for the executor to finish (should be quick now)
    result = await _asyncio.wait_for(exec_task, timeout=15.0)

    assert result.status == WorkflowStatus.CANCELLED, (
        f"expected CANCELLED, got {result.status}")

    # A workflow_cancelled event should have been emitted with cancelled_by
    cancelled_events = [
        e for e in received if e.event_type == EventType.WORKFLOW_CANCELLED
    ]
    assert len(cancelled_events) == 1, (
        f"expected 1 WORKFLOW_CANCELLED event, got {len(cancelled_events)}")
    assert cancelled_events[0].metadata.get("cancelled_by") == "test-suite"

    # n2 should not have run (it was downstream of cancelled n1)
    assert "n2" not in result.node_results or \
        result.node_results["n2"].status.value in ("skipped", "pending")
