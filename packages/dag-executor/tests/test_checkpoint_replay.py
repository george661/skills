"""Tests for checkpoint replay, history, and inspect functionality."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from dag_executor.checkpoint import CheckpointMetadata, CheckpointStore, NodeCheckpoint
from dag_executor.cli import main, run_history, run_inspect, run_replay
from dag_executor.schema import NodeDef, NodeResult, NodeStatus, WorkflowConfig, WorkflowDef, WorkflowStatus
from dag_executor.executor import WorkflowResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def checkpoint_store(tmp_path: Path) -> CheckpointStore:
    """Create a checkpoint store with temporary directory."""
    return CheckpointStore(str(tmp_path / ".dag-checkpoints"))


@pytest.fixture
def sample_metadata() -> CheckpointMetadata:
    """Create sample checkpoint metadata."""
    return CheckpointMetadata(
        workflow_name="test-workflow",
        run_id="run-123",
        started_at=datetime.now(timezone.utc).isoformat(),
        inputs={"input1": "value1"},
        status="completed",
    )


@pytest.fixture
def sample_node_result() -> NodeResult:
    """Create sample node result."""
    return NodeResult(
        status=NodeStatus.COMPLETED,
        output={"result": "test-output"},
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def sample_node_def() -> NodeDef:
    """Create sample node definition."""
    return NodeDef(
        id="node1",
        name="Test Node",
        type="bash",
        script="echo 'test'",
    )


@pytest.fixture
def simple_workflow_def() -> WorkflowDef:
    """Create a simple 3-node linear workflow: a -> b -> c."""
    return WorkflowDef(
        name="test-workflow",
        config=WorkflowConfig(checkpoint_prefix="test"),
        nodes=[
            NodeDef(id="a", name="Node A", type="bash", script="echo a"),
            NodeDef(id="b", name="Node B", type="bash", script="echo b", depends_on=["a"]),
            NodeDef(id="c", name="Node C", type="bash", script="echo c", depends_on=["b"]),
        ],
    )


def _save_three_node_run(
    store: CheckpointStore,
    workflow_name: str,
    run_id: str,
    metadata: CheckpointMetadata,
    node_result: NodeResult,
) -> None:
    """Helper: save metadata and 3 node checkpoints (a, b, c)."""
    store.save_metadata(workflow_name, run_id, metadata)
    for nid in ("a", "b", "c"):
        store.save_node(workflow_name, run_id, nid, node_result, f"hash-{nid}")


# ---------------------------------------------------------------------------
# CheckpointStore.list_runs tests
# ---------------------------------------------------------------------------


class TestListRuns:
    def test_list_runs_empty(self, checkpoint_store: CheckpointStore) -> None:
        """No checkpoint dirs exist, returns empty list."""
        result = checkpoint_store.list_runs("test-workflow")
        assert result == []

    def test_list_runs_finds_runs(
        self, checkpoint_store: CheckpointStore, sample_metadata: CheckpointMetadata,
        sample_node_result: NodeResult,
    ) -> None:
        """Create 2 run dirs, verify both found."""
        meta1 = CheckpointMetadata(
            workflow_name="test-workflow", run_id="run-001",
            started_at=datetime.now(timezone.utc).isoformat(),
            inputs={}, status="completed",
        )
        meta2 = CheckpointMetadata(
            workflow_name="test-workflow", run_id="run-002",
            started_at=datetime.now(timezone.utc).isoformat(),
            inputs={}, status="completed",
        )
        checkpoint_store.save_metadata("test-workflow", "run-001", meta1)
        checkpoint_store.save_metadata("test-workflow", "run-002", meta2)

        runs = checkpoint_store.list_runs("test-workflow")
        assert runs == ["run-001", "run-002"]

    def test_list_runs_ignores_other_workflows(
        self, checkpoint_store: CheckpointStore,
    ) -> None:
        """Create dirs for different workflow names, verify filtering."""
        meta_a = CheckpointMetadata(
            workflow_name="alpha", run_id="r1",
            started_at=datetime.now(timezone.utc).isoformat(),
            inputs={}, status="completed",
        )
        meta_b = CheckpointMetadata(
            workflow_name="beta", run_id="r1",
            started_at=datetime.now(timezone.utc).isoformat(),
            inputs={}, status="completed",
        )
        checkpoint_store.save_metadata("alpha", "r1", meta_a)
        checkpoint_store.save_metadata("beta", "r1", meta_b)

        assert checkpoint_store.list_runs("alpha") == ["r1"]
        assert checkpoint_store.list_runs("beta") == ["r1"]
        assert checkpoint_store.list_runs("gamma") == []


# ---------------------------------------------------------------------------
# CheckpointStore.clear_nodes_after tests
# ---------------------------------------------------------------------------


class TestClearNodesAfter:
    def test_clear_nodes_after(
        self, checkpoint_store: CheckpointStore, sample_node_result: NodeResult,
    ) -> None:
        """Create 3 node checkpoints (a, b, c), clear after b, verify only c removed."""
        for nid in ("a", "b", "c"):
            checkpoint_store.save_node("wf", "run1", nid, sample_node_result, f"h-{nid}")

        cleared = checkpoint_store.clear_nodes_after("wf", "run1", "b", ["a", "b", "c"])
        assert cleared == ["c"]

        # a and b still exist, c is gone
        assert checkpoint_store.load_node("wf", "run1", "a") is not None
        assert checkpoint_store.load_node("wf", "run1", "b") is not None
        assert checkpoint_store.load_node("wf", "run1", "c") is None

    def test_clear_nodes_after_unknown_node(
        self, checkpoint_store: CheckpointStore, sample_node_result: NodeResult,
    ) -> None:
        """Pass non-existent node_id, verify no deletions."""
        for nid in ("a", "b", "c"):
            checkpoint_store.save_node("wf", "run1", nid, sample_node_result, f"h-{nid}")

        cleared = checkpoint_store.clear_nodes_after("wf", "run1", "z", ["a", "b", "c"])
        assert cleared == []

        # All still present
        assert checkpoint_store.load_node("wf", "run1", "a") is not None
        assert checkpoint_store.load_node("wf", "run1", "b") is not None
        assert checkpoint_store.load_node("wf", "run1", "c") is not None


# ---------------------------------------------------------------------------
# CLI history subcommand tests
# ---------------------------------------------------------------------------


class TestHistoryCLI:
    def test_history_no_runs(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path,
    ) -> None:
        """CLI history with no runs returns empty."""
        cp_dir = str(tmp_path / ".dag-cp")
        with patch("dag_executor.cli.load_workflow") as mock_load:
            mock_load.return_value = WorkflowDef(
                name="wf", config=WorkflowConfig(checkpoint_prefix=cp_dir),
                nodes=[NodeDef(id="a", name="A", type="bash", script="echo a")],
            )
            main(["history", "workflow.yaml", "--checkpoint-dir", cp_dir])

        out = json.loads(capsys.readouterr().out)
        assert out["runs"] == []

    def test_history_lists_runs(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path,
        sample_node_result: NodeResult,
    ) -> None:
        """CLI history lists run metadata."""
        cp_dir = str(tmp_path / ".dag-cp")
        store = CheckpointStore(cp_dir)
        meta = CheckpointMetadata(
            workflow_name="wf", run_id="r1",
            started_at="2026-01-01T00:00:00+00:00",
            inputs={}, status="completed",
        )
        store.save_metadata("wf", "r1", meta)
        store.save_node("wf", "r1", "a", sample_node_result, "h-a")

        with patch("dag_executor.cli.load_workflow") as mock_load:
            mock_load.return_value = WorkflowDef(
                name="wf", config=WorkflowConfig(checkpoint_prefix=cp_dir),
                nodes=[NodeDef(id="a", name="A", type="bash", script="echo a")],
            )
            main(["history", "workflow.yaml", "--checkpoint-dir", cp_dir])

        out = json.loads(capsys.readouterr().out)
        assert len(out["runs"]) == 1
        assert out["runs"][0]["run_id"] == "r1"
        assert out["runs"][0]["status"] == "completed"
        assert out["runs"][0]["node_count"] == 1


# ---------------------------------------------------------------------------
# CLI inspect subcommand tests
# ---------------------------------------------------------------------------


class TestInspectCLI:
    def test_inspect_run(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path,
        sample_node_result: NodeResult,
    ) -> None:
        """CLI inspect shows metadata + node summaries."""
        cp_dir = str(tmp_path / ".dag-cp")
        store = CheckpointStore(cp_dir)
        meta = CheckpointMetadata(
            workflow_name="wf", run_id="r1",
            started_at="2026-01-01T00:00:00+00:00",
            inputs={"x": 1}, status="completed",
        )
        store.save_metadata("wf", "r1", meta)
        store.save_node("wf", "r1", "a", sample_node_result, "h-a")

        with patch("dag_executor.cli.load_workflow") as mock_load:
            mock_load.return_value = WorkflowDef(
                name="wf", config=WorkflowConfig(checkpoint_prefix=cp_dir),
                nodes=[NodeDef(id="a", name="A", type="bash", script="echo a")],
            )
            main(["inspect", "workflow.yaml", "--run-id", "r1", "--checkpoint-dir", cp_dir])

        out = json.loads(capsys.readouterr().out)
        assert out["workflow_name"] == "wf"
        assert out["run_id"] == "r1"
        assert len(out["nodes"]) == 1
        assert out["nodes"][0]["node_id"] == "a"

    def test_inspect_specific_node(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path,
        sample_node_result: NodeResult,
    ) -> None:
        """CLI inspect --node shows full node data."""
        cp_dir = str(tmp_path / ".dag-cp")
        store = CheckpointStore(cp_dir)
        meta = CheckpointMetadata(
            workflow_name="wf", run_id="r1",
            started_at="2026-01-01T00:00:00+00:00",
            inputs={}, status="completed",
        )
        store.save_metadata("wf", "r1", meta)
        store.save_node("wf", "r1", "a", sample_node_result, "h-a")

        with patch("dag_executor.cli.load_workflow") as mock_load:
            mock_load.return_value = WorkflowDef(
                name="wf", config=WorkflowConfig(checkpoint_prefix=cp_dir),
                nodes=[NodeDef(id="a", name="A", type="bash", script="echo a")],
            )
            main(["inspect", "workflow.yaml", "--run-id", "r1", "--node", "a", "--checkpoint-dir", cp_dir])

        out = json.loads(capsys.readouterr().out)
        assert out["node_id"] == "a"
        assert out["status"] == "completed"
        assert out["content_hash"] == "h-a"
        assert "output" in out


# ---------------------------------------------------------------------------
# CLI replay subcommand tests
# ---------------------------------------------------------------------------


class TestReplayCLI:
    def test_replay_creates_new_run(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path,
        sample_node_result: NodeResult,
    ) -> None:
        """CLI replay creates new run directory, clears downstream nodes."""
        cp_dir = str(tmp_path / ".dag-cp")
        store = CheckpointStore(cp_dir)
        wf_name = "wf"
        meta = CheckpointMetadata(
            workflow_name=wf_name, run_id="r1",
            started_at="2026-01-01T00:00:00+00:00",
            inputs={"x": 1}, status="completed",
        )
        _save_three_node_run(store, wf_name, "r1", meta, sample_node_result)

        wf_def = WorkflowDef(
            name=wf_name, config=WorkflowConfig(checkpoint_prefix=cp_dir),
            nodes=[
                NodeDef(id="a", name="A", type="bash", script="echo a"),
                NodeDef(id="b", name="B", type="bash", script="echo b", depends_on=["a"]),
                NodeDef(id="c", name="C", type="bash", script="echo c", depends_on=["b"]),
            ],
        )

        mock_result = WorkflowResult(
            status=WorkflowStatus.COMPLETED,
            node_results={
                "a": NodeResult(status=NodeStatus.COMPLETED, output={"result": "a"}),
                "b": NodeResult(status=NodeStatus.COMPLETED, output={"result": "b"}),
                "c": NodeResult(status=NodeStatus.COMPLETED, output={"result": "c"}),
            },
            run_id="r1-replay-test",
        )

        with patch("dag_executor.cli.load_workflow") as mock_load, \
             patch("dag_executor.cli.resume_workflow") as mock_resume:
            mock_load.return_value = wf_def
            mock_resume.return_value = mock_result
            main(["replay", "workflow.yaml", "--run-id", "r1", "--from-node", "b",
                  "--checkpoint-dir", cp_dir])

        out = json.loads(capsys.readouterr().out)
        assert out["parent_run_id"] == "r1"
        assert out["replayed_from"] == "b"
        assert "c" in out["nodes_cleared"]
        assert "r1-replay-" in out["new_run_id"]

        # Verify the new run directory exists
        runs = store.list_runs(wf_name)
        replay_runs = [r for r in runs if "replay" in r]
        assert len(replay_runs) == 1

    def test_replay_with_overrides(
        self, capsys: pytest.CaptureFixture[str], tmp_path: Path,
        sample_node_result: NodeResult,
    ) -> None:
        """CLI replay --with-override modifies inputs."""
        cp_dir = str(tmp_path / ".dag-cp")
        store = CheckpointStore(cp_dir)
        wf_name = "wf"
        meta = CheckpointMetadata(
            workflow_name=wf_name, run_id="r1",
            started_at="2026-01-01T00:00:00+00:00",
            inputs={"x": 1}, status="completed",
        )
        _save_three_node_run(store, wf_name, "r1", meta, sample_node_result)

        wf_def = WorkflowDef(
            name=wf_name, config=WorkflowConfig(checkpoint_prefix=cp_dir),
            nodes=[
                NodeDef(id="a", name="A", type="bash", script="echo a"),
                NodeDef(id="b", name="B", type="bash", script="echo b", depends_on=["a"]),
                NodeDef(id="c", name="C", type="bash", script="echo c", depends_on=["b"]),
            ],
        )

        mock_result = WorkflowResult(
            status=WorkflowStatus.COMPLETED,
            node_results={},
            run_id="r1-replay-test",
        )

        captured_inputs = {}

        def capture_resume(**kwargs: Any) -> WorkflowResult:
            captured_inputs.update(kwargs.get("inputs", {}))
            return mock_result

        with patch("dag_executor.cli.load_workflow") as mock_load, \
             patch("dag_executor.cli.resume_workflow") as mock_resume:
            mock_load.return_value = wf_def
            mock_resume.side_effect = capture_resume
            main([
                "replay", "workflow.yaml", "--run-id", "r1", "--from-node", "a",
                "--with-override", "x=42", "--with-override", "y=hello",
                "--checkpoint-dir", cp_dir,
            ])

        # Verify resume was called with merged inputs
        call_kwargs = mock_resume.call_args
        inputs = call_kwargs.kwargs.get("inputs") or call_kwargs[1].get("inputs", {})
        assert inputs["x"] == 42  # JSON-parsed int
        assert inputs["y"] == "hello"

    def test_replay_preserves_original(
        self, tmp_path: Path, sample_node_result: NodeResult,
    ) -> None:
        """Original run directory unchanged after replay."""
        cp_dir = str(tmp_path / ".dag-cp")
        store = CheckpointStore(cp_dir)
        wf_name = "wf"
        meta = CheckpointMetadata(
            workflow_name=wf_name, run_id="r1",
            started_at="2026-01-01T00:00:00+00:00",
            inputs={"x": 1}, status="completed",
        )
        _save_three_node_run(store, wf_name, "r1", meta, sample_node_result)

        # Snapshot original node file contents
        original_nodes = store.load_all_nodes(wf_name, "r1")
        original_meta = store.load_metadata(wf_name, "r1")

        wf_def = WorkflowDef(
            name=wf_name, config=WorkflowConfig(checkpoint_prefix=cp_dir),
            nodes=[
                NodeDef(id="a", name="A", type="bash", script="echo a"),
                NodeDef(id="b", name="B", type="bash", script="echo b", depends_on=["a"]),
                NodeDef(id="c", name="C", type="bash", script="echo c", depends_on=["b"]),
            ],
        )

        mock_result = WorkflowResult(
            status=WorkflowStatus.COMPLETED, node_results={}, run_id="r1-replay-test",
        )

        with patch("dag_executor.cli.load_workflow") as mock_load, \
             patch("dag_executor.cli.resume_workflow") as mock_resume:
            mock_load.return_value = wf_def
            mock_resume.return_value = mock_result
            main([
                "replay", "workflow.yaml", "--run-id", "r1", "--from-node", "b",
                "--checkpoint-dir", cp_dir,
            ])

        # Verify original run is untouched
        after_nodes = store.load_all_nodes(wf_name, "r1")
        after_meta = store.load_metadata(wf_name, "r1")

        assert set(after_nodes.keys()) == set(original_nodes.keys())
        for nid in original_nodes:
            assert after_nodes[nid].content_hash == original_nodes[nid].content_hash
        assert after_meta is not None
        assert after_meta.status == original_meta.status  # type: ignore[union-attr]
        assert after_meta.run_id == original_meta.run_id  # type: ignore[union-attr]
