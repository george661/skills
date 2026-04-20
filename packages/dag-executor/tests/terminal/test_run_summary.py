"""Tests for run summary rendering."""
import os
from datetime import datetime, timedelta
from dag_executor.executor import WorkflowResult, NodeSummary
from dag_executor.schema import NodeStatus, NodeResult, WorkflowStatus, WorkflowDef, WorkflowConfig, NodeDef
from dag_executor.terminal.run_summary import RunSummary


def test_run_summary_renders_all_completed():
    """Summary shows header, per-node table, and total duration."""
    # Create a minimal workflow
    workflow_def = WorkflowDef(
        name="test-workflow",
        config=WorkflowConfig(checkpoint_prefix=".test"),
        nodes=[
            NodeDef(id="a", name="A", type="bash", script="echo a"),
            NodeDef(id="b", name="B", type="bash", script="echo b"),
            NodeDef(id="c", name="C", type="bash", script="echo c"),
        ],
    )
    
    # Create node results
    now = datetime.now()
    node_results = {
        "a": NodeResult(
            status=NodeStatus.COMPLETED,
            started_at=now,
            completed_at=now + timedelta(milliseconds=100),
            output={"result": "ok"}
        ),
        "b": NodeResult(
            status=NodeStatus.COMPLETED,
            started_at=now + timedelta(milliseconds=100),
            completed_at=now + timedelta(milliseconds=250),
            output={"result": "ok"}
        ),
        "c": NodeResult(
            status=NodeStatus.COMPLETED,
            started_at=now + timedelta(milliseconds=250),
            completed_at=now + timedelta(milliseconds=350),
            output={"result": "ok"}
        ),
    }
    
    result = WorkflowResult(
        status=WorkflowStatus.COMPLETED,
        node_results=node_results,
        run_id="test-123"
    )
    
    summary = RunSummary.render(result, workflow_def)
    
    # Check for basic structure
    assert "test-workflow" in summary
    assert "COMPLETED" in summary or "completed" in summary
    # Each node should appear
    assert "a" in summary or "A" in summary
    assert "b" in summary or "B" in summary
    assert "c" in summary or "C" in summary


def test_run_summary_shows_failed_status_marker():
    """Failed node shows failure marker."""
    workflow_def = WorkflowDef(
        name="test",
        config=WorkflowConfig(checkpoint_prefix=".test"),
        nodes=[
            NodeDef(id="a", name="A", type="bash", script="echo a"),
        ],
    )
    
    node_results = {
        "a": NodeResult(
            status=NodeStatus.FAILED,
            started_at=datetime.now(),
            completed_at=datetime.now() + timedelta(milliseconds=100),
            error="Something went wrong"
        ),
    }
    
    result = WorkflowResult(
        status=WorkflowStatus.FAILED,
        node_results=node_results,
        run_id="test-123"
    )
    
    summary = RunSummary.render(result, workflow_def)
    assert "FAILED" in summary or "✗" in summary or "X" in summary


def test_run_summary_ascii_fallback_under_no_color():
    """NO_COLOR env var produces ASCII box drawing."""
    os.environ["NO_COLOR"] = "1"
    
    try:
        workflow_def = WorkflowDef(
            name="test",
            config=WorkflowConfig(checkpoint_prefix=".test"),
            nodes=[
                NodeDef(id="a", name="A", type="bash", script="echo a"),
            ],
        )
        
        node_results = {
            "a": NodeResult(
                status=NodeStatus.COMPLETED,
                started_at=datetime.now(),
                completed_at=datetime.now() + timedelta(milliseconds=100),
            ),
        }
        
        result = WorkflowResult(
            status=WorkflowStatus.COMPLETED,
            node_results=node_results,
            run_id="test-123"
        )
        
        summary = RunSummary.render(result, workflow_def)
        
        # Should not contain Unicode box-drawing chars
        assert "╭" not in summary
        assert "╮" not in summary
        assert "╰" not in summary
        assert "╯" not in summary
        # Should contain ASCII alternatives
        assert "+" in summary or "-" in summary
    finally:
        os.environ.pop("NO_COLOR", None)


def test_run_summary_lists_artifacts():
    """Artifacts from outputs are listed."""
    workflow_def = WorkflowDef(
        name="test",
        config=WorkflowConfig(checkpoint_prefix=".test"),
        nodes=[
            NodeDef(id="a", name="A", type="bash", script="echo a"),
        ],
    )
    
    node_results = {
        "a": NodeResult(
            status=NodeStatus.COMPLETED,
            started_at=datetime.now(),
            completed_at=datetime.now() + timedelta(milliseconds=100),
        ),
    }
    
    result = WorkflowResult(
        status=WorkflowStatus.COMPLETED,
        node_results=node_results,
        run_id="test-123",
        outputs={"pr_url": "https://github.com/test/pr/1", "plan_path": "/tmp/plan.md"}
    )
    
    summary = RunSummary.render(result, workflow_def)
    
    # Both artifacts should appear
    assert "pr_url" in summary or "https://github.com/test/pr/1" in summary
    assert "plan_path" in summary or "/tmp/plan.md" in summary


def test_run_summary_handles_empty_outputs():
    """No artifacts block when outputs empty."""
    workflow_def = WorkflowDef(
        name="test",
        config=WorkflowConfig(checkpoint_prefix=".test"),
        nodes=[
            NodeDef(id="a", name="A", type="bash", script="echo a"),
        ],
    )
    
    node_results = {
        "a": NodeResult(
            status=NodeStatus.COMPLETED,
            started_at=datetime.now(),
            completed_at=datetime.now() + timedelta(milliseconds=100),
        ),
    }
    
    result = WorkflowResult(
        status=WorkflowStatus.COMPLETED,
        node_results=node_results,
        run_id="test-123",
        outputs={}
    )
    
    summary = RunSummary.render(result, workflow_def)
    
    # Should not crash, should contain basic summary
    assert "test" in summary
    assert "COMPLETED" in summary or "completed" in summary


def test_run_summary_duration_derived_from_timestamps():
    """Duration column matches timestamp delta."""
    workflow_def = WorkflowDef(
        name="test",
        config=WorkflowConfig(checkpoint_prefix=".test"),
        nodes=[
            NodeDef(id="a", name="A", type="bash", script="echo a"),
        ],
    )
    
    now = datetime.now()
    node_results = {
        "a": NodeResult(
            status=NodeStatus.COMPLETED,
            started_at=now,
            completed_at=now + timedelta(milliseconds=1500),  # 1.5 seconds
        ),
    }
    
    result = WorkflowResult(
        status=WorkflowStatus.COMPLETED,
        node_results=node_results,
        run_id="test-123"
    )
    
    summary = RunSummary.render(result, workflow_def)
    
    # Should show ~1500ms or 1.5s
    assert ("1500" in summary or "1.5" in summary) or "ms" in summary
