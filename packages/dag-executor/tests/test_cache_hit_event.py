"""Test that NODE_COMPLETED event includes cache_hit metadata on cache restore."""
import asyncio
import tempfile
import uuid
from unittest.mock import patch

from dag_executor import execute_workflow
from dag_executor.channels import ChannelStore
from dag_executor.checkpoint import CheckpointStore
from dag_executor.events import EventEmitter, EventType, WorkflowEvent
from dag_executor.executor import WorkflowExecutor
from dag_executor.runners.base import BaseRunner, RunnerContext
from dag_executor.schema import (
    NodeDef,
    NodeResult,
    NodeStatus,
    WorkflowConfig,
    WorkflowDef,
)


def test_cache_hit_event_emitted_on_restore() -> None:
    """Second run with same inputs emits NODE_COMPLETED with metadata.cache_hit=True."""
    node = NodeDef(id="n1", name="Node 1", type="bash", script="echo test")
    workflow_def = WorkflowDef(
        name="test-cache-hit-event",
        config=WorkflowConfig(checkpoint_prefix="test"),
        nodes=[node],
    )

    class StubRunner(BaseRunner):
        def run(self, ctx: RunnerContext) -> NodeResult:
            return NodeResult(status=NodeStatus.COMPLETED, output={"v": 1})

    with tempfile.TemporaryDirectory() as tmpdir:
        checkpoint_store = CheckpointStore(str(tmpdir))
        run_id = str(uuid.uuid4())

        # First run: populates cache.
        with patch("dag_executor.executor.get_runner", return_value=StubRunner):
            r1 = execute_workflow(
                workflow_def, {}, checkpoint_store=checkpoint_store, run_id=run_id
            )
        assert r1.status.value == "completed"

        # Second run: same run_id and inputs → cache restore path.
        completed_events: list[WorkflowEvent] = []
        emitter = EventEmitter()

        def capture(ev: WorkflowEvent) -> None:
            if ev.event_type == EventType.NODE_COMPLETED and ev.node_id == "n1":
                completed_events.append(ev)

        emitter.add_listener(capture)
        channel_store = ChannelStore.from_workflow_def(workflow_def)

        with patch("dag_executor.executor.get_runner", return_value=StubRunner):
            executor = WorkflowExecutor()
            asyncio.run(
                executor.execute(
                    workflow_def,
                    {},
                    event_emitter=emitter,
                    checkpoint_store=checkpoint_store,
                    run_id=run_id,
                    channel_store=channel_store,
                )
            )

        assert len(completed_events) == 1, (
            "Expected exactly one NODE_COMPLETED event for the cached node"
        )
        metadata = completed_events[0].metadata or {}
        assert metadata.get("cache_hit") is True, (
            f"NODE_COMPLETED on cache restore must set metadata.cache_hit=True; got {metadata}"
        )
