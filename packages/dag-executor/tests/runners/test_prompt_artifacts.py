"""Tests for PromptRunner artifact emission."""
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from dag_executor.events import EventEmitter, EventType, WorkflowEvent
from dag_executor.runners.prompt import PromptRunner
from dag_executor.runners.base import RunnerContext
from dag_executor.schema import NodeDef, NodeStatus
from dag_executor.schema import ModelTier


class _FakeProc:
    def __init__(self, stdout_lines, rc=0, stderr=""):
        self.stdout = iter(stdout_lines)
        self.stderr = MagicMock()
        self.stderr.read.return_value = stderr
        self.stdin = None
        self._rc = rc

    def wait(self, timeout=None):
        return self._rc

    def kill(self):
        pass


def test_prompt_runner_emits_artifact_from_response() -> None:
    received: List[WorkflowEvent] = []
    emitter = EventEmitter()
    emitter.add_listener(received.append)

    node = NodeDef(
        id="n1", name="n1", type="prompt",
        model=ModelTier.LOCAL, prompt="hi",
    )
    ctx = RunnerContext(
        node_def=node, workflow_id="wf-1", event_emitter=emitter,
    )

    fake_lines = [
        "Working...\n",
        "Opened: https://github.com/a/b/pull/12\n",
        "Done.\n",
    ]
    with patch("dag_executor.runners.prompt.subprocess.Popen", return_value=_FakeProc(fake_lines)):
        result = PromptRunner().run(ctx)

    assert result.status == NodeStatus.COMPLETED
    artifact_events = [e for e in received if e.event_type == EventType.ARTIFACT_CREATED]
    # 1 PR + NODE_STREAM_TOKEN events don't count here
    assert len(artifact_events) == 1
    assert artifact_events[0].metadata["artifact_type"] == "pr"
    assert artifact_events[0].node_id == "n1"
