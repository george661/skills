"""Integration tests for on_failure=escalate behavior.

Covers:
  - A prompt node that fails with on_failure=escalate pauses the workflow
    and emits NODE_ESCALATED rather than NODE_FAILED.
  - An EscalationCheckpoint is saved with prompt/writes/error so a wrapping
    conversation can synthesize a replacement output.
  - Resuming the workflow with __escalation_output__ completes the node
    without re-executing it and lets downstream nodes see the synthesized
    value via both `$node.field` resolution and declared channel reads.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict

import pytest

from dag_executor import (
    CheckpointStore, EventEmitter,
    execute_workflow, resume_workflow, load_workflow,
    NodeStatus, WorkflowStatus,
)
from dag_executor.events import EventType, StreamMode
from dag_executor.schema import NodeResult


@pytest.fixture
def escalation_workflow(tmp_path: Path) -> Path:
    """A 3-node workflow whose middle node is forced to fail + escalate.

    Shape:
        seed (bash)          → emits a known JSON payload into channel `seed`
        think (prompt)       → model=local, on_failure=escalate, writes `answer`
        summarize (bash)     → reads both channels, asserts in stdout
    """
    yaml_path = tmp_path / "escalation.yaml"
    yaml_path.write_text(
        """
name: Escalation Test
config:
  checkpoint_prefix: {prefix}
state:
  seed:
    type: string
    reducer: overwrite
  answer:
    type: string
    reducer: overwrite
nodes:
  - id: seed_node
    name: Seed
    type: bash
    writes: [seed]
    script: |
      echo '{{"seed": "SEED-VALUE"}}'
    output_format: json

  - id: think
    name: Think
    type: prompt
    depends_on: [seed_node]
    reads: [seed]
    writes: [answer]
    model: local
    mode: agent
    on_failure: escalate
    output_format: text
    prompt: |
      Use the seed: $seed. Answer with one word.

  - id: summarize
    name: Summarize
    type: bash
    depends_on: [think]
    reads: [seed, answer]
    script: |
      echo "seed=$seed answer=$answer"
""".format(prefix=str(tmp_path / ".checkpoints")).strip()
    )
    return yaml_path


def _force_prompt_to_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace PromptRunner.run with a deterministic failure so we exercise
    the escalation path without needing Bedrock / Ollama."""
    from dag_executor.runners.prompt import PromptRunner

    def failing_run(self, ctx):  # type: ignore[no-untyped-def]
        return NodeResult(
            status=NodeStatus.FAILED,
            error="simulated local-model timeout",
        )

    monkeypatch.setattr(PromptRunner, "run", failing_run)


def test_escalate_pauses_workflow_and_emits_node_escalated(
    escalation_workflow: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """First execution should pause (not fail) and emit NODE_ESCALATED."""
    _force_prompt_to_fail(monkeypatch)

    workflow_def = load_workflow(str(escalation_workflow))
    checkpoint_store = CheckpointStore(str(tmp_path / ".checkpoints"))
    events: list[Any] = []
    emitter = EventEmitter()
    emitter.subscribe(events.append, StreamMode.ALL)

    result = execute_workflow(
        workflow_def,
        inputs={},
        checkpoint_store=checkpoint_store,
        event_emitter=emitter,
    )

    assert result.status == WorkflowStatus.PAUSED, (
        "Escalated workflow must pause, not terminally fail; got "
        f"{result.status!r}"
    )
    assert result.node_results["think"].status == NodeStatus.FAILED
    assert result.node_results["summarize"].status in (
        NodeStatus.SKIPPED,
        NodeStatus.PENDING,
    )

    # NODE_ESCALATED must have fired instead of NODE_FAILED for the escalated node.
    escalated_events = [e for e in events if e.event_type == EventType.NODE_ESCALATED]
    failed_events = [
        e for e in events
        if e.event_type == EventType.NODE_FAILED and e.node_id == "think"
    ]
    assert len(escalated_events) == 1, "expected exactly one NODE_ESCALATED event"
    assert escalated_events[0].node_id == "think"
    assert escalated_events[0].status == NodeStatus.ESCALATED
    assert not failed_events, (
        "escalated nodes must not also emit NODE_FAILED — the dashboard "
        "collector would treat them as terminally failed otherwise"
    )

    # Escalation checkpoint must exist with the right payload.
    escalation = checkpoint_store.load_escalation(workflow_def.name, result.run_id)
    assert escalation is not None
    assert escalation.node_id == "think"
    assert escalation.node_type == "prompt"
    assert "simulated local-model timeout" in escalation.error
    assert escalation.writes == ["answer"]
    assert escalation.output_format == "text"
    assert escalation.prompt is not None


def test_resume_with_synthesized_output_completes_downstream(
    escalation_workflow: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """After escalation, resuming with __escalation_output__ must skip
    re-execution of the escalated node and feed downstream the synthesized
    value via both `$node.field` AND declared channel reads."""
    _force_prompt_to_fail(monkeypatch)

    workflow_def = load_workflow(str(escalation_workflow))
    checkpoint_store = CheckpointStore(str(tmp_path / ".checkpoints"))

    first = execute_workflow(
        workflow_def, inputs={}, checkpoint_store=checkpoint_store,
    )
    assert first.status == WorkflowStatus.PAUSED

    # Resume with a synthesized answer. Crucially we do NOT restore the
    # prompt runner — if resume tried to re-run `think` the test would
    # fail again; passing confirms the prefill path is in effect.
    resumed = resume_workflow(
        workflow_name=workflow_def.name,
        run_id=first.run_id,
        checkpoint_store=checkpoint_store,
        workflow_def=workflow_def,
        resume_values={"__escalation_output__": "SYNTHESIZED"},
    )

    assert resumed.status == WorkflowStatus.COMPLETED, (
        f"expected COMPLETED after resume; got {resumed.status!r}"
    )
    assert resumed.node_results["think"].status == NodeStatus.COMPLETED
    assert resumed.node_results["summarize"].status == NodeStatus.COMPLETED

    # The summarize node reads $answer via env passthrough — the stdout
    # must contain the synthesized value, proving the channel write
    # survived the prefill path.
    summarize_out = resumed.node_results["summarize"].output or {}
    assert "SYNTHESIZED" in summarize_out.get("stdout", ""), (
        f"downstream bash did not see synthesized channel: {summarize_out!r}"
    )

    # Escalation checkpoint must be cleared so a subsequent failure on a
    # different node produces a clean new escalation.
    assert checkpoint_store.load_escalation(workflow_def.name, first.run_id) is None
