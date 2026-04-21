"""Tests for SkillRunner artifact emission."""
import json
from pathlib import Path
from typing import List

import pytest

from dag_executor.events import EventEmitter, EventType, WorkflowEvent
from dag_executor.runners.skill import SkillRunner
from dag_executor.runners.base import RunnerContext
from dag_executor.schema import NodeDef, NodeStatus


def test_skill_runner_emits_artifact_from_stdout(tmp_path: Path) -> None:
    # Fake skill script that echoes a JSON payload mentioning a PR URL
    skill = tmp_path / "fake.py"
    skill.write_text(
        "import sys, json\n"
        "print(json.dumps({'result': 'https://github.com/a/b/pull/7'}))\n"
    )

    received: List[WorkflowEvent] = []
    emitter = EventEmitter()
    emitter.add_listener(received.append)

    node = NodeDef(id="n1", name="n1", type="skill", skill="fake.py")
    ctx = RunnerContext(
        node_def=node,
        workflow_id="wf-1",
        skills_dir=tmp_path,
        event_emitter=emitter,
    )
    result = SkillRunner().run(ctx)
    assert result.status == NodeStatus.COMPLETED

    prs = [e for e in received if e.event_type == EventType.ARTIFACT_CREATED]
    assert len(prs) == 1
    assert prs[0].metadata["artifact_type"] == "pr"
    assert prs[0].node_id == "n1"
