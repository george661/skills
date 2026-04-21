"""Tests for BashRunner artifact emission."""
from datetime import datetime, timezone
from typing import List
from unittest.mock import MagicMock

from dag_executor.events import EventEmitter, EventType, WorkflowEvent
from dag_executor.runners.bash import BashRunner
from dag_executor.runners.base import RunnerContext
from dag_executor.schema import NodeDef, NodeStatus


def _make_ctx(script: str, emitter: EventEmitter) -> RunnerContext:
    node = NodeDef(id="n1", name="n1", type="bash", script=script)
    return RunnerContext(
        node_def=node,
        workflow_id="wf-1",
        event_emitter=emitter,
    )


def test_bash_runner_emits_artifact_created_on_pr_url() -> None:
    """BashRunner emits ARTIFACT_CREATED for each PR URL in stdout."""
    received: List[WorkflowEvent] = []
    emitter = EventEmitter()
    emitter.add_listener(received.append)

    script = 'echo "Opened https://github.com/george661/skills/pull/99"'
    ctx = _make_ctx(script, emitter)
    result = BashRunner().run(ctx)

    assert result.status == NodeStatus.COMPLETED
    artifact_events = [e for e in received if e.event_type == EventType.ARTIFACT_CREATED]
    assert len(artifact_events) == 1
    meta = artifact_events[0].metadata
    assert meta["artifact_type"] == "pr"
    assert meta["url"].endswith("/pull/99")
    assert artifact_events[0].node_id == "n1"
    assert artifact_events[0].workflow_id == "wf-1"


def test_bash_runner_no_artifact_event_when_stdout_has_none() -> None:
    received: List[WorkflowEvent] = []
    emitter = EventEmitter()
    emitter.add_listener(received.append)

    ctx = _make_ctx('echo "nothing here"', emitter)
    BashRunner().run(ctx)
    assert [e for e in received if e.event_type == EventType.ARTIFACT_CREATED] == []


def test_bash_runner_no_artifacts_on_failure() -> None:
    """Do not emit artifacts when script fails, even if stdout had matches."""
    received: List[WorkflowEvent] = []
    emitter = EventEmitter()
    emitter.add_listener(received.append)

    script = 'echo "https://github.com/a/b/pull/1"; exit 1'
    ctx = _make_ctx(script, emitter)
    result = BashRunner().run(ctx)

    assert result.status == NodeStatus.FAILED
    assert [e for e in received if e.event_type == EventType.ARTIFACT_CREATED] == []
