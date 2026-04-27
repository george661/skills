"""Tests for skill runner."""
import asyncio
import json
import time
from unittest.mock import AsyncMock, Mock, patch

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


def _create_mock_subprocess_exec(stdout_lines=None, stderr_lines=None, returncode=0):
    """Create a mock async subprocess_exec function with configurable output.

    Args:
        stdout_lines: List of strings (lines) to return from stdout
        stderr_lines: List of strings (lines) to return from stderr
        returncode: Process exit code

    Returns:
        Async function that returns a mock process
    """
    if stdout_lines is None:
        stdout_lines = []
    if stderr_lines is None:
        stderr_lines = []

    # Convert lines to bytes and add EOF marker
    stdout_bytes = [line.encode("utf-8") if isinstance(line, str) else line for line in stdout_lines] + [b""]
    stderr_bytes = [line.encode("utf-8") if isinstance(line, str) else line for line in stderr_lines] + [b""]

    async def mock_create_subprocess_exec(*args, **kwargs):
        mock_create_subprocess_exec.call_args = (args, kwargs)
        mock_create_subprocess_exec.call_count += 1

        stdout_reader = AsyncMock()
        stderr_reader = AsyncMock()
        stdout_reader.readline = AsyncMock(side_effect=stdout_bytes.copy())
        stderr_reader.readline = AsyncMock(side_effect=stderr_bytes.copy())

        stdin_writer = Mock()
        stdin_writer.write = Mock()
        stdin_writer.drain = AsyncMock()
        stdin_writer.close = Mock()

        process = AsyncMock()
        process.stdin = stdin_writer
        process.stdout = stdout_reader
        process.stderr = stderr_reader
        process.returncode = returncode
        process.wait = AsyncMock(return_value=returncode)
        process.kill = Mock()

        return process

    mock_create_subprocess_exec.call_args = None
    mock_create_subprocess_exec.call_count = 0

    return mock_create_subprocess_exec


# ---------------------------------------------------------------------------
# Existing behavior (converted to async mock)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_runner_valid_execution(skills_dir, valid_skill_node):
    """Skill runner executes and parses JSON output from accumulated stdout."""
    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// test stub")

    ctx = RunnerContext(node_def=valid_skill_node, skills_dir=skills_dir)

    mock_output = {"status": "success", "data": {"key": "TEST-123"}}
    mock_subprocess = _create_mock_subprocess_exec(
        stdout_lines=[json.dumps(mock_output)],
        stderr_lines=[],
        returncode=0,
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        runner = SkillRunner()
        result = await runner._run_async(ctx)

    assert result.status == NodeStatus.COMPLETED
    assert result.output == mock_output
    assert result.error is None

    # GW-5356 follow-up #4: TypeScript skills route through `npx tsx` with
    # params as argv[2], not `python3` with params on stdin. The fixture
    # skill is a .ts file; the assertion now reflects the fix.
    args, _ = mock_subprocess.call_args
    assert args[0] == "npx"
    assert args[1] == "tsx"
    assert args[2].endswith("get_issue.ts")
    # argv[3] is the JSON-encoded params from the fixture's node.params
    assert json.loads(args[3]) == valid_skill_node.params


def test_skill_path_traversal_rejected(skills_dir, valid_skill_node):
    """.. path traversal is rejected before any subprocess is spawned."""
    valid_skill_node.skill = "../../../etc/passwd"
    ctx = RunnerContext(node_def=valid_skill_node, skills_dir=skills_dir)

    runner = SkillRunner()
    result = runner.run(ctx)

    assert result.status == NodeStatus.FAILED
    assert "path traversal" in result.error.lower() or "outside skills directory" in result.error.lower()


def test_skill_path_outside_skills_dir_rejected(skills_dir, valid_skill_node):
    """Paths outside skills_dir are rejected."""
    valid_skill_node.skill = "/tmp/malicious_skill.py"
    ctx = RunnerContext(node_def=valid_skill_node, skills_dir=skills_dir)

    runner = SkillRunner()
    result = runner.run(ctx)

    assert result.status == NodeStatus.FAILED
    assert "outside skills directory" in result.error.lower()


def test_skill_sibling_directory_attack_rejected(skills_dir, valid_skill_node):
    """Sibling directory names don't bypass path validation.

    Regression test: str.startswith('/tmp/skills') matches '/tmp/skills_evil/' too.
    Path.is_relative_to() prevents this.
    """
    sibling = skills_dir.parent / (skills_dir.name + "_evil")
    sibling.mkdir()
    malicious = sibling / "malicious.py"
    malicious.write_text("print('pwned')")

    valid_skill_node.skill = str(malicious)
    ctx = RunnerContext(node_def=valid_skill_node, skills_dir=skills_dir)

    runner = SkillRunner()
    result = runner.run(ctx)

    assert result.status == NodeStatus.FAILED
    assert "outside skills directory" in result.error.lower()


@pytest.mark.asyncio
async def test_skill_non_zero_exit_code(skills_dir, valid_skill_node):
    """Skill with non-zero exit code returns FAILED status with stderr."""
    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// test stub")

    ctx = RunnerContext(node_def=valid_skill_node, skills_dir=skills_dir)

    mock_subprocess = _create_mock_subprocess_exec(
        stdout_lines=[],
        stderr_lines=["Error: Something went wrong\n"],
        returncode=1,
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        runner = SkillRunner()
        result = await runner._run_async(ctx)

    assert result.status == NodeStatus.FAILED
    assert result.error == "Error: Something went wrong\n"


@pytest.mark.asyncio
async def test_skill_non_json_output(skills_dir, valid_skill_node):
    """Non-JSON stdout falls back to {'stdout': text}."""
    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// test stub")

    ctx = RunnerContext(node_def=valid_skill_node, skills_dir=skills_dir)

    mock_subprocess = _create_mock_subprocess_exec(
        stdout_lines=["Plain text output"],
        stderr_lines=[],
        returncode=0,
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        runner = SkillRunner()
        result = await runner._run_async(ctx)

    assert result.status == NodeStatus.COMPLETED
    assert result.output == {"stdout": "Plain text output"}


# ---------------------------------------------------------------------------
# Line-streaming behavior (new in GW-5191)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_skill_streams_stdout_line_events(skills_dir, valid_skill_node):
    """Each stdout line produces a NODE_LOG_LINE event tagged stream=stdout."""
    from dag_executor.events import EventEmitter, EventType

    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// stub")

    emitter = EventEmitter()
    events = []
    emitter.add_listener(events.append)

    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir,
        workflow_id="wf-stream-stdout",
        event_emitter=emitter,
    )

    mock_subprocess = _create_mock_subprocess_exec(
        stdout_lines=["line 1\n", "line 2\n", "line 3\n"],
        stderr_lines=[],
        returncode=0,
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        runner = SkillRunner()
        result = await runner._run_async(ctx)

    assert result.status == NodeStatus.COMPLETED

    log_events = [e for e in events if e.event_type == EventType.NODE_LOG_LINE]
    assert len(log_events) == 3
    assert [e.metadata["line"] for e in log_events] == ["line 1", "line 2", "line 3"]
    assert all(e.metadata["stream"] == "stdout" for e in log_events)
    assert all(e.node_id == "skill1" for e in log_events)
    assert all(e.workflow_id == "wf-stream-stdout" for e in log_events)


@pytest.mark.asyncio
async def test_skill_streams_stderr_line_events(skills_dir, valid_skill_node):
    """stderr lines produce NODE_LOG_LINE events tagged stream=stderr."""
    from dag_executor.events import EventEmitter, EventType

    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// stub")

    emitter = EventEmitter()
    events = []
    emitter.add_listener(events.append)

    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir,
        workflow_id="wf-stream-stderr",
        event_emitter=emitter,
    )

    mock_subprocess = _create_mock_subprocess_exec(
        stdout_lines=[],
        stderr_lines=["err 1\n", "err 2\n"],
        returncode=0,
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        runner = SkillRunner()
        result = await runner._run_async(ctx)

    assert result.status == NodeStatus.COMPLETED

    log_events = [e for e in events if e.event_type == EventType.NODE_LOG_LINE]
    assert len(log_events) == 2
    assert [e.metadata["line"] for e in log_events] == ["err 1", "err 2"]
    assert all(e.metadata["stream"] == "stderr" for e in log_events)


@pytest.mark.asyncio
async def test_skill_log_line_sequence_monotonic(skills_dir, valid_skill_node):
    """Sequence numbers are monotonically increasing across both streams."""
    from dag_executor.events import EventEmitter, EventType

    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// stub")

    emitter = EventEmitter()
    events = []
    emitter.add_listener(events.append)

    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir,
        workflow_id="wf-seq",
        event_emitter=emitter,
    )

    mock_subprocess = _create_mock_subprocess_exec(
        stdout_lines=["a\n", "b\n"],
        stderr_lines=["e\n"],
        returncode=0,
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        runner = SkillRunner()
        result = await runner._run_async(ctx)

    assert result.status == NodeStatus.COMPLETED
    log_events = [e for e in events if e.event_type == EventType.NODE_LOG_LINE]
    assert len(log_events) == 3
    sequences = [e.metadata["sequence"] for e in log_events]
    assert sorted(sequences) == [0, 1, 2]
    assert len(set(sequences)) == 3  # unique


@pytest.mark.asyncio
async def test_skill_final_json_parse_unchanged(skills_dir, valid_skill_node):
    """After streaming lines, accumulated stdout is still parsed as JSON."""
    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// stub")

    ctx = RunnerContext(node_def=valid_skill_node, skills_dir=skills_dir)

    payload = {"result": "ok", "items": [1, 2, 3], "nested": {"k": "v"}}
    # Split the JSON across multiple lines to prove accumulation works.
    raw = json.dumps(payload, indent=2)
    lines_with_newlines = [ln + "\n" for ln in raw.split("\n")]

    mock_subprocess = _create_mock_subprocess_exec(
        stdout_lines=lines_with_newlines,
        stderr_lines=[],
        returncode=0,
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        runner = SkillRunner()
        result = await runner._run_async(ctx)

    assert result.status == NodeStatus.COMPLETED
    assert result.output == payload


@pytest.mark.asyncio
async def test_skill_output_size_limit_enforced(skills_dir, valid_skill_node):
    """Output exceeding max_output_bytes fails with size-exceeded error."""
    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// stub")

    ctx = RunnerContext(
        node_def=valid_skill_node,
        skills_dir=skills_dir,
        max_output_bytes=20,  # tiny cap
    )

    mock_subprocess = _create_mock_subprocess_exec(
        stdout_lines=["x" * 100 + "\n"],
        stderr_lines=[],
        returncode=0,
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess):
        runner = SkillRunner()
        result = await runner._run_async(ctx)

    assert result.status == NodeStatus.FAILED
    assert "size limit exceeded" in result.error.lower()


@pytest.mark.asyncio
async def test_skill_timeout_kills_process(skills_dir, valid_skill_node):
    """On timeout, the process is killed and FAILED is returned."""
    (skills_dir / "jira").mkdir()
    (skills_dir / "jira" / "get_issue.ts").write_text("// stub")

    valid_skill_node.timeout = 1
    ctx = RunnerContext(node_def=valid_skill_node, skills_dir=skills_dir)

    async def mock_wait_for(*args, **kwargs):
        raise asyncio.TimeoutError()

    mock_subprocess = _create_mock_subprocess_exec(
        stdout_lines=[],
        stderr_lines=[],
        returncode=0,
    )

    with patch("asyncio.create_subprocess_exec", side_effect=mock_subprocess), \
         patch("dag_executor.runners.skill.asyncio.wait_for", side_effect=mock_wait_for):
        runner = SkillRunner()
        result = await runner._run_async(ctx)

    assert result.status == NodeStatus.FAILED
    assert "timed out" in result.error.lower()


@pytest.mark.asyncio
async def test_skill_live_streaming_real_subprocess(tmp_path):
    """Integration test: real subprocess, events arrive progressively, not buffered.

    Verifies the 'progressively emits live events' acceptance criterion by
    checking that event timestamps span the subprocess runtime rather than
    all arriving at the end.
    """
    from dag_executor.events import EventEmitter, EventType

    skills = tmp_path / "skills"
    skills.mkdir()
    script = skills / "slow.py"
    # Progress goes to stderr (streamed, visible to the user); stdout is
    # reserved for the final JSON result. This mirrors how real skills work:
    # `npx tsx foo.ts` writes the JSON result to stdout and any diagnostics
    # to stderr.
    script.write_text(
        "import sys, time\n"
        "for i in range(3):\n"
        "    print(f'line {i}', file=sys.stderr, flush=True)\n"
        "    time.sleep(1)\n"
        "print('{\"done\": true}')\n"
    )

    node = NodeDef(
        id="slow",
        name="Slow",
        type="skill",
        skill="slow.py",
        timeout=10,
    )

    emitter = EventEmitter()
    events = []
    event_times = []

    def record(e):
        events.append(e)
        event_times.append(time.time())

    emitter.add_listener(record)

    ctx = RunnerContext(
        node_def=node,
        skills_dir=skills,
        workflow_id="wf-live",
        event_emitter=emitter,
    )

    start = time.time()
    runner = SkillRunner()
    result = await runner._run_async(ctx)
    total = time.time() - start

    assert result.status == NodeStatus.COMPLETED
    assert result.output == {"done": True}

    log_events = [
        (e, t) for e, t in zip(events, event_times)
        if e.event_type == EventType.NODE_LOG_LINE
    ]
    stderr_events = [e for e, _ in log_events if e.metadata["stream"] == "stderr"]
    stdout_events = [e for e, _ in log_events if e.metadata["stream"] == "stdout"]
    assert len(stderr_events) == 3
    assert len(stdout_events) == 1  # the final JSON line

    # Events for the three "line N" prints should arrive progressively:
    # first event within ~1.5s of start, last within ~3.5s. If buffered,
    # all would arrive near total.
    first_line_time = next(t for e, t in log_events if e.metadata["line"] == "line 0")
    last_line_time = next(t for e, t in log_events if e.metadata["line"] == "line 2")
    assert first_line_time - start < 1.5, (
        f"First event arrived {first_line_time - start:.2f}s after start — "
        f"expected progressive streaming"
    )
    assert last_line_time - first_line_time >= 1.5, (
        f"Only {last_line_time - first_line_time:.2f}s between first and last "
        f"events — expected ~2s from sleep(1) x 2"
    )
    assert 2.5 <= total <= 8.0, f"Expected ~3s run, got {total:.1f}s"
