"""Test that NODE_COMPLETED event includes cache_hit metadata on resume."""
import json
import tempfile
from pathlib import Path
from typing import List, Dict, Any

import pytest

from dag_executor.event_emitter import EventEmitter
from dag_executor.executor import DAGExecutor
from dag_executor.models import WorkflowConfig, NodeType


def parse_events(events_file: Path) -> List[Dict[str, Any]]:
    """Parse JSONL events file."""
    events = []
    with open(events_file) as f:
        for line in f:
            if line.strip():
                events.append(json.loads(line))
    return events


def test_cache_hit_metadata_on_second_run() -> None:
    """Run a workflow twice and verify NODE_COMPLETED includes cache_hit=True on second run."""
    
    # Create a minimal workflow with one echo node
    workflow = WorkflowConfig(
        nodes={
            "echo_node": {
                "type": NodeType.FUNCTION,
                "function": "echo",
                "args": {"message": "Hello from cache test"}
            }
        },
        edges=[],
        initial_inputs={}
    )
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        events_file = tmpdir_path / "events.jsonl"
        checkpoint_dir = tmpdir_path / "checkpoints"
        checkpoint_dir.mkdir()
        
        # First run: fresh execution
        emitter1 = EventEmitter(run_id="test-run-1", events_file=events_file)
        executor1 = DAGExecutor(
            workflow=workflow,
            event_emitter=emitter1,
            checkpoint_dir=checkpoint_dir
        )
        result1 = executor1.run()
        assert result1["echo_node"]["value"] == "Hello from cache test"
        
        # Parse first run events
        events1 = parse_events(events_file)
        completed_events1 = [e for e in events1 if e["type"] == "NODE_COMPLETED" and e["node_id"] == "echo_node"]
        assert len(completed_events1) == 1
        # First run should NOT have cache_hit (or it should be False)
        cache_hit_1 = completed_events1[0].get("metadata", {}).get("cache_hit", False)
        assert cache_hit_1 is False, "First run should not be a cache hit"
        
        # Clear events file for second run
        events_file.unlink()
        
        # Second run: same inputs, should restore from cache
        emitter2 = EventEmitter(run_id="test-run-2", events_file=events_file)
        executor2 = DAGExecutor(
            workflow=workflow,
            event_emitter=emitter2,
            checkpoint_dir=checkpoint_dir
        )
        result2 = executor2.run()
        assert result2["echo_node"]["value"] == "Hello from cache test"
        
        # Parse second run events
        events2 = parse_events(events_file)
        completed_events2 = [e for e in events2 if e["type"] == "NODE_COMPLETED" and e["node_id"] == "echo_node"]
        assert len(completed_events2) == 1
        
        # CRITICAL: Second run MUST have cache_hit=True
        cache_hit_2 = completed_events2[0].get("metadata", {}).get("cache_hit", False)
        assert cache_hit_2 is True, (
            "Second run with identical inputs should emit NODE_COMPLETED with metadata.cache_hit=True"
        )
        
        # Verify content_hash is present
        content_hash_2 = completed_events2[0].get("metadata", {}).get("content_hash")
        assert content_hash_2 is not None, "cache_hit event should include content_hash"
