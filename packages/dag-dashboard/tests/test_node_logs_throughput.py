"""Throughput test for node_logs persistence."""
import asyncio
import json
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dag_dashboard.broadcast import Broadcaster
from dag_dashboard.database import init_db
from dag_dashboard.event_collector import EventCollector


def test_1000_lines_per_second_sustained():
    """Verify node_logs can sustain 1000 lines/sec without drops."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        events_dir = Path(tmpdir) / "events"
        events_dir.mkdir()
        
        init_db(db_path)
        
        # Insert workflow run
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        run_id = "throughput-test"
        conn.execute("""
            INSERT INTO workflow_runs (id, workflow_name, status, started_at)
            VALUES (?, ?, ?, ?)
        """, (run_id, "throughput-test", "running", "2026-04-21T12:00:00Z"))
        conn.commit()
        conn.close()
        
        # Create collector
        broadcaster = MagicMock(spec=Broadcaster)
        loop = asyncio.new_event_loop()
        collector = EventCollector(
            events_dir=events_dir,
            db_path=db_path,
            broadcaster=broadcaster,
            loop=loop,
            node_log_line_cap=10000  # High enough to not hit cap
        )
        
        # Create 5000 events and measure time
        num_events = 5000
        events = []
        for i in range(1, num_events + 1):
            events.append({
                "event_type": "node_log_line",
                "run_id": run_id,
                "node_id": "throughput-node",
                "created_at": f"2026-04-21T12:00:{i:05d}Z",
                "metadata": {
                    "stream": "stdout",
                    "sequence": i,
                    "line": f"Log line {i}"
                }
            })
        
        # Write events to file
        event_file = events_dir / f"{run_id}.ndjson"
        with open(event_file, "w") as f:
            for event in events:
                f.write(json.dumps(event) + "\n")
        
        # Measure processing time directly on _persist_and_broadcast
        start_time = time.perf_counter()
        collector._process_file(event_file)
        end_time = time.perf_counter()
        
        elapsed = end_time - start_time
        rate = num_events / elapsed
        
        loop.close()
        
        # Verify all events were persisted
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT COUNT(*) FROM node_logs WHERE run_id = ? AND node_id = ?
        """, (run_id, "throughput-node"))
        count = cursor.fetchone()[0]
        conn.close()
        
        assert count == num_events, f"Expected {num_events} logs, got {count}"
        
        # Verify throughput
        print(f"\nThroughput: {rate:.0f} lines/sec (elapsed: {elapsed:.3f}s)")
        assert rate >= 1000, f"Throughput {rate:.0f} lines/sec is below 1000 lines/sec target"
