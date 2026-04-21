"""Tests for skill runner."""
import json
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


def _mock_popen(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Build a Mock Popen: .communicate() returns (stdout, stderr) and sets .returncode."""
    proc = Mock()
    proc.returncode = returncode
    proc.communicate.return_value = (stdout, stderr)
    return proc


def test_skill_runner_valid_execution(skills_dir, valid_skill_node):
    """Test skill runner executes and parses JSON output."""
    # Create the skill file so path validation passes
    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// test stub")

    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir
    )

    mock_output = {"status": "success", "data": {"key": "TEST-123"}}
    proc = _mock_popen(stdout=json.dumps(mock_output), stderr="", returncode=0)

    with patch("dag_executor.runners.skill.subprocess.Popen", return_value=proc) as mock_popen:
        runner = SkillRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED
        assert result.output == mock_output
        assert result.error is None

        # Verify subprocess was called correctly
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
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


def test_skill_sibling_directory_attack_rejected(skills_dir, valid_skill_node):
    """Test that sibling directory names don't bypass path validation.

    Regression test: str.startswith('/tmp/skills') matches '/tmp/skills_evil/' too.
    Path.is_relative_to() prevents this.
    """
    # Create a sibling directory with a prefix-matching name
    sibling = skills_dir.parent / (skills_dir.name + "_evil")
    sibling.mkdir()
    malicious = sibling / "malicious.py"
    malicious.write_text("print('pwned')")

    valid_skill_node.skill = str(malicious)

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
    # Create the skill file so path validation passes
    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// test stub")

    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir
    )

    proc = _mock_popen(stdout="", stderr="Error: Something went wrong", returncode=1)

    with patch("dag_executor.runners.skill.subprocess.Popen", return_value=proc):
        runner = SkillRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.FAILED
        assert result.error == "Error: Something went wrong"


def test_skill_non_json_output(skills_dir, valid_skill_node):
    """Test skill with non-JSON output returns raw text."""
    # Create the skill file so path validation passes
    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// test stub")

    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir
    )

    proc = _mock_popen(stdout="Plain text output", stderr="", returncode=0)

    with patch("dag_executor.runners.skill.subprocess.Popen", return_value=proc):
        runner = SkillRunner()
        result = runner.run(ctx)

        assert result.status == NodeStatus.COMPLETED
        assert result.output == {"stdout": "Plain text output"}
