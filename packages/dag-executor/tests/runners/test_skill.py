"""Tests for skill runner."""
import json
from pathlib import Path
from unittest.mock import Mock, patch
import pytest

from dag_executor.schema import NodeDef, NodeStatus
from dag_executor.runners.base import RunnerContext
from dag_executor.runners.skill import SkillRunner


@pytest.fixture
def skills_dir(tmp_path):
    """Create a temporary skills directory."""
    skills = tmp_path / "skills"
    skills.mkdir()
    return skills


@pytest.fixture
def valid_skill_node():
    """Create a valid skill node definition."""
    return NodeDef(
        id="skill1",
        name="Test Skill",
        type="skill",
        skill="jira/get_issue.ts",
        params={"issue_key": "TEST-123"}
    )


def test_skill_runner_valid_execution(skills_dir, valid_skill_node):
    """Test skill runner executes and parses JSON output."""
    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir
    )
    
    mock_output = {"status": "success", "data": {"key": "TEST-123"}}
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = json.dumps(mock_output)
    mock_result.stderr = ""
    
    with patch("subprocess.run", return_value=mock_result) as mock_run:
        runner = SkillRunner()
        result = runner.run(ctx)
        
        assert result.status == NodeStatus.COMPLETED
        assert result.output == mock_output
        assert result.error is None
        
        # Verify subprocess was called correctly
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert "python3" in call_args[0][0] or "python" in call_args[0][0]


def test_skill_path_traversal_rejected(skills_dir, valid_skill_node):
    """Test that .. path traversal is rejected."""
    valid_skill_node.skill = "../../../etc/passwd"
    
    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir
    )
    
    runner = SkillRunner()
    result = runner.run(ctx)
    
    assert result.status == NodeStatus.FAILED
    assert "path traversal" in result.error.lower() or "outside skills directory" in result.error.lower()


def test_skill_path_outside_skills_dir_rejected(skills_dir, valid_skill_node):
    """Test that paths outside skills_dir are rejected."""
    valid_skill_node.skill = "/tmp/malicious_skill.py"
    
    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir
    )
    
    runner = SkillRunner()
    result = runner.run(ctx)
    
    assert result.status == NodeStatus.FAILED
    assert "outside skills directory" in result.error.lower()


def test_skill_non_zero_exit_code(skills_dir, valid_skill_node):
    """Test skill with non-zero exit code returns FAILED status."""
    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir
    )
    
    mock_result = Mock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "Error: Something went wrong"
    
    with patch("subprocess.run", return_value=mock_result):
        runner = SkillRunner()
        result = runner.run(ctx)
        
        assert result.status == NodeStatus.FAILED
        assert result.error == "Error: Something went wrong"


def test_skill_non_json_output(skills_dir, valid_skill_node):
    """Test skill with non-JSON output returns raw text."""
    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir
    )
    
    mock_result = Mock()
    mock_result.returncode = 0
    mock_result.stdout = "Plain text output"
    mock_result.stderr = ""
    
    with patch("subprocess.run", return_value=mock_result):
        runner = SkillRunner()
        result = runner.run(ctx)
        
        assert result.status == NodeStatus.COMPLETED
        assert result.output == {"stdout": "Plain text output"}
