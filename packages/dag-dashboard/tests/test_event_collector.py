"""Tests for event collector."""
import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List

import pytest

from dag_dashboard.broadcast import Broadcaster
from dag_dashboard.database import init_db
from dag_dashboard.event_collector import EventCollector


@pytest.fixture
def test_db(tmp_path: Path) -> Path:
    """Create test database."""
    db_path = tmp_path / "test.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def events_dir(tmp_path: Path) -> Path:
    """Create events directory."""
    events_dir = tmp_path / "dag-events"
    events_dir.mkdir()
    return events_dir


@pytest.fixture
async def broadcaster() -> Broadcaster:
    """Create broadcaster."""
    return Broadcaster()


def get_persisted_events(db_path: Path, run_id: str) -> List[Dict[str, Any]]:
    """Retrieve persisted events from database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute(
            "SELECT event_type, payload, created_at FROM events WHERE run_id = ? ORDER BY created_at",
            (run_id,)
        )
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


def test_collector_initialization(test_db: Path, events_dir: Path) -> None:
    """Test that collector initializes without errors."""
    loop = asyncio.new_event_loop()
    broadcaster = Broadcaster()
    
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )
    
    assert collector is not None
    loop.close()


@pytest.mark.asyncio
async def test_collector_persists_event(test_db: Path, events_dir: Path, broadcaster: Broadcaster) -> None:
    """Test that collector persists NDJSON events to SQLite."""
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )
    
    # Start collector
    collector.start()
    
    try:
        # Write NDJSON file
        run_id = "test_run_123"
        ndjson_file = events_dir / f"{run_id}.ndjson"
        
        # WorkflowEvent shape: no "payload" field, use metadata instead
        event = {
            "workflow_name": "test_workflow",
            "event_type": "node.started",
            "node_id": "step1",
            "metadata": {"custom_field": "test_value"},
            "created_at": "2026-04-17T12:00:00Z"
        }

        with open(ndjson_file, "w") as f:
            f.write(json.dumps(event) + "\n")

        # Give watchdog time to process
        await asyncio.sleep(0.3)

        # Verify event was persisted
        persisted = get_persisted_events(test_db, run_id)
        assert len(persisted) == 1
        assert persisted[0]["event_type"] == "node.started"
        # Payload now stores full event_data
        payload_data = json.loads(persisted[0]["payload"])
        assert payload_data["node_id"] == "step1"
        assert payload_data["metadata"]["custom_field"] == "test_value"
        
    finally:
        collector.stop()


@pytest.mark.asyncio
async def test_collector_broadcasts_event(test_db: Path, events_dir: Path, broadcaster: Broadcaster) -> None:
    """Test that collector broadcasts events to subscribers."""
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )
    
    collector.start()
    
    try:
        run_id = "test_run_456"
        received_events: List[Dict[str, Any]] = []
        
        async def subscriber():
            async with broadcaster.subscribe(run_id) as queue:
                event = await asyncio.wait_for(queue.get(), timeout=2.0)
                received_events.append(event)
        
        # Start subscriber
        sub_task = asyncio.create_task(subscriber())
        await asyncio.sleep(0.05)
        
        # Write event
        ndjson_file = events_dir / f"{run_id}.ndjson"
        event = {
            "workflow_name": "test_workflow",
            "event_type": "workflow.started",
            "payload": json.dumps({"test": "data"}),
            "created_at": "2026-04-17T12:00:00Z"
        }
        
        with open(ndjson_file, "w") as f:
            f.write(json.dumps(event) + "\n")
        
        # Wait for event to be received
        await asyncio.wait_for(sub_task, timeout=2.0)
        
        assert len(received_events) == 1
        assert received_events[0]["event_type"] == "workflow.started"
        
    finally:
        collector.stop()


@pytest.mark.asyncio
async def test_collector_handles_malformed_json(test_db: Path, events_dir: Path, broadcaster: Broadcaster) -> None:
    """Test that malformed JSON lines are skipped with warning."""
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )
    
    collector.start()
    
    try:
        run_id = "test_run_malformed"
        ndjson_file = events_dir / f"{run_id}.ndjson"
        
        # Write valid event, malformed JSON, then another valid event
        with open(ndjson_file, "w") as f:
            valid_event_1 = {
                "workflow_name": "test_workflow",
                "event_type": "event1",
                "payload": json.dumps({}),
                "created_at": "2026-04-17T12:00:00Z"
            }
            f.write(json.dumps(valid_event_1) + "\n")
            f.write("{invalid json\n")  # Malformed
            valid_event_2 = {
                "workflow_name": "test_workflow",
                "event_type": "event2",
                "payload": json.dumps({}),
                "created_at": "2026-04-17T12:00:01Z"
            }
            f.write(json.dumps(valid_event_2) + "\n")
        
        await asyncio.sleep(0.3)
        
        # Only valid events should be persisted
        persisted = get_persisted_events(test_db, run_id)
        assert len(persisted) == 2
        assert persisted[0]["event_type"] == "event1"
        assert persisted[1]["event_type"] == "event2"
        
    finally:
        collector.stop()


@pytest.mark.asyncio
async def test_collector_handles_file_deletion(test_db: Path, events_dir: Path, broadcaster: Broadcaster) -> None:
    """Test that file deletion is handled gracefully (no crash)."""
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )

    collector.start()

    try:
        run_id = "test_run_deletion"
        ndjson_file = events_dir / f"{run_id}.ndjson"

        event1 = {
            "workflow_name": "test_workflow",
            "event_type": "event1",
            "payload": json.dumps({}),
            "created_at": "2026-04-17T12:00:00Z"
        }
        with open(ndjson_file, "w") as f:
            f.write(json.dumps(event1) + "\n")

        await asyncio.sleep(0.5)

        persisted_before = get_persisted_events(test_db, run_id)
        assert len(persisted_before) == 1
        assert persisted_before[0]["event_type"] == "event1"

        # Delete file — collector must not crash
        ndjson_file.unlink()
        await asyncio.sleep(0.3)

        # Collector is still running (didn't crash on deletion)
        assert collector.observer.is_alive()

    finally:
        collector.stop()


@pytest.mark.asyncio
async def test_collector_creates_workflow_runs_row(test_db: Path, events_dir: Path, broadcaster: Broadcaster) -> None:
    """Test that collector creates workflow_runs row for FK constraint."""
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )
    
    collector.start()
    
    try:
        run_id = "test_run_fk"
        ndjson_file = events_dir / f"{run_id}.ndjson"
        
        event = {
            "workflow_name": "my_workflow",
            "event_type": "workflow.started",
            "payload": json.dumps({}),
            "created_at": "2026-04-17T12:00:00Z"
        }
        
        with open(ndjson_file, "w") as f:
            f.write(json.dumps(event) + "\n")
        
        await asyncio.sleep(0.3)
        
        # Verify workflow_runs row was created
        conn = sqlite3.connect(test_db)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT id, workflow_name, status FROM workflow_runs WHERE id = ?", (run_id,))
            row = cursor.fetchone()
            
            assert row is not None
            assert row["id"] == run_id
            assert row["workflow_name"] == "my_workflow"
            assert row["status"] == "running"
        finally:
            conn.close()

    finally:
        collector.stop()


@pytest.mark.asyncio
async def test_node_progress_event_persisted(test_db: Path, events_dir: Path, broadcaster: Broadcaster) -> None:
    """Test that node_progress events with retry metadata are persisted correctly."""
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )

    collector.start()

    try:
        run_id = "test_run_node_progress"
        ndjson_file = events_dir / f"{run_id}.ndjson"

        # WorkflowEvent shape for node_progress with retry metadata
        event = {
            "workflow_name": "test_workflow",
            "event_type": "node_progress",
            "node_id": "fix_pr",
            "metadata": {
                "message": "Retry 2/3: waiting 5000ms before next attempt",
                "attempt": 2,
                "max_attempts": 3,
                "delay_ms": 5000,
                "last_error": "Connection timeout"
            },
            "timestamp": "2026-04-20T17:00:00Z"
        }

        with open(ndjson_file, "w") as f:
            f.write(json.dumps(event) + "\n")

        # Give watchdog time to process
        await asyncio.sleep(0.3)

        # Verify event was persisted with correct structure
        persisted = get_persisted_events(test_db, run_id)
        assert len(persisted) == 1
        assert persisted[0]["event_type"] == "node_progress"

        # Verify payload stores the full event as JSON string
        payload_str = persisted[0]["payload"]
        assert isinstance(payload_str, str)

        # Parse payload to access retry metadata
        payload_data = json.loads(payload_str)
        assert payload_data["node_id"] == "fix_pr"
        assert payload_data["metadata"]["attempt"] == 2
        assert payload_data["metadata"]["max_attempts"] == 3
        assert payload_data["metadata"]["delay_ms"] == 5000
        assert payload_data["metadata"]["last_error"] == "Connection timeout"

    finally:
        collector.stop()


@pytest.mark.asyncio
async def test_collector_persists_edge_traversed_event(test_db: Path, events_dir: Path, broadcaster: Broadcaster) -> None:
    """Test that collector persists EDGE_TRAVERSED events."""
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )

    collector.start()

    try:
        run_id = "test_run_edge"
        ndjson_file = events_dir / f"{run_id}.ndjson"

        # Write workflow_started first (required for foreign key)
        workflow_started = {
            "workflow_name": "conditional_workflow",
            "event_type": "workflow_started",
            "payload": {"workflow_definition": "nodes: []"},
            "created_at": "2026-04-20T12:00:00Z"
        }
        with open(ndjson_file, "w") as f:
            f.write(json.dumps(workflow_started) + "\n")

        await asyncio.sleep(0.2)

        # Write EDGE_TRAVERSED event
        edge_event = {
            "workflow_name": "conditional_workflow",
            "event_type": "edge_traversed",
            "payload": {
                "source_node_id": "review",
                "target_node_id": "merge",
                "edge_id": "review-merge-0",
                "edge_group_id": "abc123",
                "branch_set_id": "review",
                "taken": True,
                "condition": "review.verdict == 'approve'",
                "evaluated_value": True
            },
            "created_at": "2026-04-20T12:01:00Z"
        }

        with open(ndjson_file, "a") as f:
            f.write(json.dumps(edge_event) + "\n")

        await asyncio.sleep(0.3)

        # Verify event persisted
        events = get_persisted_events(test_db, run_id)
        edge_events = [e for e in events if e["event_type"] == "edge_traversed"]

        assert len(edge_events) == 1
        event_data = json.loads(edge_events[0]["payload"])
        payload = event_data["payload"]
        assert payload["edge_id"] == "review-merge-0"
        assert payload["taken"] is True

    finally:
        collector.stop()


@pytest.mark.asyncio
async def test_collector_broadcasts_edge_traversed_event(test_db: Path, events_dir: Path) -> None:
    """Test that collector broadcasts EDGE_TRAVERSED events to subscribers."""
    loop = asyncio.get_event_loop()
    broadcaster = Broadcaster()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )

    collector.start()

    run_id = "test_run_broadcast"

    try:
        async with broadcaster.subscribe(run_id) as queue:
            ndjson_file = events_dir / f"{run_id}.ndjson"

            # Write workflow_started
            workflow_started = {
                "workflow_name": "conditional_workflow",
                "event_type": "workflow_started",
                "payload": {"workflow_definition": "nodes: []"},
                "created_at": "2026-04-20T12:00:00Z"
            }
            with open(ndjson_file, "w") as f:
                f.write(json.dumps(workflow_started) + "\n")

            await asyncio.sleep(0.2)

            # Write EDGE_TRAVERSED event
            edge_event = {
                "workflow_name": "conditional_workflow",
                "event_type": "edge_traversed",
                "payload": {
                    "source_node_id": "review",
                    "target_node_id": "merge",
                    "edge_id": "review-merge-0",
                    "taken": True
                },
                "created_at": "2026-04-20T12:01:00Z"
            }

            with open(ndjson_file, "a") as f:
                f.write(json.dumps(edge_event) + "\n")

            await asyncio.sleep(0.3)

            # Collect events from queue
            broadcasted_events = []
            while not queue.empty():
                event = await queue.get()
                broadcasted_events.append(event)

            # Verify broadcast
            edge_events = [e for e in broadcasted_events if e["event_type"] == "edge_traversed"]
            assert len(edge_events) == 1

    finally:
        collector.stop()


@pytest.mark.asyncio
async def test_collector_persists_condition_evaluated_event(test_db: Path, events_dir: Path, broadcaster: Broadcaster) -> None:
    """Test that collector persists CONDITION_EVALUATED events."""
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )

    collector.start()

    try:
        run_id = "test_run_condition"
        ndjson_file = events_dir / f"{run_id}.ndjson"

        # Write workflow_started
        workflow_started = {
            "workflow_name": "conditional_workflow",
            "event_type": "workflow_started",
            "payload": {"workflow_definition": "nodes: []"},
            "created_at": "2026-04-20T12:00:00Z"
        }
        with open(ndjson_file, "w") as f:
            f.write(json.dumps(workflow_started) + "\n")

        await asyncio.sleep(0.2)

        # Write CONDITION_EVALUATED event
        condition_event = {
            "workflow_name": "conditional_workflow",
            "event_type": "condition_evaluated",
            "payload": {
                "source_node_id": "review",
                "target_node_id": "merge",
                "condition": "review.verdict == 'approve'",
                "evaluated_value": True,
                "edge_index": 0
            },
            "created_at": "2026-04-20T12:01:00Z"
        }

        with open(ndjson_file, "a") as f:
            f.write(json.dumps(condition_event) + "\n")

        await asyncio.sleep(0.3)

        # Verify event persisted
        events = get_persisted_events(test_db, run_id)
        condition_events = [e for e in events if e["event_type"] == "condition_evaluated"]

        assert len(condition_events) == 1
        event_data = json.loads(condition_events[0]["payload"])
        payload = event_data["payload"]
        assert payload["condition"] == "review.verdict == 'approve'"
        assert payload["evaluated_value"] is True

    finally:
        collector.stop()


@pytest.mark.asyncio
async def test_collector_persists_checkpoint_data(test_db: Path, events_dir: Path, broadcaster: Broadcaster) -> None:
    """Test that node_completed event with checkpoint metadata updates node_executions."""
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )

    collector.start()

    try:
        run_id = "checkpoint_test_run"
        ndjson_file = events_dir / f"{run_id}.ndjson"

        # First create a workflow_started event to initialize node_executions row
        workflow_started = {
            "workflow_name": "test_workflow",
            "event_type": "workflow_started",
            "metadata": {
                "workflow_definition": """
nodes:
  - name: process_data
    depends_on: []
"""
            },
            "created_at": "2026-04-20T12:00:00Z"
        }

        with open(ndjson_file, "w") as f:
            f.write(json.dumps(workflow_started) + "\n")

        await asyncio.sleep(0.3)

        # Now emit node_completed with checkpoint data
        # Note: node_id in events is run_id:node_name format
        node_completed = {
            "workflow_name": "test_workflow",
            "event_type": "node_completed",
            "node_id": f"{run_id}:process_data",
            "status": "completed",
            "metadata": {
                "state_diff": {"key": "value"},
                "content_hash": "a" * 64,
                "input_versions": {"channel_1": 1, "channel_2": 3}
            },
            "created_at": "2026-04-20T12:01:00Z"
        }

        with open(ndjson_file, "a") as f:
            f.write(json.dumps(node_completed) + "\n")

        await asyncio.sleep(0.3)

        # Verify checkpoint data was persisted to node_executions
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT content_hash, input_versions FROM node_executions WHERE node_name = ?",
            ("process_data",)
        )
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        content_hash, input_versions = row
        assert content_hash == "a" * 64
        assert json.loads(input_versions) == {"channel_1": 1, "channel_2": 3}

    finally:
        collector.stop()

@pytest.mark.asyncio
async def test_workflow_started_transitions_resuming_to_running(
    test_db: Path,
    events_dir: Path,
    broadcaster: Broadcaster
) -> None:
    """Test that workflow_started transitions resuming to running."""
    run_id = "test-resuming-run"
    workflow_name = "test-workflow"
    workflow_definition = '{"nodes": [{"id": "task1"}], "edges": []}'
    
    # Create run with status='resuming' and populated workflow_definition
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute(
        """
        INSERT INTO workflow_runs (id, workflow_name, status, started_at, workflow_definition)
        VALUES (?, ?, ?, datetime('now'), ?)
        """,
        (run_id, workflow_name, "resuming", workflow_definition)
    )
    conn.commit()
    conn.close()
    
    # Write workflow_started event
    event_file = events_dir / f"{run_id}.ndjson"
    event = {
        "event_type": "workflow_started",
        "created_at": "2024-01-01T12:00:00Z",
        "payload": json.dumps({
            "run_id": run_id,
            "workflow_name": workflow_name,
            "workflow_definition": workflow_definition
        })
    }
    event_file.write_text(json.dumps(event) + "\n")
    
    # Process event via collector
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )

    collector._process_file(event_file)  # Synchronous call

    # Verify status transitioned to running
    conn = sqlite3.connect(test_db)
    cursor = conn.cursor()
    cursor.execute("SELECT status FROM workflow_runs WHERE id = ?", (run_id,))
    row = cursor.fetchone()
    conn.close()

    assert row is not None
    assert row[0] == "running", f"Expected status 'running', got '{row[0]}'"


def test_event_collector_persists_parent_run_id_from_workflow_started_metadata(
    test_db: Path,
    events_dir: Path,
) -> None:
    """Sub-DAG workflow_started events should insert a child workflow_runs row
    with parent_run_id set from metadata.parent_run_id.
    """
    import sqlite3

    parent_run_id = "parent-root-1"
    sub_run_id = "child-sub-1"

    event_file = events_dir / f"{parent_run_id}.ndjson"
    event = {
        "workflow_name": "parent-workflow",
        "event_type": "workflow_started",
        "timestamp": "2026-04-22T12:00:00Z",
        "metadata": {
            "parent_run_id": parent_run_id,
            "run_id": sub_run_id,
            "workflow_name": "child-workflow",
        },
    }
    event_file.write_text(json.dumps(event) + "\n")

    loop = asyncio.new_event_loop()
    broadcaster = Broadcaster()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop,
    )
    try:
        collector._process_file(event_file)
    finally:
        loop.close()

    conn = sqlite3.connect(test_db)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, parent_run_id, workflow_name FROM workflow_runs WHERE id = ?",
            (sub_run_id,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    assert row is not None, f"Sub-DAG run {sub_run_id} not persisted"
    assert row[1] == parent_run_id
    assert row[2] == "child-workflow"


def test_event_collector_skips_self_referential_parent_run_id(
    test_db: Path,
    events_dir: Path,
    caplog,
) -> None:
    """If metadata.parent_run_id == metadata.run_id, the sub-DAG row is skipped
    and a warning is logged (defensive guard against malformed events)."""
    import logging
    import sqlite3

    same_id = "self-ref-1"
    event_file = events_dir / f"{same_id}.ndjson"
    event = {
        "workflow_name": "whatever",
        "event_type": "workflow_started",
        "timestamp": "2026-04-22T12:00:00Z",
        "metadata": {
            "parent_run_id": same_id,
            "run_id": same_id,
            "workflow_name": "whatever",
        },
    }
    event_file.write_text(json.dumps(event) + "\n")

    loop = asyncio.new_event_loop()
    broadcaster = Broadcaster()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop,
    )
    with caplog.at_level(logging.WARNING):
        try:
            collector._process_file(event_file)
        finally:
            loop.close()

    conn = sqlite3.connect(test_db)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT parent_run_id FROM workflow_runs WHERE id = ?",
            (same_id,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    # The row exists (main workflow insert) but parent_run_id stayed NULL
    assert row is not None
    assert row[0] is None
    assert any("self-referential" in record.message for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["cli", "api", "slack"])
async def test_collector_handles_approval_resolved_from_all_sources(
    test_db: Path,
    events_dir: Path,
    broadcaster: Broadcaster,
    source: str,
) -> None:
    """Test that approval_resolved events are handled identically regardless of source."""
    # Insert workflow run
    conn = sqlite3.connect(test_db)
    conn.execute(
        "INSERT INTO workflow_runs (id, workflow_name, status, started_at) VALUES (?, ?, ?, ?)",
        ("run-1", "test-wf", "running", "2026-04-22T12:00:00Z"),
    )
    conn.execute(
        "INSERT INTO node_executions (id, run_id, node_name, status) VALUES (?, ?, ?, ?)",
        ("run-1:gate-1", "run-1", "gate-1", "interrupted"),
    )
    conn.commit()
    conn.close()

    # Create event file with approval_resolved event
    event_file = events_dir / "run-1.ndjson"
    event = {
        "event_type": "approval_resolved",
        "payload": json.dumps({
            "node_name": "gate-1",
            "decision": "approved",
            "decided_by": "alice",
            "source": source,
        }),
        "created_at": "2026-04-22T12:05:00Z",
    }
    with open(event_file, "w") as f:
        f.write(json.dumps(event) + "\n")

    # Start collector
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop,
    )
    collector.start()

    try:
        # Wait for processing
        await asyncio.sleep(0.2)

        # Verify identical handling regardless of source
        # The event should be processed and no errors should occur
        conn = sqlite3.connect(test_db)
        cursor = conn.execute("SELECT status FROM node_executions WHERE id = ?", ("run-1:gate-1",))
        row = cursor.fetchone()
        conn.close()

        # Node should remain in interrupted state until workflow executor processes resume_values
        assert row is not None
        assert row[0] == "interrupted"
    finally:
        collector.stop()


@pytest.mark.asyncio
async def test_node_started_writes_model_to_node_executions(test_db: Path, events_dir: Path, broadcaster: Broadcaster):
    """node_started event with model='sonnet' writes to node_executions.model."""
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )

    collector.start()

    try:
        run_id = "test-run"
        ndjson_file = events_dir / f"{run_id}.ndjson"

        # Emit workflow_started to create the run and node_executions rows
        workflow_started = {
            "event_type": "workflow_started",
            "workflow_id": "test-workflow",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "metadata": {
                "workflow_definition": """
name: test-workflow
nodes:
  - name: node1
    type: prompt
"""
            }
        }

        # Emit node_started with model='sonnet'
        node_started = {
            "event_type": "node_started",
            "workflow_id": "test-workflow",
            "node_id": "node1",
            "model": "sonnet",
            "timestamp": "2026-01-01T00:00:01.000Z"
        }

        ndjson_file.write_text(
            json.dumps(workflow_started) + "\n" +
            json.dumps(node_started) + "\n"
        )

        # Wait for collector to process
        await asyncio.sleep(0.5)

        # Verify node_executions.model = 'sonnet'
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        cursor.execute("SELECT model, status FROM node_executions WHERE id = ?", (f"{run_id}:node1",))
        row = cursor.fetchone()
        conn.close()

        assert row is not None, "node_executions row not found"
        assert row[0] == "sonnet", f"Expected model='sonnet', got {row[0]}"
        assert row[1] == "running", f"Expected status='running', got {row[1]}"
    finally:
        collector.stop()


@pytest.mark.asyncio
async def test_node_completed_does_not_overwrite_model(test_db: Path, events_dir: Path, broadcaster: Broadcaster):
    """node_completed event does NOT overwrite node_executions.model (node_started writes it)."""
    loop = asyncio.get_event_loop()
    collector = EventCollector(
        events_dir=events_dir,
        db_path=test_db,
        broadcaster=broadcaster,
        loop=loop
    )

    collector.start()

    try:
        run_id = "test-run"
        ndjson_file = events_dir / f"{run_id}.ndjson"

        # Emit workflow_started
        workflow_started = {
            "event_type": "workflow_started",
            "workflow_id": "test-workflow",
            "timestamp": "2026-01-01T00:00:00.000Z",
            "metadata": {
                "workflow_definition": """
name: test-workflow
nodes:
  - name: node1
    type: prompt
"""
            }
        }

        # Emit node_started with model='opus'
        node_started = {
            "event_type": "node_started",
            "workflow_id": "test-workflow",
            "node_id": "node1",
            "model": "opus",
            "timestamp": "2026-01-01T00:00:01.000Z"
        }

        # Emit node_completed (no model field in metadata)
        node_completed = {
            "event_type": "node_completed",
            "workflow_id": "test-workflow",
            "node_id": "node1",
            "status": "success",
            "timestamp": "2026-01-01T00:00:02.000Z"
        }

        ndjson_file.write_text(
            json.dumps(workflow_started) + "\n" +
            json.dumps(node_started) + "\n" +
            json.dumps(node_completed) + "\n"
        )

        # Wait for collector to process
        await asyncio.sleep(0.5)

        # Verify model remains 'opus' (not overwritten by node_completed)
        conn = sqlite3.connect(test_db)
        cursor = conn.cursor()
        cursor.execute("SELECT model FROM node_executions WHERE id = ?", (f"{run_id}:node1",))
        row = cursor.fetchone()
        conn.close()

        assert row is not None
        assert row[0] == "opus"
    finally:
        collector.stop()
