"""Tests for path_resolution module."""
import os
import tempfile
from pathlib import Path

import pytest

from dag_executor.path_resolution import _resolve_workflow_relative


@pytest.fixture
def temp_repo(tmp_path):
    """Create a temporary repo structure."""
    # Create repo root with .git
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    
    # Create standard directories
    (repo / "workflows").mkdir()
    (repo / "commands").mkdir()
    (repo / "packages").mkdir()
    (repo / "packages" / "dag-executor").mkdir()
    (repo / "packages" / "dag-executor" / "workflows").mkdir()
    
    # Create some test files
    (repo / "workflows" / "parent.yaml").write_text("test")
    (repo / "workflows" / "child.yaml").write_text("test")
    (repo / "commands" / "foo.md").write_text("test")
    (repo / "packages" / "dag-executor" / "workflows" / "validate.yaml").write_text("test")
    
    return repo


def test_resolve_literal_path(temp_repo):
    """Literal path that exists is returned."""
    target = temp_repo / "workflows" / "parent.yaml"
    result = _resolve_workflow_relative(str(target), None)
    assert result == target


def test_resolve_fails_when_dir_not_file(temp_repo):
    """Directory matching the name should not match - only files."""
    # Create a directory with same name as a file
    dir_path = temp_repo / "workflows" / "somedir"
    dir_path.mkdir()
    
    # Should not resolve to the directory
    result = _resolve_workflow_relative(str(dir_path), None)
    assert result is None


def test_resolve_parent_dir_colocated(temp_repo):
    """Resolve a file in the same directory as parent."""
    parent = temp_repo / "workflows" / "parent.yaml"
    result = _resolve_workflow_relative("child.yaml", parent)
    assert result == temp_repo / "workflows" / "child.yaml"


def test_resolve_repo_commands_dir(temp_repo):
    """Resolve a file from repo root commands/ directory."""
    parent = temp_repo / "packages" / "dag-executor" / "workflows" / "validate.yaml"
    result = _resolve_workflow_relative("foo.md", parent)
    # Should find it in repo_root/commands/
    assert result == temp_repo / "commands" / "foo.md"


def test_resolve_env_var_search_path(temp_repo):
    """Resolve from DAG_DASHBOARD_WORKFLOWS_DIR."""
    env_dir = temp_repo / "env-workflows"
    env_dir.mkdir()
    (env_dir / "env-workflow.yaml").write_text("test")
    
    old_env = os.environ.get("DAG_DASHBOARD_WORKFLOWS_DIR")
    try:
        os.environ["DAG_DASHBOARD_WORKFLOWS_DIR"] = str(env_dir)
        result = _resolve_workflow_relative("env-workflow.yaml", None)
        assert result == env_dir / "env-workflow.yaml"
    finally:
        if old_env is not None:
            os.environ["DAG_DASHBOARD_WORKFLOWS_DIR"] = old_env
        else:
            os.environ.pop("DAG_DASHBOARD_WORKFLOWS_DIR", None)


def test_resolve_claude_workflows_dir(temp_repo):
    """Resolve from ~/.claude/workflows."""
    claude_dir = Path.home() / ".claude" / "workflows"
    test_file = claude_dir / "test-workflow-12345.yaml"
    
    # Create the file
    claude_dir.mkdir(parents=True, exist_ok=True)
    test_file.write_text("test")
    
    try:
        result = _resolve_workflow_relative("test-workflow-12345.yaml", None)
        assert result == test_file
    finally:
        # Clean up
        test_file.unlink(missing_ok=True)


def test_resolve_search_order_priority(temp_repo):
    """Search order: parent dir takes precedence over env/claude."""
    parent = temp_repo / "workflows" / "parent.yaml"
    (temp_repo / "workflows" / "conflict.yaml").write_text("parent-dir")
    
    env_dir = temp_repo / "env-workflows"
    env_dir.mkdir()
    (env_dir / "conflict.yaml").write_text("env-dir")
    
    old_env = os.environ.get("DAG_DASHBOARD_WORKFLOWS_DIR")
    try:
        os.environ["DAG_DASHBOARD_WORKFLOWS_DIR"] = str(env_dir)
        result = _resolve_workflow_relative("conflict.yaml", parent)
        # Should find parent dir version first
        assert result == temp_repo / "workflows" / "conflict.yaml"
        assert result.read_text() == "parent-dir"
    finally:
        if old_env is not None:
            os.environ["DAG_DASHBOARD_WORKFLOWS_DIR"] = old_env
        else:
            os.environ.pop("DAG_DASHBOARD_WORKFLOWS_DIR", None)


def test_resolve_no_match_returns_none(temp_repo):
    """When no file matches, return None."""
    result = _resolve_workflow_relative("nonexistent.yaml", None)
    assert result is None
