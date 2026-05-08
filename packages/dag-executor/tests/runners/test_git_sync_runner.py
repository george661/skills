"""Tests for git-sync runner."""
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from dag_executor.runners.git_sync import GitSyncRunner
from dag_executor.runners.base import RunnerContext
from dag_executor.schema import NodeDef, NodeStatus, WorkflowDef, WorkflowConfig, GitConfig
from dag_executor.channels import ChannelStore, LastValueChannel


@pytest.fixture
def mock_channel_store():
    """Create a channel store with workspace set."""
    store = ChannelStore()
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create channel first
        store.channels["workspace"] = LastValueChannel("workspace")
        store.write("workspace", str(tmpdir), writer_node_id="__runtime__")
        yield store


@pytest.fixture
def runner_context(mock_channel_store):
    """Create a runner context with git config."""
    workflow_def = WorkflowDef(
        name="test-git-sync",
        config=WorkflowConfig(
            checkpoint_prefix="test",
            git=GitConfig(
                url="https://github.com/test/repo.git",
                ref="main",
                depth=1
            )
        ),
        nodes=[
            NodeDef(
                id="sync",
                name="Git Sync",
                type="git-sync"
            )
        ]
    )
    
    node_def = NodeDef(
        id="sync",
        name="Git Sync",
        type="git-sync"
    )
    
    return RunnerContext(
        node_def=node_def,
        workflow_def=workflow_def,
        workflow_inputs={},
        channel_store=mock_channel_store,
        resolved_inputs={}
    )


def test_clone_path_success(runner_context):
    """Test successful git clone path."""
    runner = GitSyncRunner()
    
    with patch('subprocess.run') as mock_run:
        # Mock successful git operations
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="abc123def456\n",
            stderr=""
        )
        
        result = runner.run(runner_context)
        
        assert result.status == NodeStatus.COMPLETED
        assert "src_path" in result.output
        # Clone is the default path when no local mirror exists
        assert result.output["method"] == "clone"


def test_missing_workspace_channel(runner_context):
    """Test error when workspace channel is not set."""
    runner = GitSyncRunner()
    
    # Remove workspace from channel store
    runner_context.channel_store.channels.clear()
    
    result = runner.run(runner_context)
    
    assert result.status == NodeStatus.FAILED
    assert "workspace channel not set" in result.error


def test_missing_git_config():
    """Test error when git config is not provided."""
    runner = GitSyncRunner()
    
    # Create context without git config
    workflow_def = WorkflowDef(
        name="test-no-git",
        config=WorkflowConfig(checkpoint_prefix="test"),
        nodes=[
            NodeDef(
                id="dummy",
                name="Dummy",
                type="bash",
                script="echo test"
            )
        ]
    )
    
    node_def = NodeDef(
        id="sync",
        name="Git Sync",
        type="git-sync"
    )
    
    ctx = RunnerContext(
        node_def=node_def,
        workflow_def=workflow_def,
        workflow_inputs={},
        resolved_inputs={}
    )
    
    result = runner.run(ctx)
    
    assert result.status == NodeStatus.FAILED
    assert "git-sync node requires workflow config.git" in result.error


def test_clone_failure(runner_context):
    """Test git clone failure handling."""
    runner = GitSyncRunner()
    
    with patch('subprocess.run') as mock_run:
        # Mock failed git clone
        from subprocess import CalledProcessError
        mock_run.side_effect = CalledProcessError(
            returncode=128,
            cmd=['git', 'clone'],
            stderr="fatal: repository not found"
        )
        
        result = runner.run(runner_context)
        
        assert result.status == NodeStatus.FAILED
        assert "Clone failed" in result.error or "Git sync failed" in result.error
