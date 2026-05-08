"""Tests for GitConfig schema and validation."""
import pytest
from pydantic import ValidationError

from dag_executor.schema import GitConfig, WorkflowConfig


def test_git_config_minimal():
    """GitConfig with just url works (ref defaults to main)."""
    config = GitConfig(url="https://github.com/test/repo.git")
    assert config.url == "https://github.com/test/repo.git"
    assert config.ref == "main"
    assert config.depth == 1


def test_git_config_with_ref():
    """GitConfig with custom ref."""
    config = GitConfig(url="https://github.com/test/repo.git", ref="feature-branch")
    assert config.ref == "feature-branch"


def test_git_config_with_tag():
    """GitConfig with tag ref."""
    config = GitConfig(url="https://github.com/test/repo.git", ref="v1.0.0")
    assert config.ref == "v1.0.0"


def test_git_config_with_sha():
    """GitConfig with SHA ref."""
    config = GitConfig(url="https://github.com/test/repo.git", ref="abc123def456")
    assert config.ref == "abc123def456"


def test_git_config_extra_forbid():
    """GitConfig rejects unknown fields."""
    with pytest.raises(ValidationError) as exc_info:
        GitConfig(url="https://github.com/test/repo.git", branch="main")
    
    assert "extra" in str(exc_info.value).lower() or "unexpected" in str(exc_info.value).lower()


def test_git_config_missing_url():
    """GitConfig requires url."""
    with pytest.raises(ValidationError) as exc_info:
        GitConfig(ref="main")
    
    assert "url" in str(exc_info.value).lower()


def test_workflow_config_git_optional():
    """WorkflowConfig works without git field."""
    config = WorkflowConfig(checkpoint_prefix="test")
    assert config.git is None


def test_workflow_config_with_git():
    """WorkflowConfig accepts git field."""
    config = WorkflowConfig(
        checkpoint_prefix="test",
        git=GitConfig(url="https://github.com/test/repo.git")
    )
    assert config.git is not None
    assert config.git.url == "https://github.com/test/repo.git"
