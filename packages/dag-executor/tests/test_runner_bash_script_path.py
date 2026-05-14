"""Tests for bash runner script_path functionality."""
from pathlib import Path
import pytest
from dag_executor.channels import ChannelStore, LastValueChannel
from dag_executor.schema import NodeDef, NodeStatus
from dag_executor.runners.bash import BashRunner
from dag_executor.runners.base import RunnerContext


@pytest.fixture
def setup_workspace_with_script(tmp_path):
    """Create a workspace with a seeded script."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workflow_dir = workspace / ".workflow"
    workflow_dir.mkdir()
    scripts_dir = workflow_dir / "scripts"
    scripts_dir.mkdir()
    
    script_file = scripts_dir / "test.sh"
    script_file.write_text("#!/bin/bash\necho 'seeded-version'")
    
    return workspace, script_file


def test_bash_runner_reads_from_seeded_copy_not_source(tmp_path, setup_workspace_with_script):
    """Bash runner should read from seeded .workflow/scripts/ copy."""
    workspace, script_file = setup_workspace_with_script
    
    # Create a channel store with workspace path
    channel_store = ChannelStore({})
    channel_store.channels["workspace"] = LastValueChannel("workspace")
    channel_store.write("workspace", str(workspace), writer_node_id="__test__")
    
    # Create node with script_path
    node = NodeDef(
        id="test",
        name="Test",
        type="bash",
        script_path="scripts/test.sh"
    )
    
    # Create context
    ctx = RunnerContext(
        node_def=node,
        workflow_inputs={},
        resolved_inputs={},
        workflow_def=None,
        channel_store=channel_store
    )
    
    # Run bash runner
    runner = BashRunner()
    result = runner.run(ctx)
    
    # Should succeed and output should contain "seeded-version"
    assert result.status == NodeStatus.COMPLETED
    assert "seeded-version" in result.output['stdout']


def test_bash_runner_inline_script_unchanged(tmp_path):
    """Regression: inline script should still work as before."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    
    # Create a channel store with workspace path
    channel_store = ChannelStore({})
    channel_store.channels["workspace"] = LastValueChannel("workspace")
    channel_store.write("workspace", str(workspace), writer_node_id="__test__")
    
    # Create node with inline script
    node = NodeDef(
        id="test",
        name="Test",
        type="bash",
        script="echo 'inline-script'"
    )
    
    # Create context
    ctx = RunnerContext(
        node_def=node,
        workflow_inputs={},
        resolved_inputs={},
        workflow_def=None,
        channel_store=channel_store
    )
    
    # Run bash runner
    runner = BashRunner()
    result = runner.run(ctx)
    
    # Should succeed
    assert result.status == NodeStatus.COMPLETED
    assert "inline-script" in result.output['stdout']


def test_bash_runner_script_path_missing_in_workspace_fails_clearly(tmp_path):
    """Missing seeded script should fail with clear error."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workflow_dir = workspace / ".workflow"
    workflow_dir.mkdir()
    scripts_dir = workflow_dir / "scripts"
    scripts_dir.mkdir()
    # Note: we create the scripts dir but DON'T create the script file
    
    # Create a channel store with workspace path
    channel_store = ChannelStore({})
    channel_store.channels["workspace"] = LastValueChannel("workspace")
    channel_store.write("workspace", str(workspace), writer_node_id="__test__")
    
    # Create node with script_path
    node = NodeDef(
        id="test",
        name="Test",
        type="bash",
        script_path="scripts/missing.sh"
    )
    
    # Create context
    ctx = RunnerContext(
        node_def=node,
        workflow_inputs={},
        resolved_inputs={},
        workflow_def=None,
        channel_store=channel_store
    )
    
    # Run bash runner
    runner = BashRunner()
    result = runner.run(ctx)
    
    # Should fail with clear error
    assert result.status == NodeStatus.FAILED
    assert "seeded script not found" in result.error


def test_bash_runner_script_path_without_workspace_channel_fails(tmp_path):
    """script_path node without workspace channel should fail clearly."""
    # Create channel store WITHOUT workspace channel
    channel_store = ChannelStore({})
    
    # Create node with script_path
    node = NodeDef(
        id="test",
        name="Test",
        type="bash",
        script_path="scripts/test.sh"
    )
    
    # Create context
    ctx = RunnerContext(
        node_def=node,
        workflow_inputs={},
        resolved_inputs={},
        workflow_def=None,
        channel_store=channel_store
    )
    
    # Run bash runner
    runner = BashRunner()
    result = runner.run(ctx)
    
    # Should fail with clear error
    assert result.status == NodeStatus.FAILED
    assert "workspace channel" in result.error


def test_bash_runner_script_path_without_channel_store_fails(tmp_path):
    """script_path node without channel_store should fail clearly."""
    # Create node with script_path
    node = NodeDef(
        id="test",
        name="Test",
        type="bash",
        script_path="scripts/test.sh"
    )
    
    # Create context WITHOUT channel_store
    ctx = RunnerContext(
        node_def=node,
        workflow_inputs={},
        resolved_inputs={},
        workflow_def=None
    )
    
    # Run bash runner
    runner = BashRunner()
    result = runner.run(ctx)
    
    # Should fail with clear error
    assert result.status == NodeStatus.FAILED
    assert "channel_store is not available" in result.error
