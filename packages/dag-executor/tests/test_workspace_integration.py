"""Integration tests for workspace lifecycle."""
import os
import tempfile
from pathlib import Path

import pytest

from dag_executor import execute_workflow, load_workflow
from dag_executor.schema import WorkflowDef, WorkflowConfig, NodeDef, WorkflowStatus, NodeStatus


def test_workspace_created_for_every_run():
    """Every workflow run creates a workspace directory and emits workspace channel."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Override workspace root
        workspace_override = Path(tmpdir) / "workspaces"

        # Simple workflow with no git config
        workflow = WorkflowDef(
            name="test-workspace",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=[
                NodeDef(
                    id="echo",
                    name="Echo Test",
                    type="bash",
                    script="echo 'Hello from workspace'",
                )
            ],
        )

        result = execute_workflow(
            workflow_def=workflow,
            inputs={},
            workspace_override=workspace_override,
        )

        assert result.status == WorkflowStatus.COMPLETED
        
        # Verify workspace was created
        workspaces = list(workspace_override.glob("*"))
        assert len(workspaces) == 1
        
        # Verify it's a directory
        assert workspaces[0].is_dir()


def test_workspace_root_env_override():
    """DAG_WORKSPACE_ROOT environment variable is respected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Set env var
        os.environ["DAG_WORKSPACE_ROOT"] = tmpdir

        try:
            workflow = WorkflowDef(
                name="test-env-workspace",
                config=WorkflowConfig(checkpoint_prefix="test"),
                nodes=[
                    NodeDef(
                        id="echo",
                        name="Echo Test",
                        type="bash",
                        script="echo 'test'",
                    )
                ],
            )

            result = execute_workflow(
                workflow_def=workflow,
                inputs={},
            )

            assert result.status == WorkflowStatus.COMPLETED
            
            # Verify workspace was created in env dir
            workspaces = list(Path(tmpdir).glob("*"))
            assert len(workspaces) >= 1
            
        finally:
            del os.environ["DAG_WORKSPACE_ROOT"]


def test_workspace_channel_auto_registered():
    """Workspace channel works even when workflow has no state block."""
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace_override = Path(tmpdir) / "workspaces"
        
        # Workflow without explicit state declaration
        workflow = WorkflowDef(
            name="test-auto-channel",
            config=WorkflowConfig(checkpoint_prefix="test"),
            nodes=[
                NodeDef(
                    id="check",
                    name="Check Workspace",
                    type="bash",
                    script='if [ -z "$DAG_WORKSPACE" ]; then echo "FAIL: workspace not set"; exit 1; else echo "workspace=$DAG_WORKSPACE"; fi',
                )
            ],
        )
        
        result = execute_workflow(
            workflow_def=workflow,
            inputs={},
            workspace_override=workspace_override,
        )

        assert result.status == WorkflowStatus.COMPLETED
        # Node should have succeeded (workspace env var was set)
        assert result.node_results["check"].status == NodeStatus.COMPLETED
