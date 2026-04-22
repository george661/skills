"""Tests for skill runner."""
import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch
import pytest

from dag_executor.events import EventType
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


def _create_mock_subprocess_exec(stdout_lines=None, stderr_lines=None, returncode=0):
    """Create a mock async subprocess_exec function with configurable output."""
    if stdout_lines is None:
        stdout_lines = []
    if stderr_lines is None:
        stderr_lines = []

    stdout_bytes = [line.encode('utf-8') if isinstance(line, str) else line for line in stdout_lines] + [b'']
    stderr_bytes = [line.encode('utf-8') if isinstance(line, str) else line for line in stderr_lines] + [b'']

    async def mock_create_subprocess_exec(*args, **kwargs):
        stdout_reader = AsyncMock()
        stderr_reader = AsyncMock()
        stdout_reader.readline = AsyncMock(side_effect=stdout_bytes.copy())
        stderr_reader.readline = AsyncMock(side_effect=stderr_bytes.copy())

        process = AsyncMock()
        process.stdout = stdout_reader
        process.stderr = stderr_reader
        process.returncode = returncode
        process.wait = AsyncMock(return_value=returncode)
        process.kill = Mock()
        process.stdin = AsyncMock()
        process.stdin.write = Mock()
        process.stdin.drain = AsyncMock()
        process.stdin.close = Mock()

        return process

    return mock_create_subprocess_exec


@pytest.mark.asyncio
async def test_skill_runner_valid_execution(skills_dir, valid_skill_node):
    """Test skill runner executes and parses JSON output."""
    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// test stub")

    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir
    )

    mock_output = {"status": "success", "data": {"key": "TEST-123"}}
    mock_exec = _create_mock_subprocess_exec(
        stdout_lines=[json.dumps(mock_output) + "\n"],
        stderr_lines=[],
        returncode=0
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        runner = SkillRunner()
        result = await runner._run_async(ctx)

        assert result.status == NodeStatus.COMPLETED
        assert result.output == mock_output
        assert result.error is None


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
    """Test that sibling directory names don't bypass path validation."""
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


@pytest.mark.asyncio
async def test_skill_non_zero_exit_code(skills_dir, valid_skill_node):
    """Test skill with non-zero exit code returns FAILED status."""
    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// test stub")

    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir
    )

    mock_exec = _create_mock_subprocess_exec(
        stdout_lines=[],
        stderr_lines=["Error: Something went wrong\n"],
        returncode=1
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        runner = SkillRunner()
        result = await runner._run_async(ctx)

        assert result.status == NodeStatus.FAILED
        assert "Error: Something went wrong" in result.error


@pytest.mark.asyncio
async def test_skill_non_json_output(skills_dir, valid_skill_node):
    """Test skill with non-JSON output returns raw text."""
    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// test stub")

    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir
    )

    mock_exec = _create_mock_subprocess_exec(
        stdout_lines=["Plain text output\n"],
        stderr_lines=[],
        returncode=0
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        runner = SkillRunner()
        result = await runner._run_async(ctx)

        assert result.status == NodeStatus.COMPLETED
        assert result.output == {"stdout": "Plain text output\n"}


@pytest.mark.asyncio
async def test_skill_streams_events(skills_dir, valid_skill_node):
    """Test that stdout/stderr lines emit NODE_LOG_LINE events."""
    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// test stub")

    emitted_events = []
    event_emitter = Mock()
    event_emitter.emit = lambda e: emitted_events.append(e)

    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir,
        event_emitter=event_emitter,
        workflow_id="wf123"
    )

    mock_output = {"status": "success"}
    mock_exec = _create_mock_subprocess_exec(
        stdout_lines=[json.dumps(mock_output) + "\n"],
        stderr_lines=["log 1\n", "log 2\n"],
        returncode=0
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        runner = SkillRunner()
        result = await runner._run_async(ctx)

        assert result.status == NodeStatus.COMPLETED
        
        log_events = [e for e in emitted_events if e.event_type == EventType.NODE_LOG_LINE]
        assert len(log_events) == 3
        
        # Check sequences are monotonic
        sequences = [e.metadata["sequence"] for e in log_events]
        assert sequences == [0, 1, 2]


@pytest.mark.asyncio
async def test_skill_output_size_limit(skills_dir, valid_skill_node):
    """Test that oversized output returns FAILED."""
    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// test stub")

    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir,
        max_output_bytes=50
    )

    large_line = "x" * 100 + "\n"
    mock_exec = _create_mock_subprocess_exec(
        stdout_lines=[large_line],
        returncode=0
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_exec):
        runner = SkillRunner()
        result = await runner._run_async(ctx)

        assert result.status == NodeStatus.FAILED
        assert "size" in result.error.lower() and "exceeded" in result.error.lower()


@pytest.mark.asyncio
async def test_skill_timeout(skills_dir, valid_skill_node):
    """Test that timeout kills subprocess."""
    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// test stub")

    valid_skill_node.timeout = 0.1

    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir
    )

    async def hanging_readline():
        await asyncio.sleep(10)
        return b''

    mock_exec = _create_mock_subprocess_exec(
        stdout_lines=[],
        returncode=0
    )

    async def mock_hanging(*args, **kwargs):
        process = await mock_exec(*args, **kwargs)
        process.stdout.readline = hanging_readline
        process.stderr.readline = hanging_readline
        return process

    with patch("asyncio.create_subprocess_exec", mock_hanging):
        runner = SkillRunner()
        result = await runner._run_async(ctx)

        assert result.status == NodeStatus.FAILED
        assert "timed out" in result.error.lower() or "timeout" in result.error.lower()
